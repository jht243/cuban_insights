"""Stripe webhook handler for API key provisioning and cancellation."""

from __future__ import annotations

import json
import logging
import time

from flask import jsonify, request

from src.api import api_v1
from src.api.auth import generate_raw_key, hash_key, _get_prefix
from src.api.email import send_api_key_email, send_key_deactivated_email
from src.config import settings
from src.models import ApiKey, ApiTier, SessionLocal, init_db

logger = logging.getLogger(__name__)

# Short-lived cache: session_id -> (raw_key, timestamp)
# Keys expire after 10 minutes. Only used to display on the success page.
_KEY_CACHE: dict[str, tuple[str, float]] = {}
_KEY_CACHE_TTL = 600


def _to_dict(obj) -> dict:
    """Safely convert a Stripe object or dict to a plain dict."""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return {}


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
        event = _to_dict(event)
    else:
        event = json.loads(payload)

    event_type = event.get("type", "")
    data_object = event.get("data", {}).get("object", {})
    if not isinstance(data_object, dict) and hasattr(data_object, "to_dict"):
        data_object = data_object.to_dict()

    if event_type == "checkout.session.completed":
        session_id = data_object.get("id", "")
        _handle_checkout_completed(data_object, session_id)
    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(data_object)
    else:
        logger.debug("Ignoring Stripe event: %s", event_type)

    return jsonify({"received": True})


def _handle_checkout_completed(session: dict, session_id: str = "") -> None:
    metadata = session.get("metadata") or {}
    tier_str = metadata.get("tier", "pro")
    customer_id = session.get("customer", "") or ""
    subscription_id = session.get("subscription", "") or ""

    email = session.get("customer_email", "") or ""
    if not email:
        cd = session.get("customer_details") or {}
        email = cd.get("email", "") or ""
    if not email:
        logger.error("Stripe checkout completed but no email found on session: %s",
                     session.get("id", "unknown"))
        return

    tier_map = {"pro": ApiTier.PRO, "enterprise": ApiTier.ENTERPRISE}
    tier = tier_map.get(tier_str, ApiTier.PRO)

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

        if session_id:
            _KEY_CACHE[session_id] = (raw, time.time())

        send_api_key_email(to_email=email.lower(), raw_key=raw, tier=tier_str)
        logger.info("Provisioned %s API key for %s (key_prefix=%s, session=%s)",
                    tier_str, email, row.key_prefix, session_id)

    except Exception:
        logger.exception("Failed to provision API key for %s", email)
        db.rollback()
    finally:
        db.close()


def _handle_subscription_deleted(subscription: dict) -> None:
    customer_id = subscription.get("customer", "") or ""
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
    except Exception:
        logger.exception("Failed to handle subscription deletion for customer %s", customer_id)
        db.rollback()
    finally:
        db.close()
