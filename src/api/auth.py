"""
API key authentication decorator and helpers.

Keys are passed via the ``X-API-Key`` header. The raw key is hashed with
SHA-256 and looked up in the ``api_keys`` table. The matched row's tier
determines rate-limit quotas enforced downstream.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import date, datetime
from functools import wraps
from typing import Optional

from flask import g, jsonify, request

from src.models import ApiKey, ApiTier, SessionLocal, init_db

KEY_PREFIX_LIVE = "ci_live_"
KEY_PREFIX_TEST = "ci_test_"
KEY_BYTE_LENGTH = 24


def generate_raw_key(*, test: bool = False) -> str:
    prefix = KEY_PREFIX_TEST if test else KEY_PREFIX_LIVE
    return prefix + secrets.token_urlsafe(KEY_BYTE_LENGTH)


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _get_prefix(raw_key: str) -> str:
    return raw_key[:16]


TIER_DAILY_LIMITS: dict[ApiTier, int] = {
    ApiTier.FREE: 100,
    ApiTier.PRO: 5_000,
    ApiTier.ENTERPRISE: 1_000_000,
}

TIER_ALLOWED_ENDPOINTS: dict[ApiTier, Optional[set[str]]] = {
    ApiTier.FREE: {
        "api_v1.briefings_latest",
        "api_v1.briefings_list",
        "api_v1.fx_latest",
        "api_v1.companies_list",
        "api_v1.climate_latest",
    },
    ApiTier.PRO: None,
    ApiTier.ENTERPRISE: None,
}


def require_api_key(f):
    """Decorator that validates the ``X-API-Key`` header and attaches
    ``g.api_key_row`` for downstream use."""

    @wraps(f)
    def decorated(*args, **kwargs):
        raw = request.headers.get("X-API-Key", "").strip()
        if not raw:
            return jsonify({"error": "Missing X-API-Key header",
                            "docs": "https://cubaninsights.com/developers"}), 401

        hashed = hash_key(raw)
        init_db()
        db = SessionLocal()
        try:
            row: ApiKey | None = (
                db.query(ApiKey)
                .filter(ApiKey.key_hash == hashed, ApiKey.active.is_(True))
                .first()
            )
            if row is None:
                return jsonify({"error": "Invalid or deactivated API key"}), 401

            today = date.today()
            if row.last_request_date != today:
                row.requests_today = 0
                row.last_request_date = today

            daily_limit = TIER_DAILY_LIMITS[ApiTier(row.tier.value if hasattr(row.tier, 'value') else row.tier)]
            if row.requests_today >= daily_limit:
                return jsonify({
                    "error": "Daily request limit exceeded",
                    "limit": daily_limit,
                    "tier": row.tier.value if hasattr(row.tier, 'value') else row.tier,
                    "upgrade": "https://cubaninsights.com/developers",
                }), 429

            allowed = TIER_ALLOWED_ENDPOINTS.get(
                ApiTier(row.tier.value if hasattr(row.tier, 'value') else row.tier)
            )
            if allowed is not None and request.endpoint not in allowed:
                return jsonify({
                    "error": "Endpoint not available on your tier",
                    "tier": row.tier.value if hasattr(row.tier, 'value') else row.tier,
                    "upgrade": "https://cubaninsights.com/developers",
                }), 403

            row.requests_today += 1
            row.updated_at = datetime.utcnow()
            db.commit()

            g.api_key_row = row
            g.api_tier = ApiTier(row.tier.value if hasattr(row.tier, 'value') else row.tier)
            g.api_daily_limit = daily_limit
            g.api_requests_today = row.requests_today
        finally:
            db.close()

        resp = f(*args, **kwargs)

        if hasattr(resp, "headers"):
            resp.headers["X-RateLimit-Limit"] = str(g.api_daily_limit)
            resp.headers["X-RateLimit-Remaining"] = str(
                max(0, g.api_daily_limit - g.api_requests_today)
            )
        elif isinstance(resp, tuple) and len(resp) >= 1 and hasattr(resp[0], "headers"):
            resp[0].headers["X-RateLimit-Limit"] = str(g.api_daily_limit)
            resp[0].headers["X-RateLimit-Remaining"] = str(
                max(0, g.api_daily_limit - g.api_requests_today)
            )

        return resp

    return decorated
