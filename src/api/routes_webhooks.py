"""Stripe webhook handler for API key provisioning and cancellation."""

from __future__ import annotations

import logging

from flask import jsonify, request

from src.api import api_v1
from src.api.auth import generate_raw_key, hash_key, _get_prefix
from src.api.email import send_api_key_email, send_key_deactivated_email
from src.config import settings
from src.models import ApiKey, ApiTier, SessionLocal, init_db

logger = logging.getLogger(__name__)


@api_v1.route("/webhooks/stripe", methods=["POST"])
def stripe_webhook():
    if not settings.stripe_secret_key:
        return jsonify({"error": "Stripe not configured"}), 503

    import stripe
    stripe.api_key = settings.stripe_secret_key

    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature", "")

    if settings.stripe_webhook_secret:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig, settings.stripe_webhook_secret
            )
        except (ValueError, stripe.SignatureVerificationError):
            logger.warning("Stripe webhook signature verification failed")
            return jsonify({"error": "Invalid signature"}), 400
    else:
        import json
        event = json.loads(payload)

    event_type = event.get("type") if isinstance(event, dict) else event.type
    data_object = (
        event.get("data", {}).get("object", {})
        if isinstance(event, dict)
        else event.data.object
    )

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(data_object)
    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(data_object)
    else:
        logger.debug("Ignoring Stripe event: %s", event_type)

    return jsonify({"received": True})


def _handle_checkout_completed(session) -> None:
    metadata = session.get("metadata", {}) if isinstance(session, dict) else (session.metadata or {})
    email = metadata.get("email", "")
    tier_str = metadata.get("tier", "pro")
    customer_id = session.get("customer", "") if isinstance(session, dict) else (session.customer or "")
    subscription_id = session.get("subscription", "") if isinstance(session, dict) else (session.subscription or "")

    if not email:
        email = session.get("customer_email", "") if isinstance(session, dict) else (session.customer_email or "")
    if not email:
        logger.error("Stripe checkout completed but no email found in metadata or session")
        return

    tier = ApiTier.PRO if tier_str == "pro" else ApiTier.ENTERPRISE

    init_db()
    db = SessionLocal()
    try:
        existing = (
            db.query(ApiKey)
            .filter(ApiKey.owner_email == email.lower(), ApiKey.active.is_(True))
            .all()
        )
        for old in existing:
            old.active = False
        db.flush()

        raw = generate_raw_key()
        row = ApiKey(
            key_hash=hash_key(raw),
            key_prefix=_get_prefix(raw),
            tier=tier,
            owner_email=email.lower(),
            label=f"{tier_str.capitalize()} plan",
            stripe_customer_id=customer_id,
            stripe_subscription_id=subscription_id,
        )
        db.add(row)
        db.commit()

        send_api_key_email(to_email=email.lower(), raw_key=raw, tier=tier_str)
        logger.info("Provisioned %s API key for %s", tier_str, email)

    finally:
        db.close()


def _handle_subscription_deleted(subscription) -> None:
    customer_id = subscription.get("customer", "") if isinstance(subscription, dict) else (subscription.customer or "")
    if not customer_id:
        logger.warning("Subscription deleted but no customer_id found")
        return

    init_db()
    db = SessionLocal()
    try:
        keys = (
            db.query(ApiKey)
            .filter(ApiKey.stripe_customer_id == customer_id, ApiKey.active.is_(True))
            .all()
        )
        for key in keys:
            key.active = False
            send_key_deactivated_email(to_email=key.owner_email, reason="subscription cancelled")
            logger.info("Deactivated API key for %s (subscription cancelled)", key.owner_email)
        db.commit()
    finally:
        db.close()
