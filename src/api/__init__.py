"""
Public API v1 Blueprint for Cuban Insights.

Provides JSON endpoints for briefings, FX rates, company exposure,
sanctions feed, and investment climate data. Gated by API key
authentication with tiered rate limits.
"""

from flask import Blueprint

api_v1 = Blueprint("api_v1", __name__, url_prefix="/api/v1")

# Import route modules so they register on the blueprint.
from src.api import (  # noqa: E402, F401
    routes_briefings,
    routes_fx,
    routes_companies,
    routes_sanctions,
    routes_climate,
    routes_keys,
    routes_webhooks,
)
