"""Free-tier key signup and key rotation endpoints."""

from __future__ import annotations

import logging
import re

from flask import jsonify, request

from src.api import api_v1
from src.api.auth import generate_raw_key, hash_key, _get_prefix
from src.api.email import send_api_key_email
from src.config import settings
from src.models import ApiKey, ApiTier, SessionLocal, init_db

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@api_v1.route("/keys/signup", methods=["POST"])
def keys_signup():
    """Issue a free-tier API key. No authentication required."""
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()

    if not email or not EMAIL_RE.match(email):
        return jsonify({"error": "Valid email address required"}), 400

    init_db()
    db = SessionLocal()
    try:
        existing = (
            db.query(ApiKey)
            .filter(ApiKey.owner_email == email, ApiKey.tier == ApiTier.FREE, ApiKey.active.is_(True))
            .first()
        )
        if existing:
            return jsonify({
                "error": "A free-tier key already exists for this email. "
                         "Check your inbox or use /api/v1/keys/rotate to get a new one."
            }), 409

        raw = generate_raw_key()
        row = ApiKey(
            key_hash=hash_key(raw),
            key_prefix=_get_prefix(raw),
            tier=ApiTier.FREE,
            owner_email=email,
            label="Free tier",
        )
        db.add(row)
        db.commit()

        send_api_key_email(to_email=email, raw_key=raw, tier="free")

        return jsonify({
            "message": "API key created and emailed to you.",
            "tier": "free",
            "email": email,
            "daily_limit": 100,
        }), 201

    finally:
        db.close()


@api_v1.route("/keys/rotate", methods=["POST"])
def keys_rotate():
    """Rotate an API key. Sends the new key to the registered email."""
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()

    if not email or not EMAIL_RE.match(email):
        return jsonify({"error": "Valid email address required"}), 400

    init_db()
    db = SessionLocal()
    try:
        existing = (
            db.query(ApiKey)
            .filter(ApiKey.owner_email == email, ApiKey.active.is_(True))
            .order_by(ApiKey.created_at.desc())
            .first()
        )
        if existing is None:
            return jsonify({"error": "No active API key found for this email"}), 404

        existing.active = False
        db.flush()

        tier_val = existing.tier.value if hasattr(existing.tier, 'value') else existing.tier
        raw = generate_raw_key()
        new_row = ApiKey(
            key_hash=hash_key(raw),
            key_prefix=_get_prefix(raw),
            tier=ApiTier(tier_val),
            owner_email=email,
            label=existing.label,
            stripe_customer_id=existing.stripe_customer_id,
            stripe_subscription_id=existing.stripe_subscription_id,
        )
        db.add(new_row)
        db.commit()

        send_api_key_email(to_email=email, raw_key=raw, tier=tier_val)

        return jsonify({"message": "New API key generated and emailed to you."})

    finally:
        db.close()


@api_v1.route("/keys/checkout", methods=["POST"])
def keys_checkout():
    """Create a Stripe Checkout session for a paid tier."""
    if not settings.stripe_secret_key:
        return jsonify({"error": "Payments not configured"}), 503

    import stripe
    stripe.api_key = settings.stripe_secret_key

    body = request.get_json(silent=True) or {}
    tier = (body.get("tier") or "").strip().lower()

    price_map = {
        "test": settings.stripe_price_test,
        "pro": settings.stripe_price_pro,
        "enterprise": settings.stripe_price_enterprise,
    }
    price_id = price_map.get(tier)
    if not price_id:
        return jsonify({"error": "tier must be 'test', 'pro', or 'enterprise'"}), 400

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            metadata={"tier": tier},
            success_url=f"{settings.site_url}/developers/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{settings.site_url}/developers?checkout=cancel",
        )
        return jsonify({"checkout_url": session.url})
    except Exception as exc:
        logger.exception("Stripe Checkout creation failed")
        return jsonify({"error": str(exc)}), 500


@api_v1.route("/keys/retrieve")
def keys_retrieve():
    """Retrieve API key by Stripe checkout session ID (success page)."""
    import time
    from src.api.routes_webhooks import _KEY_CACHE, _KEY_CACHE_TTL

    session_id = request.args.get("session_id", "").strip()
    if not session_id:
        return jsonify({"error": "session_id required"}), 400

    entry = _KEY_CACHE.get(session_id)
    if entry:
        raw_key, created_at = entry
        if time.time() - created_at < _KEY_CACHE_TTL:
            del _KEY_CACHE[session_id]
            return jsonify({"api_key": raw_key})

    return jsonify({
        "error": "API key not ready yet. It may take a few seconds after payment. "
                 "Check your email — the key was also sent there."
    }), 202
