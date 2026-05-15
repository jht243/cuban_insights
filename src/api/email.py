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


TAG_LABELS = {
    "daily-briefing": "Daily Briefing",
    "sanctions-changes": "Sanctions Changes",
    "crl-updates": "Cuba Restricted List Updates",
    "cpal-updates": "CPAL Lodging Rule Changes",
    "ofac-actions": "OFAC Actions on Cuba",
    "diplomatic-updates": "U.S.–Cuba Diplomatic Updates",
    "travel-rule-changes": "Cuba Travel Rule Changes",
    "export-opportunities": "Cuba Export Opportunities",
    "sec-cuba-filings": "Cuba-Related SEC Filings",
    "entity-status-changes": "Entity Status Changes",
}


def send_subscriber_welcome_email(*, to_email: str, tags: list[str]) -> bool:
    if not settings.resend_api_key:
        logger.warning("RESEND_API_KEY not set — cannot send welcome email")
        return False

    resend.api_key = settings.resend_api_key

    interest_labels = [TAG_LABELS.get(t, t) for t in tags] if tags else ["Daily Briefing"]
    interests_html = ", ".join(f"<strong>{l}</strong>" for l in interest_labels)

    html_body = f"""\
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 560px; margin: 0 auto; padding: 32px 20px;">
  <h1 style="font-size: 22px; margin-bottom: 4px;">Cuban Insights</h1>
  <p style="color: #666; margin-top: 0;">You're subscribed. Here's what you'll get.</p>

  <div style="background: #f4f4f5; border-radius: 8px; padding: 16px 20px; margin: 24px 0;">
    <p style="margin: 0 0 8px; font-size: 14px; color: #333;"><strong>Your alerts:</strong></p>
    <p style="margin: 0; font-size: 14px; color: #333;">{interests_html}</p>
  </div>

  <p style="font-size: 14px; color: #333;">
    We'll email you when there's something worth knowing — no filler, no spam.
  </p>

  <p style="font-size: 14px; margin-top: 24px;">
    <a href="{settings.site_url}" style="color: #002b5e; font-weight: 600;">cubaninsights.com</a>
  </p>

  <hr style="border: none; border-top: 1px solid #e4e4e7; margin: 32px 0 16px;">
  <p style="font-size: 12px; color: #999;">
    You can unsubscribe anytime. Reply to this email with questions.
  </p>
</div>"""

    try:
        resend.Emails.send({
            "from": "jonathan@intake.layer3labs.io",
            "to": [to_email],
            "subject": "You're in — Cuban Insights",
            "html": html_body,
        })
        logger.info("Welcome email sent to %s (tags=%s)", to_email, tags)
        return True
    except Exception:
        logger.exception("Failed to send welcome email to %s", to_email)
        return False


def send_new_subscriber_notification(*, subscriber_email: str, tags: list[str], source_page: str, notes: str) -> bool:
    if not settings.resend_api_key:
        return False

    resend.api_key = settings.resend_api_key

    interest_labels = [TAG_LABELS.get(t, t) for t in tags] if tags else ["Daily Briefing"]
    interests_text = ", ".join(interest_labels)

    html_body = f"""\
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 560px; margin: 0 auto; padding: 32px 20px;">
  <h1 style="font-size: 20px; margin-bottom: 16px;">New Subscriber</h1>
  <table style="font-size: 14px; color: #333; border-collapse: collapse; width: 100%;">
    <tr><td style="padding: 6px 12px 6px 0; font-weight: 600; vertical-align: top;">Email</td><td style="padding: 6px 0;">{subscriber_email}</td></tr>
    <tr><td style="padding: 6px 12px 6px 0; font-weight: 600; vertical-align: top;">Interests</td><td style="padding: 6px 0;">{interests_text}</td></tr>
    <tr><td style="padding: 6px 12px 6px 0; font-weight: 600; vertical-align: top;">Source</td><td style="padding: 6px 0;">{source_page or 'N/A'}</td></tr>
    <tr><td style="padding: 6px 12px 6px 0; font-weight: 600; vertical-align: top;">Notes</td><td style="padding: 6px 0;">{notes or 'N/A'}</td></tr>
  </table>
</div>"""

    try:
        resend.Emails.send({
            "from": "jonathan@intake.layer3labs.io",
            "to": ["jonathan@layer3labs.io"],
            "subject": f"New subscriber: {subscriber_email} — {interests_text}",
            "html": html_body,
        })
        logger.info("Internal notification sent for new subscriber %s", subscriber_email)
        return True
    except Exception:
        logger.exception("Failed to send internal notification for %s", subscriber_email)
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
