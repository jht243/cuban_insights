"""Resend integration for API key delivery emails."""

from __future__ import annotations

import logging

import resend

from src.config import settings

logger = logging.getLogger(__name__)


def send_api_key_email(*, to_email: str, raw_key: str, tier: str) -> bool:
    """Send the API key to the user via Resend. Returns True on success."""
    if not settings.resend_api_key:
        logger.warning("RESEND_API_KEY not set — cannot send API key email")
        return False

    resend.api_key = settings.resend_api_key

    tier_label = tier.capitalize()
    docs_url = f"{settings.site_url}/developers"

    html_body = f"""\
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 560px; margin: 0 auto; padding: 32px 20px;">
  <h1 style="font-size: 22px; margin-bottom: 4px;">Cuban Insights API</h1>
  <p style="color: #666; margin-top: 0;">Your {tier_label} API key is ready.</p>

  <div style="background: #f4f4f5; border-radius: 8px; padding: 16px 20px; margin: 24px 0; font-family: monospace; font-size: 14px; word-break: break-all;">
    {raw_key}
  </div>

  <p style="font-size: 14px; color: #333;">
    Include this key in the <code>X-API-Key</code> header on every request:
  </p>
  <pre style="background: #1e1e2e; color: #cdd6f4; border-radius: 8px; padding: 16px; font-size: 13px; overflow-x: auto;">curl -H "X-API-Key: {raw_key}" \\
  {settings.site_url}/api/v1/briefings/latest</pre>

  <p style="font-size: 14px; margin-top: 24px;">
    <strong>Tier:</strong> {tier_label}<br>
    <strong>Docs:</strong> <a href="{docs_url}">{docs_url}</a>
  </p>

  <hr style="border: none; border-top: 1px solid #e4e4e7; margin: 32px 0 16px;">
  <p style="font-size: 12px; color: #999;">
    Keep this key secret. If compromised, reply to this email to rotate it.
  </p>
</div>"""

    try:
        resend.Emails.send({
            "from": settings.api_resend_from_email,
            "to": [to_email],
            "subject": f"Your Cuban Insights API Key ({tier_label})",
            "html": html_body,
        })
        logger.info("API key email sent to %s (tier=%s)", to_email, tier)
        return True
    except Exception:
        logger.exception("Failed to send API key email to %s", to_email)
        return False


def send_key_deactivated_email(*, to_email: str, reason: str = "subscription cancelled") -> bool:
    if not settings.resend_api_key:
        return False

    resend.api_key = settings.resend_api_key

    try:
        resend.Emails.send({
            "from": settings.api_resend_from_email,
            "to": [to_email],
            "subject": "Cuban Insights API Key Deactivated",
            "html": f"""\
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 560px; margin: 0 auto; padding: 32px 20px;">
  <h1 style="font-size: 22px;">API Key Deactivated</h1>
  <p>Your Cuban Insights API key has been deactivated ({reason}).</p>
  <p>To reactivate, visit <a href="{settings.site_url}/developers">{settings.site_url}/developers</a>
     and sign up for a new plan.</p>
</div>""",
        })
        return True
    except Exception:
        logger.exception("Failed to send deactivation email to %s", to_email)
        return False
