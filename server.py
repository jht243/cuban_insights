"""
Flask web server for Cuban Insights.

Serves the generated report.html on Render (or locally).
"""

from __future__ import annotations

import gzip
import html
import io
import logging
import time
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

import httpx
from flask import Flask, send_from_directory, abort, request, jsonify, Response, redirect
from werkzeug.exceptions import HTTPException

from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from src.config import settings
from src.storage_remote import (
    fetch_report_html,
    supabase_storage_enabled,
    supabase_storage_read_enabled,
)

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(
    __name__,
    static_folder=str(_STATIC_DIR),
    static_url_path="/static",
)

# CORS for the public API — allow any origin on /api/v1/* endpoints.
CORS(app, resources={r"/api/v1/*": {"origins": "*"}})

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["10 per minute", "3 per second"],
    storage_uri="memory://",
)

# Register the public API v1 blueprint.
from src.api import api_v1  # noqa: E402
app.register_blueprint(api_v1)
limiter.exempt(api_v1)


GZIP_MIME_PREFIXES = (
    "text/",
    "application/json",
    "application/xml",
    "application/javascript",
    "application/ld+json",
    "image/svg+xml",
)
GZIP_MIN_BYTES = 500


@app.after_request
def _gzip_response(response: Response) -> Response:
    """
    Gzip-compress eligible responses when the client advertises support.
    Skips small bodies, already-encoded responses, and non-text content.
    """
    try:
        if response.direct_passthrough:
            return response
        if response.status_code < 200 or response.status_code >= 300:
            return response
        if "Content-Encoding" in response.headers:
            return response
        if "gzip" not in (request.headers.get("Accept-Encoding", "") or "").lower():
            return response

        mimetype = (response.mimetype or "").lower()
        if not any(mimetype.startswith(p) for p in GZIP_MIME_PREFIXES):
            return response

        data = response.get_data()
        if len(data) < GZIP_MIN_BYTES:
            return response

        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as gz:
            gz.write(data)
        compressed = buf.getvalue()

        response.set_data(compressed)
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Content-Length"] = str(len(compressed))
        existing_vary = response.headers.get("Vary", "")
        if "Accept-Encoding" not in existing_vary:
            response.headers["Vary"] = (existing_vary + ", Accept-Encoding").lstrip(", ")
    except Exception as exc:
        logger.warning("gzip middleware skipped due to error: %s", exc)
    return response



_API_BANNER_HTML = """<div id="ci-api-banner" style="position:fixed;bottom:0;left:0;right:0;z-index:9999;
background:linear-gradient(135deg,#1e3a5f,#0f2744);color:#fff;padding:14px 24px;
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:14px;
display:flex;align-items:center;justify-content:center;gap:16px;box-shadow:0 -4px 20px rgba(0,0,0,0.3);">
<span style="font-size:20px;">&#9889;</span>
<span><strong>Need this data programmatically?</strong> Our <strong style="color:#22c55e;">FREE API</strong> gives you structured JSON &mdash; 100 req/day, no credit card, instant signup.</span>
<a href="/developers" style="background:#2563eb;color:#fff;padding:8px 20px;border-radius:6px;
text-decoration:none;font-weight:600;white-space:nowrap;font-size:13px;">Get Free API Key &rarr;</a>
<button onclick="this.parentElement.remove()" style="background:none;border:none;color:#94a3b8;
cursor:pointer;font-size:20px;padding:0 4px;margin-left:8px;">&times;</button>
</div>"""

_ip_hit_counter: dict[str, tuple[int, float]] = {}

@app.after_request
def _api_discovery_header(response: Response) -> Response:
    """Advertise API availability on HTML responses. Injects a sticky
    bottom banner when the visitor has made many requests in a window."""
    if not (response.mimetype or "").startswith("text/html"):
        return response
    if response.status_code != 200:
        return response

    response.headers["X-API-Available"] = f"{settings.site_url}/api/v1"
    response.headers["Link"] = (
        f'<{settings.site_url}/developers>; rel="service-doc"; '
        f'title="Cuban Insights API"'
    )

    ip = get_remote_address()
    now = time.time()
    hits, window_start = _ip_hit_counter.get(ip, (0, now))
    if now - window_start > 300:
        hits, window_start = 0, now
    hits += 1
    _ip_hit_counter[ip] = (hits, window_start)

    if hits >= 4 and not request.path.startswith("/developers"):
        try:
            data = response.get_data(as_text=True)
            if "</body>" in data and "ci-api-banner" not in data:
                data = data.replace("</body>", _API_BANNER_HTML + "</body>")
                response.set_data(data)
                response.headers.pop("Content-Length", None)
        except Exception:
            pass

    return response


@app.errorhandler(429)
def _rate_limited(e):
    """Custom 429 page for scrapers — directs them to the paid API."""
    accept = request.headers.get("Accept", "")
    if "json" in accept:
        return jsonify({
            "error": "rate_limit_exceeded",
            "message": "Too many requests. Switch to our FREE API for reliable, structured JSON access.",
            "free_api": "100 requests/day — no credit card, no account, instant key",
            "api_docs": f"{settings.site_url}/developers",
            "api_base": f"{settings.site_url}/api/v1",
            "signup": f"{settings.site_url}/api/v1/keys/signup",
            "signup_example": "curl -X POST {}/api/v1/keys/signup -H 'Content-Type: application/json' -d '{{\"email\":\"you@example.com\"}}'".format(settings.site_url),
        }), 429
    base = settings.site_url
    return Response(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rate Limited — Cuban Insights</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#0a1628;color:#e2e8f0;min-height:100vh;display:flex;align-items:center;justify-content:center}}
.wrap{{max-width:620px;padding:48px 32px;text-align:center}}
.icon{{font-size:64px;margin-bottom:24px}}
h1{{font-size:28px;color:#fff;margin-bottom:12px}}
.sub{{font-size:17px;color:#94a3b8;line-height:1.6;margin-bottom:40px}}
.card{{background:linear-gradient(135deg,#1e293b,#1a2332);border:1px solid #334155;border-radius:16px;padding:32px;margin-bottom:24px;text-align:left}}
.card h2{{font-size:20px;color:#38bdf8;margin-bottom:16px}}
.features{{list-style:none;padding:0}}
.features li{{padding:8px 0;color:#cbd5e1;font-size:15px;display:flex;align-items:center;gap:10px}}
.features li::before{{content:"\\2713";color:#22c55e;font-weight:bold;font-size:18px}}
.cta{{display:inline-block;background:linear-gradient(135deg,#2563eb,#1d4ed8);color:#fff;padding:16px 40px;border-radius:10px;text-decoration:none;font-weight:700;font-size:17px;letter-spacing:0.3px;transition:transform 0.15s,box-shadow 0.15s;margin-top:8px}}
.cta:hover{{transform:translateY(-2px);box-shadow:0 8px 25px rgba(37,99,235,0.4)}}
.or{{color:#64748b;font-size:14px;margin:20px 0}}
.code{{background:#1e293b;border:1px solid #334155;border-radius:8px;padding:16px;font-family:"SF Mono",Monaco,Consolas,monospace;font-size:13px;color:#38bdf8;text-align:left;overflow-x:auto;white-space:pre;margin-bottom:24px;line-height:1.6}}
.code .dim{{color:#475569}}
.free{{color:#22c55e;font-weight:600;font-size:14px;margin-top:12px}}
</style>
</head>
<body>
<div class="wrap">
  <div class="icon">&#9889;</div>
  <h1>You&rsquo;re moving too fast</h1>
  <p class="sub">We noticed heavy traffic from your IP. Instead of scraping HTML,
  get the same data&mdash;cleaner, faster, and more reliable&mdash;through our
  <strong style="color:#22c55e;">free API</strong>.</p>

  <div class="card">
    <h2>Cuban Insights API</h2>
    <ul class="features">
      <li>Daily briefings, FX rates, sanctions feed as structured JSON</li>
      <li>503 S&amp;P 500 company Cuba-exposure profiles</li>
      <li>Investment climate scorecard</li>
      <li>OFAC SDN &amp; Federal Register entries</li>
      <li>No parsing, no breaking changes, no scraping bans</li>
    </ul>
    <p class="free">&#10003; FREE &mdash; 100 requests/day, no credit card, instant signup</p>
  </div>

  <a class="cta" href="{base}/developers">Get Your Free API Key &rarr; It&rsquo;s Free</a>

  <p class="or">or try it right now &mdash; completely free:</p>
  <div class="code"><span class="dim"># Sign up (instant, free)</span>
curl -X POST {base}/api/v1/keys/signup \\
  -H "Content-Type: application/json" \\
  -d '{{"email":"you@example.com"}}'

<span class="dim"># Fetch today's briefing</span>
curl -H "X-API-Key: YOUR_KEY" \\
  {base}/api/v1/briefings/latest</div>

  <p style="color:#475569;font-size:13px;">
    Questions? <a href="mailto:support@layer3labs.io" style="color:#38bdf8;">support@layer3labs.io</a>
  </p>
</div>
</body>
</html>""", 429, {"Content-Type": "text/html; charset=utf-8", "Retry-After": "60"})


logger = logging.getLogger(__name__)


@app.errorhandler(404)
def _handle_404(exc):
    return Response(
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Page Not Found — Cuban Insights</title>'
        '<style>'
        'body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;'
        'background:#f8f9fa;color:#1a1a2e;display:flex;align-items:center;justify-content:center;min-height:100vh}'
        '.box{text-align:center;max-width:480px;padding:2rem}'
        'h1{font-size:1.5rem;margin-bottom:.5rem}'
        'p{color:#555;line-height:1.6}'
        'a{color:#2563eb;text-decoration:none}'
        'a:hover{text-decoration:underline}'
        '</style></head><body><div class="box">'
        '<h1>Page not found</h1>'
        "<p>The page you're looking for doesn't exist or has moved.</p>"
        '<p><a href="/">Return to Cuban Insights</a></p>'
        '</div></body></html>',
        404,
        {"Content-Type": "text/html; charset=utf-8"},
    )


@app.errorhandler(500)
def _handle_500(exc):
    logger.exception("500 Internal Server Error: %s", exc)
    return Response(
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Server Error — Cuban Insights</title>'
        '<style>'
        'body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;'
        'background:#f8f9fa;color:#1a1a2e;display:flex;align-items:center;justify-content:center;min-height:100vh}'
        '.box{text-align:center;max-width:480px;padding:2rem}'
        'h1{font-size:1.5rem;margin-bottom:.5rem}'
        'p{color:#555;line-height:1.6}'
        'a{color:#2563eb;text-decoration:none}'
        'a:hover{text-decoration:underline}'
        '</style></head><body><div class="box">'
        '<h1>Something went wrong</h1>'
        "<p>We hit an unexpected error. The issue has been logged and we're looking into it.</p>"
        '<p><a href="/">Return to Cuban Insights</a></p>'
        '</div></body></html>',
        500,
        {"Content-Type": "text/html; charset=utf-8"},
    )


OUTPUT_DIR = settings.output_dir

BUTTONDOWN_API_URL = "https://api.buttondown.com/v1/subscribers"
FEEDBACK_MAX_MESSAGE_CHARS = 2000

_REPORT_CACHE: dict = {"html": None, "fetched_at": 0.0}
_REPORT_CACHE_TTL_SECONDS = 60

_NAV_CACHE_PATHS = frozenset({
    "/briefing",
    "/invest-in-cuba",
    "/sanctions-tracker",
    "/tools",
    "/explainers",
    "/calendar",
    "/travel",
    "/sources",
})
_NAV_PAGE_CACHE: dict[str, dict] = {}
_NAV_PAGE_CACHE_TTL_SECONDS = 90


def _get_report_html() -> str | None:
    """Return rendered report HTML from Supabase Storage (cached) or local disk."""
    if supabase_storage_read_enabled():
        now = time.time()
        if _REPORT_CACHE["html"] and now - _REPORT_CACHE["fetched_at"] < _REPORT_CACHE_TTL_SECONDS:
            return _REPORT_CACHE["html"]
        html = fetch_report_html()
        if html:
            _REPORT_CACHE["html"] = html
            _REPORT_CACHE["fetched_at"] = now
            return html
        if _REPORT_CACHE["html"]:
            return _REPORT_CACHE["html"]

    report = OUTPUT_DIR / "report.html"
    if report.exists():
        return report.read_text(encoding="utf-8")
    return None


def _normalize_cache_path(path: str) -> str:
    """Normalize `/foo/` and `/foo` to the same cache key."""
    if not path:
        return "/"
    normalized = path.rstrip("/")
    return normalized or "/"


@app.before_request
def _serve_nav_page_cache():
    """Return cached HTML for top-nav pages when still fresh."""
    if request.method != "GET":
        return None
    if request.query_string:
        return None
    path = _normalize_cache_path(request.path or "/")
    if path not in _NAV_CACHE_PATHS:
        return None
    cached = _NAV_PAGE_CACHE.get(path)
    if not cached:
        return None
    if time.time() - cached.get("cached_at", 0.0) > _NAV_PAGE_CACHE_TTL_SECONDS:
        return None
    response = Response(cached["body"], mimetype=cached.get("mimetype", "text/html"))
    response.headers["X-Page-Cache"] = "HIT"
    return response


@app.after_request
def _store_nav_page_cache(response: Response) -> Response:
    """Cache successful HTML responses for top-nav pages."""
    try:
        if request.method != "GET":
            return response
        if request.query_string:
            return response
        if response.status_code != 200:
            return response
        if response.mimetype != "text/html":
            return response

        path = _normalize_cache_path(request.path or "/")
        if path not in _NAV_CACHE_PATHS:
            return response

        _NAV_PAGE_CACHE[path] = {
            "body": response.get_data(),
            "mimetype": response.mimetype,
            "cached_at": time.time(),
        }
        response.headers["X-Page-Cache"] = "MISS"
    except Exception as exc:
        logger.warning("nav page cache skipped due to error: %s", exc)
    return response


def _legacy_redirect_to(target: str, code: int = 301) -> Response:
    """Build a 301 redirect to `target`, preserving any query string."""
    qs = request.query_string.decode()
    if qs:
        return redirect(f"{target}?{qs}", code=code)
    return redirect(target, code=code)


@app.route("/")
@limiter.limit("6 per minute")
def index():
    html = _get_report_html()
    if not html:
        abort(503, description="Report not yet generated. Run the daily pipeline first.")
    if '/developers' not in html:
        html = html.replace(
            'All rights reserved.</p>',
            'All rights reserved. · <a href="/developers" style="color:rgba(255,255,255,0.85);text-decoration:none;">API</a></p>',
        )
    return Response(html, mimetype="text/html")


@app.route("/api/subscribe", methods=["POST"])
def subscribe():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip()

    if not email or "@" not in email:
        return jsonify({"ok": False, "error": "Valid email required"}), 400

    api_key = settings.buttondown_api_key
    if not api_key:
        logger.error("BUTTONDOWN_API_KEY not configured")
        return jsonify({"ok": False, "error": "Newsletter signup is not configured"}), 503

    subscriber_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    if subscriber_ip and "," in subscriber_ip:
        subscriber_ip = subscriber_ip.split(",")[0].strip()

    try:
        resp = httpx.post(
            BUTTONDOWN_API_URL,
            json={
                "email_address": email,
                "type": "regular",
                "ip_address": subscriber_ip,
            },
            headers={
                "Authorization": f"Token {api_key}",
            },
            timeout=15,
        )

        if resp.status_code in (200, 201):
            logger.info("Buttondown subscriber added: %s", email)
            return jsonify({"ok": True})

        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        code = body.get("code", "")

        if resp.status_code == 409 or code == "email_already_exists":
            return jsonify({"ok": True, "note": "Already subscribed"})

        if code == "email_invalid":
            return jsonify({"ok": False, "error": "Please enter a valid email address"}), 400

        if code == "subscriber_blocked":
            logger.warning("Buttondown firewall blocked %s, retrying with bypass", email)
            resp2 = httpx.post(
                BUTTONDOWN_API_URL,
                json={"email_address": email, "type": "regular"},
                headers={
                    "Authorization": f"Token {api_key}",
                    "X-Buttondown-Bypass-Firewall": "true",
                },
                timeout=15,
            )
            body2 = resp2.json() if resp2.headers.get("content-type", "").startswith("application/json") else {}
            code2 = body2.get("code", "")
            if resp2.status_code in (200, 201):
                logger.info("Buttondown subscriber added (bypass): %s", email)
                return jsonify({"ok": True})
            if resp2.status_code == 409 or code2 == "email_already_exists":
                return jsonify({"ok": True, "note": "Already subscribed"})
            logger.error("Buttondown bypass also failed %d: %s", resp2.status_code, resp2.text)

        logger.error("Buttondown API error %d (code=%s): %s", resp.status_code, code, resp.text)
        return jsonify({"ok": False, "error": "Subscription failed, please try again"}), 502

    except Exception as e:
        logger.error("Buttondown request failed: %s", e)
        return jsonify({"ok": False, "error": "Service unavailable"}), 503


def _valid_optional_email(email: str) -> bool:
    if not email:
        return True
    if len(email) > 320:
        return False
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        return False
    local, domain = email.rsplit("@", 1)
    return bool(local.strip() and "." in domain and " " not in email)


def _feedback_page_path(page_url: str) -> str:
    if not page_url:
        return request.path or "/"
    parsed = urlparse(page_url)
    return parsed.path or "/"


def _send_feedback_notification(submission) -> tuple[bool, str | None]:
    from src.newsletter import PROVIDERS

    provider_name = settings.newsletter_provider
    if provider_name not in PROVIDERS:
        return False, f"Unknown email provider: {provider_name}"

    created = submission.created_at or datetime.utcnow()
    date_label = created.strftime("%Y-%m-%d %H:%M UTC")
    subject = f"Cuban Insights feedback - {created.strftime('%Y-%m-%d')}"
    visitor_email = submission.email or "Not provided"
    page_url = submission.page_url or "Not provided"
    referrer = submission.referrer or "Not provided"
    user_agent = submission.user_agent or "Not provided"

    body = f"""
    <div style="font-family: Arial, sans-serif; color: #212529; line-height: 1.55;">
      <h2 style="color: #002b5e; margin: 0 0 12px;">New Cuban Insights feedback</h2>
      <p><strong>Date:</strong> {html.escape(date_label)}</p>
      <p><strong>Site:</strong> {html.escape(submission.site_name or settings.site_name)}</p>
      <p><strong>Visitor email:</strong> {html.escape(visitor_email)}</p>
      <p><strong>Page:</strong> {html.escape(page_url)}</p>
      <p><strong>Referrer:</strong> {html.escape(referrer)}</p>
      <p><strong>User agent:</strong> {html.escape(user_agent)}</p>
      <hr style="border: 0; border-top: 1px solid #e9ecef; margin: 18px 0;">
      <p style="font-size: 15px; white-space: pre-wrap;">{html.escape(submission.message)}</p>
    </div>
    """

    try:
        provider = PROVIDERS[provider_name]()
        ok = provider.send(
            to=settings.feedback_notification_email,
            subject=subject,
            html_body=body,
            from_email=settings.feedback_from_email or None,
        )
        if ok:
            return True, None
        return False, f"Provider {provider_name} did not accept the feedback email"
    except Exception as exc:
        logger.error("Feedback notification failed: %s", exc)
        return False, str(exc)


@app.route("/api/feedback", methods=["POST"])
def feedback():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    email = (data.get("email") or "").strip()
    page_url = (data.get("page_url") or "").strip()

    if not message:
        return jsonify({"ok": False, "error": "Feedback is required"}), 400
    if len(message) > FEEDBACK_MAX_MESSAGE_CHARS:
        return jsonify({"ok": False, "error": "Feedback is too long"}), 400
    if not _valid_optional_email(email):
        return jsonify({"ok": False, "error": "Please enter a valid email address"}), 400

    from src.models import FeedbackSubmission, SessionLocal, init_db

    init_db()
    db = SessionLocal()
    try:
        submission = FeedbackSubmission(
            message=message,
            email=email or None,
            page_url=page_url or None,
            page_path=_feedback_page_path(page_url),
            referrer=(request.headers.get("Referer") or "")[:1000] or None,
            user_agent=(request.headers.get("User-Agent") or "")[:500] or None,
            site_name=settings.site_name or "Cuban Insights",
        )
        db.add(submission)
        db.commit()
        db.refresh(submission)

        email_sent, email_error = _send_feedback_notification(submission)
        submission.email_sent = email_sent
        submission.email_error = email_error
        db.commit()

        if not email_sent:
            logger.error("Feedback saved but email failed: %s", email_error)
            return jsonify({
                "ok": False,
                "error": "Feedback was saved, but the notification email failed. Please try again.",
            }), 502

        return jsonify({"ok": True})
    except Exception as exc:
        db.rollback()
        logger.error("Feedback submission failed: %s", exc)
        return jsonify({"ok": False, "error": "Feedback failed, please try again"}), 503
    finally:
        db.close()


def _tool_seo_jsonld(*, slug: str, title: str, description: str, keywords: str, faq: list[dict] | None = None, dataset: dict | None = None):
    """Build standard SEO + JSON-LD payload for a /tools/* page."""
    from src.page_renderer import _base_url, _iso, settings as _s
    from datetime import datetime as _dt
    import json as _json

    base = _base_url()
    canonical = f"{base}/tools/{slug}"
    seo = {
        "title": title,
        "description": description,
        "keywords": keywords,
        "canonical": canonical,
        "site_name": _s.site_name,
        "site_url": base,
        "locale": _s.site_locale,
        "og_image": f"{base}/static/og-image.png?v=3",
        "og_type": "website",
        "published_iso": _iso(_dt.utcnow()),
        "modified_iso": _iso(_dt.utcnow()),
    }

    graph = [
        {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
                {"@type": "ListItem", "position": 2, "name": "Tools", "item": f"{base}/tools"},
                {"@type": "ListItem", "position": 3, "name": title, "item": canonical},
            ],
        },
        {
            "@type": "WebApplication",
            "@id": f"{canonical}#app",
            "name": title,
            "url": canonical,
            "description": description,
            "applicationCategory": "BusinessApplication",
            "operatingSystem": "Any (browser-based)",
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
            "publisher": {"@type": "Organization", "name": _s.site_name, "url": f"{base}/"},
        },
    ]
    if faq:
        graph.append({
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": q["q"],
                    "acceptedAnswer": {"@type": "Answer", "text": q["a"]},
                }
                for q in faq
            ],
        })
    if dataset:
        graph.append({"@type": "Dataset", "@id": f"{canonical}#dataset", **dataset})

    return seo, _json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False)


_ITA_EXPORT_SPOKES = [
    {
        "path": "/tools/cuba-trade-leads-for-us-companies",
        "name": "Cuba trade leads for U.S. companies",
        "tagline": "Find ITA-style opportunity signals and screen them against OFAC, BIS, CRL, and payment constraints.",
    },
    {
        "path": "/tools/cuba-export-opportunity-finder",
        "name": "Cuba export opportunity finder",
        "tagline": "Map sectors such as agriculture, medical goods, telecom, energy, and logistics to allowed export paths.",
    },
    {
        "path": "/tools/cuba-hs-code-opportunity-finder",
        "name": "Cuba HS code opportunity finder",
        "tagline": "Use HS-code thinking to triage Cuba demand, licensing risk, and documentation steps.",
    },
    {
        "path": "/tools/cuba-export-controls-sanctions-process-map",
        "name": "Cuba export controls and sanctions process map",
        "tagline": "A step-by-step OFAC + BIS + State CRL/CPAL route map for U.S. exporters.",
    },
    {
        "path": "/tools/can-my-us-company-export-to-cuba",
        "name": "Can my U.S. company export to Cuba?",
        "tagline": "Quickly classify whether a Cuba export idea is likely allowed, blocked, or license-dependent.",
    },
    {
        "path": "/tools/cuba-country-contacts-directory",
        "name": "Cuba country contacts directory",
        "tagline": "Start with ITA Trade Americas and U.S. Commercial Service contact paths before approaching counterparties.",
    },
    {
        "path": "/tools/us-company-cuba-market-entry-checklist",
        "name": "U.S. company Cuba market-entry checklist",
        "tagline": "A practical pre-entry checklist for product, counterparty, license, payment, and recordkeeping risk.",
    },
    {
        "path": "/tools/cuba-agricultural-medical-export-checker",
        "name": "Cuba agricultural and medical export eligibility checker",
        "tagline": "Triage TSRA, medical, humanitarian, and support-for-the-Cuban-people channels.",
    },
    {
        "path": "/tools/cuba-telecom-internet-export-checker",
        "name": "Cuba telecom and internet services export checker",
        "tagline": "Evaluate telecom, internet, software, and connectivity exports under CACR carve-outs.",
    },
    {
        "path": "/tools/cuba-mipyme-export-support-checklist",
        "name": "Cuba MIPYME export support checklist",
        "tagline": "Screen whether support for private Cuban businesses can avoid prohibited state counterparties.",
    },
    {
        "path": "/tools/cuba-trade-events-matchmaking-calendar",
        "name": "Cuba trade events and matchmaking calendar",
        "tagline": "Track ITA, Trade Americas, Caribbean, and sector events relevant to Cuba-facing exporters.",
    },
    {
        "path": "/tools/cuba-trade-barriers-tracker",
        "name": "Cuba trade barriers tracker",
        "tagline": "Monitor sanctions, payment, logistics, licensing, and Cuban-side import barriers.",
    },
    {
        "path": "/tools/cuba-export-compliance-checklist",
        "name": "Cuba export compliance checklist",
        "tagline": "Combine ITA opportunity research with OFAC, BIS, State CRL/CPAL, and records controls.",
    },
]

_ITA_OFFICIAL_RESOURCE_LINKS = [
    {
        "label": "ITA Trade Americas contact page",
        "href": "https://www.trade.gov/trade-americas-contact-us",
        "text": "Use for regional export counseling and Commercial Service routing.",
    },
    {
        "label": "ITA Market Intelligence search",
        "href": "https://www.trade.gov/market-intelligence-search",
        "text": "Use for official U.S. government market notes and sector signals.",
    },
    {
        "label": "BIS export controls guidance",
        "href": "https://www.bis.gov/",
        "text": "Use for EAR, ECCN, license, and export-control questions.",
    },
    {
        "label": "OFAC Cuba sanctions program",
        "href": "https://ofac.treasury.gov/sanctions-programs-and-country-information/cuba-sanctions",
        "text": "Use for CACR, sanctions, general licenses, and Cuba program guidance.",
    },
]

_ITA_INTERNAL_RESOURCE_LINKS = [
    {
        "label": "OFAC Cuba General License Lookup",
        "href": "/tools/ofac-cuba-general-licenses",
        "text": "Find the CACR section that could authorize the activity.",
    },
    {
        "label": "OFAC Cuba Sanctions Exposure Checker",
        "href": "/tools/ofac-cuba-sanctions-checker",
        "text": "Search names, companies, vessels, aircraft, or aliases against the Cuba SDN list.",
    },
    {
        "label": "Cuba Restricted List checker",
        "href": "/tools/cuba-restricted-list-checker",
        "text": "Screen GAESA, Gaviota, CIMEX, FINCIMEX, Habaguanex, and other restricted entities.",
    },
    {
        "label": "Public company Cuba exposure check",
        "href": "/tools/public-company-cuba-exposure-check",
        "text": "Use when a U.S.-listed counterparty, supplier, bank, or logistics provider is involved.",
    },
]


def _ita_resource_modules(page_key: str) -> list[dict]:
    base_internal = _ITA_INTERNAL_RESOURCE_LINKS
    official = _ITA_OFFICIAL_RESOURCE_LINKS
    specific: dict[str, list[dict]] = {
        "can-my-us-company-export-to-cuba": [
            {"label": "Cuba export controls and sanctions process map", "href": "/tools/cuba-export-controls-sanctions-process-map", "text": "Use after the quick answer to walk through OFAC, BIS, State, payment, shipping, and records."},
            {"label": "Cuba export compliance checklist", "href": "/tools/cuba-export-compliance-checklist", "text": "Turn the answer into a file-ready compliance checklist before quoting or shipping."},
            {"label": "Cuba country contacts directory", "href": "/tools/cuba-country-contacts-directory", "text": "Find official contact paths when the answer is yellow or you need export counseling."},
        ],
        "cuba-export-controls-sanctions-process-map": [
            {"label": "Can my U.S. company export to Cuba?", "href": "/tools/can-my-us-company-export-to-cuba", "text": "Start here if you do not yet know whether the activity is green, yellow, or red."},
            {"label": "Cuba export compliance checklist", "href": "/tools/cuba-export-compliance-checklist", "text": "Turn the process map into a file-ready compliance checklist."},
            {"label": "Cuba country contacts directory", "href": "/tools/cuba-country-contacts-directory", "text": "Find the right official contact path after the U.S.-side issue list is clear."},
        ],
        "cuba-trade-leads-for-us-companies": [
            {"label": "Cuba export opportunity finder", "href": "/tools/cuba-export-opportunity-finder", "text": "Compare a lead against sector demand and Cuba-specific execution barriers."},
            {"label": "Cuba export controls and sanctions process map", "href": "/tools/cuba-export-controls-sanctions-process-map", "text": "Screen the lead before any outreach or quote."},
            {"label": "U.S. company Cuba market-entry checklist", "href": "/tools/us-company-cuba-market-entry-checklist", "text": "Prepare the facts you need before contacting a buyer."},
        ],
        "cuba-country-contacts-directory": [
            {"label": "U.S. company Cuba market-entry checklist", "href": "/tools/us-company-cuba-market-entry-checklist", "text": "Organize your product, buyer, payment, and shipping questions before contacting ITA."},
            {"label": "Cuba trade events and matchmaking calendar", "href": "/tools/cuba-trade-events-matchmaking-calendar", "text": "Find official and sector events that may create warmer contact paths."},
            {"label": "Cuba export compliance checklist", "href": "/tools/cuba-export-compliance-checklist", "text": "Bring a clean compliance file to an advisor or counsel."},
        ],
        "us-company-cuba-market-entry-checklist": [
            {"label": "Cuba country contacts directory", "href": "/tools/cuba-country-contacts-directory", "text": "Find official counseling contacts once the checklist is mostly complete."},
            {"label": "Cuba trade barriers tracker", "href": "/tools/cuba-trade-barriers-tracker", "text": "Check operational blockers before assuming the market-entry plan can execute."},
            {"label": "Cuba export compliance checklist", "href": "/tools/cuba-export-compliance-checklist", "text": "Convert market-entry notes into compliance records."},
        ],
    }
    default_specific = [
        {"label": "Export to Cuba hub", "href": "/export-to-cuba", "text": "Return to the ordered hub workflow and choose the next tool."},
        {"label": "Can my U.S. company export to Cuba?", "href": "/tools/can-my-us-company-export-to-cuba", "text": "Classify the opportunity before acting on it."},
        {"label": "Cuba export controls and sanctions process map", "href": "/tools/cuba-export-controls-sanctions-process-map", "text": "Move from opportunity to compliance decision path."},
    ]
    return [
        {
            "heading": "Use Next",
            "subheading": "Internal tools that make this page actionable.",
            "links": specific.get(page_key, default_specific),
        },
        {
            "heading": "Screen Internally",
            "subheading": "Cuban Insights checks to run before outreach or shipment.",
            "links": base_internal,
        },
        {
            "heading": "Official Contacts & Sources",
            "subheading": "Use these for counseling, authority, and source-of-truth checks.",
            "links": official,
        },
    ]


def _ita_export_pages() -> dict[str, dict]:
    common_chips = ["ITA / Trade.gov", "U.S. exporters", "OFAC + BIS + State screening"]
    common_spokes = _ITA_EXPORT_SPOKES
    return {
        "export-to-cuba": {
            "path": "/export-to-cuba",
            "short_title": "Export to Cuba",
            "eyebrow": "Export hub · ITA + sanctions-aware",
            "title": "Export to Cuba: U.S. Company Opportunity and Compliance Hub",
            "lede": "A Cuba-specific hub for U.S. exporters that pairs International Trade Administration opportunity data with the compliance stack that actually governs Cuba: OFAC CACR general licenses, BIS export controls, the State Department Cuba Restricted List, payment constraints, and Cuban private-sector limits.",
            "description": "Cuba export hub for U.S. companies: ITA trade leads, market intelligence, HS code opportunity triage, OFAC/BIS sanctions process map, contacts, events, trade barriers, and market-entry checklist.",
            "keywords": "export to Cuba, Cuba trade leads, Cuba export controls, ITA Cuba, Trade.gov Cuba, Cuba market entry, Cuba sanctions process map",
            "chips": ["Hub page", *common_chips],
            "spokes": common_spokes,
            "hub_groups": [
                {
                    "heading": "Start Here",
                    "subheading": "Use these in order. The goal is to move from a commercial idea to a defensible go / no-go decision.",
                    "cards": [
                        {
                            "eyebrow": "Step 1",
                            "title": "Can my U.S. company export to Cuba?",
                            "text": "Start with the decision tree before opening leads or contacting a buyer.",
                            "href": "/tools/can-my-us-company-export-to-cuba",
                            "cta": "Start decision tree",
                        },
                        {
                            "eyebrow": "Step 2",
                            "title": "Find Cuba trade leads",
                            "text": "Review ITA-style opportunity signals only after you know what questions to ask.",
                            "href": "/tools/cuba-trade-leads-for-us-companies",
                            "cta": "Open leads tool",
                        },
                        {
                            "eyebrow": "Step 3",
                            "title": "Run the compliance process map",
                            "text": "Route the product, counterparty, payment, shipping, and records through OFAC, BIS, and State checks.",
                            "href": "/tools/cuba-export-controls-sanctions-process-map",
                            "cta": "Open process map",
                        },
                    ],
                },
                {
                    "heading": "Resource Library",
                    "subheading": "Pick the resource that matches the question you are trying to answer right now.",
                    "cards": [
                        {
                            "eyebrow": "Product",
                            "title": "HS code opportunity finder",
                            "text": "Use when you know the product category and need a product-level triage path.",
                            "href": "/tools/cuba-hs-code-opportunity-finder",
                            "cta": "Classify product",
                        },
                        {
                            "eyebrow": "Sector",
                            "title": "Export opportunity finder",
                            "text": "Use when you are comparing agriculture, medical, telecom, energy, logistics, or MIPYME demand.",
                            "href": "/tools/cuba-export-opportunity-finder",
                            "cta": "Compare sectors",
                        },
                        {
                            "eyebrow": "Checklist",
                            "title": "Export compliance checklist",
                            "text": "Use before quoting, signing, shipping, financing, or traveling for a Cuba opportunity.",
                            "href": "/tools/cuba-export-compliance-checklist",
                            "cta": "Open checklist",
                        },
                        {
                            "eyebrow": "Agriculture / Medical",
                            "title": "Ag and medical export checker",
                            "text": "Use for food, agricultural commodities, medicines, devices, healthcare, or humanitarian channels.",
                            "href": "/tools/cuba-agricultural-medical-export-checker",
                            "cta": "Check eligibility",
                        },
                        {
                            "eyebrow": "Telecom / Internet",
                            "title": "Telecom export checker",
                            "text": "Use for software, cloud, connectivity, communications, and information-flow exports.",
                            "href": "/tools/cuba-telecom-internet-export-checker",
                            "cta": "Check telecom path",
                        },
                        {
                            "eyebrow": "Private Sector",
                            "title": "MIPYME support checklist",
                            "text": "Use when the buyer claims to be private-sector-facing or MIPYME-related.",
                            "href": "/tools/cuba-mipyme-export-support-checklist",
                            "cta": "Screen MIPYME path",
                        },
                    ],
                },
                {
                    "heading": "Who to Contact",
                    "subheading": "Do not contact a Cuban counterparty before the U.S.-side path is clear enough to describe.",
                    "cards": [
                        {
                            "eyebrow": "Official counseling",
                            "title": "ITA / Trade Americas contacts",
                            "text": "Use for export counseling, regional market context, and finding the right U.S. government contact path.",
                            "href": "/tools/cuba-country-contacts-directory",
                            "cta": "Find contacts",
                        },
                        {
                            "eyebrow": "Buyer follow-up",
                            "title": "Market-entry checklist",
                            "text": "Use before outreach to organize product, buyer, owner, bank, shipper, and records questions.",
                            "href": "/tools/us-company-cuba-market-entry-checklist",
                            "cta": "Prepare outreach",
                        },
                        {
                            "eyebrow": "Events",
                            "title": "Trade events and matchmaking",
                            "text": "Use for Trade Americas, Caribbean, virtual counseling, and sector events that may generate leads.",
                            "href": "/tools/cuba-trade-events-matchmaking-calendar",
                            "cta": "Open calendar",
                        },
                    ],
                },
            ],
            "sections": [
                {
                    "heading": "Recommended Order",
                    "body": "Use the hub like a workflow, not a reading list. Each step should leave you with either a green, yellow, or red answer.",
                    "items": [
                        "<strong>1. Product:</strong> define the product, service, software, technology, HS code question, and end use.",
                        "<strong>2. Authorization:</strong> check OFAC CACR, BIS controls, and whether the transaction is generally authorized, license-dependent, or blocked.",
                        "<strong>3. Counterparty:</strong> screen buyer, beneficial owner, importer, bank, hotel, vessel, aircraft, and logistics provider.",
                        "<strong>4. Execution:</strong> test payment, shipping, Cuban-side import channel, recordkeeping, and hard-currency constraints.",
                        "<strong>5. Contact:</strong> use ITA / Trade Americas or counsel before approaching a Cuban counterparty if the answer is yellow.",
                    ],
                },
                {
                    "heading": "What to Collect Before Contacting Anyone",
                    "items": [
                        "Product description, HS code or classification notes, end use, and technical specifications.",
                        "Buyer legal name, trade name, parent owner, beneficial owner, importer, address, and website.",
                        "Payment route, bank, currency, shipping route, logistics provider, and delivery location.",
                        "Screening results for OFAC SDN, State CRL, CPAL, GAESA, Gaviota, CIMEX, FINCIMEX, and military-control indicators.",
                    ],
                },
                {
                    "heading": "Best-Fit Sectors to Monitor",
                    "items": [
                        "Agricultural commodities and food inputs under TSRA-style export channels.",
                        "Medical devices, medicines, healthcare technology, and humanitarian support.",
                        "Telecom, internet connectivity, software, cloud, and information-flow tools.",
                        "Energy resilience, logistics, cold chain, construction inputs, and private-sector equipment where licensing permits.",
                    ],
                },
            ],
        },
        "cuba-trade-leads-for-us-companies": {
            "short_title": "Cuba Trade Leads",
            "eyebrow": "Trade leads · U.S. exporters",
            "title": "Cuba Trade Leads for U.S. Companies",
            "lede": "A sanctions-aware view of Cuba trade leads: useful demand signals, but only after the counterparty, product, license, payment, and Cuban-side importer risks are checked.",
            "description": "Find and evaluate Cuba trade leads for U.S. companies with ITA opportunity data plus OFAC, BIS, CRL, CPAL, and payment-risk screening.",
            "keywords": "Cuba trade leads, trade leads Cuba, U.S. companies Cuba export opportunities, ITA trade leads Cuba",
            "chips": common_chips,
            "sections": [
                {"heading": "What counts as a usable lead", "items": ["A lead must identify a plausible buyer, sector, product or service, timing, and source.", "For Cuba, a lead is incomplete until the buyer and payment route clear sanctions and restricted-list screening.", "Leads involving state tourism, military-controlled distributors, or opaque import companies need enhanced review."]},
                {"heading": "Lead triage workflow", "ordered": True, "items": ["Classify the opportunity by sector and product.", "Run SDN, CRL, and CPAL checks on every named entity and parent company.", "Check whether the export can fit TSRA, medical/humanitarian, telecom, informational materials, or support-for-the-Cuban-people channels.", "Document why the lead is allowed, blocked, or needs counsel / licensing."]},
            ],
        },
        "cuba-export-opportunity-finder": {
            "short_title": "Export Opportunity Finder",
            "eyebrow": "Opportunity finder · Cuba sectors",
            "title": "Cuba Export Opportunity Finder",
            "lede": "A sector-first map of where U.S. exporters may find Cuba demand, with the compliance filters shown before the commercial upside.",
            "description": "Cuba export opportunity finder for U.S. companies by sector, combining ITA market intelligence with sanctions, licensing, and counterparty checks.",
            "keywords": "Cuba export opportunities, export opportunity finder Cuba, U.S. exports to Cuba sectors",
            "chips": common_chips,
            "sections": [
                {"heading": "Highest-signal categories", "items": ["Agriculture and food supply chains.", "Medical and humanitarian goods.", "Telecom, internet, information, and software access.", "Energy resilience, logistics, and private-sector equipment where licensing and counterparties permit."]},
                {"heading": "What makes Cuba different", "body": "The demand signal is only one part of the answer. The binding constraints are often licensing, payment, logistics, and who controls the Cuban buyer.", "items": ["Private-sector MIPYME demand is not the same as state-enterprise demand.", "A legal product can still fail if the buyer or payment channel is blocked.", "Cuban-side import rules and hard-currency scarcity can turn apparent demand into non-performance risk."]},
            ],
        },
        "cuba-hs-code-opportunity-finder": {
            "short_title": "HS Code Finder",
            "eyebrow": "HS code tool · Product triage",
            "title": "Cuba HS Code Opportunity Finder",
            "lede": "Use HS-code thinking to turn a product idea into a Cuba export workflow: demand signal, product classification, licensing question, counterparty screen, and documentation trail.",
            "description": "Cuba HS code opportunity finder for U.S. exporters evaluating product-level demand, OFAC/BIS licensing risk, and documentation requirements.",
            "keywords": "Cuba HS code, export HS code Cuba, Cuba product opportunity finder, U.S. exporter HS code Cuba",
            "chips": ["HS code", *common_chips],
            "sections": [
                {"heading": "How to use HS codes in Cuba research", "items": ["Start with the product's likely HS chapter and description.", "Map the product to Cuba-sensitive sectors: food, medicine, telecom, energy, construction, transport, or state tourism.", "Use the HS question as a prompt for BIS / ECCN review, not as a substitute for it."]},
                {"heading": "Product-level checkpoints", "ordered": True, "items": ["Identify product and end use.", "Screen end user and importer.", "Check OFAC authorization path.", "Check BIS controls and license requirements.", "Store the classification rationale with source URLs and counsel notes."]},
            ],
        },
        "cuba-export-controls-sanctions-process-map": {
            "short_title": "Process Map",
            "eyebrow": "Process map · OFAC + BIS",
            "title": "Cuba Export Controls and Sanctions Process Map",
            "lede": "A practical route map for U.S. exporters: before you quote, ship, finance, or meet a Cuban counterparty, walk the opportunity through the Cuba sanctions and export-control stack.",
            "description": "Cuba export controls and sanctions process map covering OFAC CACR, BIS export controls, State CRL/CPAL, payment routes, and recordkeeping.",
            "keywords": "Cuba export controls, Cuba sanctions process map, OFAC BIS Cuba exports, CACR export compliance",
            "chips": ["Process map", *common_chips],
            "sections": [
                {"heading": "Start With This Answer", "body": "A Cuba export is not actionable until it clears four gates: OFAC authorization, BIS product / technology controls, restricted-party screening, and executable payment / shipping. If one gate is unknown, the answer is yellow until it is resolved.", "items": ["Use <a href=\"/tools/can-my-us-company-export-to-cuba\">Can my U.S. company export to Cuba?</a> if you need the quick green / yellow / red classification first.", "Use <a href=\"/tools/ofac-cuba-general-licenses\">OFAC Cuba General License Lookup</a> to find the possible CACR authorization basis.", "Use <a href=\"/tools/cuba-restricted-list-checker\">Cuba Restricted List checker</a> and <a href=\"/tools/ofac-cuba-sanctions-checker\">OFAC Cuba Sanctions Exposure Checker</a> before any outreach."]},
                {"heading": "Before taking action", "ordered": True, "items": ["Define the transaction, product, service, software, technology, end use, and every party.", "Identify the OFAC general license, OFAC specific license path, or reason the activity is not authorized.", "Check product / technology controls through BIS and document ECCN / EAR99 thinking.", "Screen names, parents, owners, addresses, hotels, vessels, aircraft, banks, and payment intermediaries.", "If any answer is yellow, contact <a href=\"/tools/cuba-country-contacts-directory\">Cuba country contacts</a>, ITA Trade Americas, BIS, OFAC, or counsel before quoting or shipping.", "Keep records for the full required retention period."]},
            ],
        },
        "cuba-country-contacts-directory": {
            "short_title": "Contacts Directory",
            "eyebrow": "Contacts · ITA Trade Americas",
            "title": "Cuba Country Contacts Directory for U.S. Exporters",
            "lede": "A directory-style starting point for U.S. exporters who need official counseling, Trade Americas context, sector specialists, and compliance-aware next steps before approaching Cuba.",
            "description": "Cuba country contacts directory for U.S. exporters, pointing to ITA Trade Americas, Commercial Service resources, sector specialists, and compliance tools.",
            "keywords": "Cuba country contacts, ITA Cuba contacts, Commercial Service Cuba, Trade Americas Cuba contacts",
            "chips": ["Contacts", *common_chips],
            "sections": [
                {"heading": "Who to contact first", "items": ["ITA Trade Americas for regional export counseling and market intelligence.", "Relevant U.S. Commercial Service domestic office for exporter readiness.", "Sector specialists for agriculture, healthcare, telecom, energy, logistics, or professional services.", "Trade counsel for OFAC/BIS interpretation before relying on a lead."]},
                {"heading": "Questions to bring", "items": ["What is the product, end use, buyer, payment route, and shipping path?", "Does the buyer touch a restricted Cuban state or military-controlled entity?", "Is this a private-sector support case, a humanitarian case, a telecom case, or a blocked case?"]},
            ],
        },
        "can-my-us-company-export-to-cuba": {
            "short_title": "Can My Company Export?",
            "eyebrow": "Decision tree · U.S. exporters",
            "title": "Can My U.S. Company Export to Cuba?",
            "lede": "A plain-English decision tree for U.S. companies: identify the product, buyer, authorization path, export controls, restricted-party risk, payment route, and records before treating any Cuba opportunity as actionable.",
            "description": "Decision tree for whether a U.S. company can export to Cuba, covering OFAC CACR, BIS export controls, State CRL/CPAL, product eligibility, counterparties, payment, and records.",
            "keywords": "can my company export to Cuba, U.S. company export to Cuba, can I export to Cuba, OFAC BIS Cuba export decision tree",
            "chips": ["Decision tree", *common_chips],
            "sections": [
                {"heading": "Short Answer", "kind": "callout", "body": "Yes, a U.S. company can export some goods and services to Cuba, but only in narrow authorized channels. The practical answer depends on the product, end use, Cuban buyer, payment route, shipping path, and whether OFAC or BIS licensing is required.", "items": ["<strong>Likely yes:</strong> informational materials, some telecom / internet services, certain agricultural or medical exports, and some support for genuinely private Cuban businesses when parties and payment routes screen clean.", "<strong>Maybe / get review:</strong> software, equipment, services, or MIPYME support where the importer, bank, logistics provider, or end user may touch the Cuban state sector. Use the <a href=\"/tools/cuba-export-controls-sanctions-process-map\">process map</a> next.", "<strong>Likely no:</strong> transactions involving SDN-listed parties, Cuba Restricted List entities, Cuban military-controlled companies, prohibited lodging, blocked payment routes, or state tourism counterparties."]},
                {"heading": "Answer These Six Questions", "ordered": True, "items": ["<strong>What are you exporting?</strong> Product, service, software, technology, or data.", "<strong>Who receives it?</strong> End user, importer, beneficial owner, bank, shipper, and delivery location.", "<strong>Why is it allowed?</strong> OFAC general license, specific license, statutory channel, or no authorization.", "<strong>Does BIS control it?</strong> ECCN / EAR99, Cuba license requirement, license exception, or no-license determination.", "<strong>Is anyone restricted?</strong> SDN, CRL, CPAL, GAESA, Gaviota, CIMEX, FINCIMEX, ETECSA, or military-control exposure.", "<strong>Can you execute it?</strong> Payment, shipping, insurance, records, and Cuban-side import channel are feasible."]},
                {"heading": "Simple Result", "items": ["<strong>Green:</strong> product fits an authorized channel, parties screen clean, BIS path is clear, payment/shipping work, and records are retained.", "<strong>Yellow:</strong> possible, but you need counsel, ITA/BIS/OFAC guidance, a license, or missing counterparty ownership facts.", "<strong>Red:</strong> blocked party, military-controlled buyer, prohibited payment route, prohibited end use, or no defensible authorization path."]},
            ],
        },
        "us-company-cuba-market-entry-checklist": {
            "short_title": "Market-Entry Checklist",
            "eyebrow": "Checklist · Market entry",
            "title": "U.S. Company Cuba Market-Entry Checklist",
            "lede": "A pre-entry checklist for U.S. companies considering Cuba: commercial thesis first, then product authorization, counterparty screening, payment reality, and recordkeeping.",
            "description": "U.S. company Cuba market-entry checklist covering product fit, sanctions, export controls, counterparties, payments, logistics, and records.",
            "keywords": "Cuba market entry checklist, U.S. company Cuba checklist, doing business Cuba U.S. exporter",
            "chips": ["Checklist", *common_chips],
            "sections": [
                {"heading": "Checklist", "ordered": True, "items": ["Define the exportable product or service.", "Identify Cuban buyer, beneficial owner, importer, bank, and logistics provider.", "Check OFAC general license / specific license path.", "Check BIS export controls.", "Screen SDN, CRL, CPAL, GAESA/Gaviota/CIMEX/FINCIMEX exposure.", "Validate payment and hard-currency mechanics.", "Keep written records of every decision."]},
                {"heading": "Common failure points", "items": ["Assuming private-sector support applies when the importer is state-controlled.", "Ignoring payment routing and bank de-risking.", "Treating a Trade.gov opportunity as legal authorization. It is a signal, not permission."]},
            ],
        },
        "cuba-agricultural-medical-export-checker": {
            "short_title": "Agricultural / Medical Exports",
            "eyebrow": "Eligibility checker · Ag + medical",
            "title": "Cuba Agricultural and Medical Export Eligibility Checker",
            "lede": "Agricultural and medical exports are among the most plausible U.S.-to-Cuba channels, but they still require product, end-user, financing, shipping, and records analysis.",
            "description": "Cuba agricultural and medical export eligibility checker for U.S. exporters evaluating TSRA, medical, humanitarian, OFAC, and BIS constraints.",
            "keywords": "Cuba agricultural exports, Cuba medical exports, TSRA Cuba, export food medicine Cuba",
            "chips": ["Agriculture", "Medical", *common_chips],
            "sections": [
                {"heading": "Likely channels to evaluate", "items": ["Food, agricultural commodities, inputs, and related equipment.", "Medicines, medical devices, healthcare supplies, and humanitarian goods.", "Support services that are necessary and ordinarily incident to authorized exports."]},
                {"heading": "Checks before shipment", "ordered": True, "items": ["Confirm product classification.", "Confirm buyer and end user.", "Check payment / financing restrictions.", "Check BIS license requirements.", "Document OFAC authorization and shipping route."]},
            ],
        },
        "cuba-telecom-internet-export-checker": {
            "short_title": "Telecom / Internet Exports",
            "eyebrow": "Eligibility checker · Telecom",
            "title": "Cuba Telecom and Internet Services Export Checker",
            "lede": "Telecom, internet, software, and information-flow tools can have Cuba authorization paths, but ETECSA/state-control, technology controls, and payment mechanics still matter.",
            "description": "Cuba telecom and internet services export checker covering CACR telecom carve-outs, software, connectivity, ETECSA risk, and BIS controls.",
            "keywords": "Cuba telecom exports, Cuba internet services export, software exports Cuba, CACR telecom Cuba",
            "chips": ["Telecom", "Internet", *common_chips],
            "sections": [
                {"heading": "Relevant categories", "items": ["Internet connectivity and communications tools.", "Software and services that support information flow.", "Telecom equipment, cloud, hosting, and related professional services."]},
                {"heading": "Risk questions", "items": ["Does the transaction involve ETECSA or another state-controlled entity?", "Is the software or equipment controlled under BIS rules?", "Does the payment route require a prohibited Cuban financial intermediary?", "Can records show the activity supports authorized communications access?"]},
            ],
        },
        "cuba-mipyme-export-support-checklist": {
            "short_title": "MIPYME Support Checklist",
            "eyebrow": "Checklist · Private sector",
            "title": "Cuba MIPYME Export Support Checklist",
            "lede": "Cuba's private-sector MIPYMES create a real commercial thesis, but exporters need to prove the support is private-sector-facing and not routed through restricted state or military entities.",
            "description": "Cuba MIPYME export support checklist for U.S. exporters supporting private Cuban businesses while avoiding restricted counterparties.",
            "keywords": "Cuba MIPYME exports, support for Cuban private sector, Cuba private business export checklist",
            "chips": ["MIPYME", "Private sector", *common_chips],
            "sections": [
                {"heading": "What to verify", "items": ["The Cuban business is privately registered and not a front for a state or military entity.", "The importer, payment route, warehouse, hotel, or logistics provider is not CRL/SDN-linked.", "The goods or services fit an authorized support category.", "Records show end use, end user, payment path, and delivery chain."]},
                {"heading": "Practical constraints", "items": ["Many MIPYMES still rely on state-controlled import channels.", "Hard-currency scarcity can delay payment.", "Beneficial ownership and political exposure may not be obvious from the trade name alone."]},
            ],
        },
        "cuba-trade-events-matchmaking-calendar": {
            "short_title": "Events Calendar",
            "eyebrow": "Calendar · Trade events",
            "title": "Cuba Trade Events and Matchmaking Calendar",
            "lede": "Track ITA, Trade Americas, Caribbean, and sector events that could create Cuba-relevant export leads, then screen any lead before treating it as actionable.",
            "description": "Cuba trade events and matchmaking calendar for U.S. exporters monitoring ITA, Trade Americas, Caribbean, and sector-specific opportunity events.",
            "keywords": "Cuba trade events, Cuba matchmaking, Trade Americas events Cuba, ITA events Cuba",
            "chips": ["Events", "Matchmaking", *common_chips],
            "sections": [
                {"heading": "Events worth monitoring", "items": ["Trade Americas regional programming.", "Agriculture, healthcare, telecom, energy, logistics, and Caribbean infrastructure events.", "Virtual export counseling and market-intelligence sessions.", "Business matchmaking where Cuba, Caribbean, or restricted-market compliance is discussed."]},
                {"heading": "Post-event workflow", "ordered": True, "items": ["Capture lead details and source.", "Tag sector and product.", "Screen all named parties.", "Route product and technology through OFAC/BIS analysis.", "Add follow-up deadlines and recordkeeping notes."]},
            ],
        },
        "cuba-trade-barriers-tracker": {
            "short_title": "Trade Barriers",
            "eyebrow": "Tracker · Trade barriers",
            "title": "Cuba Trade Barriers Tracker",
            "lede": "Cuba trade barriers are not just tariffs. The real blockers include U.S. sanctions, export controls, Cuban import channels, currency scarcity, payment de-risking, logistics, and state-sector concentration.",
            "description": "Cuba trade barriers tracker covering sanctions, export controls, payment channels, Cuban import rules, logistics, and private-sector limits.",
            "keywords": "Cuba trade barriers, Cuba export barriers, U.S. trade barriers Cuba, payment barriers Cuba exports",
            "chips": ["Trade barriers", *common_chips],
            "sections": [
                {"heading": "Barrier categories", "items": ["OFAC authorization limits.", "BIS licensing and controlled technology.", "State / military-controlled counterparties.", "Payment and correspondent-banking de-risking.", "Cuban import permits, hard-currency scarcity, and state distribution bottlenecks.", "Shipping, insurance, and documentation friction."]},
                {"heading": "How to use this tracker", "body": "Treat barriers as a living checklist. A sector can be commercially attractive and still be blocked by one operational step.", "items": ["Attach every barrier to a source URL.", "Separate U.S.-side legal blockers from Cuban-side execution blockers.", "Update the conclusion when ITA, OFAC, BIS, State, or Cuban official sources change."]},
            ],
        },
        "cuba-export-compliance-checklist": {
            "short_title": "Export Compliance Checklist",
            "eyebrow": "Checklist · Compliance",
            "title": "Cuba Export Compliance Checklist: ITA + OFAC + BIS + State",
            "lede": "The all-in-one Cuba export compliance checklist: use ITA to find the commercial signal, then use OFAC, BIS, State CRL/CPAL, and records controls to decide whether the transaction can proceed.",
            "description": "Cuba export compliance checklist for U.S. companies combining ITA opportunity research with OFAC, BIS, State CRL/CPAL, payments, logistics, and records.",
            "keywords": "Cuba export compliance checklist, OFAC BIS Cuba exports, ITA OFAC Cuba checklist, State CRL Cuba export compliance",
            "chips": ["Compliance", *common_chips],
            "sections": [
                {"heading": "Minimum compliance file", "items": ["Product / service description and classification rationale.", "End user, beneficial owner, importer, bank, logistics provider, vessel, and hotel if travel is involved.", "OFAC authorization basis or license request path.", "BIS classification and license analysis.", "SDN, CRL, CPAL, and known Cuban military-control screening results.", "Payment, shipping, and recordkeeping plan."]},
                {"heading": "Traffic-light result", "items": ["Green: authorized path, clean parties, feasible payment, records retained.", "Yellow: possible path but needs counsel, license, or missing counterparty data.", "Red: blocked party, blocked category, prohibited payment route, or no defensible authorization."]},
            ],
        },
    }


def _render_ita_export_page(page_key: str):
    try:
        from src.page_renderer import _env, _base_url, _iso, settings as _s
        from datetime import date as _date, datetime as _dt
        import json as _json
        import re as _re
        from src.models import ExternalArticleEntry, SessionLocal, SourceType, init_db

        pages = _ita_export_pages()
        page = pages.get(page_key)
        if not page:
            abort(404)

        base = _base_url()
        path = page.get("path") or f"/tools/{page_key}"
        canonical = f"{base}{path}"
        seo = {
            "title": page["title"],
            "description": page["description"],
            "keywords": page["keywords"],
            "canonical": canonical,
            "site_name": _s.site_name,
            "site_url": base,
            "locale": _s.site_locale,
            "og_image": f"{base}/static/og-image.png?v=3",
            "og_type": "website",
            "published_iso": _iso(_dt.utcnow()),
            "modified_iso": _iso(_dt.utcnow()),
        }
        jsonld = _json.dumps({
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
                        {"@type": "ListItem", "position": 2, "name": "Tools", "item": f"{base}/tools"},
                        {"@type": "ListItem", "position": 3, "name": page["title"], "item": canonical},
                    ],
                },
                {
                    "@type": "WebApplication",
                    "@id": f"{canonical}#app",
                    "name": page["title"],
                    "url": canonical,
                    "description": page["description"],
                    "applicationCategory": "BusinessApplication",
                    "operatingSystem": "Any (browser-based)",
                    "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
                    "publisher": {"@type": "Organization", "name": _s.site_name, "url": f"{base}/"},
                    "isBasedOn": [
                        "https://developer.trade.gov/",
                        "https://www.trade.gov/market-intelligence-search",
                        "https://data.commerce.gov/trade-leads-api",
                    ],
                },
            ],
        }, ensure_ascii=False)

        from src.seo.cluster_topology import build_cluster_ctx, build_related_tools_ctx
        cluster_ctx = build_cluster_ctx(path)
        related_tools_ctx = build_related_tools_ctx(path)
        raw_resource_modules = page.get("resource_modules", _ita_resource_modules(page_key))
        resource_modules = []
        for group in raw_resource_modules:
            links = [link for link in group.get("links", []) if link.get("href") != path]
            if links:
                resource_modules.append({**group, "links": links})

        def _normalize_text(value: str | None) -> str:
            return _re.sub(r"\s+", " ", value or "").strip()

        def _truncate_text(value: str, limit: int = 280) -> str:
            value = _normalize_text(value)
            if len(value) <= limit:
                return value
            clipped = value[: limit - 1].rsplit(" ", 1)[0].strip()
            return f"{clipped or value[: limit - 1]}…"

        def _is_cuba_specific(row: ExternalArticleEntry) -> bool:
            text = " ".join([
                row.headline or "",
                row.body_text or "",
                row.source_url or "",
            ]).lower()
            return any(term in text for term in ("cuba", "cuban", "havana"))

        live_item_specs = {
            "cuba-trade-leads-for-us-companies": {
                "article_types": ("trade_lead",),
                "heading": "Current Leads From Government Sources",
                "empty_heading": "Current Leads",
                "empty_message": "There are no leads currently.",
                "empty_detail": (
                    "This page only shows real Trade.gov / government-sourced Cuba leads "
                    "stored in the database. It does not generate filler opportunities."
                ),
                "hide_static_sections_when_empty": True,
            },
            "cuba-export-opportunity-finder": {
                "article_types": ("trade_lead", "market_intelligence"),
                "heading": "Current Government-Sourced Opportunities",
                "empty_heading": "Current Opportunities",
                "empty_message": "There are no leads currently.",
                "empty_detail": (
                    "This page only shows real Trade.gov / government-sourced Cuba opportunities "
                    "stored in the database. It does not invent sector ideas when no source data exists."
                ),
                "hide_static_sections_when_empty": True,
            },
        }

        live_items: list[dict] = []
        live_spec = live_item_specs.get(page_key)
        live_error = None
        if live_spec:
            try:
                init_db()
                db = SessionLocal()
                try:
                    rows = (
                        db.query(ExternalArticleEntry)
                        .filter(ExternalArticleEntry.source == SourceType.ITA_TRADE)
                        .filter(ExternalArticleEntry.article_type.in_(live_spec["article_types"]))
                        .order_by(ExternalArticleEntry.published_date.desc(), ExternalArticleEntry.id.desc())
                        .limit(60)
                        .all()
                    )
                finally:
                    db.close()

                for row in rows:
                    if not row.source_url or "trade.gov" not in row.source_url.lower():
                        continue
                    if not _is_cuba_specific(row):
                        continue
                    live_items.append({
                        "title": _normalize_text(row.headline) or "Untitled Trade.gov item",
                        "href": row.source_url,
                        "date": row.published_date.isoformat() if row.published_date else "",
                        "type": (row.article_type or "government_item").replace("_", " ").title(),
                        "summary": _truncate_text(row.body_text or row.headline or ""),
                    })
                    if len(live_items) >= 12:
                        break
            except Exception as exc:
                logger.warning("ITA live item fetch failed for %s: %s", page_key, exc)
                live_error = str(exc)

        sections = page.get("sections", [])
        if live_spec and live_spec.get("hide_static_sections_when_empty") and not live_items:
            sections = []

        template = _env.get_template("tools/ita_export_page.html.j2")
        html = template.render(
            page={
                **page,
                "spokes": page.get("spokes", _ITA_EXPORT_SPOKES),
                "short_title": page.get("short_title", page["title"]),
                "resource_modules": resource_modules,
                "sections": sections,
                "live_items": live_items,
                "live_items_heading": live_spec.get("heading") if live_spec else None,
                "empty_items_heading": live_spec.get("empty_heading") if live_spec else None,
                "empty_items_message": live_spec.get("empty_message") if live_spec else None,
                "empty_items_detail": live_spec.get("empty_detail") if live_spec else None,
                "live_error": live_error,
            },
            seo=seo,
            jsonld=jsonld,
            cluster_ctx=cluster_ctx,
            related_tools_ctx=related_tools_ctx,
            current_year=_date.today().year,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise


@app.route("/export-to-cuba")
@app.route("/export-to-cuba/")
def export_to_cuba_hub():
    return _render_ita_export_page("export-to-cuba")


@app.route("/tools/cuba-trade-leads-for-us-companies")
@app.route("/tools/cuba-trade-leads-for-us-companies/")
def tool_cuba_trade_leads():
    return _render_ita_export_page("cuba-trade-leads-for-us-companies")


@app.route("/tools/cuba-export-opportunity-finder")
@app.route("/tools/cuba-export-opportunity-finder/")
def tool_cuba_export_opportunity_finder():
    return _render_ita_export_page("cuba-export-opportunity-finder")


@app.route("/tools/cuba-hs-code-opportunity-finder")
@app.route("/tools/cuba-hs-code-opportunity-finder/")
def tool_cuba_hs_code_opportunity_finder():
    return _render_ita_export_page("cuba-hs-code-opportunity-finder")


@app.route("/tools/cuba-export-controls-sanctions-process-map")
@app.route("/tools/cuba-export-controls-sanctions-process-map/")
def tool_cuba_export_controls_sanctions_process_map():
    return _render_ita_export_page("cuba-export-controls-sanctions-process-map")


@app.route("/tools/can-my-us-company-export-to-cuba")
@app.route("/tools/can-my-us-company-export-to-cuba/")
def tool_can_my_us_company_export_to_cuba():
    return _render_ita_export_page("can-my-us-company-export-to-cuba")


@app.route("/tools/cuba-country-contacts-directory")
@app.route("/tools/cuba-country-contacts-directory/")
def tool_cuba_country_contacts_directory():
    return _render_ita_export_page("cuba-country-contacts-directory")


@app.route("/tools/us-company-cuba-market-entry-checklist")
@app.route("/tools/us-company-cuba-market-entry-checklist/")
def tool_us_company_cuba_market_entry_checklist():
    return _render_ita_export_page("us-company-cuba-market-entry-checklist")


@app.route("/tools/cuba-agricultural-medical-export-checker")
@app.route("/tools/cuba-agricultural-medical-export-checker/")
def tool_cuba_agricultural_medical_export_checker():
    return _render_ita_export_page("cuba-agricultural-medical-export-checker")


@app.route("/tools/cuba-telecom-internet-export-checker")
@app.route("/tools/cuba-telecom-internet-export-checker/")
def tool_cuba_telecom_internet_export_checker():
    return _render_ita_export_page("cuba-telecom-internet-export-checker")


@app.route("/tools/cuba-mipyme-export-support-checklist")
@app.route("/tools/cuba-mipyme-export-support-checklist/")
def tool_cuba_mipyme_export_support_checklist():
    return _render_ita_export_page("cuba-mipyme-export-support-checklist")


@app.route("/tools/cuba-trade-events-matchmaking-calendar")
@app.route("/tools/cuba-trade-events-matchmaking-calendar/")
def tool_cuba_trade_events_matchmaking_calendar():
    return _render_ita_export_page("cuba-trade-events-matchmaking-calendar")


@app.route("/tools/cuba-trade-barriers-tracker")
@app.route("/tools/cuba-trade-barriers-tracker/")
def tool_cuba_trade_barriers_tracker():
    return _render_ita_export_page("cuba-trade-barriers-tracker")


@app.route("/tools/cuba-export-compliance-checklist")
@app.route("/tools/cuba-export-compliance-checklist/")
def tool_cuba_export_compliance_checklist():
    return _render_ita_export_page("cuba-export-compliance-checklist")


@app.route("/tools/havana-safety-by-neighborhood")
@app.route("/tools/havana-safety-by-neighborhood/")
def tool_havana_safety():
    """Curated Havana neighborhood safety reference."""
    try:
        from src.data.havana_neighborhoods import list_havana_neighborhoods
        from src.data.havana_landmarks import list_havana_landmarks
        from src.page_renderer import _env
        from datetime import date as _date

        neighborhoods = list_havana_neighborhoods()
        landmarks = list_havana_landmarks()

        seo, jsonld = _tool_seo_jsonld(
            slug="havana-safety-by-neighborhood",
            title="Is Cuba Safe? Havana Safety Map by Neighborhood (2026)",
            description=(
                "Is Cuba safe to visit? Neighborhood-by-neighborhood safety "
                "scores for Havana — Miramar, Vedado, Habana Vieja, Centro "
                "Habana, and more. U.S. State Dept rates Cuba Level 2. "
                "Low violent crime but practical risks: blackouts, no ATMs "
                "for U.S. cards, scams. Interactive map + safety tips."
            ),
            keywords=(
                "is cuba safe, is it safe to travel to cuba, havana safety, "
                "is cuba safe for tourists, cuba safety 2026, safe "
                "neighborhoods havana, is cuba dangerous, cuba crime rate, "
                "havana safety map, where to stay in havana, cuba travel safety"
            ),
            faq=[
                {
                    "q": "Is Cuba safe to visit in 2026?",
                    "a": (
                        "Cuba is generally considered one of the safer "
                        "Caribbean destinations for tourists. The U.S. State "
                        "Department rates Cuba at Level 2 ('Exercise Increased "
                        "Caution') — the same level as France, the UK, and "
                        "Germany. Violent crime against tourists is rare. The "
                        "main risks are petty crime (pickpocketing, "
                        "distraction theft, short-change scams), infrastructure "
                        "hazards (rolling blackouts called 'apagones,' "
                        "crumbling buildings in Centro Habana), and the fact "
                        "that U.S.-issued bank cards do not work anywhere on "
                        "the island."
                    ),
                },
                {
                    "q": "Is it safe to travel to Cuba as an American?",
                    "a": (
                        "Yes — American tourists face the same low violent-"
                        "crime environment as other nationalities. The "
                        "additional considerations for Americans are legal, "
                        "not physical: you must travel under one of OFAC's "
                        "12 authorized categories, avoid CPAL-listed hotels, "
                        "and your Visa/Mastercard/Amex will not work. Bring "
                        "clean USD or EUR cash. The U.S. Embassy in Havana "
                        "resumed limited services in 2023 but cannot provide "
                        "full consular assistance in emergencies."
                    ),
                },
                {
                    "q": "What is the safest neighborhood in Havana?",
                    "a": (
                        "Miramar (Playa municipality) is the safest — it "
                        "houses most embassies, international businesses, and "
                        "modern hotels (Meliá Habana, Memories Miramar). "
                        "Vedado is second, with a mix of hotels, restaurants, "
                        "and ministries. La Habana Vieja (Old Havana) is safe "
                        "during the day for tourists but requires more "
                        "awareness at night. Centro Habana has the most "
                        "reported petty crime and infrastructure decay."
                    ),
                },
                {
                    "q": "What are the biggest safety risks in Cuba for tourists?",
                    "a": (
                        "In order of likelihood: (1) Petty theft and scams "
                        "(especially in Old Havana and around tourist "
                        "attractions), (2) Power outages that kill AC, "
                        "lighting, and water pumps for 4-8 hours/day outside "
                        "Havana, (3) Road conditions — poorly lit, no "
                        "guardrails, animals on highways, (4) Limited medical "
                        "care — hospitals lack supplies despite good doctors; "
                        "travel insurance with medical evacuation coverage is "
                        "essential, (5) Arbitrary detention risk for "
                        "journalists and activists (U.S. State Dept warning)."
                    ),
                },
                {
                    "q": "Is the airport road in Havana safe?",
                    "a": (
                        "The corridor between José Martí International "
                        "Airport (HAV, Boyeros) and downtown Havana is "
                        "functional and well-policed. Pre-arrange a transfer "
                        "through your casa particular or hotel — the official "
                        "taxi queue at Terminal 3 is reliable. The drive takes "
                        "20-40 minutes to Vedado/Miramar depending on traffic."
                    ),
                },
            ],
        )

        from src.seo.cluster_topology import build_related_tools_ctx
        related_tools_ctx = build_related_tools_ctx("/tools/havana-safety-by-neighborhood")

        template = _env.get_template("tools/safety_map.html.j2")
        html = template.render(
            neighborhoods=neighborhoods,
            landmarks=landmarks,
            seo=seo,
            jsonld=jsonld,
            related_tools_ctx=related_tools_ctx,
            current_year=_date.today().year,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("safety map render failed: %s", exc)
        abort(500)


@app.route("/tools/cuba-visa-requirements")
@app.route("/tools/cuba-visa-requirements/")
def tool_cuba_visa_requirements():
    """Cuba visa & travel-advisory checker by passport country."""
    try:
        from src.data.visa_requirements import list_visa_requirements
        from src.models import (
            ExternalArticleEntry, SessionLocal, SourceType, init_db,
        )
        from src.page_renderer import _env
        from datetime import date as _date
        import copy as _copy

        visas = [_copy.copy(v) for v in list_visa_requirements()]

        try:
            init_db()
            db = SessionLocal()
            try:
                latest = (
                    db.query(ExternalArticleEntry)
                    .filter(ExternalArticleEntry.source == SourceType.TRAVEL_ADVISORY)
                    .order_by(ExternalArticleEntry.published_date.desc())
                    .first()
                )
            finally:
                db.close()
        except Exception as exc:
            logger.warning("travel advisory live fetch failed, using static fallback: %s", exc)
            latest = None

        if latest is not None:
            meta = latest.extra_metadata or {}
            level = meta.get("level")
            level_text = (meta.get("level_text") or "").strip()
            level_label_map = {
                1: "Exercise Normal Precautions",
                2: "Exercise Increased Caution",
                3: "Reconsider Travel",
                4: "Do Not Travel",
            }
            if isinstance(level, int) and 1 <= level <= 4:
                label = level_text or level_label_map.get(level, "")
                advisory_summary = (
                    f"{label} — current US State Department designation "
                    f"(updated {latest.published_date.isoformat()}). "
                    "See the full advisory for region-specific risk indicators "
                    "and the OFAC travel-category overlay under 31 CFR §515."
                )
                for v in visas:
                    if v.get("code") == "US":
                        v["advisory_level"] = level
                        v["advisory_summary"] = advisory_summary

        seo, jsonld = _tool_seo_jsonld(
            slug="cuba-visa-requirements",
            title="Cuba Visa Requirements (2026): Tourist Card, Cost & How to Get One",
            description=(
                "Do you need a visa for Cuba? Complete guide to Cuba visa and "
                "Tourist Card (Tarjeta del Turista) requirements by nationality. "
                "Cost: $50-100 (U.S.) or €25-30 (others). Where to buy, "
                "maximum stay, documents needed at Havana immigration, and "
                "special rules for U.S. passport holders (OFAC categories). "
                "Updated for 2026."
            ),
            keywords=(
                "cuba visa, cuba visa requirements, do i need a visa for cuba, "
                "cuba tourist card, cuba entry requirements 2026, cuba visa cost, "
                "cuba visa for us citizens, tarjeta del turista cuba, "
                "cuba travel advisory, D'Viajeros cuba, cuba travel documents"
            ),
            faq=[
                {
                    "q": "Do US citizens need a visa to travel to Cuba?",
                    "a": (
                        "US passport holders do not get a regular tourist visa — "
                        "tourism per se is prohibited under the Cuban Assets "
                        "Control Regulations (CACR, 31 CFR Part 515). US "
                        "travellers must instead self-certify travel under one "
                        "of OFAC's 12 authorized categories (§515.560–.578) — "
                        "most commonly 'support for the Cuban people' "
                        "(§515.574) — and purchase the pink US-version Tourist "
                        "Card (~US$100 from the airline at check-in or in "
                        "advance from a third-party vendor) which serves as the "
                        "Cuban entry permit. Proof of Cuban-law-compliant "
                        "travel-medical insurance and a completed D'Viajeros "
                        "customs/health form (within 72 h of arrival) are also "
                        "mandatory at the border."
                    ),
                },
                {
                    "q": "Do UK, EU, and Canadian citizens need a visa to travel to Cuba?",
                    "a": (
                        "No tourist visa is required up front, but every "
                        "foreign visitor must arrive holding a Tourist Card "
                        "(Tarjeta del Turista — the green non-US version, "
                        "~€25–€30, sold by the airline at check-in or by the "
                        "Cuban consulate). UK passports get up to 90 days "
                        "and Canadian passports up to 90 days extendable to "
                        "180; most EU passports get 30 days extendable to 90. "
                        "Travel-medical insurance valid in Cuba is checked at "
                        "the border for all nationalities."
                    ),
                },
                {
                    "q": "What's the difference between the Tourist Card and a real visa?",
                    "a": (
                        "The Tourist Card is a single-entry tear-off slip "
                        "stapled into the passport at arrival — it covers "
                        "leisure / family / OFAC-authorized travel and is what "
                        "almost every visitor uses. A formal visa is required "
                        "only for journalism (D-6), business meetings outside "
                        "the OFAC general-license framework (D-1 through D-9), "
                        "study, or any employment activity, and must be "
                        "arranged in advance through a Cuban consulate or a "
                        "Cuban host institution."
                    ),
                },
                {
                    "q": "What documents do I need to actually clear immigration in Havana?",
                    "a": (
                        "Six items: (1) passport valid 6+ months past entry "
                        "date, (2) the correct-colour Tourist Card, (3) a "
                        "return / onward ticket, (4) the QR code from the "
                        "D'Viajeros online customs and health declaration "
                        "filed within 72 hours of arrival "
                        "(dviajeros.mitrans.gob.cu), (5) proof of "
                        "travel-medical insurance valid in Cuba, and (6) for "
                        "US travelers, a written record of the OFAC general-"
                        "license category you are travelling under (kept for "
                        "five years per §515.601)."
                    ),
                },
            ],
        )

        from src.seo.cluster_topology import build_related_tools_ctx
        related_tools_ctx = build_related_tools_ctx("/tools/cuba-visa-requirements")

        template = _env.get_template("tools/visa_requirements.html.j2")
        html = template.render(
            visas=visas,
            seo=seo,
            jsonld=jsonld,
            related_tools_ctx=related_tools_ctx,
            current_year=_date.today().year,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("visa tool render failed: %s", exc)
        abort(500)


@app.route("/tools/venezuela-visa-requirements")
@app.route("/tools/venezuela-visa-requirements/")
def _legacy_visa_requirements_redirect():
    return _legacy_redirect_to("/tools/cuba-visa-requirements")


@app.route("/tools/cuba-investment-roi-calculator")
@app.route("/tools/cuba-investment-roi-calculator/")
def tool_roi_calculator():
    """Sector ROI / IRR / NPV calculator with Cuba risk premium overlays."""
    try:
        from src.page_renderer import _env
        from datetime import date as _date

        seo, jsonld = _tool_seo_jsonld(
            slug="cuba-investment-roi-calculator",
            title="Cuba Investment ROI Calculator — IRR, NPV, Cash Flow Tool",
            description=(
                "Free Cuba investment ROI calculator. Estimate IRR, NPV, and "
                "multi-year cash flow for tourism & hospitality, MIPYMES, "
                "biotech (BioCubaFarma), agriculture, telecom (ETECSA), "
                "renewables, and Mariel ZED projects — with sector-specific "
                "Cuba risk premiums, CACR / Helms-Burton overlays, and the "
                "MLC / CUP / USD currency-stack friction baked in."
            ),
            keywords=(
                "Cuba investment calculator, Cuba IRR calculator, Cuba NPV, "
                "Cuba ROI, Mariel ZED ROI, MIPYMES Cuba investment, "
                "BioCubaFarma ROI, sector risk premium Cuba, Helms-Burton "
                "title III, CACR investment"
            ),
            faq=[
                {
                    "q": "How is the Cuba risk premium calculated?",
                    "a": (
                        "Sector-specific premiums are anchored to comparable "
                        "Caribbean / EM sovereign spreads (Cuba has no traded "
                        "external sovereign benchmark since the 1986 default) "
                        "and adjusted by sector based on CACR sanctions "
                        "exposure, Helms-Burton Title III trafficking-claim "
                        "risk, MLC / CUP repatriation friction, electricity "
                        "reliability, and the binary US-Cuba normalisation "
                        "trade. Defaults range from ~9% (tourism / "
                        "hospitality with Mariel ZED standing) to 16%+ "
                        "(telecom and energy projects requiring direct "
                        "GAESA counterparties)."
                    ),
                },
                {
                    "q": "What's a reasonable discount rate for a Cuban investment?",
                    "a": (
                        "Most institutional investors use a USD-denominated "
                        "WACC of 10–14% as the base, then add the sector-"
                        "specific Cuba risk premium of 9–16% plus any project-"
                        "specific Helms-Burton or OFAC-license overlay, for "
                        "an all-in discount rate of 19–32%. Mariel ZED "
                        "projects with a Ley 118 tax holiday and a non-US "
                        "JV partner price closer to the low end; tourism "
                        "exposed to Cuba Restricted List or CPAL hotels "
                        "price closer to the top."
                    ),
                },
                {
                    "q": "Does the calculator handle Helms-Burton Title III exposure?",
                    "a": (
                        "Only as a risk-premium add-on. The Helms-Burton Act "
                        "(LIBERTAD Act, 22 USC §6021–6091) Title III creates "
                        "a US federal cause of action for trafficking in "
                        "confiscated Cuban property; the suspension was "
                        "lifted in 2019 and the docket is active. Real "
                        "diligence requires mapping every site, tenant, and "
                        "supplier against the certified-claim and Title IV "
                        "registries — outside the scope of this filter tool."
                    ),
                },
                {
                    "q": "Is this calculator a substitute for a fully diligenced model?",
                    "a": (
                        "No. The calculator is a first-round filter that "
                        "surfaces order-of-magnitude returns. A real Cuba "
                        "investment decision requires a fully diligenced "
                        "model with MLC / CUP / USD currency stack, OFAC "
                        "and CACR compliance overlay, Cuba Restricted List "
                        "and CPAL screening, Helms-Burton trafficking-claim "
                        "insurance, country-of-origin tax structure, and "
                        "project-finance terms negotiated with the Cuban "
                        "counterparty (typically a GAESA-affiliated SOE)."
                    ),
                },
            ],
        )

        from src.seo.cluster_topology import build_related_tools_ctx
        related_tools_ctx = build_related_tools_ctx("/tools/cuba-investment-roi-calculator")

        template = _env.get_template("tools/roi_calculator.html.j2")
        html = template.render(
            seo=seo,
            jsonld=jsonld,
            related_tools_ctx=related_tools_ctx,
            current_year=_date.today().year,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("ROI calculator render failed: %s", exc)
        abort(500)


@app.route("/tools/venezuela-investment-roi-calculator")
@app.route("/tools/venezuela-investment-roi-calculator/")
def _legacy_roi_calculator_redirect():
    return _legacy_redirect_to("/tools/cuba-investment-roi-calculator")


@app.route("/tools/eltoque-trmi-rate")
@app.route("/tools/eltoque-trmi-rate/")
def tool_eltoque_trmi():
    """Live elTOQUE TRMI informal CUP/USD/MLC/USDT rate widget + free converter.

    Reads the latest persisted ELTOQUE_RATE row written by
    src/scraper/eltoque.py. The TRMI is the de-facto market reference
    for any Cuba transaction — the BCC's tasaEspecial covers state /
    JV transactions but ordinary cash, MLC top-ups, and remittance
    flow track elTOQUE almost exclusively.
    """
    try:
        from src.models import ExternalArticleEntry, SessionLocal, SourceType, init_db
        from src.page_renderer import _env
        from datetime import date as _date

        rate_usd: float | None = None
        rate_eur: float | None = None
        rate_mlc: float | None = None
        rate_usdt: float | None = None
        rate_date: str = ""
        attribution: str = (
            "Tasa Representativa del Mercado Informal — elTOQUE "
            "(tasas.eltoque.com)"
        )

        init_db()
        db = SessionLocal()
        try:
            cached = (
                db.query(ExternalArticleEntry)
                .filter(ExternalArticleEntry.source == SourceType.ELTOQUE_RATE)
                .order_by(ExternalArticleEntry.published_date.desc())
                .first()
            )
            if cached and cached.extra_metadata:
                meta = cached.extra_metadata or {}
                rate_usd = meta.get("usd")
                rate_mlc = meta.get("mlc")
                rate_usdt = meta.get("usdt_trc20")
                # elTOQUE doesn't publish an EUR pair directly; the EUR
                # cross-rate (if surfaced) is computed in the template
                # so we can leave it None here.
                rate_eur = meta.get("eur")
                attribution = meta.get("attribution") or attribution
                rate_date = cached.published_date.isoformat()
        finally:
            db.close()

        title_today = (
            f"Cuban Peso to USD Exchange Rate Today: {rate_usd:,.0f} CUP = $1 (Real Rate)"
            if rate_usd else
            "Cuban Peso to USD Exchange Rate — CUP/USD Real Market Rate (elTOQUE TRMI)"
        )
        description_today = (
            f"Today's real Cuban peso exchange rate: {rate_usd:,.0f} CUP per "
            f"US$1 (elTOQUE TRMI informal market). Google and banks show the "
            f"official BCC rate of 24 CUP/$1 — but nobody uses it. Free "
            f"CUP-to-USD converter, MLC rate, USDT rate, and explanation "
            f"of Cuba's triple-currency system."
            if rate_usd else
            "Live Cuban peso to USD exchange rate (CUP/USD) from elTOQUE "
            "TRMI — the real informal-market rate Cubans actually use. Free "
            "converter, MLC rate, USDT rate, and Cuba currency explainer."
        )

        seo, jsonld = _tool_seo_jsonld(
            slug="eltoque-trmi-rate",
            title=title_today,
            description=description_today,
            keywords=(
                "cup to usd, cuban peso exchange rate, cuban peso to dollar, "
                "cuba exchange rate, CUP USD rate today, elTOQUE TRMI, "
                "cuban peso converter, MLC rate Cuba, tasa informal Cuba, "
                "how much is a cuban peso worth, cuba currency"
            ),
            faq=[
                {
                    "q": "What is the elTOQUE TRMI and why does it matter for Cuba?",
                    "a": (
                        "The Tasa Representativa del Mercado Informal "
                        "(TRMI) is elTOQUE's daily index of the informal "
                        "CUP/USD, CUP/MLC, and CUP/USDT exchange rates "
                        "computed from a basket of Telegram-channel and "
                        "classifieds signals. It is the rate at which "
                        "ordinary Cubans, remittance senders, and "
                        "private-sector MIPYMES actually transact — the "
                        "BCC's official tasaEspecial covers state and "
                        "joint-venture flows but is not where street-level "
                        "demand clears."
                    ),
                },
                {
                    "q": "What's the difference between the BCC official rate and the elTOQUE TRMI?",
                    "a": (
                        "The Banco Central de Cuba publishes three official "
                        "segments — tasaOficial (the legacy 1:24 peg), "
                        "tasaPublica (the CADECA window, ~5x official), and "
                        "tasaEspecial (the institutional rate introduced "
                        "August 2022 at ~120 CUP/USD and used for state and "
                        "foreign-JV transactions). The elTOQUE TRMI is the "
                        "informal-market rate, currently several hundred "
                        "CUP per USD wider than the tasaEspecial. The "
                        "spread between the two is the single most-watched "
                        "macro indicator on the island."
                    ),
                },
                {
                    "q": "What is MLC and how does it relate to USD in Cuba?",
                    "a": (
                        "Moneda Libremente Convertible (MLC) is a virtual "
                        "currency the Cuban state introduced in 2019, "
                        "denominated 1:1 with the USD, redeemable only in "
                        "designated MLC stores (which carry imported goods "
                        "scarce in CUP retail). MLC is loaded onto a state-"
                        "issued card via a hard-currency wire from abroad. "
                        "The elTOQUE TRMI tracks the informal CUP/MLC rate "
                        "separately from CUP/USD because the two diverge — "
                        "MLC trades at a small discount to cash USD because "
                        "it cannot be withdrawn or exchanged back."
                    ),
                },
                {
                    "q": "Can I use my US-issued credit or debit card in Cuba?",
                    "a": (
                        "No. Cards issued by US banks or processed through "
                        "US payment networks (Visa, Mastercard, Amex) do "
                        "not work in Cuba — neither at ATMs nor at "
                        "merchants — because of OFAC's Cuban Assets "
                        "Control Regulations (CACR, 31 CFR Part 515). "
                        "Bring USD or EUR cash in clean, undamaged "
                        "denominations and exchange to CUP at the airport "
                        "CADECA, your hotel front desk, or informally. "
                        "A non-US-issued card (Canadian, EU, UK) generally "
                        "works at major hotels and ATMs."
                    ),
                },
                {
                    "q": "Can foreign investors freely repatriate hard currency from Cuba?",
                    "a": (
                        "Repatriation requires registration with the BCC "
                        "and approval against the prevailing exchange-"
                        "control framework (Ley 118 for foreign investment, "
                        "Decreto 313 for Mariel ZED). FX availability and "
                        "the spread between the BCC tasaEspecial and the "
                        "elTOQUE TRMI is the single largest operational "
                        "risk for any foreign investor — a 4–5x divergence "
                        "translates directly into project IRR drag at "
                        "remittance and dividend events."
                    ),
                },
            ],
        )

        from src.seo.cluster_topology import build_related_tools_ctx
        related_tools_ctx = build_related_tools_ctx("/tools/eltoque-trmi-rate")

        template = _env.get_template("tools/eltoque_trmi.html.j2")
        html = template.render(
            rate_usd=rate_usd,
            rate_eur=rate_eur,
            rate_mlc=rate_mlc,
            rate_usdt=rate_usdt,
            rate_date=rate_date or _date.today().isoformat(),
            attribution=attribution,
            seo=seo,
            jsonld=jsonld,
            related_tools_ctx=related_tools_ctx,
            current_year=_date.today().year,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("elTOQUE TRMI tool render failed: %s", exc)
        abort(500)


@app.route("/tools/bolivar-usd-exchange-rate")
@app.route("/tools/bolivar-usd-exchange-rate/")
def _legacy_bolivar_usd_redirect():
    return _legacy_redirect_to("/tools/eltoque-trmi-rate")


def _sdn_normalize_type(raw: str) -> str:
    """OFAC encodes a missing SDN type as ``-0-`` (their null sentinel),
    which should be read as "Entity" — the default for SDN rows that
    aren't explicitly tagged as a vessel, aircraft, or individual."""
    t = (raw or "").strip().lower()
    if not t or t in {"-0-", "entity"}:
        return "Entity"
    return t.capitalize()


# Ordered (longest / most specific keywords first so e.g. "GRUPO DE
# ADMINISTRACION EMPRESARIAL" wins over a generic "GRUPO" rule).
_SDN_SECTOR_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("GAESA", ("GRUPO DE ADMINISTRACION EMPRESARIAL", "GRUPO GAE", "GAESA")),
    ("CIMEX group", ("CIMEX",)),
    ("Tourism & travel", (
        "HAVANATUR", "CUBANATUR", "CUBANACAN", "HOLA SUN", "TROPIC TOURS",
        "VIAJES", "VINALES TOURS", "TURISMO",
    )),
    ("Banking & finance", ("BANCO", "BANK", "FINANCIERA", "HAVIN")),
    ("Mining & metals", ("NICKEL", "COBALT", "NIQUEL")),
    ("Aviation", ("AVIACION", "AERO")),
    ("Maritime & fishing", (
        "MARINE", "MARITIME", "NAVES", "FLETES", "PESCADO",
        "PESCABRAVA", "CARIBEX",
    )),
    ("Tobacco & cigars", ("CIGAR", "TABACO", "LA MAISON")),
    ("Media & publishing", ("PRENSA", "EDICIONES")),
    ("Trading & commodities", (
        "COMERCIAL", "TRADING", "IMPORT", "EXPORT", "ETCO", "KAVE",
        "BOUTIQUE", "CASA DE CUBA",
    )),
]


def _sdn_sector_for(name: str, remarks: str) -> str:
    """Heuristic sector tag for an SDN entry, derived from name +
    remarks keywords. Returns "Other / holdings" as the fallback bucket
    so the picker is never blank for a row."""
    text = f"{name or ''} {remarks or ''}".upper()
    for label, keywords in _SDN_SECTOR_RULES:
        for kw in keywords:
            if kw in text:
                return label
    return "Other / holdings"


@app.route("/tools/ofac-cuba-sanctions-checker")
@app.route("/tools/ofac-cuba-sanctions-checker/")
def tool_ofac_sanctions_checker():
    """Search the cached OFAC SDN data (CUBA program) for fuzzy matches against a query."""
    try:
        from src.models import ExternalArticleEntry, SessionLocal, SourceType, init_db
        from src.page_renderer import _env
        from datetime import date as _date
        from difflib import SequenceMatcher
        from collections import Counter
        import re as _re

        query = (request.args.get("q") or "").strip()
        type_filter = (request.args.get("type") or "").strip()
        sector_filter = (request.args.get("sector") or "").strip()

        matches: list[dict] = []
        total_sdn = 0
        entries_alpha: list[dict] = []
        type_counts: list[tuple[str, int]] = []
        sector_counts: list[tuple[str, int]] = []

        init_db()
        db = SessionLocal()
        try:
            rows = (
                db.query(ExternalArticleEntry)
                .filter(ExternalArticleEntry.source == SourceType.OFAC_SDN)
                .all()
            )
            total_sdn = len(rows)

            # Pre-compute the row dicts once so picker/filter/match all
            # share the same normalized view (type and sector tagging).
            normalized: list[dict] = []
            for r in rows:
                meta = r.extra_metadata or {}
                name = (meta.get("name") or r.headline or "").strip()
                if not name:
                    continue
                program = (meta.get("program") or "").strip()
                remarks = (meta.get("remarks") or "").strip()
                if remarks == "-0-":
                    remarks = ""
                normalized.append({
                    "name": name,
                    "type": _sdn_normalize_type(meta.get("type")),
                    "sector": _sdn_sector_for(name, remarks),
                    "program": program,
                    "remarks": remarks,
                })

            entries_alpha = sorted(normalized, key=lambda x: x["name"].lower())

            type_counter: Counter[str] = Counter(x["type"] for x in normalized)
            # Entity first (the bulk), then vessels, individuals, anything
            # else alphabetically.
            _type_priority = {"Entity": 0, "Vessel": 1, "Individual": 2}
            type_counts = sorted(
                type_counter.items(),
                key=lambda kv: (_type_priority.get(kv[0], 99), kv[0]),
            )

            sector_counter: Counter[str] = Counter(x["sector"] for x in normalized)
            # Push "Other / holdings" to the bottom; everything else
            # alphabetical so the long list scans predictably.
            sector_counts = sorted(
                sector_counter.items(),
                key=lambda kv: (1 if kv[0] == "Other / holdings" else 0, kv[0]),
            )

            if query or type_filter or sector_filter:
                q_low = query.lower()
                q_norm = _re.sub(r"[^a-z0-9]+", "", q_low)

                for x in normalized:
                    if type_filter and x["type"] != type_filter:
                        continue
                    if sector_filter and x["sector"] != sector_filter:
                        continue

                    if query:
                        haystack = " ".join([x["name"], x["program"], x["remarks"]]).lower()
                        haystack_norm = _re.sub(r"[^a-z0-9]+", "", haystack)
                        score = 0.0
                        if q_low in haystack:
                            score = max(score, 0.95)
                        elif q_norm and q_norm in haystack_norm:
                            score = max(score, 0.85)
                        else:
                            ratio = SequenceMatcher(None, q_low, x["name"].lower()).ratio()
                            if ratio >= 0.7:
                                score = max(score, ratio)
                        if score < 0.7:
                            continue
                    else:
                        score = 1.0

                    matches.append({
                        "name": x["name"],
                        "type": x["type"],
                        "sector": x["sector"],
                        "program": x["program"],
                        "remarks": x["remarks"],
                        "score": int(round(score * 100)),
                    })

                matches.sort(key=lambda m: (-m["score"], m["sector"], m["name"]))
                matches = matches[:60]
        finally:
            db.close()

        seo, jsonld = _tool_seo_jsonld(
            slug="ofac-cuba-sanctions-checker",
            title="OFAC Cuba Sanctions Exposure Checker — Free Screening Tool",
            description=(
                f"Free OFAC sanctions screening tool: check any name, company, "
                f"vessel IMO, aircraft tail number, or Cuban identity document "
                f"against all {total_sdn} active CUBA-program SDN designations "
                f"under the Cuban Assets Control Regulations (CACR, 31 CFR "
                f"Part 515)."
            ),
            keywords=(
                "OFAC sanctions checker Cuba, SDN screening Cuba, CACR 515, "
                "GAESA sanctions check, Cuba Restricted List, OFAC Cuba "
                "fuzzy match, Helms-Burton screening"
            ),
            faq=[
                {
                    "q": "How accurate is this OFAC Cuba sanctions check?",
                    "a": (
                        "This tool uses fuzzy matching against the OFAC SDN "
                        "list filtered for the CUBA program. It surfaces "
                        "likely matches but does not perform full ownership-"
                        "chain analysis (the OFAC 50% Rule), nor does it "
                        "check the State Department's Cuba Restricted List "
                        "(CRL) or Cuba Prohibited Accommodations List "
                        "(CPAL) — both of which prohibit transactions even "
                        "for entities NOT on the SDN. Always verify with "
                        "the official OFAC source and consider qualified "
                        "sanctions counsel for high-stakes counterparties."
                    ),
                },
                {
                    "q": "What data is checked?",
                    "a": (
                        f"All {total_sdn} entries on the OFAC consolidated "
                        f"SDN list designated under the CUBA program "
                        f"(administered under the Cuban Assets Control "
                        f"Regulations, 31 CFR Part 515), refreshed twice "
                        f"daily. The tool searches names, aliases, IMO "
                        f"numbers, aircraft tail numbers, Cuban identity "
                        f"documents, and SDN remarks fields. For Cuba "
                        f"Restricted List and CPAL exposure (separate "
                        f"State-Department lists not on the SDN), see the "
                        f"per-company exposure pages."
                    ),
                },
                {
                    "q": "Is this tool free?",
                    "a": "Yes. The OFAC Cuba sanctions exposure checker is completely free to use, with no registration required.",
                },
            ],
        )

        from src.seo.cluster_topology import build_cluster_ctx, build_related_tools_ctx
        cluster_ctx = build_cluster_ctx("/tools/ofac-cuba-sanctions-checker")
        related_tools_ctx = build_related_tools_ctx("/tools/ofac-cuba-sanctions-checker")

        template = _env.get_template("tools/ofac_sanctions_checker.html.j2")
        html = template.render(
            query=query,
            type_filter=type_filter,
            sector_filter=sector_filter,
            matches=matches,
            total_sdn=total_sdn,
            entries_alpha=entries_alpha,
            type_counts=type_counts,
            sector_counts=sector_counts,
            today_human=_date.today().strftime("%B %Y"),
            seo=seo,
            jsonld=jsonld,
            cluster_ctx=cluster_ctx,
            related_tools_ctx=related_tools_ctx,
            current_year=_date.today().year,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("sanctions checker render failed: %s", exc)
        abort(500)


@app.route("/tools/ofac-venezuela-sanctions-checker")
@app.route("/tools/ofac-venezuela-sanctions-checker/")
def _legacy_ofac_sanctions_checker_redirect():
    return _legacy_redirect_to("/tools/ofac-cuba-sanctions-checker")


# Canonical Cuban tourist neighborhood / zone names mapped to the
# regex patterns we'll search for inside CPAL address strings. Each
# canonical key may have multiple variant spellings (with/without
# diacritics, with municipality qualifiers, etc.). Order matters
# slightly: more specific zones (e.g. "Cayo Santa María") are listed
# before more generic ones (e.g. "Playa") so the first match wins.
_CPAL_NEIGHBORHOODS: list[tuple[str, list[str]]] = [
    # Cayos (always specific — match these first)
    ("Cayo Coco", [r"Cayo\s+Coco"]),
    ("Cayo Guillermo", [r"Cayo\s+Guillermo"]),
    ("Cayo Santa María", [r"Cayo\s+Santa\s+Mar[ií]a"]),
    ("Cayo Las Brujas", [r"Cayo\s+Las\s+Brujas"]),
    ("Cayo Ensenachos", [r"Cayo\s+Ensenachos"]),
    ("Cayo Largo", [r"Cayo\s+Largo"]),
    ("Cayo Levisa", [r"Cayo\s+Levisa"]),
    ("Cayo Cruz", [r"Cayo\s+Cruz"]),
    ("Cayo Paredón Grande", [r"Cayo\s+Pared[oó]n\s+Grande"]),
    ("Cayo Romano", [r"Cayo\s+Romano"]),
    # Varadero / Matanzas peninsula
    ("Varadero", [r"\bVaradero\b"]),
    ("Matanzas (city)", [r"\bMatanzas\b"]),
    # Havana neighborhoods (specific zones before broad municipios)
    ("Santa María del Mar (Playas del Este)", [r"Santa\s+Mar[ií]a\s+del\s+Mar"]),
    ("Boca Ciega (Playas del Este)", [r"Boca\s+Ciega"]),
    ("Guanabo (Playas del Este)", [r"\bGuanabo\b"]),
    ("Tarará (Playas del Este)", [r"Tarar[áa]"]),
    ("Cojímar", [r"Coj[ií]mar"]),
    ("Habana Vieja", [r"Habana\s+Vieja|La\s+Habana\s+Vieja"]),
    ("Habana del Este", [r"Habana\s+del\s+Este|La\s+Habana\s+del\s+Este"]),
    ("Centro Habana", [r"Centro\s+Habana"]),
    ("Vedado", [r"\bVedado\b"]),
    ("Miramar", [r"\bMiramar\b"]),
    ("Kohly", [r"\bKohly\b"]),
    ("Siboney (Havana)", [r"\bSiboney\b"]),
    ("Marianao", [r"\bMarianao\b"]),
    ("Cerro", [r"\bCerro\b"]),
    ("Playa (Havana municipio)", [r"\bPlaya\b"]),
    ("Plaza de la Revolución", [r"Plaza\s+de\s+la\s+Revoluci[oó]n|\bPlaza\b"]),
    ("Boyeros", [r"\bBoyeros\b"]),
    # Other tourist hubs
    ("Trinidad", [r"\bTrinidad\b"]),
    ("Viñales", [r"Vi[ñn]ales"]),
    ("Las Terrazas", [r"Las\s+Terrazas"]),
    ("Soroa", [r"\bSoroa\b"]),
    ("Topes de Collantes", [r"Topes\s+de\s+Collantes"]),
    ("Punta Gorda (Cienfuegos)", [r"Punta\s+Gorda"]),
    ("Ancón (Trinidad)", [r"Anc[oó]n"]),
    ("Guardalavaca", [r"Guardalavaca"]),
    ("Playa Pesquero", [r"Playa\s+Pesquero"]),
    ("Playa Esmeralda", [r"Playa\s+Esmeralda"]),
    ("Marea del Portillo", [r"Marea\s+del\s+Portillo"]),
    ("Santa Lucía (Camagüey)", [r"Santa\s+Luc[ií]a"]),
    ("Santiago de Cuba (city)", [r"Santiago\s+de\s+Cuba"]),
    ("Nueva Gerona (Isla de la Juventud)", [r"Nueva\s+Gerona"]),
]


def _extract_cpal_neighborhood(address: str) -> str | None:
    """Identify the first known Cuban tourist neighborhood / zone
    inside a free-form CPAL address string. Returns the canonical
    display name, or None if no match. More-specific zones are tried
    before broader municipios so e.g. "Cayo Santa María" beats "Playa".
    """
    import re as _re
    if not address:
        return None
    for canonical, patterns in _CPAL_NEIGHBORHOODS:
        for pat in patterns:
            if _re.search(pat, address, _re.IGNORECASE):
                return canonical
    return None


_STATE_DEPT_SNAPSHOT_CACHE: dict[str, tuple[float, dict, str]] = {}
_STATE_DEPT_SNAPSHOT_TTL_SECONDS = 6 * 60 * 60  # 6 hours


def _load_state_dept_snapshot(prefix: str) -> tuple[dict, str]:
    """Return ``(entries_dict, refreshed_on_iso)`` for the most recent
    State Department snapshot whose filename starts with ``prefix``
    (``"cpal"`` or ``"crl"``).

    Resolution order (Venezuela-style Supabase bridge):

    1. **Local disk** — ``storage/state_dept_snapshots/{prefix}_*.json``,
       written by the daily cron and by step 2 below. Fast path.
    2. **Supabase Storage** — ``state_dept_snapshots/{prefix}_*.json``
       in the public ``reports`` bucket, uploaded by the cron after
       each successful scrape. This is how the web service (a separate
       Render container with its own ephemeral disk) sees the data the
       cron produced.
    3. **Live scrape** — last-resort safety net: run the scraper inline
       once, persist locally and to Supabase, then return its output.
       Only fires on a fresh deploy when both disk and Supabase are
       empty (e.g. before the first cron run has ever completed).

    Results are memoised in-process for ``_STATE_DEPT_SNAPSHOT_TTL_SECONDS``
    so we don't re-hit Supabase on every request. The cache is per-worker
    (gunicorn forks), which is fine — each worker pays the cost once
    per TTL window.
    """
    import time as _time

    cached = _STATE_DEPT_SNAPSHOT_CACHE.get(prefix)
    if cached and (_time.time() - cached[0]) < _STATE_DEPT_SNAPSHOT_TTL_SECONDS:
        return cached[1], cached[2]

    data, refreshed = _load_state_dept_snapshot_from_disk(prefix)

    if not data:
        data, refreshed = _load_state_dept_snapshot_from_supabase(prefix)

    if not data:
        data, refreshed = _scrape_state_dept_snapshot_now(prefix)

    if data:
        _STATE_DEPT_SNAPSHOT_CACHE[prefix] = (_time.time(), data, refreshed)
    return data, refreshed


def _load_state_dept_snapshot_from_disk(prefix: str) -> tuple[dict, str]:
    """Read the newest locally-cached snapshot, or ``({}, "")`` if none."""
    import json as _json
    from src.config import settings as _settings

    snapshot_dir = _settings.storage_dir / "state_dept_snapshots"
    if not snapshot_dir.exists():
        return {}, ""

    candidates = sorted(snapshot_dir.glob(f"{prefix}_*.json"))
    if not candidates:
        return {}, ""

    latest = candidates[-1]
    try:
        with latest.open("r", encoding="utf-8") as f:
            data = _json.load(f)
        if not isinstance(data, dict):
            return {}, ""
        date_part = latest.stem.split("_", 1)[-1]
        return data, date_part
    except Exception as exc:
        logger.warning("Failed to load %s snapshot %s: %s", prefix, latest, exc)
        return {}, ""


def _load_state_dept_snapshot_from_supabase(prefix: str) -> tuple[dict, str]:
    """Pull the newest snapshot for ``prefix`` from Supabase Storage.

    Lists ``state_dept_snapshots/{prefix}_*.json`` in the public bucket,
    picks the lexically-greatest key (filenames are ISO-dated, so this
    is also the newest by date), downloads it, and persists a copy to
    local disk so subsequent calls hit the fast path.
    """
    import json as _json
    from src.config import settings as _settings

    try:
        from src.storage_remote import (
            download_object,
            list_object_keys,
            supabase_storage_read_enabled,
        )
    except Exception as exc:
        logger.debug("Supabase storage helpers unavailable: %s", exc)
        return {}, ""

    if not supabase_storage_read_enabled():
        return {}, ""

    keys = list_object_keys("state_dept_snapshots")
    matching = sorted(
        k for k in keys
        if k.rsplit("/", 1)[-1].startswith(f"{prefix}_") and k.endswith(".json")
    )
    if not matching:
        return {}, ""

    latest_key = matching[-1]
    body = download_object(latest_key)
    if not body:
        return {}, ""

    try:
        data = _json.loads(body.decode("utf-8"))
    except Exception as exc:
        logger.warning("Could not parse Supabase snapshot %s: %s", latest_key, exc)
        return {}, ""
    if not isinstance(data, dict):
        return {}, ""

    filename = latest_key.rsplit("/", 1)[-1]
    date_part = filename[: -len(".json")].split("_", 1)[-1]

    # Persist to local disk so the next call (and any sibling worker
    # that ends up reading the same path) hits the fast path.
    try:
        snapshot_dir = _settings.storage_dir / "state_dept_snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        (snapshot_dir / filename).write_bytes(body)
    except Exception as exc:
        logger.debug("Could not cache Supabase snapshot to disk: %s", exc)

    logger.info(
        "Loaded %s snapshot from Supabase Storage: %s (%d entries)",
        prefix, latest_key, len(data),
    )
    return data, date_part


def _scrape_state_dept_snapshot_now(prefix: str) -> tuple[dict, str]:
    """Last-resort: run the scraper inline once.

    Only used on a brand-new deploy when both local disk and Supabase
    are empty. The scraper writes the snapshot to local disk and
    (best-effort) to Supabase Storage as a side effect, so subsequent
    calls won't have to repeat this.
    """
    from datetime import date as _date

    try:
        if prefix == "cpal":
            from src.scraper.state_dept_cpal import StateDeptCPALScraper as _Scraper
        elif prefix == "crl":
            from src.scraper.state_dept_crl import StateDeptCRLScraper as _Scraper
        else:
            return {}, ""
    except Exception as exc:
        logger.warning("Could not import %s scraper: %s", prefix, exc)
        return {}, ""

    try:
        result = _Scraper().scrape()
    except Exception as exc:
        logger.warning("Inline %s scrape failed: %s", prefix, exc)
        return {}, ""

    if not getattr(result, "success", False):
        logger.warning(
            "Inline %s scrape returned no data: %s",
            prefix, getattr(result, "error", "unknown"),
        )
        return {}, ""

    # The scraper has now persisted to disk; re-read so we use the
    # exact same parsed shape the cron would produce.
    data, refreshed = _load_state_dept_snapshot_from_disk(prefix)
    if data:
        logger.info(
            "Inline %s scrape populated snapshot (%d entries, refreshed=%s)",
            prefix, len(data), refreshed or _date.today().isoformat(),
        )
    return data, refreshed


def _fuzzy_score(query: str, *fields: str) -> float:
    """Score how well ``query`` matches any of the given text fields.
    Returns 0.0 if below the relevance floor (0.7); otherwise 0.7-1.0.

    Three-tier match: substring (0.95), normalised substring (0.85),
    SequenceMatcher ratio (0.7-1.0). Used by the CPAL and CRL checkers.
    """
    from difflib import SequenceMatcher
    import re as _re

    q_low = (query or "").lower().strip()
    if not q_low:
        return 0.0
    q_norm = _re.sub(r"[^a-z0-9]+", "", q_low)

    haystack_parts = [(f or "").lower() for f in fields if f]
    haystack = " ".join(haystack_parts)
    haystack_norm = _re.sub(r"[^a-z0-9]+", "", haystack)

    if q_low in haystack:
        return 0.95
    if q_norm and q_norm in haystack_norm:
        return 0.85

    best = 0.0
    for part in haystack_parts:
        ratio = SequenceMatcher(None, q_low, part).ratio()
        if ratio > best:
            best = ratio
    return best if best >= 0.7 else 0.0


_CPAL_PROFILE_INDEX_CACHE: dict = {"loaded_at": 0.0, "by_slug": {}, "ordered": []}
_CPAL_PROFILE_INDEX_TTL = 300.0
_CRL_PROFILE_INDEX_CACHE: dict = {"loaded_at": 0.0, "by_slug": {}, "ordered": []}
_CRL_PROFILE_INDEX_TTL = 300.0


def _cpal_slug_for(name: str, province: str = "") -> str:
    """Stable URL slug for a CPAL property.

    Stability matters — once a hotel slug is indexed, changing it
    breaks every backlink and search-result. We bake province in only
    when there is a name collision across provinces.
    """
    import re as _re
    import unicodedata as _ud

    def _s(value: str) -> str:
        if not value:
            return ""
        norm = _ud.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        return _re.sub(r"[^a-z0-9]+", "-", norm.lower()).strip("-")

    base_slug = _s(name) or "property"
    if province:
        return f"{base_slug}-{_s(province)}"[:120].strip("-") or "property"
    return base_slug[:120]


def _cpal_profile_index() -> dict:
    """Build / cache `{slug: row}` for every CPAL entry.

    Disambiguates name collisions by appending the province slug
    on the second-and-later occurrences of the same base slug.
    """
    import time as _time

    cache = _CPAL_PROFILE_INDEX_CACHE
    if cache.get("by_slug") and (_time.time() - cache["loaded_at"]) < _CPAL_PROFILE_INDEX_TTL:
        return cache

    entries, refreshed_on = _load_state_dept_snapshot("cpal")
    rows = list(entries.values())

    by_slug: dict[str, dict] = {}
    name_seen: set[str] = set()
    ordered: list[tuple[str, dict]] = []
    for r in rows:
        name = (r.get("name") or "").strip()
        if not name:
            continue
        province = (r.get("province") or "").strip()
        base = _cpal_slug_for(name)
        slug = base if base not in name_seen else _cpal_slug_for(name, province)
        suffix = 2
        while slug in by_slug:
            slug = f"{_cpal_slug_for(name, province)}-{suffix}"
            suffix += 1
        name_seen.add(base)
        row_with_slug = dict(r)
        row_with_slug["slug"] = slug
        row_with_slug["url_path"] = f"/sanctions/cpal/{slug}"
        by_slug[slug] = row_with_slug
        ordered.append((slug, row_with_slug))

    cache.update({
        "loaded_at": _time.time(),
        "by_slug": by_slug,
        "ordered": ordered,
        "refreshed_on": refreshed_on,
    })
    return cache


def list_cpal_profiles() -> list[dict]:
    """All CPAL rows with `slug` + `url_path` populated. Used by sitemap
    + per-hotel pages."""
    return [row for _, row in _cpal_profile_index()["ordered"]]


def _crl_slug_for(name: str, section: str = "") -> str:
    """Stable URL slug for a Cuba Restricted List entity."""
    import re as _re
    import unicodedata as _ud

    def _s(value: str) -> str:
        if not value:
            return ""
        norm = _ud.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        return _re.sub(r"[^a-z0-9]+", "-", norm.lower()).strip("-")

    base_slug = _s(name) or "entity"
    if section:
        return f"{base_slug}-{_s(section)}"[:120].strip("-") or "entity"
    return base_slug[:120]


def _crl_profile_index() -> dict:
    """Build / cache `{slug: row}` for every Cuba Restricted List entry."""
    import time as _time

    cache = _CRL_PROFILE_INDEX_CACHE
    if cache.get("by_slug") and (_time.time() - cache["loaded_at"]) < _CRL_PROFILE_INDEX_TTL:
        return cache

    entries, refreshed_on = _load_state_dept_snapshot("crl")
    rows = list(entries.values())

    by_slug: dict[str, dict] = {}
    name_seen: set[str] = set()
    ordered: list[tuple[str, dict]] = []
    for r in rows:
        name = (r.get("name") or "").strip()
        if not name:
            continue
        section = (r.get("section") or "").strip()
        base = _crl_slug_for(name)
        slug = base if base not in name_seen else _crl_slug_for(name, section)
        suffix = 2
        while slug in by_slug:
            slug = f"{_crl_slug_for(name, section)}-{suffix}"
            suffix += 1
        name_seen.add(base)
        row_with_slug = dict(r)
        row_with_slug["slug"] = slug
        row_with_slug["url_path"] = f"/sanctions/crl/{slug}"
        row_with_slug["kind"] = _crl_kind_for_section(section)
        row_with_slug["location"] = _crl_location_for_section(section)
        by_slug[slug] = row_with_slug
        ordered.append((slug, row_with_slug))

    ordered.sort(key=lambda pair: (pair[1].get("name") or "").lower())
    cache.update({
        "loaded_at": _time.time(),
        "by_slug": by_slug,
        "ordered": ordered,
        "refreshed_on": refreshed_on,
    })
    return cache


def list_crl_profiles() -> list[dict]:
    """All CRL rows with `slug` + `url_path` populated."""
    return [row for _, row in _crl_profile_index()["ordered"]]


@app.route("/sanctions/cpal/<slug>")
@app.route("/sanctions/cpal/<slug>/")
def cpal_profile_page(slug: str):
    """One Cuba Prohibited Accommodations List entry → one indexable
    page. Title leads with the property name + 'Sanctions' to match
    GSC queries like '[hotel name] sanctions'.
    """
    from src.page_renderer import _env, _base_url, _iso, settings as _s
    from datetime import date as _date, datetime as _dt
    import json as _json

    index = _cpal_profile_index()
    row = index["by_slug"].get(slug)
    if not row:
        abort(404)

    try:
        name = (row.get("name") or "").strip()
        province = (row.get("province") or "").strip()
        address = (row.get("address") or "").strip()
        marker = (row.get("marker") or "").strip()
        neighborhood = _extract_cpal_neighborhood(address) or ""

        siblings: list[dict] = []
        if province:
            for r in list_cpal_profiles():
                if r["slug"] == slug:
                    continue
                if (r.get("province") or "").strip() == province:
                    siblings.append(r)
                if len(siblings) >= 8:
                    break

        base = _base_url()
        canonical = f"{base}/sanctions/cpal/{slug}"
        today_human = _date.today().strftime("%B %Y")
        today_iso = _date.today().isoformat()
        year = _date.today().year

        title = f"{name} — Cuba Hotel Sanctions Status ({year})"
        loc_phrase = f" in {province}" if province else ""
        description = (
            f"{name}{loc_phrase} is on the U.S. Cuba Prohibited "
            f"Accommodations List (CPAL) as of {today_human}. "
            f"U.S. persons cannot stay at this property under "
            f"§515.210 CACR regardless of booking channel."
        )[:300]

        seo = {
            "title": title,
            "description": description,
            "keywords": (
                f"{name} sanctions, {name} CPAL, {name} Cuba prohibited, "
                f"is {name} on the CPAL, US travelers {name}, "
                f"{name} sanciones, {name} alojamiento prohibido Cuba, "
                f"§515.210 CACR, Cuba Prohibited Accommodations List, "
                f"hoteles prohibidos Cuba"
            ),
            "canonical": canonical,
            "site_name": _s.site_name,
            "site_url": base,
            "locale": _s.site_locale,
            "locale_alternate": "es_CU",
            "og_image": f"{base}/static/og-image.png?v=3",
            "og_type": "article",
            "published_iso": _iso(_dt.utcnow()),
            "modified_iso": _iso(_dt.utcnow()),
        }

        breadcrumb = {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
                {"@type": "ListItem", "position": 2, "name": "Cuba Sanctions", "item": f"{base}/sanctions-tracker"},
                {"@type": "ListItem", "position": 3, "name": "Prohibited Accommodations", "item": f"{base}/tools/cuba-prohibited-hotels-checker"},
                {"@type": "ListItem", "position": 4, "name": name, "item": canonical},
            ],
        }
        hotel_node = {
            "@type": "Hotel",
            "@id": f"{canonical}#hotel",
            "name": name,
            "url": canonical,
            "description": description,
        }
        if address or province:
            hotel_node["address"] = {
                "@type": "PostalAddress",
                "addressLocality": province or "Cuba",
                "addressCountry": "CU",
                "streetAddress": address or province or "Cuba",
            }
        is_q = f"Is {name} on the Cuba Prohibited Accommodations List?"
        is_a = (
            f"Yes. As of {today_human}, {name}{loc_phrase} is on the U.S. "
            f"State Department Cuba Prohibited Accommodations List (CPAL) "
            f"under §515.210 of the Cuban Assets Control Regulations. U.S. "
            f"persons are prohibited from lodging or paying for lodging at "
            f"this property, regardless of whether the booking is made "
            f"through a U.S., Cuban, or third-country travel agent or platform."
        )
        why_q = f"Why is {name} on the CPAL?"
        why_a = (
            "The State Department adds properties to the CPAL when they are "
            "owned or controlled by a Cuban government entity, party "
            "official, or other prohibited party. Inclusion is a "
            "compliance determination made by State, separate from the "
            "OFAC SDN list and the State Department Cuba Restricted List."
        )
        faq_node = {
            "@type": "FAQPage",
            "@id": f"{canonical}#faq",
            "mainEntity": [
                {"@type": "Question", "name": is_q, "acceptedAnswer": {"@type": "Answer", "text": is_a[:500]}},
                {"@type": "Question", "name": why_q, "acceptedAnswer": {"@type": "Answer", "text": why_a[:500]}},
            ],
        }

        jsonld = _json.dumps({
            "@context": "https://schema.org",
            "@graph": [breadcrumb, hotel_node, faq_node],
        }, ensure_ascii=False)

        template = _env.get_template("sanctions/cpal_profile.html.j2")
        html = template.render(
            name=name,
            province=province,
            neighborhood=neighborhood,
            address=address,
            marker=marker,
            siblings=siblings,
            seo=seo,
            jsonld=jsonld,
            today_human=today_human,
            today_iso=today_iso,
            year=year,
            refreshed_on=index.get("refreshed_on", ""),
            faq=[{"q": is_q, "a": is_a}, {"q": why_q, "a": why_a}],
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("CPAL profile render failed for slug=%s: %s", slug, exc)
        abort(500)


@app.route("/sanctions/hotel-san-alejandro")
@app.route("/sanctions/hotel-san-alejandro/")
def hotel_san_alejandro_cpal_redirect():
    """Short GSC-friendly alias for the indexed CPAL property page."""
    return redirect("/sanctions/cpal/hotel-san-alejandro", code=301)


@app.route("/sanctions/hotel-san-fernando")
@app.route("/sanctions/hotel-san-fernando/")
def hotel_san_fernando_cpal_redirect():
    """Short GSC-friendly alias for the indexed CPAL property page."""
    return redirect("/sanctions/cpal/hotel-san-fernando", code=301)


@app.route("/sanctions/crl/<slug>")
@app.route("/sanctions/crl/<slug>/")
def crl_profile_page(slug: str):
    """One Cuba Restricted List entity -> one indexable page.

    These pages cover exact-query intent such as "la maisón (fashion)
    sanctions" where a searcher needs a definitive State Department CRL
    answer, not just the broader checker UI.
    """
    from src.page_renderer import _env, _base_url, _iso, settings as _s
    from datetime import date as _date, datetime as _dt
    import json as _json

    index = _crl_profile_index()
    row = index["by_slug"].get(slug)
    if not row:
        abort(404)

    try:
        name = (row.get("name") or "").strip()
        section = (row.get("section") or "").strip()
        kind = row.get("kind") or _crl_kind_for_section(section)
        location = row.get("location") or _crl_location_for_section(section)

        siblings: list[dict] = []
        if section:
            for r in list_crl_profiles():
                if r["slug"] == slug:
                    continue
                if (r.get("section") or "").strip() == section:
                    siblings.append(r)
                if len(siblings) >= 8:
                    break

        base = _base_url()
        canonical = f"{base}/sanctions/crl/{slug}"
        today_human = _date.today().strftime("%B %Y")
        today_iso = _date.today().isoformat()
        year = _date.today().year

        title = f"{name} — Cuba Sanctions Status ({year})"
        section_phrase = f" in {section}" if section else ""
        description = (
            f"{name}{section_phrase} is on the U.S. Cuba Restricted "
            f"List (CRL) as of {today_human}. U.S. persons are "
            f"prohibited from direct financial transactions with "
            f"this entity under §515.209 CACR."
        )[:300]

        seo = {
            "title": title,
            "description": description,
            "keywords": (
                f"{name} sanctions, {name} Cuba Restricted List, "
                f"{name} CRL, is {name} sanctioned, "
                f"{name} sanciones, {name} lista restringida Cuba, "
                f"OFAC Cuba Restricted List, §515.209 CACR, "
                "State Department Cuba Restricted List, "
                "entidades restringidas Cuba"
            ),
            "canonical": canonical,
            "site_name": _s.site_name,
            "site_url": base,
            "locale": _s.site_locale,
            "locale_alternate": "es_CU",
            "og_image": f"{base}/static/og-image.png?v=3",
            "og_type": "article",
            "published_iso": _iso(_dt.utcnow()),
            "modified_iso": _iso(_dt.utcnow()),
        }

        breadcrumb = {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
                {"@type": "ListItem", "position": 2, "name": "Cuba Sanctions", "item": f"{base}/sanctions-tracker"},
                {"@type": "ListItem", "position": 3, "name": "Cuba Restricted List", "item": f"{base}/tools/cuba-restricted-list-checker"},
                {"@type": "ListItem", "position": 4, "name": name, "item": canonical},
            ],
        }
        entity_node = {
            "@type": "Organization",
            "@id": f"{canonical}#entity",
            "name": name,
            "url": canonical,
            "description": description,
            "subjectOf": {
                "@type": "GovernmentService",
                "name": "Cuba Restricted List",
                "provider": {"@type": "GovernmentOrganization", "name": "U.S. Department of State"},
            },
        }
        if section:
            entity_node["additionalType"] = section

        is_q = f"Is {name} on the Cuba Restricted List?"
        is_a = (
            f"Yes. As of {today_human}, {name} is listed on the U.S. "
            f"State Department Cuba Restricted List under §515.209 of "
            "the Cuban Assets Control Regulations. U.S. persons are "
            "generally prohibited from engaging in direct financial "
            "transactions with the entity unless a narrow OFAC "
            "authorization applies."
        )
        sdn_q = f"Is {name} the same as an OFAC SDN listing?"
        sdn_a = (
            "Not necessarily. The Cuba Restricted List is maintained by "
            "the State Department and is separate from the Treasury OFAC "
            "SDN list. A Cuban entity can be restricted under §515.209 "
            "even if it does not appear as an SDN."
        )
        faq = [{"q": is_q, "a": is_a}, {"q": sdn_q, "a": sdn_a}]
        faq_node = {
            "@type": "FAQPage",
            "@id": f"{canonical}#faq",
            "mainEntity": [
                {"@type": "Question", "name": f["q"], "acceptedAnswer": {"@type": "Answer", "text": f["a"][:500]}}
                for f in faq
            ],
        }

        jsonld = _json.dumps({
            "@context": "https://schema.org",
            "@graph": [breadcrumb, entity_node, faq_node],
        }, ensure_ascii=False)

        template = _env.get_template("sanctions/crl_profile.html.j2")
        html = template.render(
            name=name,
            section=section,
            kind=kind,
            location=location,
            siblings=siblings,
            seo=seo,
            jsonld=jsonld,
            today_human=today_human,
            today_iso=today_iso,
            year=year,
            refreshed_on=index.get("refreshed_on", ""),
            faq=faq,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("CRL profile render failed for slug=%s: %s", slug, exc)
        abort(500)


@app.route("/travel/cuba-prohibited-accommodations-list")
@app.route("/travel/cuba-prohibited-accommodations-list/")
def cuba_prohibited_accommodations_list_redirect():
    """Exact-query alias; canonical content lives on the CPAL checker."""
    return redirect("/tools/cuba-prohibited-hotels-checker", code=301)


@app.route("/tools/cuba-prohibited-hotels-checker")
@app.route("/tools/cuba-prohibited-hotels-checker/")
def tool_cpal_hotel_checker():
    """Search the State Department Cuba Prohibited Accommodations List for
    a property name (CACR §515.210)."""
    try:
        from src.page_renderer import _env
        from datetime import date as _date
        from collections import Counter

        query = (request.args.get("q") or "").strip()
        province_filter = (request.args.get("province") or "").strip()
        neighborhood_filter = (request.args.get("neighborhood") or "").strip()

        entries, refreshed_on = _load_state_dept_snapshot("cpal")
        all_rows = list(entries.values())
        total_entries = len(all_rows)

        # Tag every row with a derived neighborhood (best-effort match
        # against curated list of Cuban tourist zones). Also store on
        # the row dicts so the option lists and result cards can both
        # reference it without re-running the regex.
        for r in all_rows:
            r["_neighborhood"] = _extract_cpal_neighborhood(r.get("address") or "")

        provinces = sorted({r.get("province", "") for r in all_rows if r.get("province")})

        province_counter: Counter[str] = Counter(
            r.get("province", "") for r in all_rows if r.get("province")
        )
        province_counts = sorted(province_counter.items(), key=lambda kv: kv[0])

        neighborhood_counter: Counter[str] = Counter(
            r["_neighborhood"] for r in all_rows if r.get("_neighborhood")
        )
        # Sort neighborhoods by frequency (most CPAL properties first)
        # so high-traffic tourist zones surface at the top of the picker.
        neighborhood_counts = neighborhood_counter.most_common()

        # Build (province, [property_dicts]) tuples for the <optgroup>
        # picker — same alphabetical province ordering as the filter
        # dropdown, with each province's properties sorted by name.
        properties_by_province: list[tuple[str, list[dict]]] = []
        for province in provinces:
            props = sorted(
                [r for r in all_rows if r.get("province") == province],
                key=lambda r: (r.get("name") or "").lower(),
            )
            properties_by_province.append((province, props))

        matches: list[dict] = []
        if query or province_filter or neighborhood_filter:
            for r in all_rows:
                name = (r.get("name") or "").strip()
                province = (r.get("province") or "").strip()
                address = (r.get("address") or "").strip()
                marker = (r.get("marker") or "").strip()
                neighborhood = r.get("_neighborhood") or ""

                if province_filter and province != province_filter:
                    continue
                if neighborhood_filter and neighborhood != neighborhood_filter:
                    continue

                if query:
                    score = _fuzzy_score(query, name, address)
                    if score < 0.7:
                        continue
                else:
                    score = 1.0

                matches.append({
                    "name": name,
                    "province": province,
                    "neighborhood": neighborhood,
                    "address": address,
                    "marker": marker,
                    "score": int(round(score * 100)),
                })

            matches.sort(key=lambda m: (-m["score"], m["province"], m["name"]))
            matches = matches[:60]

            cpal_idx = _cpal_profile_index()["by_slug"]
            name_to_slug: dict[str, str] = {}
            for s, row in cpal_idx.items():
                name_to_slug.setdefault((row.get("name") or "").strip(), s)
            for m in matches:
                slug = name_to_slug.get(m["name"])
                if slug:
                    m["url_path"] = f"/sanctions/cpal/{slug}"

        if query:
            tool_title = f"Is {query.title()} on the Cuba Prohibited Hotels List? — CPAL Checker"
            tool_desc = (
                f"Check whether {query.title()} is on the U.S. State "
                f"Department Cuba Prohibited Accommodations List (CPAL). "
                f"Search all {total_entries} sanctioned properties — "
                f"hotels, casas particulares, and resorts. Updated daily."
            )
        else:
            tool_title = f"Cuba Prohibited Hotels List ({total_entries} Properties, {_date.today().year}) — Sanctions Checker"
            tool_desc = (
                f"Check if your Cuba hotel is sanctioned. Search all "
                f"{total_entries} properties on the U.S. State Department "
                f"Prohibited Accommodations List (CPAL) — hotels, casas "
                f"particulares, and resorts. Filter by name, province, or "
                f"neighborhood. Updated daily."
            )

        seo, jsonld = _tool_seo_jsonld(
            slug="cuba-prohibited-hotels-checker",
            title=tool_title,
            description=tool_desc,
            keywords=(
                "Cuba prohibited accommodations list, Cuba prohibited "
                "accommodations list OFAC 2026, CPAL hotel checker, State "
                "Department Cuba accommodations, §515.210 CACR, Hotel San "
                "Alejandro sanctions, Hotel San Fernando sanctions, Hotel "
                "Nacional CPAL, Iberostar Cuba banned, Meliá Cuba sanctions, "
                "Habaguanex OFAC, Gaviota hotels US prohibition, Lista de "
                "Alojamientos Prohibidos de Cuba, hoteles prohibidos en Cuba, "
                "alojamientos prohibidos Cuba"
            ),
            faq=[
                {
                    "q": "What is the Cuba Prohibited Accommodations List (CPAL)?",
                    "a": (
                        "The CPAL is a list maintained by the U.S. State "
                        "Department under §515.210 of the Cuban Assets "
                        "Control Regulations identifying specific hotels, "
                        "hostales, casas, and resorts in Cuba at which "
                        "U.S. persons are prohibited from lodging or "
                        "paying for related accommodations expenses, "
                        "regardless of whether the booking is made "
                        "through a U.S. or third-country travel agent or "
                        "platform. Inclusion is based on the property "
                        "being owned or controlled by a Cuban government "
                        "entity, party official, or prohibited party."
                    ),
                },
                {
                    "q": "Is the CPAL the same as the Cuba Restricted List (CRL)?",
                    "a": (
                        "No. They are separate lists, both maintained by "
                        "the State Department but published under "
                        "different sections of the CACR. The CRL "
                        "(§515.209) lists Cuban entities U.S. persons "
                        "may not engage in direct financial transactions "
                        "with (e.g. GAESA, CIMEX, Gaviota, Habaguanex). "
                        "The CPAL (§515.210) lists specific lodging "
                        "properties. A property may be on CPAL because "
                        "its operator is on the CRL, but the lists are "
                        "structurally distinct and you must check both. "
                        "Neither overlaps fully with the OFAC SDN list."
                    ),
                },
                {
                    "q": "What if I book through Booking.com, Airbnb, or a non-U.S. agent?",
                    "a": (
                        "The §515.210 prohibition follows the U.S. "
                        "person, not the booking channel. A U.S. citizen "
                        "lodging at a CPAL-listed property is "
                        "prohibited even when the reservation, payment, "
                        "or platform is foreign. Airbnb and similar "
                        "platforms operate under separate authorisations "
                        "(§515.578 telecoms / general internet services) "
                        "but the underlying lodging prohibition still "
                        "applies."
                    ),
                },
                {
                    "q": "What about casas particulares?",
                    "a": (
                        "Genuine independently-owned casas particulares "
                        "are generally permissible under §515.574 "
                        "(\u201csupport for the Cuban people\u201d) and are the "
                        "canonical U.S.-traveller compliance pattern. "
                        "However, the State Department flags two "
                        "subcategories on the CPAL: properties marketed "
                        "as casas but actually state-owned (* marker), "
                        "and genuine private casas that nevertheless "
                        "meet CPAL inclusion criteria (^ marker). Both "
                        "are prohibited."
                    ),
                },
            ],
            dataset={
                "name": "Cuba Prohibited Accommodations List (CPAL)",
                "description": (
                    f"State Department list of Cuban hotels, hostales and "
                    f"casas at which U.S. persons may not lodge under "
                    f"§515.210 CACR. {total_entries} properties across "
                    f"{len(provinces)} provinces."
                ),
                "creator": {
                    "@type": "Organization",
                    "name": "U.S. Department of State",
                    "url": "https://www.state.gov/",
                },
                "license": "https://www.usa.gov/government-works",
                "isAccessibleForFree": True,
            },
        )

        from src.seo.cluster_topology import build_cluster_ctx, build_related_tools_ctx
        cluster_ctx = build_cluster_ctx("/tools/cuba-prohibited-hotels-checker")
        related_tools_ctx = build_related_tools_ctx("/tools/cuba-prohibited-hotels-checker")

        all_profiles = list_cpal_profiles()
        profiles_by_prov: list[tuple[str, list[dict]]] = []
        prov_bucket: dict[str, list[dict]] = {}
        for p in all_profiles:
            prov_bucket.setdefault(p["province"], []).append(p)
        for prov in sorted(prov_bucket):
            profiles_by_prov.append((prov, sorted(prov_bucket[prov], key=lambda x: x["name"])))

        template = _env.get_template("tools/cpal_hotel_checker.html.j2")
        html = template.render(
            query=query,
            province_filter=province_filter,
            neighborhood_filter=neighborhood_filter,
            provinces=provinces,
            province_counts=province_counts,
            neighborhood_counts=neighborhood_counts,
            properties_by_province=properties_by_province,
            matches=matches,
            total_entries=total_entries,
            refreshed_on=refreshed_on or "snapshot pending",
            seo=seo,
            jsonld=jsonld,
            cluster_ctx=cluster_ctx,
            related_tools_ctx=related_tools_ctx,
            profiles_by_province=profiles_by_prov,
            current_year=_date.today().year,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("CPAL hotel checker render failed: %s", exc)
        abort(500)


def _crl_location_for_section(section: str) -> str:
    """Map a CRL section label to a human-readable location, or "" if the
    section has no geographic dimension (e.g. "Holding Companies",
    "Ministries", "Additional Subentities of CIMEX")."""
    if not section:
        return ""
    s = section.strip()
    # "Hotels in <X> Province" / "Hotels <X> Province" (irregular spellings
    # in the State Dept source)
    for prefix in ("Hotels in ", "Hotels "):
        if s.startswith(prefix):
            rest = s[len(prefix):]
            if rest.endswith(" Province"):
                rest = rest[: -len(" Province")]
            return rest.strip()
    if s.startswith("Stores in "):
        return s[len("Stores in "):].strip()
    if s.startswith("Cayo ") or s == "Topes de Collantes":
        return s
    return ""


def _crl_kind_for_section(section: str) -> str:
    """Roll up State Dept's 23 granular section headings (e.g. "Hotels in
    La Habana Province", "Additional Subentities of CIMEX") into ~8
    coarse browse buckets. The raw section is still preserved on every
    match card and in the entity picker, so audit traceability is intact.
    """
    if not section:
        return ""
    s = section.strip()
    if (
        s.startswith("Hotels in ")
        or s.startswith("Hotels ")
        or s.startswith("Cayo ")
        or s == "Topes de Collantes"
    ):
        return "Hotels"
    if s.startswith("Additional Subentities of "):
        return "Subentities"
    if s.startswith("Stores in "):
        return "Stores"
    if s == "Entities Directly Serving the Defense and Security Sectors":
        return "Defense"
    if s == "Marinas":
        return "Marinas"
    if s == "Holding Companies":
        return "Holdings"
    if s == "Tourist Agencies":
        return "Tourist agencies"
    if s == "Ministries":
        return "Ministries"
    return s


@app.route("/tools/cuba-restricted-list-checker")
@app.route("/tools/cuba-restricted-list-checker/")
def tool_crl_entity_checker():
    """Search the State Department Cuba Restricted List for an entity name
    (CACR §515.209)."""
    try:
        from src.page_renderer import _env
        from datetime import date as _date
        from collections import Counter

        query = (request.args.get("q") or "").strip()
        # ``section`` is kept for backward compatibility with any inbound
        # links that pre-date the kind rollup; the picker now exposes
        # ``kind`` (the rolled-up bucket) instead.
        section_filter = (request.args.get("section") or "").strip()
        kind_filter = (request.args.get("kind") or "").strip()
        location_filter = (request.args.get("location") or "").strip()

        entries, refreshed_on = _load_state_dept_snapshot("crl")
        all_rows = list(entries.values())
        total_entries = len(all_rows)
        crl_profile_by_key = {
            ((r.get("name") or "").strip(), (r.get("section") or "").strip()): r
            for r in list_crl_profiles()
        }

        sections = sorted({r.get("section", "") for r in all_rows if r.get("section")})
        section_counter: Counter[str] = Counter(
            r.get("section", "") for r in all_rows if r.get("section")
        )
        section_counts = sorted(section_counter.items(), key=lambda kv: kv[0])

        kind_counter: Counter[str] = Counter()
        for r in all_rows:
            k = _crl_kind_for_section(r.get("section", ""))
            if k:
                kind_counter[k] += 1
        # Show "Hotels" / "Subentities" first since they dominate the list,
        # then the rest alphabetically — feels right for a browse picker.
        _kind_priority = {"Hotels": 0, "Subentities": 1, "Defense": 2}
        kind_counts = sorted(
            kind_counter.items(),
            key=lambda kv: (_kind_priority.get(kv[0], 99), kv[0]),
        )

        location_counter: Counter[str] = Counter()
        for r in all_rows:
            loc = _crl_location_for_section(r.get("section", ""))
            if loc:
                location_counter[loc] += 1
        location_counts = sorted(location_counter.items(), key=lambda kv: kv[0])

        # Flat A-Z list for the "Pick an entity" dropdown. Section
        # context is preserved on each match card after the user picks,
        # so we don't need to clutter the long picker with optgroups.
        entities_alpha = sorted(
            (
                {
                    "name": (r.get("name") or "").strip(),
                    "section": (r.get("section") or "").strip(),
                }
                for r in all_rows
                if (r.get("name") or "").strip()
            ),
            key=lambda x: x["name"].lower(),
        )

        matches: list[dict] = []
        if query or section_filter or kind_filter or location_filter:
            for r in all_rows:
                name = (r.get("name") or "").strip()
                section = (r.get("section") or "").strip()

                if section_filter and section != section_filter:
                    continue
                if kind_filter and _crl_kind_for_section(section) != kind_filter:
                    continue
                if location_filter and _crl_location_for_section(section) != location_filter:
                    continue

                if query:
                    score = _fuzzy_score(query, name, section)
                    if score < 0.7:
                        continue
                else:
                    score = 1.0

                matches.append({
                    "name": name,
                    "section": section,
                    "url_path": (
                        crl_profile_by_key.get((name, section), {}).get("url_path")
                    ),
                    "score": int(round(score * 100)),
                })

            matches.sort(key=lambda m: (-m["score"], m["section"], m["name"]))
            matches = matches[:60]

        seo, jsonld = _tool_seo_jsonld(
            slug="cuba-restricted-list-checker",
            title=f"Cuba Restricted List Checker ({total_entries} Entities, 2026) — CRL Search",
            description=(
                f"Search the Cuba Restricted List (CRL) — all "
                f"{total_entries} Cuban entities U.S. persons cannot "
                f"transact with under §515.209, including GAESA, Gaviota, "
                f"CIMEX, Habaguanex, FINCIMEX, and MINFAR. Updated daily "
                f"from state.gov. Not the same as the OFAC SDN — check both."
            ),
            keywords=(
                "OFAC Cuba Restricted List, Cuba Restricted List checker, CRL Cuba lookup, GAESA "
                "sanctions check, CIMEX OFAC, Gaviota CRL, Habaguanex "
                "restricted, §515.209 CACR, State Department Cuba "
                "entities, MINFAR sanctions, FINCIMEX prohibited, Lista "
                "Restringida de Cuba, lista de entidades restringidas de Cuba, "
                "sanciones de Cuba"
            ),
            faq=[
                {
                    "q": "What is the Cuba Restricted List (CRL)?",
                    "a": (
                        "The CRL is a list of Cuban government and "
                        "Communist Party-affiliated entities maintained "
                        "by the U.S. State Department under §515.209 of "
                        "the Cuban Assets Control Regulations. U.S. "
                        "persons are prohibited from engaging in direct "
                        "financial transactions with any entity on the "
                        "list. The list anchors on GAESA (the military "
                        "holding company that controls a large share of "
                        "Cuba's tourism economy) and its dozens of "
                        "subentities — CIMEX, Gaviota, Habaguanex, "
                        "FINCIMEX, AT Comercial, ALMEST, BFI, and many "
                        "more."
                    ),
                },
                {
                    "q": "How is the CRL different from the OFAC SDN list?",
                    "a": (
                        "The OFAC Specially Designated Nationals (SDN) "
                        "list is the Treasury-maintained sanctions list "
                        "covering parties designated under all U.S. "
                        "sanctions programs. The CRL is a State "
                        "Department-maintained list covering only Cuba. "
                        "Most entities on the CRL — including GAESA, "
                        "CIMEX, Gaviota and Habaguanex — are NOT on the "
                        "OFAC SDN. A clean SDN screen does NOT mean a "
                        "Cuban counterparty is safe to transact with. "
                        "Both lists must be checked independently, "
                        "alongside the OFAC 50% Rule ownership-chain "
                        "analysis and the CPAL accommodations list."
                    ),
                },
                {
                    "q": "What does a transaction with a CRL entity actually look like?",
                    "a": (
                        "Direct financial transactions include paying for "
                        "lodging at a CRL-controlled hotel, paying a CRL "
                        "tour operator, transferring funds to a CRL "
                        "ministry or holding company, or routing payments "
                        "through a CRL-listed bank such as BFI. Some "
                        "transactions are carved out — most notably those "
                        "authorised by §515.578 (telecoms / internet "
                        "services), §515.582 (exports to independent "
                        "Cuban entrepreneurs), §515.533 (TSRA agricultural "
                        "and medical exports), and certain remittances "
                        "and people-to-people educational activities — "
                        "but the carve-outs are narrow and fact-specific."
                    ),
                },
            ],
            dataset={
                "name": "Cuba Restricted List (CRL)",
                "description": (
                    f"State Department list of Cuban entities U.S. persons "
                    f"may not engage in direct financial transactions with "
                    f"under §515.209 CACR. {total_entries} entries across "
                    f"{len(sections)} categories (ministries, holdings, "
                    f"hotels, marinas, stores, defense entities, "
                    f"subentities)."
                ),
                "creator": {
                    "@type": "Organization",
                    "name": "U.S. Department of State",
                    "url": "https://www.state.gov/",
                },
                "license": "https://www.usa.gov/government-works",
                "isAccessibleForFree": True,
            },
        )

        from src.seo.cluster_topology import build_cluster_ctx, build_related_tools_ctx
        cluster_ctx = build_cluster_ctx("/tools/cuba-restricted-list-checker")
        related_tools_ctx = build_related_tools_ctx("/tools/cuba-restricted-list-checker")

        template = _env.get_template("tools/crl_entity_checker.html.j2")
        html = template.render(
            query=query,
            section_filter=section_filter,
            kind_filter=kind_filter,
            location_filter=location_filter,
            sections=sections,
            section_counts=section_counts,
            kind_counts=kind_counts,
            location_counts=location_counts,
            entities_alpha=entities_alpha,
            matches=matches,
            total_entries=total_entries,
            refreshed_on=refreshed_on or "snapshot pending",
            seo=seo,
            jsonld=jsonld,
            cluster_ctx=cluster_ctx,
            related_tools_ctx=related_tools_ctx,
            current_year=_date.today().year,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("CRL entity checker render failed: %s", exc)
        abort(500)


# Mapping of trip-purpose IDs → OFAC general-license citation, label, and
# short marketing-style description. Keyed in trip-frequency order so the
# wizard surfaces the categories most U.S. travellers actually use first.
_TRAVEL_PURPOSE_OPTIONS: list[dict] = [
    {"id": "support", "label": "Support for the Cuban people (independent travel)",
     "cite": "§515.574 — the most-used individual category"},
    {"id": "family", "label": "Visit close family in Cuba",
     "cite": "§515.563 — family visits"},
    {"id": "education", "label": "Educational program / people-to-people group",
     "cite": "§515.565 — must be sponsored by a U.S. organisation"},
    {"id": "research", "label": "Professional research or professional meeting",
     "cite": "§515.564 — academics, conference attendees, industry meetings"},
    {"id": "journalism", "label": "Journalism / news gathering",
     "cite": "§515.561 — full-time employed journalists"},
    {"id": "religious", "label": "Religious activity",
     "cite": "§515.566 — church, faith-based delegation"},
    {"id": "humanitarian", "label": "Humanitarian project",
     "cite": "§515.575 — medical relief, NGO work"},
    {"id": "performance", "label": "Public performance, sports, workshop, exhibition",
     "cite": "§515.567 — musicians, athletes, FIHAV exhibitors"},
    {"id": "government", "label": "Official U.S./foreign government or IGO business",
     "cite": "§515.562 — embassy staff, USDA, intergovernmental orgs"},
    {"id": "exports", "label": "Support an authorised export (TSRA ag, medical, MIPYME goods)",
     "cite": "§515.572 / §515.582 — agricultural and MIPYMES exporters"},
    {"id": "foundation", "label": "Activity of a private foundation or research institute",
     "cite": "§515.576 — Ford, Open Society, Brookings, etc."},
    {"id": "tourism", "label": "Pure tourism (beach, leisure, no other category fits)",
     "cite": "Not authorised under any general license"},
]


# Per-purpose verdicts. Each entry produces the headline, the OFAC-citation
# block, the body explanation, and a checklist of what the traveller must
# actually do. Cuban-side requirements are appended uniformly at the end.
_TRAVEL_VERDICTS: dict[str, dict] = {
    "support": {
        "tone": "allowed",
        "headline": "Yes — your trip is authorised under \u201csupport for the Cuban people.\u201d",
        "gl": "31 CFR §515.574",
        "gl_title": "Support for the Cuban People",
        "body": (
            "This is the only individual self-organised category that survived the 2019 Trump-era restrictions. "
            "It requires a full-time schedule of activities that meaningfully interact with Cubans — staying in "
            "casas particulares, eating at paladares, hiring independent guides, and supporting MIPYME businesses. "
            "Pure beach-and-resort itineraries do not qualify."
        ),
        "checklist": [
            "Build and keep a written full-time daily schedule of qualifying activities (casa visits, paladar meals, MIPYME interactions, civil-society meetings).",
            "Stay only at independent <a href=\"/tools/cuba-prohibited-hotels-checker\">casas particulares NOT on the CPAL</a> — check every single property before booking.",
            "Avoid any <a href=\"/tools/cuba-restricted-list-checker\">CRL-listed counterparty</a> (GAESA, Gaviota, Habaguanex, CIMEX, FINCIMEX) for hotels, tours, or payments.",
            "Retain ALL records — schedule, receipts, contact list — for 5 years per §515.601.",
            "Self-attest the §515.574 category at airline check-in (the airline records the OFAC category for the U.S.-version Tourist Card).",
        ],
    },
    "family": {
        "tone": "allowed",
        "headline": "Yes — family visits to close relatives in Cuba are authorised.",
        "gl": "31 CFR §515.563",
        "gl_title": "Family visits to close relatives in Cuba",
        "body": (
            "Cuban-American and U.S.-permanent-resident travellers may visit close relatives in Cuba "
            "(parents, grandparents, siblings, children, spouses, and certain in-laws). The Trump-era "
            "frequency caps were partially relaxed under the Biden administration in May 2022; current "
            "rules permit reasonable family-visit frequency."
        ),
        "checklist": [
            "Confirm the relative meets the §515.339 \u201cclose relative\u201d definition (parents, grandparents, siblings, children, spouses, including in-laws).",
            "Keep documentation of the family relationship and the visit purpose.",
            "Family visits CAN include lodging at family homes — but if you stay at a hotel or casa, it must not be on the <a href=\"/tools/cuba-prohibited-hotels-checker\">CPAL</a>.",
            "Remittances accompanying the trip are governed separately under §515.570 — review limits.",
            "Retain travel records for 5 years per §515.601.",
        ],
    },
    "education": {
        "tone": "conditional",
        "headline": "Yes — but only as part of a U.S.-sponsored educational program.",
        "gl": "31 CFR §515.565",
        "gl_title": "Educational activities and people-to-people exchanges",
        "body": (
            "After the 2019 amendments, individual people-to-people travel is no longer authorised. "
            "All educational and people-to-people travel must now be conducted under the auspices of a "
            "U.S.-based academic institution or a sponsoring U.S. organisation that maintains the "
            "OFAC compliance program for the trip."
        ),
        "checklist": [
            "Confirm a qualifying U.S. sponsor (university, accredited program, or licensed group operator) is the legal sponsor.",
            "Travel must be in a group with a U.S. representative accompanying the group.",
            "Full-time schedule of educational activities — no free time at resorts.",
            "Sponsor handles OFAC documentation; you should still keep a personal copy of the schedule.",
            "Sponsor must avoid <a href=\"/tools/cuba-restricted-list-checker\">CRL-listed</a> hotels and tour operators — verify before payment.",
        ],
    },
    "research": {
        "tone": "allowed",
        "headline": "Yes — professional research and meetings are authorised.",
        "gl": "31 CFR §515.564",
        "gl_title": "Professional research and professional meetings in Cuba",
        "body": (
            "Authorises full-time professional research and attendance at professional meetings in any "
            "field, provided the activity is not for personal recreation. Used by academics, industry "
            "professionals attending conferences (FIHAV, biotech symposia, Mariel ZED investor briefings), "
            "and consultants conducting field research."
        ),
        "checklist": [
            "Maintain a documented research plan and / or conference agenda.",
            "Schedule must be full-time; incidental tourism is permitted but cannot dominate.",
            "Hotel choice — verify no <a href=\"/tools/cuba-prohibited-hotels-checker\">CPAL</a> listing and avoid <a href=\"/tools/cuba-restricted-list-checker\">CRL</a> operators where feasible.",
            "Retain agenda, tickets, attendance records, contact list for 5 years (§515.601).",
            "If meeting Cuban government counterparties, screen each against the <a href=\"/tools/ofac-cuba-sanctions-checker\">OFAC SDN list</a>.",
        ],
    },
    "journalism": {
        "tone": "conditional",
        "headline": "Yes — full-time journalists for news organisations are authorised.",
        "gl": "31 CFR §515.561",
        "gl_title": "Journalistic activity",
        "body": (
            "Authorises travel by full-time journalists employed by news-gathering organisations and by "
            "supporting broadcast / technical staff. Freelancers must demonstrate a regular publishing "
            "track record. Cuba separately requires a journalist visa (D-6) issued by MINREX — the U.S. "
            "OFAC authority does not waive Cuban-side accreditation."
        ),
        "checklist": [
            "Carry employer credentials and a letter of assignment.",
            "Apply in advance for the Cuban D-6 journalist visa via the Cuban Embassy / MINREX — the standard Tourist Card does NOT cover journalism.",
            "Document the news-gathering schedule.",
            "Lodging — verify no <a href=\"/tools/cuba-prohibited-hotels-checker\">CPAL</a> listing.",
            "Retain reporting records, story drafts, and source contact list (with appropriate source-protection care) for 5 years per §515.601.",
        ],
    },
    "religious": {
        "tone": "allowed",
        "headline": "Yes — religious activities are authorised.",
        "gl": "31 CFR §515.566",
        "gl_title": "Religious activities in Cuba",
        "body": (
            "Authorises travel and related transactions for religious activities by religious "
            "organisations or members travelling under the auspices of such organisations."
        ),
        "checklist": [
            "Travel under the auspices of a recognised religious organisation.",
            "Maintain a full-time schedule of religious activities.",
            "Lodging — verify no <a href=\"/tools/cuba-prohibited-hotels-checker\">CPAL</a> listing; many faith-based delegations historically use church guesthouses.",
            "Retain itinerary and organisational sponsorship documentation for 5 years.",
        ],
    },
    "humanitarian": {
        "tone": "allowed",
        "headline": "Yes — humanitarian projects are authorised.",
        "gl": "31 CFR §515.575",
        "gl_title": "Humanitarian projects",
        "body": (
            "Authorises travel for humanitarian projects in Cuba listed in §515.575 — medical and "
            "health projects, disaster relief, support for human rights activities, and a defined "
            "set of community-development categories."
        ),
        "checklist": [
            "Confirm the project fits one of the §515.575(b) enumerated categories.",
            "Maintain a full-time schedule documenting humanitarian activities.",
            "Project sponsor (typically a U.S. NGO) handles primary recordkeeping.",
            "Lodging — verify no <a href=\"/tools/cuba-prohibited-hotels-checker\">CPAL</a> listing; coordinate with project sponsor on safe vendors.",
        ],
    },
    "performance": {
        "tone": "allowed",
        "headline": "Yes — public performances, clinics, and exhibitions are authorised.",
        "gl": "31 CFR §515.567",
        "gl_title": "Public performances, clinics, workshops, athletic and other competitions, and exhibitions",
        "body": (
            "Authorises U.S. participation in qualifying public performances and competitions, clinics, "
            "workshops, athletic events and exhibitions. Used by U.S. sports federations, music ensembles, "
            "and exhibitors at the FIHAV trade fair."
        ),
        "checklist": [
            "Confirm the event is a public performance / competition / exhibition (not a private engagement).",
            "Maintain documentation of the event, schedule, and any compensation arrangements.",
            "Profits from athletic competitions must be donated to U.S. NGOs that benefit the Cuban people.",
            "Lodging — verify no <a href=\"/tools/cuba-prohibited-hotels-checker\">CPAL</a> listing.",
        ],
    },
    "government": {
        "tone": "allowed",
        "headline": "Yes — official government and IGO business is authorised.",
        "gl": "31 CFR §515.562",
        "gl_title": "Official business of the U.S. government, foreign governments, and intergovernmental organisations",
        "body": (
            "Authorises travel by U.S. government employees on official business, foreign government "
            "officials transiting the U.S., and representatives of international organisations such as "
            "the UN, OAS, and others, on official business."
        ),
        "checklist": [
            "Travel orders or official mission documentation in hand.",
            "Standard CPAL / CRL screening still applies for any non-mission lodging or vendor choices.",
            "Coordinate with U.S. Embassy Havana (RPO) for ground logistics.",
        ],
    },
    "exports": {
        "tone": "allowed",
        "headline": "Yes — travel to support an authorised export is authorised.",
        "gl": "31 CFR §515.572 (TSRA / MIPYME exports)",
        "gl_title": "Travel-related transactions necessary to support authorised exports",
        "body": (
            "Authorises travel-related transactions for U.S. agricultural exporters (TSRA, §515.533), "
            "medical exporters (§515.533), telecom and internet-services providers (§515.578), and "
            "exporters supplying independent Cuban entrepreneurs (§515.582). The travel must be tied to "
            "the underlying export activity (negotiating, contracting, servicing)."
        ),
        "checklist": [
            "Carry export documentation tying the trip to a specific authorised transaction.",
            "TSRA exporters — confirm cash-in-advance or third-country financing terms; ALIMPORT is the standard counterparty.",
            "MIPYME exporters under §515.582 — verify the buyer is a private cuentapropista, NOT a state-sector entity.",
            "Lodging — verify no <a href=\"/tools/cuba-prohibited-hotels-checker\">CPAL</a> listing.",
            "Retain export documentation and trip records for 5 years (§515.601).",
        ],
    },
    "foundation": {
        "tone": "allowed",
        "headline": "Yes — qualifying private foundations and institutes are authorised.",
        "gl": "31 CFR §515.576",
        "gl_title": "Activities of private foundations or research or educational institutes",
        "body": (
            "Authorises travel for U.S. private foundations or research / educational institutes that "
            "have an established interest in international relations, to collect information not generally "
            "available and to conduct programs not for profit."
        ),
        "checklist": [
            "Confirm the institution qualifies as a §515.576 foundation / institute.",
            "Travel must be in the institutional capacity, not for personal use.",
            "Standard CPAL / CRL screening for lodging and vendors.",
            "Retain institutional documentation and full-time schedule for 5 years.",
        ],
    },
    "tourism": {
        "tone": "prohibited",
        "headline": "No — pure tourism to Cuba is NOT authorised for U.S. persons.",
        "gl": "31 CFR §515.560",
        "gl_title": "General travel framework",
        "body": (
            "Tourism per se is explicitly excluded from the OFAC general-license framework. "
            "U.S. citizens, U.S. permanent residents, and U.S.-resident persons may not travel to Cuba "
            "for pure leisure / beach / resort purposes. Engaging in tourist transactions in Cuba "
            "violates the CACR and exposes the traveller to civil and criminal penalties under the "
            "International Emergency Economic Powers Act (IEEPA) and the Trading With the Enemy Act."
        ),
        "checklist": [
            "If the trip can be honestly restructured around a qualifying category — most commonly <strong>support for the Cuban people (§515.574)</strong> — re-take this wizard with that purpose.",
            "If no qualifying category truly fits the trip, do not travel; or apply to OFAC for a specific license under §515.801.",
            "Travelling to Cuba via a third country (e.g. Mexico, Bahamas, Cancun) does NOT cure the violation. The CACR follows the U.S. person, not the routing.",
            "Working with U.S. sanctions counsel before any high-stakes trip is strongly recommended.",
        ],
    },
}

_NON_US_VERDICT = {
    "tone": "allowed",
    "headline": "Yes — non-U.S. citizens may travel to Cuba freely as tourists.",
    "gl": None,
    "gl_title": None,
    "body": (
        "The Cuban Assets Control Regulations apply only to U.S. persons (U.S. citizens, U.S. permanent residents, "
        "anyone physically located in the U.S., and U.S. companies). If you hold a non-U.S. passport and are not "
        "ordinarily resident in the U.S., you face NO U.S. legal restrictions on Cuba travel. The only requirements "
        "are Cuban-side: a Tourist Card (Tarjeta del Turista, ~€25–30), travel-medical insurance valid in Cuba, "
        "and the D'Viajeros customs/health declaration filed within 72 h of arrival."
    ),
    "checklist": None,
}

_CUBAN_SIDE_REQUIREMENTS = [
    "Passport valid 6+ months past your entry date.",
    "Tourist Card (Tarjeta del Turista) — pink US-version (~$100, sold by the airline at check-in) for U.S. travellers, green non-US version (~€25-30) for everyone else.",
    "Travel-medical insurance valid in Cuba — checked at the border.",
    "D'Viajeros online customs and health declaration filed within 72 hours of arrival (dviajeros.mitrans.gob.cu) — carry the QR code.",
    "Return / onward ticket.",
    "U.S. travellers — keep written record of your OFAC general-license category for 5 years per §515.601.",
]


@app.route("/tools/can-i-travel-to-cuba")
@app.route("/tools/can-i-travel-to-cuba/")
def tool_can_i_travel_to_cuba():
    """OFAC 12-category travel decision tree for U.S. and non-U.S. travellers."""
    try:
        from src.page_renderer import _env
        from datetime import date as _date

        step = (request.args.get("step") or "").strip().lower()
        passport = (request.args.get("passport") or "").strip().lower()
        purpose = (request.args.get("purpose") or "").strip().lower()

        if step not in ("passport", "purpose", "verdict"):
            step = "passport"

        passport_label = ""
        if passport == "us":
            passport_label = "U.S. citizen / green-card holder"
        elif passport == "us-resident":
            passport_label = "Foreign national resident in the U.S."
        elif passport == "non-us":
            passport_label = "Non-U.S., non-resident"

        purpose_label = ""
        for opt in _TRAVEL_PURPOSE_OPTIONS:
            if opt["id"] == purpose:
                purpose_label = opt["label"]
                break

        if step == "purpose" and not passport:
            step = "passport"
        if step == "verdict" and (not passport or not purpose):
            step = "passport" if not passport else "purpose"

        verdict = None
        if step == "verdict":
            if passport == "non-us":
                verdict = dict(_NON_US_VERDICT)
                verdict["cuban_side"] = _CUBAN_SIDE_REQUIREMENTS
            else:
                base = _TRAVEL_VERDICTS.get(purpose)
                if base is not None:
                    verdict = dict(base)
                    verdict["cuban_side"] = _CUBAN_SIDE_REQUIREMENTS

        step_num_map = {"passport": 1, "purpose": 2, "verdict": 3}
        step_num = step_num_map.get(step, 1)

        seo, jsonld = _tool_seo_jsonld(
            slug="can-i-travel-to-cuba",
            title="Can Americans Travel to Cuba? (2026) — 12 Legal Ways + Requirements",
            description=(
                "Find out if you can legally travel to Cuba in 2026. Free "
                "decision tool covering the 12 OFAC-authorized travel "
                "categories, what records you must keep for 5 years, "
                "which hotels are banned (CPAL), and Cuban-side entry "
                "requirements (Tourist Card, insurance, D'Viajeros). "
                "Works for U.S. and non-U.S. passport holders."
            ),
            keywords=(
                "can americans travel to cuba, can I travel to cuba, "
                "can us citizens travel to cuba, cuba travel ban, "
                "what are the 12 requirements to travel to cuba, "
                "why cant americans go to cuba, OFAC 12 travel categories, "
                "support for the Cuban people §515.574, CACR travel rules, "
                "is it legal to travel to cuba, cuba travel requirements 2026"
            ),
            faq=[
                {
                    "q": "Can Americans travel to Cuba in 2026?",
                    "a": (
                        "Yes — U.S. citizens can legally travel to Cuba, "
                        "but only under one of OFAC's 12 authorized travel "
                        "categories defined in the Cuban Assets Control "
                        "Regulations (CACR §515.560–.578). Pure tourism is "
                        "NOT one of the categories. The most common "
                        "category for individual travelers is §515.574 "
                        "'Support for the Cuban People,' which requires a "
                        "full-time schedule of activities supporting Cuban "
                        "private-sector businesses (casas particulares, "
                        "paladares, MIPYMES). You must avoid all properties "
                        "on the Cuba Prohibited Accommodations List (CPAL) "
                        "and entities on the Cuba Restricted List (CRL)."
                    ),
                },
                {
                    "q": "What are the 12 requirements to travel to Cuba?",
                    "a": (
                        "The '12 requirements' refer to the 12 OFAC-"
                        "authorized travel categories — you must qualify "
                        "under at least one: (1) Family visits §515.561, "
                        "(2) Official U.S. government business §515.562, "
                        "(3) Journalistic activity §515.563, "
                        "(4) Professional research §515.564, "
                        "(5) Educational activities §515.565, "
                        "(6) Religious activities §515.566, "
                        "(7) Public performances §515.567, "
                        "(8) Support for the Cuban people §515.574, "
                        "(9) Humanitarian projects §515.575, "
                        "(10) Private foundation activities §515.576, "
                        "(11) Exportation transactions §515.533, and "
                        "(12) Informational materials §515.545. "
                        "Additionally, all travelers need a Cuban Tourist "
                        "Card (~$50–100), travel-medical insurance valid in "
                        "Cuba, and must complete the D'Viajeros online "
                        "customs/health declaration within 72 hours of arrival."
                    ),
                },
                {
                    "q": "Why can't Americans go to Cuba as tourists?",
                    "a": (
                        "The U.S. trade embargo on Cuba, codified in the "
                        "Cuban Assets Control Regulations (31 CFR Part 515) "
                        "since 1963, prohibits most financial transactions "
                        "between U.S. persons and Cuba. Tourism per se is "
                        "not one of the 12 authorized categories. However, "
                        "the 'Support for the Cuban People' category "
                        "(§515.574) allows individual travel with a "
                        "full-time schedule of activities that directly "
                        "engage with Cuba's private sector — staying at "
                        "casas particulares, eating at paladares, and "
                        "shopping at MIPYME businesses. This is the "
                        "category most individual U.S. travelers use."
                    ),
                },
                {
                    "q": "Do non-U.S. citizens face restrictions on Cuba travel?",
                    "a": (
                        "Non-U.S. citizens who are not U.S. permanent "
                        "residents and not physically in the U.S. face NO "
                        "U.S. legal restrictions on Cuba travel. They may "
                        "visit Cuba freely as tourists. The only "
                        "requirements are Cuban-side: a Tourist Card "
                        "(Tarjeta del Turista, ~€25–30 from your airline "
                        "or a Cuban consulate), travel-medical insurance "
                        "valid in Cuba, and the D'Viajeros customs/health "
                        "declaration filed within 72 hours of arrival."
                    ),
                },
                {
                    "q": "What records must I keep for a Cuba trip?",
                    "a": (
                        "Under CACR §515.601, U.S. travelers must retain "
                        "records for 5 years proving which authorized "
                        "category their trip fell under. Required documents "
                        "include: your full-time schedule of qualifying "
                        "activities, all hotel and transportation receipts, "
                        "a list of Cubans you engaged with (names, "
                        "businesses), export documentation if applicable, "
                        "and any sponsor letter for educational/religious/"
                        "humanitarian travel. OFAC can audit at any time — "
                        "failure to produce records can be treated as "
                        "evidence of unauthorized travel."
                    ),
                },
                {
                    "q": "Is it safe to travel to Cuba?",
                    "a": (
                        "Cuba is generally considered safe for tourists "
                        "compared to other Caribbean and Latin American "
                        "destinations, with low rates of violent crime "
                        "against visitors. The U.S. State Department rates "
                        "Cuba at Level 2 ('Exercise Increased Caution'), "
                        "citing civil unrest risk and arbitrary detention. "
                        "Practical concerns include: rolling blackouts "
                        "(especially outside Havana), limited ATM/card "
                        "infrastructure (U.S.-issued Visa/Mastercard do "
                        "not work), cash-only economy for most transactions, "
                        "and intermittent internet. Use our Havana Safety "
                        "Map for neighborhood-level guidance."
                    ),
                },
            ],
        )

        from src.seo.cluster_topology import build_cluster_ctx, build_related_tools_ctx
        cluster_ctx = build_cluster_ctx("/tools/can-i-travel-to-cuba")
        related_tools_ctx = build_related_tools_ctx("/tools/can-i-travel-to-cuba")

        template = _env.get_template("tools/can_i_travel_to_cuba.html.j2")
        html = template.render(
            step=step,
            step_num=step_num,
            passport=passport,
            passport_label=passport_label,
            purpose=purpose,
            purpose_label=purpose_label,
            purpose_options=_TRAVEL_PURPOSE_OPTIONS,
            verdict=verdict,
            seo=seo,
            jsonld=jsonld,
            cluster_ctx=cluster_ctx,
            related_tools_ctx=related_tools_ctx,
            current_year=_date.today().year,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Cuba travel decision tree render failed: %s", exc)
        abort(500)


@app.route("/tools/ofac-cuba-general-licenses")
@app.route("/tools/ofac-cuba-general-licenses/")
def tool_ofac_general_licenses():
    """Searchable lookup of OFAC general licenses under the Cuban Assets Control Regulations."""
    try:
        from src.data.ofac_general_licenses import list_general_licenses
        from src.page_renderer import _env
        from datetime import date as _date

        licenses = list_general_licenses()

        seo, jsonld = _tool_seo_jsonld(
            slug="ofac-cuba-general-licenses",
            title="OFAC General License List for Cuba (2026) — All CACR §515 Licenses Explained",
            description=(
                "Complete list of OFAC general licenses for Cuba under "
                "the Cuban Assets Control Regulations (31 CFR Part 515). "
                "Covers all 12 travel categories, telecom, remittances, "
                "agricultural exports, and §515.574 Support for the Cuban "
                "People. Searchable, filterable, with links to official "
                "OFAC text. Free compliance tool."
            ),
            keywords=(
                "OFAC general license Cuba, CACR §515.560, CACR §515.574 "
                "support for Cuban people, §515.542 telecom Cuba, §515.533 "
                "agricultural exports Cuba, OFAC Cuba compliance, Cuba "
                "general license search"
            ),
            faq=[
                {
                    "q": "What is an OFAC general license?",
                    "a": (
                        "An OFAC general license is a published "
                        "authorisation that permits a defined category of "
                        "transaction that would otherwise be prohibited by "
                        "US sanctions, without each party having to apply "
                        "for an individual specific license. Under the "
                        "Cuban Assets Control Regulations (31 CFR Part "
                        "515), the general-license framework covers the "
                        "12 authorized travel categories, "
                        "telecommunications, family remittances, "
                        "agricultural and medical exports under TSRA, and "
                        "support for the emerging Cuban private sector "
                        "(MIPYMES)."
                    ),
                },
                {
                    "q": "Which OFAC general license covers travel to Cuba?",
                    "a": (
                        "There is no general license for tourism. US "
                        "travel to Cuba is authorized only under one of "
                        "the 12 categories at 31 CFR §515.560–.578: "
                        "family visits (§515.561), official US-government "
                        "and intergovernmental business (§515.562 / "
                        "§515.563), journalistic activity (§515.563), "
                        "professional research and meetings (§515.564), "
                        "educational activity (§515.565), religious "
                        "(§515.566), public performances and athletic "
                        "competitions (§515.567), support for the Cuban "
                        "people (§515.574, the most-used category), "
                        "humanitarian projects (§515.575), private-"
                        "foundation activity (§515.576), exportation of "
                        "informational materials (§515.545), and "
                        "authorized export transactions (§515.533)."
                    ),
                },
                {
                    "q": "Are OFAC Cuba general licenses permanent?",
                    "a": (
                        "No. OFAC's CACR general licenses have been "
                        "amended repeatedly across the Obama, Trump, "
                        "Biden, and current administrations — for example "
                        "the 2017 rescission of people-to-people group "
                        "travel under §515.565, the 2020 revocation of "
                        "specific licenses for US hotel operations, and "
                        "the 2022 reauthorisation of certain remittance "
                        "categories. Always confirm the current text on "
                        "the OFAC website (treasury.gov/ofac) before "
                        "relying on a general license."
                    ),
                },
            ],
        )

        from src.seo.cluster_topology import build_cluster_ctx, build_related_tools_ctx
        cluster_ctx = build_cluster_ctx("/tools/ofac-cuba-general-licenses")
        related_tools_ctx = build_related_tools_ctx("/tools/ofac-cuba-general-licenses")

        template = _env.get_template("tools/ofac_general_licenses.html.j2")
        html = template.render(
            licenses=licenses,
            seo=seo,
            jsonld=jsonld,
            cluster_ctx=cluster_ctx,
            related_tools_ctx=related_tools_ctx,
            current_year=_date.today().year,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("tool render failed: %s", exc)
        abort(500)


@app.route("/tools/cuba-travel-advisory")
@app.route("/tools/cuba-travel-advisory/")
def tool_cuba_travel_advisory():
    """Cuba travel advisory explainer — State Dept levels, risks, and practical guidance."""
    try:
        from src.page_renderer import _env
        from datetime import date as _date

        seo, jsonld = _tool_seo_jsonld(
            slug="cuba-travel-advisory",
            title="Cuba Travel Advisory 2026: Level 2 — What It Means & Safety Tips",
            description=(
                "Current U.S. State Department travel advisory for Cuba: "
                "Level 2 (Exercise Increased Caution). What risks are cited, "
                "how Cuba compares to other Caribbean destinations, practical "
                "safety tips, and additional OFAC rules for American travelers. "
                "Updated for 2026."
            ),
            keywords=(
                "cuba travel advisory, cuba travel advisory 2026, "
                "is cuba safe to travel, cuba state department advisory, "
                "cuba travel warning, cuba safety level, "
                "is there a travel ban on cuba, cuba travel ban, "
                "cuba travel restrictions, cuba travel ban 2026"
            ),
            faq=[
                {
                    "q": "What is the current travel advisory for Cuba?",
                    "a": (
                        "As of 2026, the U.S. State Department rates Cuba at "
                        "Level 2: 'Exercise Increased Caution.' This is the "
                        "second-lowest of four levels — the same as France, "
                        "Germany, and Spain. Risks cited include civil unrest, "
                        "crime, arbitrary enforcement of local laws, and "
                        "limited U.S. Embassy services in Havana."
                    ),
                },
                {
                    "q": "Is there a travel ban on Cuba?",
                    "a": (
                        "There is no blanket travel ban to Cuba. U.S. citizens "
                        "can legally travel under one of 12 OFAC-authorized "
                        "categories. What's prohibited is tourism — spending "
                        "money for pure leisure with no qualifying activity. "
                        "The most-used category is §515.574 'Support for the "
                        "Cuban People.' Non-U.S. citizens face no U.S. legal "
                        "restrictions."
                    ),
                },
                {
                    "q": "Is Cuba safe to travel to right now?",
                    "a": (
                        "Yes, for most travelers. Cuba's Level 2 advisory is "
                        "the same or lower than most Caribbean destinations "
                        "(Jamaica is Level 3, Haiti is Level 4). Violent crime "
                        "against tourists is rare. Main practical risks: petty "
                        "theft, power outages, limited medical care, and "
                        "U.S. bank cards not working."
                    ),
                },
                {
                    "q": "What happens if I travel to Cuba illegally as an American?",
                    "a": (
                        "OFAC can impose civil penalties up to ~$330,000 per "
                        "violation or criminal penalties up to $1,000,000 and "
                        "20 years imprisonment for willful violations. In "
                        "practice, most first-time individual travelers "
                        "receive warning letters. However, enforcement "
                        "increases during policy-tightening periods."
                    ),
                },
            ],
        )

        from src.seo.cluster_topology import build_cluster_ctx, build_related_tools_ctx
        cluster_ctx = build_cluster_ctx("/tools/cuba-travel-advisory")
        related_tools_ctx = build_related_tools_ctx("/tools/cuba-travel-advisory")

        template = _env.get_template("tools/cuba_travel_advisory.html.j2")
        html = template.render(
            seo=seo,
            jsonld=jsonld,
            cluster_ctx=cluster_ctx,
            related_tools_ctx=related_tools_ctx,
            current_year=_date.today().year,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Cuba travel advisory render failed: %s", exc)
        abort(500)


@app.route("/tools/what-is-ofac")
@app.route("/tools/what-is-ofac/")
def tool_what_is_ofac():
    """OFAC explainer — what the agency does, the SDN list, penalties, and Cuba context."""
    try:
        from src.page_renderer import _env
        from datetime import date as _date

        seo, jsonld = _tool_seo_jsonld(
            slug="what-is-ofac",
            title="What Is OFAC? U.S. Sanctions Agency Explained (2026 Guide)",
            description=(
                "OFAC (Office of Foreign Assets Control) is the U.S. Treasury "
                "bureau that enforces economic sanctions. Learn what OFAC does, "
                "how the SDN list works, what OFAC compliance means, penalties "
                "for violations (up to $20M), and how OFAC applies to Cuba, "
                "Iran, Russia, and 30+ sanctions programs."
            ),
            keywords=(
                "ofac, what is ofac, ofac sanctions, ofac meaning, "
                "ofac compliance, ofac sdn list, office of foreign assets "
                "control, ofac penalties, ofac cuba, ofac search, "
                "what does ofac stand for, is cuba sanctioned by ofac"
            ),
            faq=[
                {
                    "q": "What does OFAC stand for?",
                    "a": (
                        "OFAC stands for the Office of Foreign Assets Control, "
                        "a bureau within the U.S. Department of the Treasury "
                        "responsible for administering and enforcing U.S. "
                        "economic and trade sanctions programs."
                    ),
                },
                {
                    "q": "What is OFAC compliance?",
                    "a": (
                        "OFAC compliance refers to the processes businesses use "
                        "to avoid violating U.S. sanctions — screening "
                        "customers against the SDN list, implementing written "
                        "compliance programs, training employees, and reporting "
                        "blocked transactions. All U.S. persons and businesses "
                        "with international exposure must comply."
                    ),
                },
                {
                    "q": "Is Cuba sanctioned by OFAC?",
                    "a": (
                        "Yes. Cuba is under one of OFAC's most restrictive "
                        "programs — a comprehensive embargo since 1962 enforced "
                        "through the Cuban Assets Control Regulations (31 CFR "
                        "Part 515). Nearly all transactions between U.S. "
                        "persons and Cuba require authorization."
                    ),
                },
                {
                    "q": "What happens if you violate OFAC sanctions?",
                    "a": (
                        "Civil penalties up to ~$330,000 per violation (strict "
                        "liability — no intent required); criminal penalties "
                        "up to $20 million and 20 years imprisonment for "
                        "willful violations. OFAC publishes enforcement actions "
                        "and settlement agreements on treasury.gov."
                    ),
                },
                {
                    "q": "How do I check if someone is on the OFAC list?",
                    "a": (
                        "Use OFAC's official Sanctions List Search at "
                        "sanctionssearch.ofac.treas.gov, or use our Cuba-"
                        "specific SDN checker at cubaninsights.com which "
                        "includes fuzzy matching. Commercial tools like Dow "
                        "Jones, World-Check, and LexisNexis integrate "
                        "international sanctions databases."
                    ),
                },
            ],
        )

        from src.seo.cluster_topology import build_cluster_ctx, build_related_tools_ctx
        cluster_ctx = build_cluster_ctx("/tools/what-is-ofac")
        related_tools_ctx = build_related_tools_ctx("/tools/what-is-ofac")

        template = _env.get_template("tools/what_is_ofac.html.j2")
        html = template.render(
            seo=seo,
            jsonld=jsonld,
            cluster_ctx=cluster_ctx,
            related_tools_ctx=related_tools_ctx,
            current_year=_date.today().year,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("OFAC explainer render failed: %s", exc)
        abort(500)


@app.route("/tools/cuba-embargo-explained")
@app.route("/tools/cuba-embargo-explained/")
def tool_cuba_embargo_explainer():
    """Cuba Embargo explainer — history, laws, timeline, and current status."""
    try:
        from src.page_renderer import _env
        from datetime import date as _date

        seo, jsonld = _tool_seo_jsonld(
            slug="cuba-embargo-explained",
            title="Cuba Embargo Explained: History, Laws & Current Status (2026)",
            description=(
                "Complete guide to the U.S. embargo on Cuba — the longest "
                "trade embargo in modern history (since 1962). Covers what's "
                "prohibited, the 6 laws that enforce it (TWEA, CACR, "
                "Torricelli, Helms-Burton, TSRA), timeline across 12 "
                "presidents, economic impact, and current status. FAQ included."
            ),
            keywords=(
                "cuba embargo, cuban embargo, us embargo on cuba, "
                "cuba embargo explained, why is cuba embargoed, "
                "cuba trade embargo, cuba sanctions history, "
                "when did the cuba embargo start, is the cuba embargo "
                "still in effect, why can't we trade with cuba, embargo de "
                "Cuba, bloqueo a Cuba, bloqueo de Cuba, sanciones de Estados "
                "Unidos contra Cuba"
            ),
            faq=[
                {
                    "q": "What is the Cuba embargo?",
                    "a": (
                        "The Cuba embargo is a comprehensive U.S. commercial, "
                        "economic, and financial sanctions regime in continuous "
                        "effect since 1962. It prohibits nearly all trade, "
                        "investment, travel, and financial transactions between "
                        "U.S. persons and Cuba. Enforced by OFAC through the "
                        "Cuban Assets Control Regulations (31 CFR Part 515), it "
                        "is the longest-running embargo in modern history."
                    ),
                },
                {
                    "q": "Why is there an embargo on Cuba?",
                    "a": (
                        "The embargo was imposed in 1960-1962 after Cuba "
                        "nationalized U.S.-owned businesses without adequate "
                        "compensation, aligned with the Soviet Union, and "
                        "permitted Soviet nuclear missiles on its soil during "
                        "the Cuban Missile Crisis. It was reinforced by the "
                        "Helms-Burton Act in 1996 after Cuba shot down two "
                        "civilian Brothers to the Rescue aircraft."
                    ),
                },
                {
                    "q": "Is the Cuba embargo still in effect?",
                    "a": (
                        "Yes. As of 2026, the core embargo remains fully in "
                        "force. The Helms-Burton Act (1996) codified it into "
                        "statute, so it cannot be lifted by executive order "
                        "alone — it requires an act of Congress. Title III "
                        "lawsuits have been active since 2019. Cuba remains "
                        "on the State Sponsor of Terrorism list."
                    ),
                },
                {
                    "q": "Can a U.S. president lift the Cuba embargo?",
                    "a": (
                        "No — not unilaterally. The Helms-Burton Act (1996) "
                        "codified the embargo into federal law. Lifting it "
                        "requires Congress to certify that Cuba has held free "
                        "elections, released political prisoners, legalized "
                        "independent media, and made progress on property "
                        "restitution. Presidents can tighten or loosen "
                        "enforcement (as Obama and Trump demonstrated) but "
                        "cannot eliminate the statutory prohibitions."
                    ),
                },
                {
                    "q": "How does the UN vote on the Cuba embargo?",
                    "a": (
                        "Every year since 1992, the UN General Assembly has "
                        "voted overwhelmingly to condemn the embargo. The 2023 "
                        "vote was 187-2 (only the U.S. and Israel against). "
                        "The resolution is non-binding and has no effect on "
                        "U.S. domestic law."
                    ),
                },
            ],
        )

        from src.seo.cluster_topology import build_cluster_ctx, build_related_tools_ctx
        cluster_ctx = build_cluster_ctx("/tools/cuba-embargo-explained")
        related_tools_ctx = build_related_tools_ctx("/tools/cuba-embargo-explained")

        template = _env.get_template("tools/cuba_embargo_explainer.html.j2")
        html = template.render(
            seo=seo,
            jsonld=jsonld,
            cluster_ctx=cluster_ctx,
            related_tools_ctx=related_tools_ctx,
            current_year=_date.today().year,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Cuba embargo explainer render failed: %s", exc)
        abort(500)


@app.route("/tools/helms-burton-act-explained")
@app.route("/tools/helms-burton-act-explained/")
def tool_helms_burton_explainer():
    """Helms-Burton Act (LIBERTAD Act) explainer — Title III lawsuits,
    confiscated-property claims, and what it means for investors."""
    try:
        from src.page_renderer import _env
        from datetime import date as _date

        seo, jsonld = _tool_seo_jsonld(
            slug="helms-burton-act-explained",
            title="Helms-Burton Act Explained (2026): Title III Lawsuits & Confiscated Property",
            description=(
                "What is the Helms-Burton Act? Complete guide to the Cuban "
                "Liberty and Democratic Solidarity Act of 1996, Title III "
                "trafficking lawsuits (Carnival, Meliá, Booking.com), "
                "confiscated property claims, and what it means for "
                "investors and S&P 500 companies with Cuba exposure."
            ),
            keywords=(
                "helms burton act, helms burton, helms-burton title iii, "
                "helms burton act explained, cuba confiscated property, "
                "LIBERTAD act, cuban liberty and democratic solidarity act, "
                "helms burton lawsuits, carnival cuba lawsuit, melia cuba "
                "lawsuit, cuba property claims, trafficking confiscated property"
            ),
            faq=[
                {
                    "q": "What is the Helms-Burton Act?",
                    "a": (
                        "The Helms-Burton Act (formally the Cuban Liberty and "
                        "Democratic Solidarity Act of 1996, 22 U.S.C. "
                        "§§6021-6091) is a U.S. federal law that codifies the "
                        "Cuba trade embargo into statute and creates a private "
                        "right of action (Title III) allowing U.S. nationals to "
                        "sue anyone who 'traffics' in property confiscated by "
                        "the Cuban government after 1959. Title III was suspended "
                        "for 22 years and activated for the first time on "
                        "May 2, 2019."
                    ),
                },
                {
                    "q": "What does 'trafficking' mean under Helms-Burton Title III?",
                    "a": (
                        "'Trafficking' is broadly defined: knowingly and "
                        "intentionally selling, transferring, managing, using, "
                        "or otherwise acquiring or holding an interest in "
                        "confiscated property. Operating a hotel on confiscated "
                        "land, docking a cruise ship at a confiscated port, or "
                        "mining nickel at a confiscated facility all qualify. "
                        "The definition extends to foreign companies."
                    ),
                },
                {
                    "q": "Can European or Canadian companies be sued under Helms-Burton?",
                    "a": (
                        "Yes. Title III applies to any person or entity that "
                        "traffics in confiscated property, regardless of "
                        "nationality. Meliá Hotels (Spain), Sherritt "
                        "International (Canada), and others have faced exposure. "
                        "The EU passed a Blocking Statute (Regulation 2271/96) "
                        "prohibiting EU companies from complying with "
                        "Helms-Burton, creating a legal conflict."
                    ),
                },
                {
                    "q": "Has any company paid a Helms-Burton judgment?",
                    "a": (
                        "As of 2026, no Title III case has resulted in a final "
                        "collected judgment. Several cases remain in active "
                        "litigation — Carnival Corporation (Havana Docks), "
                        "Meliá Hotels, and online booking platforms. The "
                        "litigation risk itself drives SEC disclosure "
                        "requirements and investment decisions for Cuba-exposed "
                        "companies."
                    ),
                },
                {
                    "q": "How does Helms-Burton affect SEC filings?",
                    "a": (
                        "U.S.-listed companies with Cuba exposure must disclose "
                        "material litigation risks from Title III in 10-K, 20-F, "
                        "and 10-Q filings. Certified claims, contingent "
                        "liabilities, and pending lawsuits all trigger disclosure "
                        "obligations. Use our SEC EDGAR Cuba search tool to find "
                        "these disclosures."
                    ),
                },
            ],
        )

        from src.seo.cluster_topology import build_cluster_ctx, build_related_tools_ctx
        cluster_ctx = build_cluster_ctx("/tools/helms-burton-act-explained")
        related_tools_ctx = build_related_tools_ctx("/tools/helms-burton-act-explained")

        template = _env.get_template("tools/helms_burton_explainer.html.j2")
        html = template.render(
            seo=seo,
            jsonld=jsonld,
            cluster_ctx=cluster_ctx,
            related_tools_ctx=related_tools_ctx,
            current_year=_date.today().year,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Helms-Burton explainer render failed: %s", exc)
        abort(500)


@app.route("/tools/ofac-venezuela-general-licenses")
@app.route("/tools/ofac-venezuela-general-licenses/")
def _legacy_ofac_general_licenses_redirect():
    return _legacy_redirect_to("/tools/ofac-cuba-general-licenses")


@app.route("/tools/sec-edgar-cuba-impairment-search")
@app.route("/tools/sec-edgar-cuba-impairment-search/")
def tool_sec_edgar_cuba_search():
    """Pre-canned SEC EDGAR full-text search presets for Cuba /
    Helms-Burton / Cuba Restricted List / impairment / contingent-
    liability research, plus a curated quick-jump table of S&P 500
    companies known to disclose Cuba items in their filings.

    Two surfaces:
      - Preset deeplinks live entirely client-side: each card opens
        a pre-filled efts.sec.gov search in a new tab.
      - The curated table is sourced from
        src/data/curated_cuba_exposure.py (single source of truth
        for any "known disclosers" list across the site).
    """
    try:
        from src.data.edgar_search_presets import list_presets, list_curated_disclosers
        from src.page_renderer import _env
        from datetime import date as _date

        presets = list_presets()
        disclosers = list_curated_disclosers(max_n=30)
        today_human = _date.today().strftime("%B %Y")

        faq = [
            {
                "q": "Which S&P 500 companies disclose Cuba exposure to the SEC?",
                "a": (
                    "As of " + today_human + ", the most operationally Cuba-exposed "
                    "S&P 500 companies are the US carriers running scheduled service "
                    "under DOT route awards and OFAC §515.560–567 authorized travel "
                    "(American AAL, Delta DAL, JetBlue JBLU, United UAL); the major "
                    "cruise lines that ran 2016–2019 Havana itineraries and are now "
                    "Helms-Burton Title III defendants in Havana Docks Corp. "
                    "(Carnival CCL, Royal Caribbean RCL, Norwegian NCLH); the "
                    "telecoms with §515.542 ETECSA roaming agreements (AT&T T, "
                    "Verizon VZ, T-Mobile TMUS); the agricultural exporters under "
                    "TSRA selling to ALIMPORT (ADM, Bunge BG, Tyson TSN); and "
                    "Marriott MAR for its historical Four Points Habana operation "
                    "(license revoked 2020). Use the curated table on this page for "
                    "the full list."
                ),
            },
            {
                "q": "How do I search SEC EDGAR for Cuba-related disclosures?",
                "a": (
                    "Open https://efts.sec.gov/LATEST/search-index/ and enter a "
                    "query like '\"Cuba\" OR \"Helms-Burton\" OR \"CACR\"' "
                    "constrained to forms 10-K, 20-F, 10-Q, and 8-K over a 24-month "
                    "window. The preset cards on this page each open EDGAR with that "
                    "work already done — including Helms-Burton Title III "
                    "trafficking-claim queries, Cuba Restricted List exposure, OFAC "
                    "§515 compliance disclosures, and ALIMPORT / GAESA / ETECSA / "
                    "Mariel ZED counterparty mentions."
                ),
            },
            {
                "q": "Why combine Cuba, Helms-Burton, and contingent-liability search terms?",
                "a": (
                    "Cuba exposure rarely shows up as a standalone disclosure. Most "
                    "S&P 500 companies that touched Cuba during the 2016-2019 "
                    "Obama-era opening now reference it indirectly — via Helms-"
                    "Burton Title III contingent liabilities (Havana Docks-style "
                    "trafficking claims), impairment write-downs from license "
                    "revocations (the 2020 Marriott exit, the 2017–2019 cruise "
                    "wind-down), or Cuba Restricted List / CACR compliance program "
                    "footnotes. Searching for those terms alongside 'Cuba' or "
                    "'Havana' or 'CACR' is the most reliable way to find substantive "
                    "disclosure."
                ),
            },
        ]

        seo, jsonld = _tool_seo_jsonld(
            slug="sec-edgar-cuba-impairment-search",
            title=(
                "SEC EDGAR Cuba / Helms-Burton / Impairment Search — "
                f"S&P 500 Disclosures ({today_human})"
            ),
            description=(
                "Free, pre-canned SEC EDGAR full-text search for Cuba, "
                "Helms-Burton Title III, Cuba Restricted List, CACR §515, "
                "ALIMPORT / GAESA / ETECSA, and impairment / contingent-"
                "liability disclosures across S&P 500 10-K, 20-F, 10-Q, "
                "and 8-K filings. Includes a curated table of S&P 500 "
                f"companies known to disclose Cuba items, updated "
                f"{today_human}."
            ),
            keywords=(
                "sec edgar cuba, sec edgar helms-burton, cuba impairment "
                "search, cuba contingent liability, havana docks edgar "
                "search, sec filings cuba exposure, ofac cuba 10-K, "
                "sp500 cuba disclosures, CACR §515 disclosures, ETECSA "
                "telecom edgar"
            ),
            faq=faq,
        )

        from src.seo.cluster_topology import build_cluster_ctx, build_related_tools_ctx
        cluster_ctx = build_cluster_ctx("/tools/sec-edgar-cuba-impairment-search")
        related_tools_ctx = build_related_tools_ctx("/tools/sec-edgar-cuba-impairment-search")

        template = _env.get_template("tools/sec_edgar_cuba_search.html.j2")
        html = template.render(
            presets=presets,
            disclosers=disclosers,
            faq=faq,
            seo=seo,
            jsonld=jsonld,
            cluster_ctx=cluster_ctx,
            related_tools_ctx=related_tools_ctx,
            current_year=_date.today().year,
            today_human=today_human,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("tool render failed: %s", exc)
        abort(500)


@app.route("/tools/sec-edgar-venezuela-impairment-search")
@app.route("/tools/sec-edgar-venezuela-impairment-search/")
def _legacy_sec_edgar_redirect():
    return _legacy_redirect_to("/tools/sec-edgar-cuba-impairment-search")


@app.route("/tools")
@app.route("/tools/")
def tools_index():
    """Index of all free Cuba investor tools."""
    try:
        from src.page_renderer import _env, _base_url, _iso, settings as _s
        from datetime import date as _date, datetime as _dt
        import json as _json

        tools = [
            {
                "url": "/travel/emergency-card",
                "name": "Havana Emergency Card — Printable Pocket Sheet",
                "category": "Travel",
                "summary": "Print a single A4 sheet for your passport: bilingual hospital and embassy addresses a taxi driver can read, big phone numbers a stranger can dial, your blood type and home contact, and a throwaway pre-departure checklist. Pick your embassy and the card auto-personalizes.",
            },
            {
                "url": "/tools/ofac-cuba-sanctions-checker",
                "name": "OFAC Cuba Sanctions Exposure Checker",
                "category": "Compliance",
                "summary": "Search any name, company, vessel IMO, aircraft tail number, or Cuban identity document against every active CUBA-program OFAC SDN designation under the Cuban Assets Control Regulations (CACR, 31 CFR Part 515), with fuzzy matching and a clean compliance disclaimer.",
            },
            {
                "url": "/tools/cuba-restricted-list-checker",
                "name": "Cuba Restricted List (CRL) Entity Checker",
                "category": "Compliance",
                "summary": "Search any Cuban company, ministry, holding, hotel, marina, or store against the U.S. State Department's Cuba Restricted List under §515.209 — covers GAESA, CIMEX, Gaviota, Habaguanex, FINCIMEX, MINFAR, MININT and every named subentity. Cross-references the SDN list and the CPAL.",
            },
            {
                "url": "/tools/cuba-prohibited-hotels-checker",
                "name": "Cuba Prohibited Hotels (CPAL) Checker",
                "category": "Compliance",
                "summary": "Type any Cuban hotel, casa particular, or resort to instantly check whether it is on the State Department's Cuba Prohibited Accommodations List (§515.210) — properties U.S. travelers may not lodge at, even when booked via a third-country agent. Filter by province, see addresses, identify state-controlled \"casas\".",
            },
            {
                "url": "/tools/can-i-travel-to-cuba",
                "name": "Can I Legally Travel to Cuba? (OFAC Decision Tree)",
                "category": "Travel",
                "summary": "Free decision tree that walks you through the 12 OFAC authorized travel categories (CACR §515.560–.578) — identifies which general license your trip qualifies under, the records you must keep for 5 years, and the hotels and counterparties you must avoid. Non-U.S. travelers get the Cuban-side entry checklist.",
            },
            {
                "url": "/tools/public-company-cuba-exposure-check",
                "name": "Public Company Cuba Exposure Check",
                "category": "Compliance",
                "summary": "Type any S&P 500 company name or ticker — instantly see whether the company has Cuba exposure on the OFAC SDN list, on the State Department Cuba Restricted List or CPAL hotel blacklist, in its recent SEC filings, or in our news corpus. Backed by 500+ per-ticker landing pages.",
            },
            {
                "url": "/tools/sec-edgar-cuba-impairment-search",
                "name": "SEC EDGAR Cuba / Helms-Burton / Impairment Search",
                "category": "Compliance",
                "summary": "Pre-canned SEC EDGAR full-text searches for Cuba, Helms-Burton Title III, Cuba Restricted List, CACR §515, ALIMPORT / GAESA / ETECSA / Mariel ZED, and impairment / contingent-liability disclosures across 10-K, 20-F, 10-Q, and 8-K filings — plus a curated quick-jump table of S&P 500 companies known to disclose Cuba items.",
            },
            {
                "url": "/tools/ofac-cuba-general-licenses",
                "name": "OFAC Cuba General License Lookup (CACR §515)",
                "category": "Compliance",
                "summary": "Searchable directory of the active OFAC general licenses under the Cuban Assets Control Regulations: the 12 authorized travel categories (§515.560–.578), telecom (§515.542), agricultural / medical exports under TSRA (§515.533), remittances (§515.570), and support for the Cuban people (§515.574).",
            },
            {
                "url": "/tools/cuba-travel-advisory",
                "name": "Cuba Travel Advisory (State Dept Level 2)",
                "category": "Travel",
                "summary": "Current U.S. State Department travel advisory for Cuba explained: what Level 2 means, specific risks cited, how Cuba compares to Jamaica/DR/Mexico, and additional OFAC rules for American travelers.",
            },
            {
                "url": "/tools/what-is-ofac",
                "name": "What Is OFAC? U.S. Sanctions Agency Explained",
                "category": "Compliance",
                "summary": "Complete guide to OFAC (Office of Foreign Assets Control) — what the agency does, the SDN list, 30+ sanctions programs, compliance requirements, penalties up to $20M, and how OFAC applies to Cuba.",
            },
            {
                "url": "/tools/cuba-embargo-explained",
                "name": "Cuba Embargo Explained (History, Laws & Status)",
                "category": "Compliance",
                "summary": "Complete guide to the U.S. trade embargo on Cuba — the longest-running embargo in modern history. Covers the 6 laws that enforce it, timeline across 12 presidents, what's prohibited, economic impact, and current status.",
            },
            {
                "url": "/tools/helms-burton-act-explained",
                "name": "Helms-Burton Act Explained (Title III Lawsuits)",
                "category": "Compliance",
                "summary": "Complete guide to the Helms-Burton Act (LIBERTAD Act 1996): Title III confiscated-property lawsuits, notable cases (Carnival, Meliá, Booking.com), timeline of suspensions and activation, and what it means for S&P 500 investors with Cuba exposure.",
            },
            {
                "url": "/export-to-cuba",
                "name": "Export to Cuba — U.S. Company Hub",
                "category": "Exports",
                "summary": "Cuba export hub for U.S. companies: ITA / Trade.gov trade leads, market intelligence, contacts, trade events, HS-code opportunity triage, and a sanctions-aware OFAC + BIS + State CRL/CPAL process map.",
            },
            {
                "url": "/tools/cuba-trade-leads-for-us-companies",
                "name": "Cuba Trade Leads for U.S. Companies",
                "category": "Exports",
                "summary": "Find and evaluate Cuba trade leads with ITA opportunity signals, then screen product, buyer, parent company, payment route, and shipping path against OFAC, BIS, the Cuba Restricted List, and CPAL.",
            },
            {
                "url": "/tools/cuba-export-opportunity-finder",
                "name": "Cuba Export Opportunity Finder",
                "category": "Exports",
                "summary": "Map Cuba demand by sector — agriculture, medical goods, telecom, energy, logistics, and MIPYME equipment — to the authorization and counterparty checks a U.S. exporter needs before acting.",
            },
            {
                "url": "/tools/cuba-hs-code-opportunity-finder",
                "name": "Cuba HS Code Opportunity Finder",
                "category": "Exports",
                "summary": "Use HS-code thinking to triage product-level Cuba demand, likely licensing questions, end-use risk, BIS review, documentation, and sanctions-sensitive sectors.",
            },
            {
                "url": "/tools/cuba-export-controls-sanctions-process-map",
                "name": "Cuba Export Controls & Sanctions Process Map",
                "category": "Compliance",
                "summary": "Step-by-step route map for U.S. exporters: OFAC CACR authorization, BIS export controls, State CRL/CPAL screening, payment constraints, logistics, and records.",
            },
            {
                "url": "/tools/can-my-us-company-export-to-cuba",
                "name": "Can My U.S. Company Export to Cuba?",
                "category": "Exports",
                "summary": "Plain-English decision tree for U.S. companies: product, end user, OFAC authorization, BIS controls, SDN/CRL/CPAL screening, payment path, shipping, and recordkeeping.",
            },
            {
                "url": "/tools/cuba-country-contacts-directory",
                "name": "Cuba Country Contacts Directory",
                "category": "Exports",
                "summary": "Directory-style starting point for ITA Trade Americas, U.S. Commercial Service, sector specialists, and compliance-aware contact paths before approaching Cuba counterparties.",
            },
            {
                "url": "/tools/us-company-cuba-market-entry-checklist",
                "name": "U.S. Company Cuba Market-Entry Checklist",
                "category": "Exports",
                "summary": "Practical pre-entry checklist for U.S. companies: product fit, OFAC authorization, BIS controls, SDN/CRL/CPAL screening, payment feasibility, logistics, and recordkeeping.",
            },
            {
                "url": "/tools/cuba-export-compliance-checklist",
                "name": "Cuba Export Compliance Checklist",
                "category": "Compliance",
                "summary": "Combine ITA opportunity research with OFAC, BIS, State CRL/CPAL, payment, logistics, and recordkeeping checks in one Cuba export compliance workflow.",
            },
            {
                "url": "/tools/cuba-agricultural-medical-export-checker",
                "name": "Cuba Agricultural & Medical Export Checker",
                "category": "Exports",
                "summary": "Triage agriculture, food, medical devices, medicines, healthcare technology, and humanitarian exports against TSRA-style channels, OFAC authorization, BIS controls, and end-user risk.",
            },
            {
                "url": "/tools/cuba-telecom-internet-export-checker",
                "name": "Cuba Telecom & Internet Export Checker",
                "category": "Exports",
                "summary": "Evaluate telecom, internet, software, cloud, connectivity, and information-flow exports under CACR carve-outs, BIS controls, ETECSA exposure, and payment constraints.",
            },
            {
                "url": "/tools/cuba-mipyme-export-support-checklist",
                "name": "Cuba MIPYME Export Support Checklist",
                "category": "Exports",
                "summary": "Screen whether support for Cuban private businesses is genuinely private-sector-facing and can avoid prohibited state, military, importer, bank, and logistics counterparties.",
            },
            {
                "url": "/tools/cuba-trade-events-matchmaking-calendar",
                "name": "Cuba Trade Events & Matchmaking Calendar",
                "category": "Exports",
                "summary": "Track ITA, Trade Americas, Caribbean, virtual counseling, and sector events that can create Cuba-relevant leads, then run post-event screening before follow-up.",
            },
            {
                "url": "/tools/cuba-trade-barriers-tracker",
                "name": "Cuba Trade Barriers Tracker",
                "category": "Exports",
                "summary": "Monitor Cuba trade barriers across sanctions, export controls, Cuban import channels, hard-currency scarcity, payments, shipping, insurance, and state-sector concentration.",
            },
            {
                "url": "/tools/eltoque-trmi-rate",
                "name": "elTOQUE TRMI — CUP / USD / MLC Rate & Converter",
                "category": "Markets",
                "summary": "Live elTOQUE TRMI informal-market CUP / USD / MLC / USDT exchange rates plus a free converter, sourced from the authenticated tasas.eltoque.com API. Falls back to cached values when the upstream feed is unreachable. Cross-references the BCC tasaEspecial official rate.",
            },
            {
                "url": "/tools/cuba-investment-roi-calculator",
                "name": "Cuba Investment ROI Calculator",
                "category": "Modelling",
                "summary": "Estimate IRR, NPV, and multi-year cash flow across tourism & hospitality, MIPYMES, biotech (BioCubaFarma), agriculture, telecom (ETECSA), renewables, and Mariel ZED projects — with sector-specific Cuba risk premiums, CACR / Helms-Burton overlays, and the MLC / CUP / USD currency-stack friction baked in.",
            },
            {
                "url": "/tools/havana-safety-by-neighborhood",
                "name": "Havana Safety Score by Neighborhood",
                "category": "Travel",
                "summary": "Curated 1–5 safety rating for every major Havana neighborhood (Miramar, Vedado, La Habana Vieja, Centro Habana, the Mariel ZEDM corridor, and more), with embassies, hospitals, business-use guidance, and specific risks to avoid (jineteros, apagones, distraction theft).",
            },
            {
                "url": "/tools/cuba-visa-requirements",
                "name": "Cuba Visa & Tourist Card Requirements",
                "category": "Travel",
                "summary": "Pick your passport country to see whether you need a Tourist Card (Tarjeta del Turista) or a formal visa, the maximum stay, the live US/UK travel-advisory level, and what US travelers need to know about the OFAC 12 authorized-travel categories before flying to Havana.",
            },
        ]

        base = _base_url()
        canonical = f"{base}/tools"
        seo = {
            "title": "Free Cuba Investor Tools — Sanctions, elTOQUE TRMI, ROI Calculator",
            "description": (
                "Free toolkit for evaluating Cuba exposure: OFAC CUBA-"
                "program sanctions screening, CACR §515 general license "
                "lookup, live elTOQUE TRMI CUP/USD informal-market rate, "
                "sector ROI calculator with Helms-Burton overlay, Havana "
                "safety map, and Tourist Card requirements."
            ),
            "keywords": (
                "Cuba investor tools, OFAC checker Cuba, elTOQUE TRMI, "
                "Cuba ROI calculator, Havana safety, Cuba visa, CACR §515, "
                "Helms-Burton tools"
            ),
            "canonical": canonical,
            "site_name": _s.site_name,
            "site_url": base,
            "locale": _s.site_locale,
            "og_image": f"{base}/static/og-image.png?v=3",
            "og_type": "website",
            "published_iso": _iso(_dt.utcnow()),
            "modified_iso": _iso(_dt.utcnow()),
        }
        jsonld = _json.dumps({
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
                        {"@type": "ListItem", "position": 2, "name": "Tools", "item": canonical},
                    ],
                },
                {
                    "@type": "ItemList",
                    "@id": f"{canonical}#tools",
                    "name": "Free Cuba Investor Tools",
                    "itemListElement": [
                        {
                            "@type": "ListItem",
                            "position": i + 1,
                            "url": f"{base}{t['url']}",
                            "name": t["name"],
                        }
                        for i, t in enumerate(tools)
                    ],
                },
            ],
        }, ensure_ascii=False)

        from src.seo.cluster_topology import companion_links as _companion_links
        companion_ctx = {
            "eyebrow": "Other hubs across Cuban Insights",
            "title": "Where to go next from /tools",
            "links": _companion_links([
                "/sanctions-tracker",
                "/companies",
                "/invest-in-cuba",
                "/travel",
                "/explainers",
                "/sanctions/by-sector",
            ]),
        }

        template = _env.get_template("tools_index.html.j2")
        html = template.render(
            tools=tools,
            seo=seo,
            jsonld=jsonld,
            companion_ctx=companion_ctx,
            current_year=_date.today().year,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("tools index render failed: %s", exc)
        abort(500)


@app.route("/explainers")
@app.route("/explainers/")
def explainers_index():
    """Index of evergreen explainers."""
    try:
        from src.models import LandingPage, SessionLocal, init_db
        from src.page_renderer import _env, _base_url, _iso, settings as _s
        from datetime import date as _date, datetime as _dt
        import json as _json

        init_db()
        db = SessionLocal()
        try:
            explainers = (
                db.query(LandingPage)
                .filter(LandingPage.page_type == "explainer")
                .order_by(LandingPage.last_generated_at.desc())
                .all()
            )
        finally:
            db.close()

        base = _base_url()
        canonical = f"{base}/explainers"
        seo = {
            "title": "Cuba Investor Explainers — Plain-English Guides",
            "description": (
                "Evergreen plain-English explainers covering OFAC sanctions "
                "on Cuba (CACR §515), the State Department Cuba Restricted "
                "List, the Helms-Burton Act, the Banco Central de Cuba and "
                "the elTOQUE TRMI, the MLC virtual currency, the Mariel "
                "ZED foreign-investment regime, and how to do business in "
                "Havana under the post-2021 MIPYMES framework."
            ),
            "keywords": (
                "Cuba explainer, OFAC Cuba explained, CACR §515 explained, "
                "Helms-Burton Act, Cuba Restricted List, BCC explained, "
                "elTOQUE TRMI explained, MLC Cuba, MIPYMES Cuba, Mariel "
                "ZED, doing business in Havana"
            ),
            "canonical": canonical,
            "site_name": _s.site_name,
            "site_url": base,
            "locale": _s.site_locale,
            "og_image": f"{base}/static/og-image.png?v=3",
            "og_type": "website",
            "published_iso": _iso(_dt.utcnow()),
            "modified_iso": _iso(_dt.utcnow()),
        }
        jsonld = _json.dumps({
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
                        {"@type": "ListItem", "position": 2, "name": "Explainers", "item": canonical},
                    ],
                },
                {
                    "@type": "ItemList",
                    "@id": f"{canonical}#list",
                    "name": "Cuba Investor Explainers",
                    "itemListElement": [
                        {
                            "@type": "ListItem",
                            "position": i + 1,
                            "url": f"{base}{e.canonical_path}",
                            "name": e.title,
                        }
                        for i, e in enumerate(explainers)
                    ],
                },
            ],
        }, ensure_ascii=False)

        template = _env.get_template("explainers_index.html.j2")
        html = template.render(explainers=explainers, seo=seo, jsonld=jsonld, current_year=_date.today().year)
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("explainers index render failed: %s", exc)
        abort(500)


@app.route("/explainers/<slug>")
def explainer_page(slug: str):
    """Evergreen explainer landing page."""
    try:
        from src.models import BlogPost, LandingPage, SessionLocal, init_db
        from src.page_renderer import render_landing_page

        init_db()
        db = SessionLocal()
        try:
            page = (
                db.query(LandingPage)
                .filter(LandingPage.page_key == f"explainer:{slug}")
                .first()
            )
            if not page:
                abort(404)
            recent = (
                db.query(BlogPost)
                .order_by(BlogPost.published_date.desc())
                .limit(6)
                .all()
            )
            html = render_landing_page(page, recent_briefings=recent)
            return Response(html, mimetype="text/html")
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("explainer page render failed for slug=%s: %s", slug, exc)
        abort(500)


@app.route("/developers/success")
@app.route("/developers/success/")
def developers_success_page():
    """Post-checkout success page showing the API key."""
    try:
        from src.page_renderer import _env, _base_url, settings as _s

        tpl = _env.get_template("developers_success.html.j2")
        html = tpl.render(
            site_url=_s.site_url,
            seo={
                "title": "Payment Successful — Cuban Insights API",
                "description": "Your API key is ready.",
                "canonical": f"{_base_url()}/developers/success",
                "og_type": "website",
                "site_name": _s.site_name,
            },
        )
        return Response(html, content_type="text/html; charset=utf-8")
    except Exception as exc:
        logger.exception("developers success page render failed: %s", exc)
        abort(500)


@app.route("/developers")
@app.route("/developers/")
def developers_page():
    """API developer portal — pricing, docs, signup."""
    try:
        from src.page_renderer import _env, _base_url, settings as _s

        tpl = _env.get_template("developers.html.j2")
        html = tpl.render(
            site_url=_s.site_url,
            seo={
                "title": "API for Developers — Cuban Insights",
                "description": "Structured Cuba sanctions, investment, and FX data via a clean JSON API. Free tier available.",
                "canonical": f"{_base_url()}/developers",
                "og_type": "website",
                "site_name": _s.site_name,
            },
        )
        return Response(html, content_type="text/html; charset=utf-8")
    except Exception as exc:
        logger.exception("developers page render failed: %s", exc)
        abort(500)


@app.route("/sources")
@app.route("/sources/")
def sources_page():
    """Methodology + primary sources we monitor — authority signal page."""
    try:
        from src.models import (
            AssemblyNewsEntry,
            ExternalArticleEntry,
            GazetteEntry,
            SessionLocal,
            SourceType,
            init_db,
        )
        from src.page_renderer import _env, _base_url, _iso, settings as _s
        from datetime import date as _date, datetime as _dt
        import json as _json

        init_db()
        db = SessionLocal()
        try:
            def _count_ext(src: SourceType) -> int:
                try:
                    return db.query(ExternalArticleEntry).filter(ExternalArticleEntry.source == src).count()
                except Exception:
                    return 0

            def _count_gazette(src: SourceType) -> int:
                try:
                    return db.query(GazetteEntry).filter(GazetteEntry.source == src).count()
                except Exception:
                    return 0

            def _count_assembly(src: SourceType) -> int:
                try:
                    return db.query(AssemblyNewsEntry).filter(AssemblyNewsEntry.source == src).count()
                except Exception:
                    # Fall back to the raw count if the source filter
                    # isn't a column on this table.
                    try:
                        return db.query(AssemblyNewsEntry).count()
                    except Exception:
                        return 0

            sources = [
                {
                    "name": "OFAC Specially Designated Nationals (SDN) list — CUBA program",
                    "kind": "US Treasury", "tier": "Primary",
                    "url": "https://www.treasury.gov/ofac/downloads/sdn.csv",
                    "description": "The complete US Treasury OFAC consolidated SDN list, filtered for the CUBA program (administered under the Cuban Assets Control Regulations, 31 CFR Part 515). Tracks every individual, entity, vessel, and aircraft sanctioned in connection with Cuba.",
                    "cadence": "Twice daily (10am, 5pm)",
                    "entries_count": _count_ext(SourceType.OFAC_SDN),
                },
                {
                    "name": "US State Department — Cuba Restricted List (CRL)",
                    "kind": "US State Department", "tier": "Primary",
                    "url": "https://www.state.gov/cuba-sanctions/list-of-restricted-entities-and-subentities-associated-with-cuba/",
                    "description": "Entities and subentities the executive branch has prohibited direct financial transactions with under §515.209. Distinct from the OFAC SDN — most CRL entries (GAESA holdings, Gaviota, Cubanacán, Habaguanex hotels, etc.) are NOT on the SDN.",
                    "cadence": "Live polling on State Dept publication",
                    "entries_count": _count_ext(SourceType.STATE_DEPT_CRL),
                },
                {
                    "name": "US State Department — Cuba Prohibited Accommodations List (CPAL)",
                    "kind": "US State Department", "tier": "Primary",
                    "url": "https://www.state.gov/cuba-prohibited-accommodations-list/",
                    "description": "Specific hotels and casas particulares that fail the §515.210 'no commerce with the Cuban government' test. Used by the company-exposure tooling to flag MAR / HLT / IHG / CHH branded properties that touch Gaviota or Cubanacán.",
                    "cadence": "Live polling on State Dept publication",
                    "entries_count": _count_ext(SourceType.STATE_DEPT_CPAL),
                },
                {
                    "name": "US Federal Register — Cuba",
                    "kind": "US Government", "tier": "Primary",
                    "url": "https://www.federalregister.gov/documents/search?conditions[term]=cuba",
                    "description": "Final rules, proposed rules, executive orders, and notices published by federal agencies. Source of truth for OFAC CACR amendments, BIS export-control updates, and State Department Cuba Restricted List actions.",
                    "cadence": "Twice daily",
                    "entries_count": _count_ext(SourceType.FEDERAL_REGISTER),
                },
                {
                    "name": "Asamblea Nacional del Poder Popular",
                    "kind": "Cuban Government", "tier": "Primary",
                    "url": "https://www.parlamentocubano.gob.cu",
                    "description": "Official news feed of the Cuban National Assembly: bills introduced, laws passed (Ley 118 foreign investment, the MIPYMES framework), committee work, and parliamentary diplomacy. Translated into English by our analyzer.",
                    "cadence": "Twice daily",
                    "entries_count": _count_assembly(SourceType.ASAMBLEA_NACIONAL_CU),
                },
                {
                    "name": "Gaceta Oficial de la República de Cuba",
                    "kind": "Cuban Government", "tier": "Primary",
                    "url": "https://www.gacetaoficial.gob.cu",
                    "description": "The official gazette publishing every Cuban law, decree, and government resolution. We OCR scanned PDFs and persist the underlying text so each item is searchable and analyzable.",
                    "cadence": "Twice daily",
                    "entries_count": _count_gazette(SourceType.GACETA_OFICIAL_CU),
                },
                {
                    "name": "Banco Central de Cuba (BCC)",
                    "kind": "Cuban Government", "tier": "Primary",
                    "url": "https://www.bc.gob.cu",
                    "description": "Official daily reference rates of the Cuban peso (CUP) against the US dollar and other currencies — tasaOficial, tasaPublica (CADECA), and tasaEspecial (the 2022 institutional rate used for state and joint-venture transactions). Pulled from the public api.bc.gob.cu REST API.",
                    "cadence": "Daily",
                    "entries_count": _count_ext(SourceType.BCC_RATES),
                },
                {
                    "name": "elTOQUE — Tasa Representativa del Mercado Informal (TRMI)",
                    "kind": "Independent media", "tier": "Primary",
                    "url": "https://eltoque.com/tasas-de-cambio-de-moneda-en-cuba-hoy",
                    "description": "elTOQUE's daily index of the informal CUP/USD, CUP/MLC, and CUP/USDT exchange rates — the de-facto market reference for ordinary Cubans, remittance senders, and MIPYMES. Pulled from the authenticated tasas.eltoque.com API. Attribution required by elTOQUE ToS is preserved on every surface.",
                    "cadence": "Twice daily",
                    "entries_count": _count_ext(SourceType.ELTOQUE_RATE),
                },
                {
                    "name": "Ministerio de Relaciones Exteriores (MINREX)",
                    "kind": "Cuban Government", "tier": "Primary",
                    "url": "https://www.cubaminrex.cu",
                    "description": "Press releases and diplomatic statements from Cuba's foreign ministry. Used to surface bilateral and multilateral developments relevant to investors (US-Cuba dialogue, EU PDCA progress, Mexico / Brazil / China engagement).",
                    "cadence": "Twice daily",
                    "entries_count": _count_ext(SourceType.MINREX),
                },
                {
                    "name": "Oficina Nacional de Estadística e Información (ONEI)",
                    "kind": "Cuban Government", "tier": "Primary",
                    "url": "https://www.onei.gob.cu",
                    "description": "Cuba's national statistics office — GDP, trade, demographics, sectoral output. The macro baseline for any sector model.",
                    "cadence": "On publication",
                    "entries_count": _count_ext(SourceType.ONEI),
                },
                {
                    "name": "International Trade Administration / Trade.gov",
                    "kind": "US Department of Commerce", "tier": "Primary",
                    "url": "https://developer.trade.gov/",
                    "description": "U.S. export-facing market intelligence, trade leads, events, contacts, and export guidance. We use ITA / Trade.gov as the commercial-opportunity layer and then cross-check Cuba items against OFAC, BIS, State CRL/CPAL, payment, and counterparty constraints.",
                    "cadence": "Twice daily",
                    "entries_count": _count_ext(SourceType.ITA_TRADE),
                },
                {
                    "name": "US State Department — Cuba travel advisory",
                    "kind": "US Government", "tier": "Primary",
                    "url": "https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories/cuba-travel-advisory.html",
                    "description": "Official US State Department travel advisory level for Cuba. Used in the security and operating-environment sections of the pillar guide and travel-related tools.",
                    "cadence": "Daily check, alerts on level change",
                    "entries_count": None,
                },
                {
                    "name": "Cuban press (RSS aggregator)",
                    "kind": "Independent and state media", "tier": "Secondary",
                    "url": "https://www.granma.cu",
                    "description": "Aggregated RSS feeds from Granma (state), Cubadebate (state), 14ymedio (independent), OnCuba (diaspora), Diario de Cuba (opposition), and Havana Times. Per-outlet attribution preserved on every entry.",
                    "cadence": "Twice daily",
                    "entries_count": _count_ext(SourceType.PRESS_RSS),
                },
                {
                    "name": "GDELT Project (global event database)",
                    "kind": "Open data", "tier": "Secondary",
                    "url": "https://www.gdeltproject.org",
                    "description": "Global news event database used as a tone signal — we use the GDELT V2 GKG tone score as one of the inputs that decides which items get the more expensive LLM analysis treatment.",
                    "cadence": "Twice daily",
                    "entries_count": _count_ext(SourceType.GDELT),
                },
            ]

            base = _base_url()
            canonical = f"{base}/sources"
            seo = {
                "title": "Sources & Methodology — Cuban Insights",
                "description": (
                    "How Cuban Insights produces its investor briefings: "
                    "primary Cuban and US government sources we monitor, "
                    "refresh cadence, LLM filtering pipeline, and editorial "
                    "standards."
                ),
                "keywords": (
                    "Cuba investment sources, OFAC monitoring Cuba, Cuba "
                    "Restricted List, CPAL, Asamblea Nacional Cuba, Gaceta "
                    "Oficial Cuba, BCC, elTOQUE TRMI, methodology"
                ),
                "canonical": canonical,
                "site_name": _s.site_name,
                "site_url": base,
                "locale": _s.site_locale,
                "og_image": f"{base}/static/og-image.png?v=3",
                "og_type": "website",
                "published_iso": _iso(_dt.utcnow()),
                "modified_iso": _iso(_dt.utcnow()),
            }
            jsonld = _json.dumps({
                "@context": "https://schema.org",
                "@graph": [
                    {
                        "@type": "BreadcrumbList",
                        "itemListElement": [
                            {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
                            {"@type": "ListItem", "position": 2, "name": "Sources & Methodology", "item": canonical},
                        ],
                    },
                    {
                        "@type": "AboutPage",
                        "@id": f"{canonical}#about",
                        "url": canonical,
                        "name": seo["title"],
                        "description": seo["description"],
                        "publisher": {"@type": "Organization", "name": _s.site_name, "url": f"{base}/"},
                    },
                ],
            }, ensure_ascii=False)

            template = _env.get_template("sources.html.j2")
            html = template.render(
                sources=sources,
                seo=seo,
                jsonld=jsonld,
                current_year=_date.today().year,
            )
            return Response(html, mimetype="text/html")
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("sources page render failed: %s", exc)
        abort(500)


_US_CUBA_DIPLOMACY_TERMS = (
    "us-cuba", "u.s.-cuba", "u.s. cuba", "united states and cuba",
    "cuba and the united states", "eeuu-cuba", "ee.uu.-cuba",
)
_US_CUBA_SIGNAL_TERMS = (
    "united states", "u.s.", "us-", "u.s.-", "eeuu", "ee.uu",
    "washington", "state department", "embassy", "embajada",
    "senate", "senado", "trump", "biden", "rubio", "marco rubio",
    "bloqueo",
)
_CUBA_SIGNAL_TERMS = (
    "cuba", "cuban", "cubano", "cubana", "cubanos", "cubanas",
    "havana", "habana",
)
_DIPLOMACY_POLICY_TERMS = (
    "bilateral", "diplomatic", "diplomacy", "diplomacia", "talks",
    "meeting", "reunion", "reunión", "dialogue", "dialogo", "diálogo",
    "negotiation", "negociacion", "negociación", "normalization",
    "normalisation", "embassy", "embajada", "consular", "migration",
    "migracion", "migración", "visa", "travel advisory", "policy",
    "sanctions", "sanciones", "embargo", "permit", "licence", "license",
)
_US_CUBA_EXCLUDE_TERMS = (
    "cuba restricted list baseline",
    "cuba prohibited accommodations list baseline",
    "cuba prohibited accommodations list",
    "cuba restricted list",
    "cpal",
    "§515.209",
    "§515.210",
)


def _is_us_cuba_diplomacy_row(*parts: str, sectors: list | None = None, source=None) -> bool:
    haystack = " ".join(p or "" for p in parts).lower()
    sector_set = {str(s).lower().replace("_", "-") for s in (sectors or [])}
    if any(term in haystack for term in _US_CUBA_EXCLUDE_TERMS):
        return False
    if any(term in haystack for term in _US_CUBA_DIPLOMACY_TERMS):
        return True
    source_value = getattr(source, "value", source)
    if source_value == "minrex" and any(t in haystack for t in ("united states", "u.s.", "us-", "washington", "bilateral", "migration")):
        return True
    has_cuba = any(term in haystack for term in _CUBA_SIGNAL_TERMS)
    has_us = any(term in haystack for term in _US_CUBA_SIGNAL_TERMS)
    has_policy = any(term in haystack for term in _DIPLOMACY_POLICY_TERMS)
    if has_cuba and has_us and has_policy:
        return True
    return "diplomatic" in sector_set and has_cuba and has_us


@app.route("/us-cuba-relations-recent-developments-2026")
@app.route("/us-cuba-relations-recent-developments-2026/")
def us_cuba_relations_redirect():
    return redirect("/us-cuba-diplomatic-meeting-recent-developments-2026", code=301)


@app.route("/us-cuba-diplomatic-meeting-recent-developments-2026")
@app.route("/us-cuba-diplomatic-meeting-recent-developments-2026/")
def us_cuba_diplomatic_developments_tracker():
    """Live tracker for the exact GSC query:
    "us cuba diplomatic meeting recent developments 2026".
    """
    try:
        from src.models import BlogPost, ExternalArticleEntry, AssemblyNewsEntry, SessionLocal, SourceType, init_db
        from src.page_renderer import _env, _base_url, _iso, settings as _s
        from datetime import date as _date, datetime as _dt, timedelta as _td
        import json as _json

        init_db()
        db = SessionLocal()
        try:
            cutoff = _date.today() - _td(days=365)
            external_rows = (
                db.query(ExternalArticleEntry)
                .filter(ExternalArticleEntry.published_date >= cutoff)
                .order_by(ExternalArticleEntry.published_date.desc())
                .limit(500)
                .all()
            )
            assembly_rows = (
                db.query(AssemblyNewsEntry)
                .filter(AssemblyNewsEntry.published_date >= cutoff)
                .order_by(AssemblyNewsEntry.published_date.desc())
                .limit(150)
                .all()
            )
            blog_lookup = {
                (row.source_table, row.source_id): row.slug
                for row in db.query(BlogPost.source_table, BlogPost.source_id, BlogPost.slug).all()
            }

            events: list[dict] = []
            seen_event_keys: set[str] = set()
            for row in external_rows:
                analysis = row.analysis_json or {}
                sectors = analysis.get("sectors") or []
                relevance = int(analysis.get("relevance_score") or 0)
                official_source = row.source in (SourceType.MINREX, SourceType.FEDERAL_REGISTER, SourceType.TRAVEL_ADVISORY)
                if not official_source and relevance < 4:
                    continue
                body = row.body_text or ""
                filter_body = body[:1200] if official_source else ""
                filter_takeaway = analysis.get("takeaway", "") if official_source else ""
                if not _is_us_cuba_diplomacy_row(
                    row.headline,
                    row.source_name or "",
                    filter_body,
                    filter_takeaway,
                    sectors=sectors,
                    source=row.source,
                ):
                    continue
                dedupe_key = " ".join((row.headline or "").lower().split())[:180]
                if dedupe_key in seen_event_keys:
                    continue
                seen_event_keys.add(dedupe_key)
                source_label = (
                    "MINREX" if row.source == SourceType.MINREX
                    else "U.S. State Department" if row.source == SourceType.TRAVEL_ADVISORY
                    else "Federal Register" if row.source == SourceType.FEDERAL_REGISTER
                    else row.source_name or row.source.value.replace("_", " ").title()
                )
                events.append({
                    "date": row.published_date,
                    "date_iso": row.published_date.isoformat(),
                    "date_display": row.published_date.strftime("%b %d, %Y"),
                    "headline": row.headline,
                    "summary": analysis.get("takeaway") or (body[:260] + ("..." if len(body) > 260 else "")),
                    "source_label": source_label,
                    "source_url": row.source_url,
                    "blog_slug": blog_lookup.get(("external_articles", row.id)),
                    "relevance": relevance,
                    "kind": "Official" if row.source in (SourceType.MINREX, SourceType.FEDERAL_REGISTER, SourceType.TRAVEL_ADVISORY) else "Press",
                })

            for row in assembly_rows:
                analysis = row.analysis_json or {}
                sectors = analysis.get("sectors") or []
                relevance = int(analysis.get("relevance_score") or 0)
                if relevance < 4:
                    continue
                body = row.body_text or ""
                if not _is_us_cuba_diplomacy_row(
                    row.headline,
                    row.commission or "",
                    "",
                    "",
                    sectors=sectors,
                ):
                    continue
                dedupe_key = " ".join((row.headline or "").lower().split())[:180]
                if dedupe_key in seen_event_keys:
                    continue
                seen_event_keys.add(dedupe_key)
                events.append({
                    "date": row.published_date,
                    "date_iso": row.published_date.isoformat(),
                    "date_display": row.published_date.strftime("%b %d, %Y"),
                    "headline": row.headline,
                    "summary": analysis.get("takeaway") or (body[:260] + ("..." if len(body) > 260 else "")),
                    "source_label": "Asamblea Nacional / Granma",
                    "source_url": row.source_url,
                    "blog_slug": blog_lookup.get(("assembly_news", row.id)),
                    "relevance": relevance,
                    "kind": "Official",
                })

            events.sort(key=lambda e: (e["date"], e["relevance"]), reverse=True)
            events = events[:40]

            base = _base_url()
            canonical = f"{base}/us-cuba-diplomatic-meeting-recent-developments-2026"
            generated_at = _dt.utcnow()
            latest_date = events[0]["date_display"] if events else "awaiting first matching scrape"
            seo = {
                "title": "US-Cuba Relations & Diplomatic Developments 2026 — Live Tracker",
                "description": (
                    "Live tracker of recent U.S.-Cuba relations and diplomatic "
                    "developments in 2026: meetings, migration talks, embassy "
                    "updates, MINREX statements, State Department actions, "
                    "sanctions changes, and investor implications."
                ),
                "keywords": (
                    "us cuba diplomatic meeting recent developments 2026, "
                    "us cuba relations recent developments 2026, "
                    "US Cuba diplomatic talks 2026, US Cuba relations tracker, "
                    "Cuba diplomacy 2026, Cuba diplomatic engagement 2026, "
                    "MINREX United States, Havana Washington talks"
                ),
                "canonical": canonical,
                "site_name": _s.site_name,
                "site_url": base,
                "locale": _s.site_locale,
                "og_image": f"{base}/static/og-image.png?v=3",
                "og_type": "website",
                "published_iso": _iso(generated_at),
                "modified_iso": _iso(generated_at),
            }

            item_list = {
                "@type": "ItemList",
                "name": "Latest US-Cuba diplomatic developments",
                "itemListOrder": "https://schema.org/ItemListOrderDescending",
                "numberOfItems": len(events),
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": idx,
                        "url": ev.get("source_url") or canonical,
                        "name": ev.get("headline") or "",
                    }
                    for idx, ev in enumerate(events[:20], start=1)
                ],
            }
            jsonld = _json.dumps({
                "@context": "https://schema.org",
                "@graph": [
                    {
                        "@type": "BreadcrumbList",
                        "itemListElement": [
                            {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
                            {"@type": "ListItem", "position": 2, "name": "US-Cuba Diplomatic Developments", "item": canonical},
                        ],
                    },
                    {
                        "@type": "WebPage",
                        "@id": f"{canonical}#webpage",
                        "url": canonical,
                        "name": seo["title"],
                        "description": seo["description"],
                        "isAccessibleForFree": True,
                        "dateModified": seo["modified_iso"],
                    },
                    item_list,
                ],
            }, ensure_ascii=False)

            template = _env.get_template("us_cuba_diplomatic_developments.html.j2")
            html = template.render(
                seo=seo,
                jsonld=jsonld,
                events=events,
                latest_date=latest_date,
                generated_at=generated_at.strftime("%b %d, %Y %-I:%M %p UTC"),
                current_year=_date.today().year,
            )
            return Response(html, mimetype="text/html")
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("US-Cuba diplomatic developments tracker failed: %s", exc)
        abort(500)


@app.route("/sanctions-tracker")
@app.route("/sanctions-tracker/")
def sanctions_tracker():
    """OFAC SDN tracker — searchable / filterable table of all CUBA-program designations."""
    try:
        from src.models import ExternalArticleEntry, ScrapeLog, SessionLocal, SourceType, init_db
        from src.page_renderer import _env, _base_url, _iso, settings as _s
        from datetime import date as _date, datetime as _dt, timedelta as _td, timezone as _tz
        import json as _json

        init_db()
        db = SessionLocal()
        try:
            rows = (
                db.query(ExternalArticleEntry)
                .filter(ExternalArticleEntry.source == SourceType.OFAC_SDN)
                .order_by(ExternalArticleEntry.published_date.desc())
                .all()
            )

            last_scrape_row = (
                db.query(ScrapeLog)
                .filter(
                    ScrapeLog.source == SourceType.OFAC_SDN,
                    ScrapeLog.success.is_(True),
                    ScrapeLog.entries_found > 0,
                )
                .order_by(ScrapeLog.created_at.desc())
                .first()
            )

            now_utc = _dt.now(_tz.utc)
            cron_hours_utc = (15, 22)
            next_run_utc = None
            for hh in cron_hours_utc:
                candidate = now_utc.replace(hour=hh, minute=0, second=0, microsecond=0)
                if candidate > now_utc:
                    next_run_utc = candidate
                    break
            if next_run_utc is None:
                next_run_utc = (now_utc + _td(days=1)).replace(
                    hour=cron_hours_utc[0], minute=0, second=0, microsecond=0
                )

            havana_tz = _tz(_td(hours=-4))  # America/Havana, no DST tracking here
            last_refreshed_local = None
            last_refreshed_relative = None
            if last_scrape_row and last_scrape_row.created_at is not None:
                last_utc = last_scrape_row.created_at.replace(tzinfo=_tz.utc)
                last_local = last_utc.astimezone(havana_tz)
                last_refreshed_local = last_local.strftime("%b %d, %Y · %-I:%M %p") + " (Havana)"
                delta = now_utc - last_utc
                hours = int(delta.total_seconds() // 3600)
                minutes = int((delta.total_seconds() % 3600) // 60)
                if hours >= 24:
                    last_refreshed_relative = f"{hours // 24}d ago"
                elif hours >= 1:
                    last_refreshed_relative = f"{hours}h ago"
                else:
                    last_refreshed_relative = f"{max(minutes, 1)}m ago"

            next_refresh_local = next_run_utc.astimezone(havana_tz).strftime(
                "%b %d · %-I:%M %p"
            ) + " (Havana)"

            from src.data.sdn_profiles import list_all_profiles as _list_all_sdn_profiles
            try:
                _profile_url_by_db_id = {
                    p.db_id: p.url_path for p in _list_all_sdn_profiles()
                }
            except Exception:
                logger.exception("sanctions_tracker: failed to build SDN profile url map")
                _profile_url_by_db_id = {}

            sdn_entries = []
            stats = {
                "total": 0, "individuals": 0, "entities": 0,
                "vessels": 0, "aircraft": 0,
            }
            for r in rows:
                meta = r.extra_metadata or {}
                ent_type = (meta.get("type") or "").lower()
                if ent_type not in ("individual", "vessel", "aircraft", "entity"):
                    ent_type = "entity"
                sdn_entries.append({
                    "name": meta.get("name") or r.headline,
                    "type": ent_type,
                    "program": meta.get("program") or "",
                    "remarks": meta.get("remarks") or "",
                    "url_path": _profile_url_by_db_id.get(r.id),
                })
                stats["total"] += 1
                stats[
                    "individuals" if ent_type == "individual"
                    else "vessels" if ent_type == "vessel"
                    else "aircraft" if ent_type == "aircraft"
                    else "entities"
                ] += 1

            base = _base_url()
            canonical = f"{base}/sanctions-tracker"
            seo = {
                "title": f"Cuba Sanctions List ({stats['total']} OFAC Entries, 2026) — Live SDN Tracker",
                "description": (
                    f"Complete Cuba sanctions tracker: all {stats['total']} OFAC SDN "
                    "designations under the CUBA program, searchable by name, "
                    "vessel, aircraft, or type. Refreshed 2× daily from "
                    "treasury.gov. Includes entities, individuals, vessels, "
                    "and aircraft sanctioned under the Cuban Assets Control "
                    "Regulations (31 CFR Part 515)."
                ),
                "keywords": (
                    "cuba sanctions, ofac cuba, cuba sanctions list, "
                    "cuba ofac sanctions, OFAC SDN Cuba, us sanctions on cuba, "
                    "cuba embargo sanctions, CACR §515, GAESA sanctions, "
                    "cuba sanctions 2026, is cuba sanctioned"
                ),
                "canonical": canonical,
                "site_name": _s.site_name,
                "site_url": base,
                "locale": _s.site_locale,
                "og_image": f"{base}/static/og-image.png?v=3",
                "og_type": "website",
                "published_iso": _iso(_dt.utcnow()),
                "modified_iso": _iso(_dt.utcnow()),
            }

            jsonld = _json.dumps({
                "@context": "https://schema.org",
                "@graph": [
                    {
                        "@type": "BreadcrumbList",
                        "itemListElement": [
                            {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
                            {"@type": "ListItem", "position": 2, "name": "Invest in Cuba", "item": f"{base}/invest-in-cuba"},
                            {"@type": "ListItem", "position": 3, "name": "OFAC Sanctions Tracker", "item": canonical},
                        ],
                    },
                    {
                        "@type": "Dataset",
                        "@id": f"{canonical}#dataset",
                        "name": "OFAC Cuba SDN Tracker",
                        "description": seo["description"],
                        "url": canonical,
                        "creator": {"@type": "Organization", "name": _s.site_name, "url": f"{base}/"},
                        "license": "https://www.usa.gov/government-works",
                        "isAccessibleForFree": True,
                        "variableMeasured": ["name", "type", "program", "remarks"],
                        "distribution": [{
                            "@type": "DataDownload",
                            "encodingFormat": "text/csv",
                            "contentUrl": "https://www.treasury.gov/ofac/downloads/sdn.csv",
                        }],
                    },
                ],
            }, ensure_ascii=False)

            from src.seo.cluster_topology import build_cluster_ctx, ClusterLink
            cluster_ctx = build_cluster_ctx("/sanctions-tracker")
            companion_ctx = {
                "eyebrow": "Related tools",
                "title": "Cross-check any name against Cuba sanctions lists",
                "links": [
                    ClusterLink("/tools/ofac-cuba-sanctions-checker",
                                "OFAC sanctions checker",
                                "Search any person or entity against the live SDN list"),
                    ClusterLink("/tools/cuba-restricted-list-checker",
                                "Cuba Restricted List checker",
                                "Screen names against the State Department CRL"),
                    ClusterLink("/tools/cuba-prohibited-hotels-checker",
                                "Prohibited hotels checker",
                                "Check if a Cuban hotel is on the CPAL list"),
                    ClusterLink("/tools/public-company-cuba-exposure-check",
                                "Public company exposure check",
                                "Look up Cuba exposure for any S&P 500 company"),
                    ClusterLink("/tools/sec-edgar-cuba-impairment-search",
                                "SEC EDGAR search",
                                "Find Cuba-related disclosures in SEC filings"),
                    ClusterLink("/tools/ofac-cuba-general-licenses",
                                "General licenses",
                                "Browse all active OFAC general licenses for Cuba"),
                    ClusterLink("/companies",
                                "S&P 500 Cuba exposure register",
                                "A-Z directory of companies with Cuba-linked activity"),
                    ClusterLink("/explainers/helms-burton-title-iii",
                                "Helms-Burton Title III",
                                "Confiscated-property lawsuits against US-listed companies"),
                ],
            }

            try:
                from src.data.sdn_profiles import sector_stats as _sector_stats
                sector_stats_payload = _sector_stats()
            except Exception as exc:
                logger.warning("sanctions tracker: sector_stats lookup failed: %s", exc)
                sector_stats_payload = None

            template = _env.get_template("sanctions_tracker.html.j2")
            html = template.render(
                sdn_entries=sdn_entries,
                stats=stats,
                sector_stats=sector_stats_payload,
                seo=seo,
                jsonld=jsonld,
                cluster_ctx=cluster_ctx,
                companion_ctx=companion_ctx,
                current_year=_date.today().year,
                last_refreshed_local=last_refreshed_local,
                last_refreshed_relative=last_refreshed_relative,
                next_refresh_local=next_refresh_local,
            )
            return Response(html, mimetype="text/html")
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("sanctions tracker render failed: %s", exc)
        abort(500)


@app.route("/sanctions/by-sector")
@app.route("/sanctions/by-sector/")
def sanctions_by_sector_index():
    """Pillar landing page that pivots the SDN list by sector."""
    from src.data.sdn_profiles import (
        SECTOR_KEYS, SECTOR_LABELS, SECTOR_DESCRIPTIONS, SECTOR_SLUGS,
        list_by_sector, sector_stats, stats as sdn_stats,
    )
    from src.page_renderer import _env, _base_url, _iso, settings as _s
    from datetime import date as _date, datetime as _dt
    import json as _json

    try:
        s_counts = sector_stats()
        bucket_stats = sdn_stats()

        sectors_payload: list[dict] = []
        for key in SECTOR_KEYS:
            profs = list_by_sector(key)
            sectors_payload.append({
                "key": key,
                "label": SECTOR_LABELS.get(key, key.title()),
                "description": SECTOR_DESCRIPTIONS.get(key, ""),
                "url_path": f"/sanctions/sector/{SECTOR_SLUGS.get(key, key)}",
                "count": len(profs),
                "top_names": profs[:6],
            })

        base = _base_url()
        canonical = f"{base}/sanctions/by-sector"
        today_human = _date.today().strftime("%B %-d, %Y")

        title = (
            "OFAC Cuba SDN List by Sector — Currently Sanctioned "
            "Military, Economic, Diplomatic & Governance Officials"
        )[:120]
        description = (
            f"All {bucket_stats['total']} active OFAC CUBA-program SDN "
            f"designations grouped by sector: {s_counts.get('military', 0)} military "
            f"officials, {s_counts.get('economic', 0)} economic & financial actors, "
            f"{s_counts.get('diplomatic', 0)} diplomatic officials, and "
            f"{s_counts.get('governance', 0)} government & political figures. Updated {today_human}."
        )[:300]

        seo = {
            "title": title,
            "description": description,
            "keywords": (
                "OFAC Cuba SDN list, OFAC sanctions by sector, "
                "Cuba military sanctions, Cuba economic sanctions, "
                "Cuba diplomatic sanctions, OFAC governance sanctions, "
                "current OFAC Cuba list, GAESA sanctions, MININT sanctions"
            ),
            "canonical": canonical,
            "site_name": _s.site_name,
            "site_url": base,
            "locale": _s.site_locale,
            "og_image": f"{base}/static/og-image.png?v=3",
            "og_type": "website",
            "published_iso": _iso(_dt.utcnow()),
            "modified_iso": _iso(_dt.utcnow()),
        }

        jsonld = _json.dumps({
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
                        {"@type": "ListItem", "position": 2, "name": "OFAC Cuba Sanctions", "item": f"{base}/sanctions-tracker"},
                        {"@type": "ListItem", "position": 3, "name": "By sector", "item": canonical},
                    ],
                },
                {
                    "@type": "CollectionPage",
                    "@id": f"{canonical}#collection",
                    "name": title,
                    "description": description,
                    "url": canonical,
                    "isPartOf": {"@type": "WebSite", "url": f"{base}/", "name": _s.site_name},
                    "hasPart": [
                        {
                            "@type": "ItemList",
                            "name": item["label"],
                            "url": f"{base}{item['url_path']}",
                            "numberOfItems": item["count"],
                            "description": item["description"],
                        }
                        for item in sectors_payload
                    ],
                },
            ],
        }, ensure_ascii=False)

        from src.seo.cluster_topology import build_cluster_ctx
        cluster_ctx = build_cluster_ctx("/sanctions/by-sector")

        template = _env.get_template("sanctions/by_sector_index.html.j2")
        html = template.render(
            sectors=sectors_payload,
            stats=bucket_stats | s_counts,
            today_human=today_human,
            seo=seo,
            jsonld=jsonld,
            cluster_ctx=cluster_ctx,
            current_year=_date.today().year,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("sanctions by-sector index render failed: %s", exc)
        abort(500)


@app.route("/sanctions/sector/<slug>")
@app.route("/sanctions/sector/<slug>/")
def sanctions_by_sector_detail(slug: str):
    """A-Z directory of every SDN designation in one sector."""
    from src.data.sdn_profiles import (
        SECTOR_KEYS, SECTOR_LABELS, SECTOR_DESCRIPTIONS, SECTOR_SLUGS,
        list_by_sector, sector_stats,
    )
    from src.page_renderer import _env, _base_url, _iso, settings as _s
    from datetime import date as _date, datetime as _dt
    import json as _json

    if slug not in SECTOR_KEYS:
        abort(404)

    try:
        profiles = list_by_sector(slug)
        sector_label = SECTOR_LABELS.get(slug, slug.title())
        sector_description = SECTOR_DESCRIPTIONS.get(slug, "")
        s_counts = sector_stats()

        grouped: list[tuple[str, list]] = []
        current_letter = None
        current_items: list = []
        for p in profiles:
            letter = (p.raw_name[:1] or "#").upper()
            if not letter.isalpha():
                letter = "#"
            if letter != current_letter:
                if current_items:
                    grouped.append((current_letter, current_items))
                current_letter = letter
                current_items = []
            current_items.append(p)
        if current_items:
            grouped.append((current_letter, current_items))

        sectors_nav = [
            {
                "key": k,
                "label": SECTOR_LABELS.get(k, k.title()),
                "url_path": f"/sanctions/sector/{SECTOR_SLUGS.get(k, k)}",
                "count": s_counts.get(k, 0),
            }
            for k in SECTOR_KEYS
        ]

        base = _base_url()
        canonical = f"{base}/sanctions/sector/{slug}"
        today_human = _date.today().strftime("%B %-d, %Y")

        title = (
            f"OFAC Cuba SDN — Currently Sanctioned {sector_label} "
            f"({len(profiles)})"
        )[:120]
        description = (
            f"Complete list of {len(profiles)} {sector_label.lower()} currently on the "
            f"OFAC Cuba SDN list (CACR §515) as of {today_human}. Includes program code, "
            f"designation date, and a permanent profile page for every name. "
            f"Updated twice daily from US Treasury."
        )[:300]

        seo = {
            "title": title,
            "description": description,
            "keywords": (
                f"OFAC Cuba {sector_label.lower()}, "
                f"sanctioned {sector_label.lower()} Cuba, "
                f"OFAC SDN {slug} Cuba, "
                f"current OFAC Cuba {slug} list"
            ),
            "canonical": canonical,
            "site_name": _s.site_name,
            "site_url": base,
            "locale": _s.site_locale,
            "og_image": f"{base}/static/og-image.png?v=3",
            "og_type": "website",
            "published_iso": _iso(_dt.utcnow()),
            "modified_iso": _iso(_dt.utcnow()),
        }

        jsonld = _json.dumps({
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
                        {"@type": "ListItem", "position": 2, "name": "OFAC Cuba Sanctions", "item": f"{base}/sanctions-tracker"},
                        {"@type": "ListItem", "position": 3, "name": "By sector", "item": f"{base}/sanctions/by-sector"},
                        {"@type": "ListItem", "position": 4, "name": sector_label, "item": canonical},
                    ],
                },
                {
                    "@type": "ItemList",
                    "@id": f"{canonical}#list",
                    "name": title,
                    "description": description,
                    "numberOfItems": len(profiles),
                    "itemListElement": [
                        {
                            "@type": "ListItem",
                            "position": idx + 1,
                            "url": f"{base}{p.url_path}",
                            "name": p.display_name,
                        }
                        for idx, p in enumerate(profiles[:200])
                    ],
                },
            ],
        }, ensure_ascii=False)

        from src.seo.cluster_topology import build_cluster_ctx
        cluster_ctx = build_cluster_ctx(f"/sanctions/sector/{slug}")

        template = _env.get_template("sanctions/by_sector.html.j2")
        html = template.render(
            active_key=slug,
            sector_label=sector_label,
            sector_description=sector_description,
            profiles=profiles,
            grouped=grouped,
            sectors_nav=sectors_nav,
            today_human=today_human,
            seo=seo,
            jsonld=jsonld,
            cluster_ctx=cluster_ctx,
            current_year=_date.today().year,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("sanctions by-sector detail render failed for slug=%s: %s", slug, exc)
        abort(500)


@app.route("/sanctions/<bucket>")
@app.route("/sanctions/<bucket>/")
def sanctions_index_page(bucket: str):
    """A-Z directory of every SDN entry in one bucket
    (individuals / entities / vessels / aircraft)."""
    from src.data.sdn_profiles import (
        ENTITY_BUCKETS, _BUCKET_SINGULAR, list_profiles, stats as sdn_stats,
    )
    from src.page_renderer import _env, _base_url, _iso, settings as _s
    from datetime import date as _date, datetime as _dt
    import json as _json

    if bucket not in ENTITY_BUCKETS:
        abort(404)

    try:
        profiles = list_profiles(bucket)
        s = sdn_stats()
        singular = _BUCKET_SINGULAR.get(bucket, bucket)

        grouped: list[tuple[str, list]] = []
        current_letter = None
        current_items: list = []
        for p in profiles:
            letter = (p.raw_name[:1] or "#").upper()
            if not letter.isalpha():
                letter = "#"
            if letter != current_letter:
                if current_items:
                    grouped.append((current_letter, current_items))
                current_letter = letter
                current_items = []
            current_items.append(p)
        if current_items:
            grouped.append((current_letter, current_items))

        base = _base_url()
        canonical = f"{base}/sanctions/{bucket}"
        today_human = _date.today().strftime("%B %Y")
        today_iso = _date.today().isoformat()

        plural = singular if singular.endswith("s") else f"{singular}s"
        seo = {
            "title": (
                f"Currently Sanctioned Cuba {bucket.capitalize()} — "
                f"OFAC SDN List ({len(profiles)} Active, {today_human})"
            )[:120],
            "description": (
                f"All {len(profiles)} Cuban {plural} actively sanctioned by "
                f"OFAC under the CUBA program (CACR, 31 CFR Part 515) as of "
                f"{today_human}. Browse the full SDN list A–Z, with each "
                f"name linking to a permanent profile (program code, "
                f"designation date, biographical data, and direct OFAC "
                f"source link). Updated twice daily from the live US "
                f"Treasury feed."
            )[:300],
            "keywords": (
                f"currently sanctioned Cuba {bucket}, OFAC Cuba "
                f"{bucket} list, Cuba SDN {bucket} {today_human.split()[-1]}, "
                f"OFAC Cuba sanctions list, OFAC SDN search, CACR §515"
            ),
            "canonical": canonical,
            "site_name": _s.site_name,
            "site_url": base,
            "locale": _s.site_locale,
            "og_image": f"{base}/static/og-image.png?v=3",
            "og_type": "website",
            "published_iso": _iso(_dt.utcnow()),
            "modified_iso": _iso(_dt.utcnow()),
        }

        jsonld = _json.dumps({
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
                        {"@type": "ListItem", "position": 2, "name": "OFAC Cuba Sanctions", "item": f"{base}/sanctions-tracker"},
                        {"@type": "ListItem", "position": 3, "name": bucket.capitalize(), "item": canonical},
                    ],
                },
                {
                    "@type": "ItemList",
                    "@id": f"{canonical}#list",
                    "name": f"OFAC Cuba SDN — {bucket.capitalize()}",
                    "numberOfItems": len(profiles),
                    "itemListElement": [
                        {
                            "@type": "ListItem",
                            "position": idx + 1,
                            "url": f"{base}{p.url_path}",
                            "name": p.display_name,
                        }
                        for idx, p in enumerate(profiles[:200])
                    ],
                },
            ],
        }, ensure_ascii=False)

        from src.seo.cluster_topology import build_cluster_ctx
        cluster_ctx = build_cluster_ctx(f"/sanctions/{bucket}")

        template = _env.get_template("sanctions/index.html.j2")
        html = template.render(
            bucket=bucket,
            singular=singular,
            profiles=profiles,
            grouped=grouped,
            stats=s,
            seo=seo,
            jsonld=jsonld,
            cluster_ctx=cluster_ctx,
            current_year=_date.today().year,
            today_human=today_human,
            today_iso=today_iso,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("sanctions index render failed for bucket=%s: %s", bucket, exc)
        abort(500)


@app.route("/sanctions/<bucket>/<slug>")
@app.route("/sanctions/<bucket>/<slug>/")
def sanctions_profile_page(bucket: str, slug: str):
    """One OFAC SDN entry's permanent, indexable profile page."""
    from src.data.sdn_profiles import (
        ENTITY_BUCKETS, family_members, find_related_news, get_profile,
        list_profiles, resolve_linked_to, stats as sdn_stats,
    )
    from src.page_renderer import _env, _base_url, _iso, settings as _s
    from datetime import date as _date, datetime as _dt
    import json as _json

    if bucket not in ENTITY_BUCKETS:
        abort(404)
    profile = get_profile(bucket, slug)
    if profile is None:
        abort(404)

    try:
        family = family_members(profile)
        linked_to = resolve_linked_to(profile)
        related_news = find_related_news(profile)
        s = sdn_stats()

        all_in_bucket = list_profiles(bucket)
        siblings: list = []
        try:
            idx = next(i for i, p in enumerate(all_in_bucket) if p.db_id == profile.db_id)
            for i in range(max(0, idx - 3), min(len(all_in_bucket), idx + 4)):
                if all_in_bucket[i].db_id == profile.db_id:
                    continue
                siblings.append(all_in_bucket[i])
                if len(siblings) >= 6:
                    break
        except StopIteration:
            siblings = []

        base = _base_url()
        canonical = f"{base}{profile.url_path}"
        today_human = _date.today().strftime("%B %Y")
        today_iso = _date.today().isoformat()

        title = (
            f"{profile.display_name} Sanctions — OFAC SDN Cuba Status "
            f"({_date.today().year})"
        )[:120]

        ident_bits: list[str] = []
        if profile.parsed.get("nationality"):
            ident_bits.append(profile.parsed["nationality"])
        if profile.parsed.get("dob"):
            ident_bits.append(f"born {profile.parsed['dob']}")
        if profile.parsed.get("imo"):
            ident_bits.append(f"IMO {profile.parsed['imo']}")
        if profile.parsed.get("aircraft_tail"):
            ident_bits.append(f"tail {profile.parsed['aircraft_tail']}")
        ident_phrase = (" (" + ", ".join(ident_bits) + ")") if ident_bits else ""
        program_phrase = profile.program or "the CUBA program (CACR, 31 CFR Part 515)"

        description = (
            f"{profile.display_name}{ident_phrase} is actively sanctioned by "
            f"OFAC under {program_phrase} as of {today_human}. View the live "
            f"SDN entry, linked entities, and the Cuban Assets Control "
            f"Regulations basis under which the designation was made."
        ).strip()[:300]

        seo = {
            "title": title,
            "description": description,
            "keywords": (
                f"is {profile.display_name} sanctioned, "
                f"{profile.display_name} OFAC, {profile.display_name} sanctions, "
                f"{profile.raw_name}, OFAC Cuba {profile.category_singular}, "
                f"OFAC SDN {profile.category_singular}, {profile.program}, "
                f"CACR §515"
            ),
            "canonical": canonical,
            "site_name": _s.site_name,
            "site_url": base,
            "locale": _s.site_locale,
            "og_image": f"{base}/static/og-image.png?v=3",
            "og_type": "profile",
            "published_iso": _iso(_dt.utcnow()),
            "modified_iso": _iso(_dt.utcnow()),
        }

        breadcrumb = {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
                {"@type": "ListItem", "position": 2, "name": "OFAC Cuba Sanctions", "item": f"{base}/sanctions-tracker"},
                {"@type": "ListItem", "position": 3, "name": profile.bucket.capitalize(), "item": f"{base}/sanctions/{profile.bucket}"},
                {"@type": "ListItem", "position": 4, "name": profile.display_name, "item": canonical},
            ],
        }

        identifiers: list = []
        if profile.parsed.get("cedula"):
            identifiers.append({"@type": "PropertyValue", "propertyID": "Cedula", "value": profile.parsed["cedula"]})
        if profile.parsed.get("passport"):
            identifiers.append({"@type": "PropertyValue", "propertyID": "Passport", "value": profile.parsed["passport"]})
        if profile.parsed.get("national_id"):
            identifiers.append({"@type": "PropertyValue", "propertyID": "NationalID", "value": profile.parsed["national_id"]})
        if profile.parsed.get("imo"):
            identifiers.append({"@type": "PropertyValue", "propertyID": "IMO", "value": profile.parsed["imo"]})
        if profile.parsed.get("mmsi"):
            identifiers.append({"@type": "PropertyValue", "propertyID": "MMSI", "value": profile.parsed["mmsi"]})
        if profile.parsed.get("aircraft_tail"):
            identifiers.append({"@type": "PropertyValue", "propertyID": "AircraftTailNumber", "value": profile.parsed["aircraft_tail"]})
        if profile.parsed.get("aircraft_serial"):
            identifiers.append({"@type": "PropertyValue", "propertyID": "AircraftSerialNumber", "value": profile.parsed["aircraft_serial"]})

        if profile.bucket == "individuals":
            entity_node = {
                "@type": "Person",
                "@id": f"{canonical}#person",
                "name": profile.display_name,
                "alternateName": profile.raw_name,
                "url": canonical,
                "description": description,
                "subjectOf": {
                    "@type": "GovernmentService",
                    "name": profile.program_label,
                    "provider": {"@type": "GovernmentOrganization", "name": "US Treasury Office of Foreign Assets Control (OFAC)"},
                },
            }
            if profile.parsed.get("dob"):
                entity_node["birthDate"] = profile.parsed["dob"]
            if profile.parsed.get("pob"):
                entity_node["birthPlace"] = profile.parsed["pob"]
            if profile.parsed.get("nationality"):
                entity_node["nationality"] = profile.parsed["nationality"]
            if profile.parsed.get("gender"):
                entity_node["gender"] = profile.parsed["gender"]
            if identifiers:
                entity_node["identifier"] = identifiers
        elif profile.bucket == "entities":
            entity_node = {
                "@type": "Organization",
                "@id": f"{canonical}#org",
                "name": profile.display_name,
                "alternateName": profile.raw_name,
                "url": canonical,
                "description": description,
            }
            if identifiers:
                entity_node["identifier"] = identifiers
        else:
            entity_node = {
                "@type": "Vehicle",
                "@id": f"{canonical}#vehicle",
                "name": profile.display_name,
                "alternateName": profile.raw_name,
                "url": canonical,
                "description": description,
                "vehicleConfiguration": "vessel" if profile.bucket == "vessels" else "aircraft",
            }
            if profile.parsed.get("aircraft_model"):
                entity_node["model"] = profile.parsed["aircraft_model"]
            if profile.parsed.get("vessel_year"):
                entity_node["vehicleModelDate"] = profile.parsed["vessel_year"]
            if identifiers:
                entity_node["identifier"] = identifiers

        program_label = profile.program_label or "the OFAC CUBA program (CACR §515)"
        added_human = profile.designation_date or "the date OFAC first published the designation"

        is_sanctioned_q = f"Is {profile.display_name} currently sanctioned by OFAC?"
        is_sanctioned_a = (
            f"Yes. As of {today_human}, {profile.display_name} is on the active US Treasury "
            f"Office of Foreign Assets Control (OFAC) Specially Designated Nationals (SDN) "
            f"list under {program_label}. All assets under US jurisdiction are blocked and "
            f"US persons are generally prohibited from dealing with them under the Cuban "
            f"Assets Control Regulations (31 CFR Part 515)."
        )

        program_q = f"What OFAC program is {profile.display_name} sanctioned under?"
        program_a = (
            f"{profile.display_name} is designated under {program_label}. "
            "OFAC's Cuba sanctions are administered under the Cuban Assets "
            "Control Regulations (CACR, 31 CFR Part 515), the comprehensive "
            "embargo framework that has been in continuous effect since "
            "1962. Distinct from the SDN designation, the State Department "
            "separately maintains the Cuba Restricted List (CRL, §515.209) "
            "and the Cuba Prohibited Accommodations List (CPAL, §515.210), "
            "which prohibit transactions even with entities not on the SDN."
        )

        added_q = f"When was {profile.display_name} added to the OFAC SDN list?"
        added_a = (
            f"{profile.display_name} was added to the OFAC SDN list on {added_human}. "
            "OFAC publishes designations as part of broader CUBA-program actions; "
            "the linked OFAC source page records the original press release. The "
            "designation remains active until OFAC removes it via a delisting action."
        )

        faq_block = [
            {"q": is_sanctioned_q, "a": is_sanctioned_a},
            {"q": program_q,       "a": program_a},
            {"q": added_q,         "a": added_a},
        ]

        faq_node = {
            "@type": "FAQPage",
            "@id": f"{canonical}#faq",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": f["q"],
                    "acceptedAnswer": {"@type": "Answer", "text": f["a"][:500]},
                }
                for f in faq_block
            ],
        }

        jsonld = _json.dumps({
            "@context": "https://schema.org",
            "@graph": [breadcrumb, entity_node, faq_node],
        }, ensure_ascii=False)

        from src.seo.cluster_topology import build_cluster_ctx, sector_for_program
        cluster_ctx = build_cluster_ctx(profile.url_path)
        sector_link = sector_for_program(profile.program)

        template = _env.get_template("sanctions/profile.html.j2")
        html = template.render(
            profile=profile,
            family=family,
            linked_to=linked_to,
            related_news=related_news,
            siblings=siblings,
            stats=s,
            sector_link=sector_link,
            cluster_ctx=cluster_ctx,
            seo=seo,
            jsonld=jsonld,
            current_year=_date.today().year,
            today_human=today_human,
            today_iso=today_iso,
            faq_block=faq_block,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "sanctions profile render failed for bucket=%s slug=%s: %s",
            bucket, slug, exc,
        )
        abort(500)


# ──────────────────────────────────────────────────────────────────────
# /people — Cuban power figures directory
# ──────────────────────────────────────────────────────────────────────
#
# Editorial-magazine treatment of the people inside the Cuban
# government, the PCC, the security services, the judiciary, and the
# opposition. Every figure has a permanent, name-titled profile so a
# Google search like "miguel diaz canel" or "bruno rodriguez cuba"
# lands directly here, with the matching name in the SERP snippet.
# ──────────────────────────────────────────────────────────────────────

@app.route("/people")
@app.route("/people/")
def people_index_page():
    """Pillar page for the Cuban power-figures cluster."""
    from src.data.people import (
        all_people, COHORTS, COHORT_ORDER, VERIFIED_AS_OF,
        people_in_cohort, cohort_url,
    )
    from src.page_renderer import _env, _base_url, _iso, settings as _s
    from datetime import date as _date, datetime as _dt
    import json as _json

    try:
        people = all_people()
        cohort_cards = []
        for key in COHORT_ORDER:
            meta = COHORTS[key]
            cohort_cards.append({
                "key": key,
                "label": meta["label"],
                "description": meta["description"],
                "path": cohort_url(key),
                "count": len(people_in_cohort(key)),
            })

        base = _base_url()
        canonical = f"{base}/people"
        verified_iso = VERIFIED_AS_OF
        verified_dt = _dt.strptime(VERIFIED_AS_OF, "%Y-%m-%d")
        verified_human = verified_dt.strftime("%B %Y")
        current_year = _date.today().year

        seo = {
            "title": (
                f"Cuban Power Figures — Who Actually Runs Cuba in {current_year} "
                f"(Verified Profiles)"
            )[:120],
            "description": (
                f"Profiles of {len(people)} people inside the Cuban government, "
                f"the Communist Party (PCC), the FAR and MININT security "
                f"services, the judiciary, and the opposition — verified "
                f"against current news as of {verified_human}, with sanctions "
                f"cross-references where they apply."
            )[:300],
            "keywords": (
                "Cuba president, Cuba prime minister, who runs Cuba, Cuban "
                "Communist Party, PCC Politburo, Cuba MINFAR, Cuba MININT, "
                "Cuba Fiscal General, Cuba opposition, UNPACU, Damas de Blanco"
            ),
            "canonical": canonical,
            "site_name": _s.site_name,
            "site_url": base,
            "locale": _s.site_locale,
            "og_image": f"{base}/static/og-image.png?v=3",
            "og_type": "website",
            "published_iso": _iso(_dt.utcnow()),
            "modified_iso": _iso(_dt.utcnow()),
        }

        jsonld = _json.dumps({
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
                        {"@type": "ListItem", "position": 2, "name": "Cuban power figures", "item": canonical},
                    ],
                },
                {
                    "@type": "ItemList",
                    "@id": f"{canonical}#list",
                    "name": "Cuban power figures",
                    "numberOfItems": len(people),
                    "itemListElement": [
                        {
                            "@type": "ListItem",
                            "position": idx + 1,
                            "url": f"{base}{p.url_path}",
                            "name": p.name,
                        }
                        for idx, p in enumerate(people)
                    ],
                },
            ],
        }, ensure_ascii=False)

        from src.seo.cluster_topology import build_cluster_ctx
        cluster_ctx = build_cluster_ctx("/people")

        template = _env.get_template("people/index.html.j2")
        html = template.render(
            people=people,
            cohorts=COHORTS,
            cohort_cards=cohort_cards,
            verified_iso=verified_iso,
            verified_human=verified_human,
            current_year=current_year,
            seo=seo,
            jsonld=jsonld,
            cluster_ctx=cluster_ctx,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("people index render failed: %s", exc)
        abort(500)


@app.route("/people/by-role/<cohort>")
@app.route("/people/by-role/<cohort>/")
def people_cohort_page(cohort: str):
    """Cohort hub — every person tagged with this cohort key."""
    from src.data.people import (
        COHORTS, COHORT_ORDER, VERIFIED_AS_OF,
        people_in_cohort, cohort_url,
    )
    from src.page_renderer import _env, _base_url, _iso, settings as _s
    from datetime import date as _date, datetime as _dt
    import json as _json

    if cohort not in COHORTS:
        abort(404)

    try:
        meta = COHORTS[cohort]
        people = people_in_cohort(cohort)
        other_cohorts = [
            {
                "key": k,
                "label": COHORTS[k]["label"],
                "description": COHORTS[k]["description"],
                "path": cohort_url(k),
            }
            for k in COHORT_ORDER if k != cohort
        ]

        base = _base_url()
        canonical = f"{base}/people/by-role/{cohort}"
        verified_iso = VERIFIED_AS_OF
        verified_human = _dt.strptime(VERIFIED_AS_OF, "%Y-%m-%d").strftime("%B %Y")
        current_year = _date.today().year

        seo = {
            "title": (
                f"{meta['label']} — Cuban Power Figures ({current_year})"
            )[:120],
            "description": (
                f"{meta['description']} Verified profiles of "
                f"{len(people)} {'figure' if len(people) == 1 else 'figures'} "
                f"as of {verified_human}."
            )[:300],
            "keywords": f"Cuba {meta['short'].lower()}, who runs Cuba, Cuban government officials",
            "canonical": canonical,
            "site_name": _s.site_name,
            "site_url": base,
            "locale": _s.site_locale,
            "og_image": f"{base}/static/og-image.png?v=3",
            "og_type": "website",
            "published_iso": _iso(_dt.utcnow()),
            "modified_iso": _iso(_dt.utcnow()),
        }

        jsonld = _json.dumps({
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
                        {"@type": "ListItem", "position": 2, "name": "Cuban power figures", "item": f"{base}/people"},
                        {"@type": "ListItem", "position": 3, "name": meta["label"], "item": canonical},
                    ],
                },
                {
                    "@type": "ItemList",
                    "@id": f"{canonical}#list",
                    "name": meta["label"],
                    "numberOfItems": len(people),
                    "itemListElement": [
                        {
                            "@type": "ListItem",
                            "position": idx + 1,
                            "url": f"{base}{p.url_path}",
                            "name": p.name,
                        }
                        for idx, p in enumerate(people)
                    ],
                },
            ],
        }, ensure_ascii=False)

        from src.seo.cluster_topology import build_cluster_ctx
        cluster_ctx = build_cluster_ctx(f"/people/by-role/{cohort}")

        template = _env.get_template("people/by_role.html.j2")
        html = template.render(
            cohort_key=cohort,
            cohort_label=meta["label"],
            cohort_description=meta["description"],
            people=people,
            other_cohorts=other_cohorts,
            verified_iso=verified_iso,
            verified_human=verified_human,
            current_year=current_year,
            seo=seo,
            jsonld=jsonld,
            cluster_ctx=cluster_ctx,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("people cohort render failed for %s: %s", cohort, exc)
        abort(500)


@app.route("/people/<slug>")
@app.route("/people/<slug>/")
def people_profile_page(slug: str):
    """One Cuban power figure → one permanent, name-titled profile."""
    from src.data.people import (
        get_person, cohort_label, cohort_url, related_people,
        cohort_siblings, status_badge, VERIFIED_AS_OF,
    )
    from src.page_renderer import _env, _base_url, _iso, settings as _s
    from datetime import date as _date, datetime as _dt
    import json as _json

    person = get_person(slug)
    if person is None:
        abort(404)

    try:
        related = related_people(person)
        siblings = cohort_siblings(person, limit=6)
        badge = status_badge(person.status)

        base = _base_url()
        canonical = f"{base}{person.url_path}"
        verified_iso = VERIFIED_AS_OF
        verified_human = _dt.strptime(VERIFIED_AS_OF, "%Y-%m-%d").strftime("%B %Y")
        current_year = _date.today().year

        title = f"{person.name} — {person.role} ({current_year})"
        seo = {
            "title": title[:120],
            "description": person.one_liner[:300],
            "keywords": (
                f"who is {person.name}, {person.name} biography, "
                f"{person.name} role, {person.name} Cuba"
                f"{', ' + person.name + ' OFAC sanctions' if person.sanctioned else ''}"
            ),
            "canonical": canonical,
            "site_name": _s.site_name,
            "site_url": base,
            "locale": _s.site_locale,
            "og_image": f"{base}/static/og-image.png?v=3",
            "og_type": "profile",
            "published_iso": _iso(_dt.utcnow()),
            "modified_iso": _iso(_dt.utcnow()),
        }

        person_node = {
            "@type": "Person",
            "@id": f"{canonical}#person",
            "name": person.name,
            "url": canonical,
            "jobTitle": person.role,
            "nationality": person.nationality,
            "description": person.one_liner,
        }
        if person.aliases:
            person_node["alternateName"] = list(person.aliases)
        if person.born:
            person_node["birthDate"] = person.born
        if person.birthplace:
            person_node["birthPlace"] = person.birthplace
        if person.affiliations:
            person_node["affiliation"] = [
                {"@type": "Organization", "name": a} for a in person.affiliations
            ]
        same_as: list[str] = []
        if person.wikidata_id:
            same_as.append(f"https://www.wikidata.org/wiki/{person.wikidata_id}")
        if person.wikipedia_url:
            same_as.append(person.wikipedia_url)
        if same_as:
            person_node["sameAs"] = same_as

        breadcrumb = {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
                {"@type": "ListItem", "position": 2, "name": "Cuban power figures", "item": f"{base}/people"},
                {"@type": "ListItem", "position": 3, "name": cohort_label(person.primary_cohort), "item": f"{base}{cohort_url(person.primary_cohort)}"},
                {"@type": "ListItem", "position": 4, "name": person.name, "item": canonical},
            ],
        }

        graph = [breadcrumb, person_node]
        if person.faqs:
            graph.append({
                "@type": "FAQPage",
                "@id": f"{canonical}#faq",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": f.q,
                        "acceptedAnswer": {"@type": "Answer", "text": f.a[:500]},
                    }
                    for f in person.faqs
                ],
            })

        jsonld = _json.dumps({
            "@context": "https://schema.org",
            "@graph": graph,
        }, ensure_ascii=False)

        from src.seo.cluster_topology import build_cluster_ctx
        cluster_ctx = build_cluster_ctx(person.url_path)

        template = _env.get_template("people/profile.html.j2")
        html = template.render(
            person=person,
            related=related,
            siblings=siblings,
            badge=badge,
            cohort_label=cohort_label(person.primary_cohort),
            cohort_url=cohort_url(person.primary_cohort),
            verified_iso=verified_iso,
            verified_human=verified_human,
            current_year=current_year,
            seo=seo,
            jsonld=jsonld,
            cluster_ctx=cluster_ctx,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("people profile render failed for slug=%s: %s", slug, exc)
        abort(500)


def _company_index_letter(name: str) -> str:
    letter = (name[:1] or "#").upper()
    return letter if letter.isalpha() else "#"


@app.route("/companies")
@app.route("/companies/")
@limiter.limit("6 per minute")
def companies_index_page():
    """A-Z directory of every S&P 500 ticker with a Cuba-exposure page."""
    try:
        from src.data.company_exposure import list_company_index_rows
        from src.page_renderer import _env, _base_url, _iso, settings as _s
        from datetime import date as _date, datetime as _dt
        import json as _json

        rows = list_company_index_rows(include_sdn_scan=True)

        grouped: list[tuple[str, list]] = []
        current_letter: str | None = None
        current_items: list = []
        counts = {"direct": 0, "indirect": 0, "historical": 0, "none": 0, "unknown": 0}
        for r in rows:
            counts[r.classification] = counts.get(r.classification, 0) + 1
            letter = _company_index_letter(r.name)
            if letter != current_letter:
                if current_items:
                    grouped.append((current_letter, current_items))
                current_letter = letter
                current_items = []
            current_items.append(r)
        if current_items:
            grouped.append((current_letter, current_items))

        base = _base_url()
        canonical = f"{base}/companies"
        seo = {
            "title": (
                f"Public Company Cuba Exposure & Sanctions Check — S&P 500 List"
            ),
            "description": (
                f"Search {len(rows)} S&P 500 companies for Cuba exposure, "
                f"OFAC sanctions signals, Cuba Restricted List and CPAL "
                f"links, Helms-Burton risk, CACR §515 issues, and SEC "
                f"filing disclosures. Refreshed daily."
            ),
            "keywords": (
                "S&P 500 Cuba exposure, public company Cuba exposure, "
                "OFAC sanctions S&P 500, Cuba Restricted List exposure, "
                "Helms-Burton public company, EDGAR Cuba filings"
            ),
            "canonical": canonical,
            "site_name": _s.site_name,
            "site_url": base,
            "locale": _s.site_locale,
            "og_image": f"{base}/static/og-image.png?v=3",
            "og_type": "website",
            "published_iso": _iso(_dt.utcnow()),
            "modified_iso": _iso(_dt.utcnow()),
        }
        jsonld = _json.dumps({
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
                        {"@type": "ListItem", "position": 2, "name": "S&P 500 Cuba Exposure", "item": canonical},
                    ],
                },
                {
                    "@type": "ItemList",
                    "@id": f"{canonical}#list",
                    "name": "S&P 500 Cuba Exposure Register",
                    "numberOfItems": len(rows),
                    "itemListElement": [
                        {
                            "@type": "ListItem",
                            "position": idx + 1,
                            "url": f"{base}{r.url_path}",
                            "name": r.name,
                        }
                        for idx, r in enumerate(rows[:200])
                    ],
                },
            ],
        }, ensure_ascii=False)

        from src.seo.cluster_topology import build_cluster_ctx, companion_links as _companion_links
        cluster_ctx = build_cluster_ctx("/companies")
        companion_ctx = {
            "eyebrow": "Screening tools for any listed company",
            "title": "Vet a name beyond the S&P 500",
            "links": _companion_links([
                "/tools/public-company-cuba-exposure-check",
                "/tools/sec-edgar-cuba-impairment-search",
                "/tools/ofac-cuba-sanctions-checker",
                "/tools/cuba-restricted-list-checker",
                "/tools/cuba-prohibited-hotels-checker",
                "/sanctions-tracker",
                "/explainers/helms-burton-title-iii",
                "/explainers/cuba-restricted-list",
            ]),
        }

        template = _env.get_template("companies/index.html.j2")
        html = template.render(
            rows=rows,
            grouped=grouped,
            counts=counts,
            seo=seo,
            jsonld=jsonld,
            cluster_ctx=cluster_ctx,
            companion_ctx=companion_ctx,
            current_year=_date.today().year,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("companies index render failed: %s", exc)
        abort(500)


@app.route("/companies/<slug>")
@app.route("/companies/<slug>/")
@limiter.limit("6 per minute")
def companies_slug_page(slug: str):
    """Serve the company profile directly (canonical is /companies/<slug>/cuba-exposure).

    Previously redirected 301 → /companies/<slug>/cuba-exposure, but that caused
    hundreds of "Page with redirect" warnings in Google Search Console.
    Now serves the same content with a canonical tag so Google consolidates signals."""
    return companies_profile_page(slug)


@app.route("/companies/<slug>/cuba-exposure")
@app.route("/companies/<slug>/cuba-exposure/")
@limiter.limit("6 per minute")
def companies_profile_page(slug: str):
    """Per-company Cuba-exposure landing page."""
    try:
        from src.data.company_exposure import (
            build_exposure_report, find_company_by_slug, list_company_index_rows,
        )
        from src.page_renderer import _env, _base_url, _iso, settings as _s
        from datetime import date as _date, datetime as _dt
        import json as _json

        company = find_company_by_slug(slug)
        if company is None:
            abort(404)

        if company.slug != slug:
            return redirect(f"/companies/{company.slug}/cuba-exposure", code=301)

        report = build_exposure_report(company)

        all_rows = list_company_index_rows(include_sdn_scan=False)
        same_sector = [
            r for r in all_rows
            if r.sector == company.sector and r.ticker != company.ticker
        ]
        siblings = [r for r in same_sector if r.has_curated][:6]
        if len(siblings) < 6:
            for r in same_sector:
                if r in siblings:
                    continue
                siblings.append(r)
                if len(siblings) >= 6:
                    break

        base = _base_url()
        canonical = f"{base}/companies/{company.slug}/cuba-exposure"
        today_human = _date.today().strftime("%B %Y")
        today_iso = _date.today().isoformat()

        title = (
            f"{company.name} Sanctions Check — Cuba & OFAC Exposure "
            f"({today_human})"
        )[:120]

        binary_yes_no = {
            "direct":     ("Yes",   "has direct Cuba exposure on the public record"),
            "indirect":   ("Partly", "has indirect Cuba exposure via subsidiaries or counterparties"),
            "historical": ("No (resolved)", "has only historical Cuba exposure (wound down or written off)"),
            "none":       ("No",   "has no current Cuba exposure on the public record"),
            "unknown":    ("No",   "has no Cuba exposure on the public record"),
        }
        yes_no, binary_phrase = binary_yes_no.get(
            report.classification, ("Unknown", "exposure to Cuba has not been determined")
        )

        description = (
            f"{company.short_name} (${company.ticker}) {binary_phrase} as of "
            f"{today_human}. Independent check across the OFAC CUBA-program "
            f"SDN list, the State Department Cuba Restricted List and CPAL, "
            f"SEC EDGAR 10-K/10-Q/20-F filings, and the Cuban Insights news "
            f"corpus."
        ).strip()[:300]

        seo = {
            "title": title,
            "description": description,
            "keywords": (
                f"is {company.short_name} sanctioned, {company.short_name} Cuba, "
                f"{company.ticker} Cuba exposure, {company.short_name} OFAC, "
                f"{company.short_name} Helms-Burton, {company.short_name} CACR, "
                f"{company.ticker} sanctions, public company Cuba exposure"
            ),
            "canonical": canonical,
            "site_name": _s.site_name,
            "site_url": base,
            "locale": _s.site_locale,
            "og_image": f"{base}/static/og-image.png?v=3",
            "og_type": "article",
            "published_iso": _iso(_dt.utcnow()),
            "modified_iso": _iso(_dt.utcnow()),
        }

        breadcrumb = {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
                {"@type": "ListItem", "position": 2, "name": "S&P 500 Cuba Exposure", "item": f"{base}/companies"},
                {"@type": "ListItem", "position": 3, "name": company.short_name, "item": canonical},
            ],
        }
        article_node = {
            "@type": "Article",
            "@id": f"{canonical}#article",
            "url": canonical,
            "headline": title,
            "description": description,
            "datePublished": _iso(_dt.utcnow()),
            "dateModified": _iso(_dt.utcnow()),
            "inLanguage": "en-US",
            "isAccessibleForFree": True,
            "author": {"@type": "Organization", "name": _s.site_name, "url": f"{base}/"},
            "publisher": {
                "@type": "Organization",
                "name": _s.site_name,
                "url": f"{base}/",
                "logo": {"@type": "ImageObject", "url": f"{base}/static/og-image.png?v=3"},
            },
            "about": {
                "@type": "Organization",
                "name": company.name,
                "alternateName": company.ticker,
            },
        }

        is_sanctioned_a = (
            f"As of {today_human}, {company.short_name} ({company.ticker}) is "
            + ("listed on, or directly connected to entities on, the OFAC CUBA-program SDN list."
               if report.sdn_matches else
               "not listed on the OFAC CUBA-program SDN list. No direct or subsidiary entity match was found in our scan against the live US Treasury SDN feed. Note that the State Department's Cuba Restricted List and Cuba Prohibited Accommodations List apply separately and should be checked alongside the SDN.")
            + " Always re-verify against the official OFAC Sanctions Search before relying on this for a compliance decision."
        )

        edgar_n = len(report.edgar_mentions)
        sec_disclosure_a = (
            f"{company.short_name} has filed {edgar_n} recent SEC document"
            f"{'s' if edgar_n != 1 else ''} containing Cuba-related references "
            f"(searched across 10-K, 10-Q, 8-K, 20-F, and 6-K filings on EDGAR over the last 24 months — "
            f"queries include 'Cuba', 'Helms-Burton', 'CACR', 'Cuba Restricted List', and 'Havana'). "
            "See the SEC filings section on the page for the matched excerpts and links to each filing."
        ) if edgar_n else (
            f"No recent SEC filings by {company.short_name} ({company.ticker}) contain Cuba, "
            "Helms-Burton, CACR, or Havana references in our EDGAR search across 10-K, 10-Q, "
            "8-K, 20-F, and 6-K forms over the last 24 months. Use SEC EDGAR's full-text "
            "search to verify."
        )

        revenue_exposure_a = (
            f"{report.headline} {report.summary[:200]}".strip()
        )[:300]

        faq_node = {
            "@type": "FAQPage",
            "@id": f"{canonical}#faq",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": f"Is {company.short_name} ({company.ticker}) sanctioned by OFAC?",
                    "acceptedAnswer": {"@type": "Answer", "text": is_sanctioned_a[:400]},
                },
                {
                    "@type": "Question",
                    "name": f"Does {company.short_name} have Cuba revenue exposure?",
                    "acceptedAnswer": {"@type": "Answer", "text": revenue_exposure_a[:400]},
                },
                {
                    "@type": "Question",
                    "name": f"Has {company.short_name} disclosed Cuba in its SEC filings?",
                    "acceptedAnswer": {"@type": "Answer", "text": sec_disclosure_a[:400]},
                },
            ],
        }

        jsonld = _json.dumps(
            {"@context": "https://schema.org", "@graph": [breadcrumb, article_node, faq_node]},
            ensure_ascii=False,
        )

        from src.seo.cluster_topology import build_cluster_ctx
        cluster_ctx = build_cluster_ctx(f"/companies/{company.slug}/cuba-exposure")

        faq_block = [
            {
                "q": f"Is {company.short_name} ({company.ticker}) sanctioned by OFAC?",
                "a": is_sanctioned_a,
            },
            {
                "q": f"Does {company.short_name} have Cuba revenue exposure?",
                "a": revenue_exposure_a,
            },
            {
                "q": f"Has {company.short_name} disclosed Cuba in its SEC filings?",
                "a": sec_disclosure_a,
            },
        ]

        template = _env.get_template("companies/profile.html.j2")
        html = template.render(
            report=report,
            siblings=siblings,
            seo=seo,
            jsonld=jsonld,
            cluster_ctx=cluster_ctx,
            current_year=_date.today().year,
            today_human=today_human,
            today_iso=today_iso,
            faq_block=faq_block,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("company profile render failed for slug=%s: %s", slug, exc)
        abort(500)


@app.route("/companies/<slug>/venezuela-exposure")
@app.route("/companies/<slug>/venezuela-exposure/")
def _company_venezuela_exposure_page(slug: str):
    """Serve the company profile directly (canonical is /companies/<slug>/cuba-exposure)."""
    return companies_profile_page(slug)


@app.route("/tools/public-company-cuba-exposure-check")
@app.route("/tools/public-company-cuba-exposure-check/")
def tool_public_company_exposure_check():
    """Interactive lookup tool that resolves a free-text query to one
    of the per-company landing pages."""
    try:
        from src.data.company_exposure import (
            build_exposure_report, list_company_index_rows,
        )
        from src.data.sp500_companies import find_company
        from src.page_renderer import _env
        from datetime import date as _date
        from collections import Counter

        query = (request.args.get("q") or "").strip()
        sector_filter = (request.args.get("sector") or "").strip()
        exposure_filter = (request.args.get("exposure") or "").strip()

        report = None
        if query:
            company = find_company(query)
            if company is not None:
                report = build_exposure_report(company, use_edgar=True, network=False)

        # Build the picker dataset once. include_sdn_scan=False keeps this
        # cheap (no per-company SDN match) — we only need ticker/name/sector
        # /classification metadata for the dropdowns and the browse list.
        all_rows = list_company_index_rows(include_sdn_scan=False)
        entries_alpha = [
            {
                "ticker": r.ticker,
                "name": r.name,
                "short_name": r.short_name,
                "sector": r.sector,
                "url_path": r.url_path,
                "classification": r.classification,
            }
            for r in all_rows
        ]

        # Sector facet — natural S&P GICS labels straight from the source.
        sector_counter = Counter(e["sector"] for e in entries_alpha if e["sector"])
        sector_counts = sorted(sector_counter.items(), key=lambda kv: kv[0])

        # Exposure facet — kept in fixed compliance-priority order (most
        # actionable signals first).
        EXPOSURE_LABELS = {
            "direct": "Direct exposure",
            "indirect": "Indirect exposure",
            "historical": "Historical exposure",
            "none": "No current exposure",
            "unknown": "No exposure on record",
        }
        EXPOSURE_ORDER = ["direct", "indirect", "historical", "none", "unknown"]
        exposure_counter = Counter(e["classification"] for e in entries_alpha)
        exposure_counts = [
            {"key": k, "label": EXPOSURE_LABELS.get(k, k), "count": exposure_counter.get(k, 0)}
            for k in EXPOSURE_ORDER if exposure_counter.get(k, 0)
        ]

        # When a facet is active, render the matching companies as a
        # browseable list (in addition to / instead of the single-company
        # report). Skip when a query is also present — the report wins.
        filtered_companies: list[dict] = []
        if not query and (sector_filter or exposure_filter):
            for e in entries_alpha:
                if sector_filter and e["sector"] != sector_filter:
                    continue
                if exposure_filter and e["classification"] != exposure_filter:
                    continue
                filtered_companies.append({
                    **e,
                    "exposure_label": EXPOSURE_LABELS.get(e["classification"], e["classification"]),
                })

        # Pre-baked "popular" list for the empty state. Reflects the
        # most-asked Cuba-exposure tickers across compliance, IR, and
        # M&A desks: scheduled-service US carriers, Helms-Burton Title
        # III cruise-line defendants, telecoms with §515.542 ETECSA
        # roaming, hotel chains touching Gaviota / Cubanacán, and
        # ag exporters supplying ALIMPORT under TSRA.
        popular_tickers = [
            ("AAL",  "Direct (scheduled service to HAV under OFAC §515.560-567)"),
            ("DAL",  "Direct (scheduled MIA/JFK/ATL–HAV)"),
            ("JBLU", "Direct (FLL/JFK–HAV under OFAC authorized travel)"),
            ("UAL",  "Direct (EWR/IAH–HAV scheduled service)"),
            ("CCL",  "Historical (Helms-Burton Title III defendant — Havana Docks)"),
            ("RCL",  "Historical (Havana Docks Title III co-defendant)"),
            ("NCLH", "Historical (Havana Docks Title III co-defendant)"),
            ("MAR",  "Historical (Four Points Habana — license revoked 2020)"),
            ("T",    "Direct (ETECSA roaming under CACR §515.542)"),
            ("VZ",   "Direct (ETECSA roaming under CACR §515.542)"),
            ("TMUS", "Direct (ETECSA roaming under CACR §515.542)"),
            ("ADM",  "Direct (TSRA ag exports to ALIMPORT)"),
            ("BG",   "Direct (TSRA ag exports to ALIMPORT)"),
            ("TSN",  "Direct (TSRA ag exports — frozen poultry to ALIMPORT)"),
            ("PFE",  "Direct (medical / pharma exports under §515.547)"),
            ("MA",   "Direct (CACR §515.584 financial services GL)"),
        ]
        popular_lookup = {t: lbl for t, lbl in popular_tickers}
        popular: list[dict] = []
        for r in list_company_index_rows(include_sdn_scan=False):
            if r.ticker in popular_lookup:
                popular.append({
                    "ticker": r.ticker,
                    "short_name": r.short_name,
                    "url_path": r.url_path,
                    "label": popular_lookup[r.ticker],
                })
        order = {t: i for i, (t, _) in enumerate(popular_tickers)}
        popular.sort(key=lambda p: order.get(p["ticker"], 999))

        seo, jsonld = _tool_seo_jsonld(
            slug="public-company-cuba-exposure-check",
            title="Public Company Cuba Exposure Check — Free OFAC + SEC Tool",
            description=(
                "Free tool: type any S&P 500 company name or ticker and "
                "instantly see whether the company has Cuba exposure on the "
                "OFAC SDN list, on the State Department Cuba Restricted "
                "List, on the Cuba Prohibited Accommodations List, in its "
                "recent SEC filings (Helms-Burton, CACR §515), or in our "
                "news corpus. Backed by 500+ per-ticker landing pages."
            ),
            keywords=(
                "public company Cuba exposure, S&P 500 Cuba check, "
                "OFAC company screening Cuba, Cuba exposure search, "
                "Cuba Restricted List exposure, Helms-Burton public "
                "company, ETECSA telecom check, ALIMPORT ag exports"
            ),
            faq=[
                {
                    "q": "How do I check if a public company has Cuba exposure?",
                    "a": (
                        "Type the company name or its ticker into the search "
                        "box above. The tool resolves the query against the "
                        "S&P 500 list, runs an OFAC CUBA-program SDN scan, "
                        "checks the State Department Cuba Restricted List "
                        "and Cuba Prohibited Accommodations List, scans "
                        "recent SEC filings (10-K, 10-Q, 8-K, 20-F, 6-K) "
                        "for Cuba / Helms-Burton / CACR §515 references, "
                        "and surfaces matching Federal Register notices "
                        "and news articles from the Cuban Insights corpus."
                    ),
                },
                {
                    "q": "Which companies are covered?",
                    "a": (
                        "Every S&P 500 constituent (about 500 tickers) has "
                        "a dedicated profile page at "
                        "/companies/<slug>/cuba-exposure. About 30 of those "
                        "have a hand-curated analyst note covering Cuban "
                        "subsidiaries, Helms-Burton Title III litigation "
                        "history, OFAC general-license context (CACR "
                        "§515.560-578 travel, §515.542 telecom, §515.533 "
                        "ag exports under TSRA, etc.); the rest rely on "
                        "algorithmic signals (OFAC SDN, CRL, CPAL, EDGAR "
                        "full-text, news corpus)."
                    ),
                },
                {
                    "q": "What does \"no exposure on the public record\" mean?",
                    "a": (
                        "It means there is no entry on the OFAC CUBA-"
                        "program SDN list matching the company or any of "
                        "its known subsidiaries, no hit on the State "
                        "Department Cuba Restricted List or Cuba "
                        "Prohibited Accommodations List, no Cuba-related "
                        "disclosure in the company's recent SEC filings "
                        "that we have indexed, and no analyzed news "
                        "article in our corpus naming the company "
                        "alongside Cuban context. This is the answer most "
                        "analysts come to verify."
                    ),
                },
                {
                    "q": "Is this tool a substitute for sanctions counsel?",
                    "a": (
                        "No. The tool surfaces signals that justify deeper "
                        "diligence; it does not perform full ownership-"
                        "chain analysis (the OFAC 50% Rule), check non-"
                        "SDN sectoral lists in full depth, evaluate "
                        "Helms-Burton Title III / IV trafficking-claim "
                        "exposure on a case-by-case basis, or verify "
                        "enforcement context. For high-stakes Cuba "
                        "counterparties, retain qualified sanctions counsel."
                    ),
                },
            ],
        )

        from src.seo.cluster_topology import build_cluster_ctx, build_related_tools_ctx
        cluster_ctx = build_cluster_ctx("/tools/public-company-cuba-exposure-check")
        related_tools_ctx = build_related_tools_ctx("/tools/public-company-cuba-exposure-check")

        template = _env.get_template("tools/public_company_exposure_check.html.j2")
        html = template.render(
            query=query,
            report=report,
            popular=popular,
            entries_alpha=entries_alpha,
            sector_counts=sector_counts,
            exposure_counts=exposure_counts,
            sector_filter=sector_filter,
            exposure_filter=exposure_filter,
            filtered_companies=filtered_companies,
            total_entries=len(entries_alpha),
            seo=seo,
            jsonld=jsonld,
            cluster_ctx=cluster_ctx,
            related_tools_ctx=related_tools_ctx,
            current_year=_date.today().year,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("public company exposure tool render failed: %s", exc)
        abort(500)


@app.route("/tools/public-company-venezuela-exposure-check")
@app.route("/tools/public-company-venezuela-exposure-check/")
def _legacy_public_company_exposure_redirect():
    return _legacy_redirect_to("/tools/public-company-cuba-exposure-check")


@app.route("/calendar")
@app.route("/calendar/")
def calendar_page():
    """Standalone investor calendar page — same data the home report uses."""
    try:
        from src.report_generator import _build_calendar
        from src.models import (
            AssemblyNewsEntry,
            ExternalArticleEntry,
            GazetteStatus,
            SessionLocal,
            init_db,
        )
        from src.page_renderer import _env, _base_url, _iso, settings as _s
        from datetime import date as _date, datetime as _dt, timedelta as _td
        import json as _json

        init_db()
        db = SessionLocal()
        try:
            cutoff = _date.today() - _td(days=settings.report_lookback_days)
            ext = (
                db.query(ExternalArticleEntry)
                .filter(ExternalArticleEntry.status == GazetteStatus.ANALYZED)
                .filter(ExternalArticleEntry.published_date >= cutoff)
                .all()
            )
            asm = (
                db.query(AssemblyNewsEntry)
                .filter(AssemblyNewsEntry.status == GazetteStatus.ANALYZED)
                .filter(AssemblyNewsEntry.published_date >= cutoff)
                .all()
            )
            calendar_events = _build_calendar(ext, asm)

            base = _base_url()
            canonical = f"{base}/calendar"
            seo = {
                "title": "Cuba Investor Calendar — OFAC, BCC, Asamblea Nacional key dates",
                "description": (
                    "Upcoming OFAC CACR §515 amendment windows, Asamblea "
                    "Nacional sessions, BCC announcements, MIPYMES "
                    "regulatory deadlines, Helms-Burton Title III docket "
                    "milestones, and Mariel ZED project timelines. "
                    "Updated twice daily."
                ),
                "keywords": (
                    "Cuba investor calendar, OFAC CACR amendments, "
                    "Asamblea Nacional Cuba dates, BCC calendar, MIPYMES "
                    "deadlines, Mariel ZED timelines"
                ),
                "canonical": canonical,
                "site_name": _s.site_name,
                "site_url": base,
                "locale": _s.site_locale,
                "og_image": f"{base}/static/og-image.png?v=3",
                "og_type": "website",
                "published_iso": _iso(_dt.utcnow()),
                "modified_iso": _iso(_dt.utcnow()),
            }
            jsonld = _json.dumps({
                "@context": "https://schema.org",
                "@graph": [{
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
                        {"@type": "ListItem", "position": 2, "name": "Invest in Cuba", "item": f"{base}/invest-in-cuba"},
                        {"@type": "ListItem", "position": 3, "name": "Investor Calendar", "item": canonical},
                    ],
                }],
            }, ensure_ascii=False)

            template = _env.get_template("calendar.html.j2")
            html = template.render(
                calendar_events=calendar_events,
                seo=seo,
                jsonld=jsonld,
                current_year=_date.today().year,
            )
            return Response(html, mimetype="text/html")
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("calendar page render failed: %s", exc)
        abort(500)


# ──────────────────────────────────────────────────────────────────────
# Venezuela signposting pages.
#
# /travel currently picks up ~12 imp/mo for "transport venezuela" and
# a handful of other Venezuela-travel queries. They can never convert
# on a Cuba publication. These thin landing pages capture the existing
# search demand and forward it to caracasresearch.com (sister site)
# rather than letting it fail silently on the Cuba travel page.
# ──────────────────────────────────────────────────────────────────────

CARACAS_RESEARCH_TRAVEL_URL = "https://caracasresearch.com/travel"

_VENEZUELA_TOPICS: dict[str, dict] = {
    "transport": {
        "slug": "transport",
        "h1": "Transport in Venezuela — Caracas Taxis, Metro, Domestic Flights & Security",
        "short_title": "Transport in Venezuela",
        "eyebrow": "Venezuela · Transport overview",
        "title": "Transport in Venezuela 2026 — Caracas Taxis, Metro & Domestic Flights",
        "description": (
            "Overview of ground transport in Venezuela for 2026: pre-arranged "
            "Caracas airport transfers, Metro de Caracas, intercity buses, "
            "domestic flights, and security considerations. Full guide on "
            "Caracas Research."
        ),
        "keywords": (
            "transport venezuela, transport in venezuela, caracas taxis, "
            "caracas airport transfer, venezuela domestic flights, "
            "metro de caracas, venezuela ground transport, caracas research"
        ),
        "lede": (
            "A short reference for U.S. travelers, journalists, and operators "
            "asking how to move around Venezuela in 2026 — from Caracas "
            "airport transfers to intercity bus and domestic flight options. "
            "For the full Venezuela travel handbook, visit Caracas Research."
        ),
        "cta_url": CARACAS_RESEARCH_TRAVEL_URL,
        "cta_label": "Open the full Caracas & Venezuela travel guide",
        "sections": [
            {
                "heading": "Caracas airport (CCS / Maiquetía) transfers",
                "body": (
                    "Pre-arranged transfers booked through your hotel, an embassy "
                    "list, or a vetted security provider are the standard option "
                    "for foreign visitors arriving at Simón Bolívar International "
                    "Airport (CCS / Maiquetía). The Caracas-airport corridor "
                    "passes through Vargas state and the highway has historically "
                    "had armed-robbery incidents at night; daylight arrivals and "
                    "pre-arranged drivers are the dominant risk-mitigation pattern."
                ),
            },
            {
                "heading": "Caracas urban transport",
                "bullets": [
                    "<strong>Metro de Caracas:</strong> functional but service quality and security vary by line and time of day.",
                    "<strong>Taxis:</strong> use radio-dispatched or app-based services arranged through your hotel; avoid hailing from the street.",
                    "<strong>Walking:</strong> daylight and curated zones (Las Mercedes, Altamira, Chacao) only.",
                ],
            },
            {
                "heading": "Intercity and domestic flights",
                "body": (
                    "Domestic carriers serve Maracaibo, Valencia, Barcelona, "
                    "Mérida, Porlamar (Margarita), and other regional hubs. "
                    "Schedules and reliability change frequently; confirm with "
                    "the carrier within 24 hours of departure. Intercity bus "
                    "service exists but is generally not recommended for "
                    "foreign visitors due to security and reliability concerns."
                ),
            },
            {
                "heading": "Security overview",
                "body": (
                    "The U.S. State Department maintains a Level 4: Do Not Travel "
                    "advisory for Venezuela. Any in-country movement plan should "
                    "assume vetted drivers, daylight movements where possible, "
                    "and an in-country security contact. The full operational "
                    "checklist (drivers, vehicles, comms, embassy contacts) lives "
                    "in the Caracas Research travel guide."
                ),
            },
        ],
    },
    "caracas-travel-advisory": {
        "slug": "caracas-travel-advisory",
        "h1": "Caracas Travel Advisory 2026 — Current U.S. State Department Guidance",
        "short_title": "Caracas Travel Advisory",
        "eyebrow": "Venezuela · Travel advisory",
        "title": "Caracas Travel Advisory 2026 — U.S. State Dept Level & Risks",
        "description": (
            "Current U.S. State Department travel advisory for Caracas and "
            "Venezuela in 2026, key risk categories, and where to find the "
            "full operational travel guide on Caracas Research."
        ),
        "keywords": (
            "caracas travel advisory, venezuela travel advisory, caracas safety "
            "2026, is caracas safe, venezuela state department warning, "
            "venezuela tourism, travel to caracas venezuela, caracas research"
        ),
        "lede": (
            "A short signposting page for travelers and corporate-security teams "
            "checking the current U.S. State Department Caracas / Venezuela "
            "travel advisory and what it means in practice. The full guide "
            "lives on Caracas Research."
        ),
        "cta_url": CARACAS_RESEARCH_TRAVEL_URL,
        "cta_label": "Open the full Caracas travel guide",
        "sections": [
            {
                "heading": "Current U.S. State Department advisory level",
                "body": (
                    "The U.S. Department of State maintains a <strong>Level 4: "
                    "Do Not Travel</strong> advisory for Venezuela, citing "
                    "wrongful detentions, terrorism, kidnapping, civil unrest, "
                    "crime, poor health infrastructure, and the absence of a "
                    "U.S. embassy presence to assist U.S. citizens in country. "
                    "The advisory is reviewed periodically; check "
                    "<a href=\"https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories/venezuela-travel-advisory.html\" rel=\"nofollow noopener\" target=\"_blank\">travel.state.gov</a> for the live text."
                ),
            },
            {
                "heading": "Key risk categories cited",
                "bullets": [
                    "<strong>Wrongful detention:</strong> documented pattern of U.S. citizens being detained by Venezuelan authorities.",
                    "<strong>Crime:</strong> violent crime including armed robbery, carjacking, and kidnapping in Caracas and other cities.",
                    "<strong>Terrorism and civil unrest:</strong> intermittent demonstrations and irregular armed-group activity.",
                    "<strong>Health:</strong> shortages of medicines, limited emergency services, and unreliable utilities.",
                    "<strong>No U.S. embassy presence:</strong> the U.S. Embassy in Caracas is closed; U.S. citizens cannot expect routine consular assistance.",
                ],
            },
            {
                "heading": "What this means operationally",
                "body": (
                    "Travel decisions for Venezuela should be made with a vetted "
                    "in-country security contact, evacuation insurance, and a "
                    "documented communications plan. The Caracas Research "
                    "travel guide covers airport transfer providers, lodging, "
                    "communications, medical, and embassy-of-third-country "
                    "contact paths in detail."
                ),
            },
        ],
    },
}


@app.route("/venezuela")
@app.route("/venezuela/")
def _venezuela_index_redirect():
    return _legacy_redirect_to("/venezuela/transport")


@app.route("/tools/caracas-safety-by-neighborhood")
@app.route("/tools/caracas-safety-by-neighborhood/")
def _caracas_safety_redirect():
    return _legacy_redirect_to("/tools/havana-safety-by-neighborhood")


@app.route("/venezuela/<slug>")
@app.route("/venezuela/<slug>/")
def venezuela_topic_page(slug: str):
    """Thin Venezuela-topic landing pages; CTA to caracasresearch.com."""
    from src.page_renderer import _env, _base_url, _iso, settings as _s
    from datetime import datetime as _dt
    import json as _json

    topic = _VENEZUELA_TOPICS.get(slug)
    if not topic:
        abort(404)

    try:
        base = _base_url()
        canonical = f"{base}/venezuela/{slug}"
        seo = {
            "title": topic["title"],
            "description": topic["description"],
            "keywords": topic["keywords"],
            "canonical": canonical,
            "site_name": _s.site_name,
            "site_url": base,
            "locale": _s.site_locale,
            "og_image": f"{base}/static/og-image.png?v=3",
            "og_type": "article",
            "published_iso": _iso(_dt.utcnow()),
            "modified_iso": _iso(_dt.utcnow()),
        }
        jsonld = _json.dumps({
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
                        {"@type": "ListItem", "position": 2, "name": "Venezuela", "item": f"{base}/venezuela/{slug}"},
                        {"@type": "ListItem", "position": 3, "name": topic["short_title"], "item": canonical},
                    ],
                },
                {
                    "@type": "Article",
                    "@id": f"{canonical}#article",
                    "url": canonical,
                    "headline": topic["h1"],
                    "description": topic["description"],
                    "datePublished": _iso(_dt.utcnow()),
                    "dateModified": _iso(_dt.utcnow()),
                    "author": {"@type": "Organization", "name": _s.site_name, "url": f"{base}/"},
                    "publisher": {"@type": "Organization", "name": _s.site_name, "url": f"{base}/"},
                },
            ],
        }, ensure_ascii=False)

        template = _env.get_template("venezuela/topic.html.j2")
        html = template.render(
            h1=topic["h1"],
            short_title=topic["short_title"],
            eyebrow=topic["eyebrow"],
            lede=topic["lede"],
            sections=topic["sections"],
            cta_url=topic["cta_url"],
            cta_label=topic["cta_label"],
            seo=seo,
            jsonld=jsonld,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("venezuela topic page render failed for slug=%s: %s", slug, exc)
        abort(500)


@app.route("/travel")
@app.route("/travel/")
def travel_page():
    """
    Havana travel hub — embassies, hotels, restaurants, hospitals,
    transport, security firms, money/comms, and the pre-trip + safety
    checklists. Static curated dataset; the travel-advisory banner
    is overridden live from the State Dept scraper when available.
    """
    try:
        from src.data import travel as travel_data
        from src.models import (
            ExternalArticleEntry, SessionLocal, SourceType, init_db,
        )
        from src.page_renderer import _env, _base_url, _iso, settings as _s
        from datetime import date as _date, datetime as _dt
        import copy as _copy
        import json as _json

        advisory = _copy.deepcopy(travel_data.TRAVEL_ADVISORY_SUMMARY)

        try:
            init_db()
            db = SessionLocal()
            try:
                latest = (
                    db.query(ExternalArticleEntry)
                    .filter(ExternalArticleEntry.source == SourceType.TRAVEL_ADVISORY)
                    .order_by(ExternalArticleEntry.published_date.desc())
                    .first()
                )
            finally:
                db.close()
        except Exception as exc:
            logger.warning("travel advisory live fetch failed; using static fallback: %s", exc)
            latest = None

        if latest is not None:
            meta = latest.extra_metadata or {}
            level = meta.get("level")
            level_text = (meta.get("level_text") or "").strip()
            level_label_map = {
                1: "Exercise Normal Precautions",
                2: "Exercise Increased Caution",
                3: "Reconsider Travel",
                4: "Do Not Travel",
            }
            if isinstance(level, int) and 1 <= level <= 4:
                advisory["level"] = level
                advisory["label"] = level_text or level_label_map.get(level, advisory["label"])
                advisory["issued"] = latest.published_date.strftime("%B %-d, %Y")

        base = _base_url()
        canonical = f"{base}/travel"
        title = "Cuba Travel Restrictions, Prohibited Hotels & Safety Guide 2026"
        description = (
            "Check Cuba travel restrictions, prohibited hotels and "
            "accommodations, Havana safety, embassy contacts, money rules "
            "(USD cash, MLC, no US-issued cards), airport transport, SIM "
            "cards, D'Viajeros, and pre-trip compliance steps."
        )
        seo = {
            "title": title,
            "description": description,
            "keywords": (
                "travel to Cuba, Havana business travel, Havana hotels, "
                "Havana restaurants, Havana safety, embassies in Havana, "
                "Havana airport transfer, Cuba security firms, "
                "Havana hospitals, Cuba travel checklist, ETECSA SIM, "
                "MLC cards Cuba"
            ),
            "canonical": canonical,
            "site_name": _s.site_name,
            "site_url": base,
            "locale": _s.site_locale,
            "og_image": f"{base}/static/og-image.png?v=3",
            "og_type": "article",
            "published_iso": _iso(_dt.utcnow()),
            "modified_iso": _iso(_dt.utcnow()),
        }

        faq = [
            {
                "q": "Is it safe to travel to Havana right now?",
                "a": (
                    "Havana has a relatively low violent-crime rate by "
                    "Latin American capital standards. The dominant "
                    "risks for foreign visitors are petty crime "
                    "(pickpocketing, distraction theft, jinetero / "
                    "jinetera approaches in tourist zones), the rolling "
                    "electricity outages (\"apagones\") that affect "
                    "elevators, refrigeration, and ATM uptime, and "
                    "intermittent fuel and pharmacy shortages. The "
                    "current US State Department travel advisory level "
                    "is shown in the banner above and refreshed daily."
                ),
            },
            {
                "q": "Where do business travellers stay in Havana?",
                "a": (
                    "Default to Miramar (Playa municipality) for foreign-"
                    "investor meetings and joint-venture negotiations — "
                    "Meliá Habana, Memories Miramar, H10 Habana Panorama, "
                    "Comodoro. Vedado is the secondary option, closer to "
                    "ministries and cultural institutions: Hotel Nacional "
                    "de Cuba, Meliá Cohiba, Hotel Tryp Habana Libre. La "
                    "Habana Vieja is the leisure / colonial-architecture "
                    "district. Check the State Department Cuba Prohibited "
                    "Accommodations List (CPAL) before booking — many "
                    "Gaviota- and Cubanacán-operated properties are "
                    "blocked for US persons."
                ),
            },
            {
                "q": "How do I get from José Martí airport (HAV) to Havana safely?",
                "a": (
                    "Pre-arrange a transfer through your hotel before "
                    "flying — this is the single most important logistics "
                    "step. The official taxi queue at Terminal 3 (T3, "
                    "international) is reliable but the language barrier "
                    "creates friction and the cash-USD or EUR rate is "
                    "unpredictable. Avoid unmarked cars approaching you "
                    "in the parking lot. The drive to Miramar / Vedado / "
                    "Habana Vieja is 25–40 minutes depending on time of "
                    "day."
                ),
            },
            {
                "q": "Is there a US embassy in Havana?",
                "a": (
                    "Yes — the US Embassy in Havana resumed full "
                    "consular services in January 2023 after the 2017 "
                    "draw-down related to the 'Havana Syndrome' health "
                    "incidents. The embassy is at Calzada and L Streets, "
                    "Vedado. Emergency line for US citizens: +53 7839-"
                    "4100 (Havana switchboard) or 1-888-407-4747 toll-"
                    "free from the US/Canada. US travellers should "
                    "register with STEP (step.state.gov) before arrival."
                ),
            },
            {
                "q": "What currency should I bring to Cuba?",
                "a": (
                    "Bring USD or EUR cash in clean, undamaged "
                    "denominations. Cards issued by US banks DO NOT WORK "
                    "in Cuba — neither at ATMs nor at merchants — "
                    "because of the Cuban Assets Control Regulations "
                    "(31 CFR Part 515). A non-US-issued card (Canadian, "
                    "EU, UK) generally works at major hotels and CADECA "
                    "ATMs, but always carry enough hard cash for the "
                    "full trip. CUP (Cuban peso) is the day-to-day "
                    "currency for street-level purchases and private "
                    "MIPYMES; MLC (Moneda Libremente Convertible, the "
                    "state's USD-pegged digital wallet) is needed only "
                    "for state-run MLC stores carrying scarce imported "
                    "goods."
                ),
            },
            {
                "q": "Do I need a visa to enter Cuba?",
                "a": (
                    "Most foreign visitors enter on a Tarjeta del "
                    "Turista (Tourist Card), not a formal visa — sold "
                    "by the airline at check-in or by the Cuban "
                    "consulate (~€25–€30 for non-US passports, ~US$100 "
                    "pink US-version sold at US-gateway airports). US "
                    "travellers must additionally self-certify travel "
                    "under one of the OFAC 12 authorized categories at "
                    "31 CFR §515.560–.578 and keep a written record for "
                    "five years. Travel-medical insurance valid in Cuba "
                    "is mandatory and checked at the border for all "
                    "nationalities. Use our Cuba visa & Tourist Card "
                    "checker to confirm rules for your passport."
                ),
            },
            {
                "q": "What about the D'Viajeros customs and health form?",
                "a": (
                    "Every traveller arriving in Cuba must file the "
                    "D'Viajeros declaration online within 72 hours "
                    "before arrival (dviajeros.mitrans.gob.cu) — it "
                    "covers customs, health, and contact information. "
                    "The QR code generated is checked at immigration. "
                    "Filing on the plane Wi-Fi or after arrival is too "
                    "late."
                ),
            },
            {
                "q": "Which corporate security firms operate in Cuba?",
                "a": (
                    "Established international firms that cover Cuba "
                    "include Control Risks, International SOS, Crisis24 "
                    "(Garda World), and Pinkerton. They can arrange "
                    "vetted ground transport, pre-trip threat briefs, "
                    "and 24/7 medical evacuation cover (which is a real "
                    "consideration given the limited acute-care capacity "
                    "in the Cuban public system). OSAC (US State "
                    "Department) is also a free public-private "
                    "intelligence-sharing service for US-incorporated "
                    "companies."
                ),
            },
        ]

        graph = [
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
                    {"@type": "ListItem", "position": 2, "name": "Invest in Cuba", "item": f"{base}/invest-in-cuba"},
                    {"@type": "ListItem", "position": 3, "name": "Travel to Cuba", "item": canonical},
                ],
            },
            {
                "@type": "Article",
                "@id": f"{canonical}#article",
                "url": canonical,
                "headline": title,
                "description": description,
                "datePublished": seo["published_iso"],
                "dateModified": seo["modified_iso"],
                "author": {"@type": "Organization", "name": _s.site_name, "url": base + "/"},
                "publisher": {
                    "@type": "Organization",
                    "name": _s.site_name,
                    "url": base + "/",
                    "logo": {
                        "@type": "ImageObject",
                        "url": f"{base}/static/og-image.png?v=3",
                    },
                },
                "mainEntityOfPage": {"@type": "WebPage", "@id": canonical, "name": title},
            },
            {
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": q["q"],
                        "acceptedAnswer": {"@type": "Answer", "text": q["a"]},
                    }
                    for q in faq
                ],
            },
        ]
        jsonld = _json.dumps(
            {"@context": "https://schema.org", "@graph": graph},
            ensure_ascii=False,
        )

        template = _env.get_template("travel.html.j2")
        html = template.render(
            seo=seo,
            jsonld=jsonld,
            advisory=advisory,
            registration_programs=travel_data.EMBASSY_REGISTRATION_PROGRAMS,
            embassies=travel_data.EMBASSIES,
            hotels=travel_data.HOTELS,
            restaurants=travel_data.RESTAURANTS,
            medical=travel_data.MEDICAL_PROVIDERS,
            transport=travel_data.GROUND_TRANSPORT,
            security=travel_data.SECURITY_FIRMS,
            communications=travel_data.COMMUNICATIONS,
            money=travel_data.MONEY_AND_BANKING,
            pre_trip=travel_data.PRE_TRIP_CHECKLIST,
            safety=travel_data.SAFETY_CHECKLIST,
            emergency=travel_data.EMERGENCY_NUMBERS,
            updated_label=_date.today().strftime("%B %-d, %Y"),
            current_year=_date.today().year,
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("travel page render failed: %s", exc)
        abort(500)


@app.route("/travel/emergency-card")
@app.route("/travel/emergency-card/")
def travel_emergency_card():
    """
    Printable, two-page bilingual emergency card for visitors to Havana.
    Front: Spanish-first "show this to a stranger" sheet (hospitals, embassies,
    big phone numbers, fillable medical + hotel info).
    Back: English "for me, when I'm rattled" reference (decision tree, safe
    corridor, six rules, money cheat-sheet, Spanish phrases).

    Designed to print double-sided on A4/Letter and fold into a passport.
    """
    try:
        from src.data import travel as travel_data
        from src.page_renderer import _env, _base_url
        from datetime import date as _date

        country_es_map = {
            "United States": ("EE.UU.", "US"),
            "United Kingdom": ("Reino Unido", "UK"),
            "Canada": ("Canadá", "CA"),
            "Spain": ("España", "ES"),
            "France": ("Francia", "FR"),
            "Germany": ("Alemania", "DE"),
            "Italy": ("Italia", "IT"),
            "Netherlands": ("Países Bajos", "NL"),
            "Switzerland": ("Suiza", "CH"),
            "Brazil": ("Brasil", "BR"),
            "Mexico": ("México", "MX"),
            "Russia": ("Rusia", "RU"),
        }
        embassies_top = []
        for e in travel_data.EMBASSIES:
            country_es, short = country_es_map.get(
                e["country"], (e["country"], e["country"][:2].upper())
            )
            address = e.get("address", "")
            address_short = address.split(",")[0].strip() if address else ""
            embassies_top.append({
                "country_en": e["country"],
                "country_es": country_es,
                "short": short,
                "address": address,
                "address_short": address_short,
                "phone": e.get("phone", ""),
                "after_hours": e.get("after_hours", ""),
            })

        base = _base_url()
        seo = {
            "title": "Havana Emergency Card — Printable Bilingual Pocket Sheet",
            "description": (
                "Two-page printable pocket card for visitors to Havana. "
                "Spanish-first front shows hospitals, embassies and "
                "emergency numbers a taxi driver or stranger can act on; "
                "English back is a what-to-do reference if your phone is "
                "dead or stolen."
            ),
            "canonical": f"{base}/travel/emergency-card",
        }

        template = _env.get_template("emergency_card.html.j2")
        hotels_picker = []
        for h in travel_data.HOTELS:
            hotels_picker.append({
                "name": h.get("name", ""),
                "neighborhood": h.get("neighborhood", ""),
                "address": h.get("address", ""),
                "phone": h.get("phone", ""),
            })

        html = template.render(
            seo=seo,
            embassies_top=embassies_top,
            hotels_picker=hotels_picker,
            medical=travel_data.MEDICAL_PROVIDERS,
            emergency=travel_data.EMERGENCY_NUMBERS,
            updated_label=_date.today().strftime("%B %-d, %Y"),
        )
        return Response(html, mimetype="text/html")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("emergency card render failed: %s", exc)
        abort(500)


@app.route("/sectors/<slug>")
def sector_page(slug: str):
    """Evergreen sector landing page."""
    try:
        from src.models import BlogPost, LandingPage, SessionLocal, init_db
        from src.page_renderer import render_landing_page

        init_db()
        db = SessionLocal()
        try:
            page = (
                db.query(LandingPage)
                .filter(LandingPage.page_key == f"sector:{slug}")
                .first()
            )
            if not page:
                abort(404)

            normalized = slug.replace("-", "_")
            recent = (
                db.query(BlogPost)
                .filter(
                    (BlogPost.primary_sector == normalized)
                    | (BlogPost.primary_sector == slug)
                )
                .order_by(BlogPost.published_date.desc())
                .limit(8)
                .all()
            )
            html = render_landing_page(page, recent_briefings=recent)
            return Response(html, mimetype="text/html")
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("sector page render failed for slug=%s: %s", slug, exc)
        abort(500)


@app.route("/invest-in-cuba")
@app.route("/invest-in-cuba/")
def pillar_invest_in_cuba():
    """Evergreen pillar landing page."""
    try:
        from src.models import BlogPost, LandingPage, SessionLocal, init_db
        from src.page_renderer import render_landing_page

        init_db()
        db = SessionLocal()
        try:
            page = (
                db.query(LandingPage)
                .filter(LandingPage.page_key == "pillar:invest-in-cuba")
                .first()
            )
            if not page:
                abort(503, description="Pillar page not yet generated. Run `python scripts/generate_landing_pages.py --pillar`.")

            page.title = "Invest in Cuba: Sanctions, Sectors, Risks & Opportunities (2026 Guide)"
            page.summary = (
                "Complete guide to investing in Cuba — navigate OFAC sanctions, "
                "Helms-Burton Title III risks, sector opportunities (tourism, "
                "agriculture, telecom, energy, MIPYMEs), the CUP/MLC/USD currency "
                "stack, and due-diligence tools. Updated for 2026."
            )

            recent = (
                db.query(BlogPost)
                .order_by(BlogPost.published_date.desc())
                .limit(6)
                .all()
            )
            html = render_landing_page(page, recent_briefings=recent)
            return Response(html, mimetype="text/html")
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("pillar render failed: %s", exc)
        abort(500)


@app.route("/invest-in-venezuela")
@app.route("/invest-in-venezuela/")
def _legacy_invest_in_venezuela_redirect():
    return _legacy_redirect_to("/invest-in-cuba")


@app.route("/briefing")
@app.route("/briefing/")
@limiter.limit("6 per minute")
def briefing_index():
    """List all long-form blog posts, newest first."""
    try:
        from src.models import BlogPost, SessionLocal, init_db
        from src.page_renderer import render_blog_index

        init_db()
        db = SessionLocal()
        try:
            posts = (
                db.query(BlogPost)
                .order_by(BlogPost.published_date.desc(), BlogPost.id.desc())
                .limit(200)
                .all()
            )
            html = render_blog_index(posts)
            return Response(html, mimetype="text/html")
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("briefing index render failed: %s", exc)
        abort(500)


@app.route("/briefing/feed.xml")
def briefing_feed():
    """Atom feed of the most recent blog posts."""
    try:
        from src.models import BlogPost, SessionLocal, init_db
        from src.page_renderer import render_blog_feed_xml

        init_db()
        db = SessionLocal()
        try:
            posts = (
                db.query(BlogPost)
                .order_by(BlogPost.published_date.desc(), BlogPost.id.desc())
                .limit(50)
                .all()
            )
            xml = render_blog_feed_xml(posts)
            return Response(xml, mimetype="application/atom+xml")
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("briefing feed render failed: %s", exc)
        abort(500)


@app.route("/briefing/us-cuba-diplomatic-meeting-2026")
@app.route("/briefing/us-cuba-diplomatic-meeting-2026/")
def us_cuba_diplomatic_meeting_2026_redirect():
    """Legacy exact-query alias for the live diplomacy tracker."""
    return redirect(
        "/us-cuba-diplomatic-meeting-recent-developments-2026",
        code=301,
    )


_BRIEFING_POST_CACHE: dict[str, dict] = {}
_BRIEFING_POST_CACHE_TTL_SECONDS = 600
_BRIEFING_POST_CACHE_MAX_ENTRIES = 200


def _briefing_cache_get(slug: str) -> bytes | None:
    cached = _BRIEFING_POST_CACHE.get(slug)
    if not cached:
        return None
    if time.time() - cached.get("cached_at", 0.0) > _BRIEFING_POST_CACHE_TTL_SECONDS:
        return None
    return cached.get("body")


def _briefing_cache_put(slug: str, body: bytes) -> None:
    if len(_BRIEFING_POST_CACHE) >= _BRIEFING_POST_CACHE_MAX_ENTRIES:
        ordered = sorted(
            _BRIEFING_POST_CACHE.items(),
            key=lambda kv: kv[1].get("cached_at", 0.0),
        )
        for evict_slug, _ in ordered[: _BRIEFING_POST_CACHE_MAX_ENTRIES // 4]:
            _BRIEFING_POST_CACHE.pop(evict_slug, None)
    _BRIEFING_POST_CACHE[slug] = {"body": body, "cached_at": time.time()}


@app.route("/briefing/<slug>")
@limiter.limit("6 per minute")
def briefing_post(slug: str):
    """Render a single blog post by slug."""
    cached_body = _briefing_cache_get(slug)
    if cached_body is not None:
        resp = Response(cached_body, mimetype="text/html")
        resp.headers["X-Page-Cache"] = "HIT"
        return resp

    try:
        from src.models import BlogPost, SessionLocal, init_db
        from src.page_renderer import render_blog_post

        init_db()
        db = SessionLocal()
        try:
            post = db.query(BlogPost).filter(BlogPost.slug == slug).first()
            if not post:
                abort(404)

            related_q = db.query(BlogPost).filter(BlogPost.id != post.id)
            if post.primary_sector:
                related_q = related_q.filter(BlogPost.primary_sector == post.primary_sector)
            related = (
                related_q.order_by(BlogPost.published_date.desc()).limit(5).all()
            )
            if len(related) < 3:
                fill = (
                    db.query(BlogPost)
                    .filter(BlogPost.id != post.id)
                    .filter(~BlogPost.id.in_([r.id for r in related]))
                    .order_by(BlogPost.published_date.desc())
                    .limit(5 - len(related))
                    .all()
                )
                related.extend(fill)

            html = render_blog_post(post, related=related)
            body = html.encode("utf-8") if isinstance(html, str) else html
            _briefing_cache_put(slug, body)
            resp = Response(body, mimetype="text/html")
            resp.headers["X-Page-Cache"] = "MISS"
            return resp
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("briefing post render failed for slug=%s: %s", slug, exc)
        abort(500)


@app.route("/robots.txt")
def robots_txt():
    """
    robots.txt — allow indexing of the public report and tools, point at
    the dynamic sitemap, and explicitly disallow API and health endpoints.
    """
    base = settings.site_url.rstrip("/")
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        "Disallow: /health\n"
        "Crawl-delay: 10\n"
        f"Sitemap: {base}/sitemap.xml\n"
        f"Sitemap: {base}/sitemap-core.xml\n"
        f"Sitemap: {base}/sitemap-briefings-recent.xml\n"
        f"Sitemap: {base}/sitemap-companies-priority.xml\n"
        f"Sitemap: {base}/sitemap-sdn-priority.xml\n"
        f"Sitemap: {base}/sitemap-cpal.xml\n"
        f"Sitemap: {base}/sitemap-crl.xml\n"
        f"Sitemap: {base}/news-sitemap.xml\n"
        f"Sitemap: {base}/curated-sitemap.xml\n"
    )
    return Response(body, mimetype="text/plain")


def _sitemap_today_iso() -> str:
    from datetime import datetime as _datetime, timezone as _tz
    return _datetime.utcnow().replace(tzinfo=_tz.utc).date().isoformat()


def _sitemap_route_exists(path: str) -> bool:
    """Return True if *path* matches a registered Flask route.

    Used to guard DB-sourced sitemap entries (BlogPost, LandingPage,
    sector slugs) against orphaned records whose URL pattern no longer
    exists in the routing table.  Does NOT catch content-less wildcard
    matches — those are caught by the nightly spot-check.
    """
    try:
        adapter = app.url_map.bind("")
        adapter.match(path)
        return True
    except Exception:
        return False


def _emit_urlset(urls: list[dict]) -> Response:
    from xml.sax.saxutils import escape as _xml_escape
    parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    parts.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for u in urls:
        parts.append("<url>")
        parts.append(f"<loc>{_xml_escape(u['loc'])}</loc>")
        parts.append(f"<lastmod>{u['lastmod']}</lastmod>")
        parts.append(f"<changefreq>{u['changefreq']}</changefreq>")
        parts.append(f"<priority>{u['priority']}</priority>")
        parts.append("</url>")
    parts.append("</urlset>")
    resp = Response("".join(parts), mimetype="application/xml")
    resp.headers["Cache-Control"] = "public, max-age=1800"
    return resp


def _people_sitemap_urls() -> list[dict]:
    """Pillar + every cohort hub + every per-figure profile, walked
    from the registry so adding a person to src/data/people.py auto-
    adds them to the sitemap (no duplicate hand-curated list)."""
    from src.data.people import (
        all_people, COHORT_ORDER, VERIFIED_AS_OF, cohort_url,
    )
    base = settings.site_url.rstrip("/")
    out: list[dict] = [
        {"loc": f"{base}/people", "lastmod": VERIFIED_AS_OF, "changefreq": "weekly", "priority": "0.85"},
    ]
    for cohort in COHORT_ORDER:
        out.append({
            "loc": f"{base}{cohort_url(cohort)}",
            "lastmod": VERIFIED_AS_OF,
            "changefreq": "weekly",
            "priority": "0.8",
        })
    for p in all_people():
        out.append({
            "loc": f"{base}{p.url_path}",
            "lastmod": VERIFIED_AS_OF,
            "changefreq": "monthly",
            "priority": "0.75",
        })
    return out


def _core_static_urls() -> list[dict]:
    base = settings.site_url.rstrip("/")
    today_iso = _sitemap_today_iso()
    return [
        {"loc": f"{base}/", "lastmod": today_iso, "changefreq": "daily", "priority": "1.0"},
        {"loc": f"{base}/invest-in-cuba", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.9"},
        {"loc": f"{base}/sanctions-tracker", "lastmod": today_iso, "changefreq": "daily", "priority": "0.9"},
        {"loc": f"{base}/sanctions/by-sector", "lastmod": today_iso, "changefreq": "daily", "priority": "0.9"},
        {"loc": f"{base}/sanctions/sector/military", "lastmod": today_iso, "changefreq": "daily", "priority": "0.85"},
        {"loc": f"{base}/sanctions/sector/economic", "lastmod": today_iso, "changefreq": "daily", "priority": "0.85"},
        {"loc": f"{base}/sanctions/sector/diplomatic", "lastmod": today_iso, "changefreq": "daily", "priority": "0.85"},
        {"loc": f"{base}/sanctions/sector/governance", "lastmod": today_iso, "changefreq": "daily", "priority": "0.85"},
        {"loc": f"{base}/sanctions/individuals", "lastmod": today_iso, "changefreq": "daily", "priority": "0.85"},
        {"loc": f"{base}/sanctions/entities", "lastmod": today_iso, "changefreq": "daily", "priority": "0.85"},
        {"loc": f"{base}/sanctions/vessels", "lastmod": today_iso, "changefreq": "daily", "priority": "0.8"},
        {"loc": f"{base}/sanctions/aircraft", "lastmod": today_iso, "changefreq": "daily", "priority": "0.8"},
        {"loc": f"{base}/calendar", "lastmod": today_iso, "changefreq": "daily", "priority": "0.7"},
        {"loc": f"{base}/travel", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.8"},
        {"loc": f"{base}/travel/emergency-card", "lastmod": today_iso, "changefreq": "monthly", "priority": "0.7"},
        {"loc": f"{base}/export-to-cuba", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.9"},
        {"loc": f"{base}/sources", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.6"},
        {"loc": f"{base}/briefing", "lastmod": today_iso, "changefreq": "daily", "priority": "0.9"},
        {"loc": f"{base}/us-cuba-diplomatic-meeting-recent-developments-2026", "lastmod": today_iso, "changefreq": "daily", "priority": "0.85"},
        {"loc": f"{base}/tools", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.8"},
        {"loc": f"{base}/explainers", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.8"},
        {"loc": f"{base}/tools/eltoque-trmi-rate", "lastmod": today_iso, "changefreq": "daily", "priority": "0.7"},
        {"loc": f"{base}/tools/ofac-cuba-sanctions-checker", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.7"},
        {"loc": f"{base}/tools/cuba-restricted-list-checker", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.75"},
        {"loc": f"{base}/tools/cuba-prohibited-hotels-checker", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.75"},
        {"loc": f"{base}/tools/can-i-travel-to-cuba", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.85"},
        {"loc": f"{base}/tools/public-company-cuba-exposure-check", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.75"},
        {"loc": f"{base}/tools/sec-edgar-cuba-impairment-search", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.75"},
        {"loc": f"{base}/companies", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.85"},
        {"loc": f"{base}/tools/ofac-cuba-general-licenses", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.7"},
        {"loc": f"{base}/tools/cuba-trade-leads-for-us-companies", "lastmod": today_iso, "changefreq": "daily", "priority": "0.85"},
        {"loc": f"{base}/tools/cuba-export-opportunity-finder", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.85"},
        {"loc": f"{base}/tools/cuba-hs-code-opportunity-finder", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.8"},
        {"loc": f"{base}/tools/cuba-export-controls-sanctions-process-map", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.85"},
        {"loc": f"{base}/tools/can-my-us-company-export-to-cuba", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.85"},
        {"loc": f"{base}/tools/cuba-country-contacts-directory", "lastmod": today_iso, "changefreq": "monthly", "priority": "0.75"},
        {"loc": f"{base}/tools/us-company-cuba-market-entry-checklist", "lastmod": today_iso, "changefreq": "monthly", "priority": "0.8"},
        {"loc": f"{base}/tools/cuba-agricultural-medical-export-checker", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.8"},
        {"loc": f"{base}/tools/cuba-telecom-internet-export-checker", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.8"},
        {"loc": f"{base}/tools/cuba-mipyme-export-support-checklist", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.8"},
        {"loc": f"{base}/tools/cuba-trade-events-matchmaking-calendar", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.75"},
        {"loc": f"{base}/tools/cuba-trade-barriers-tracker", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.75"},
        {"loc": f"{base}/tools/cuba-export-compliance-checklist", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.85"},
        {"loc": f"{base}/tools/havana-safety-by-neighborhood", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.7"},
        {"loc": f"{base}/tools/cuba-investment-roi-calculator", "lastmod": today_iso, "changefreq": "monthly", "priority": "0.6"},
        {"loc": f"{base}/tools/cuba-visa-requirements", "lastmod": today_iso, "changefreq": "monthly", "priority": "0.7"},
        {"loc": f"{base}/tools/helms-burton-act-explained", "lastmod": today_iso, "changefreq": "monthly", "priority": "0.8"},
        {"loc": f"{base}/tools/cuba-embargo-explained", "lastmod": today_iso, "changefreq": "monthly", "priority": "0.8"},
        {"loc": f"{base}/tools/cuba-travel-advisory", "lastmod": today_iso, "changefreq": "monthly", "priority": "0.75"},
        {"loc": f"{base}/tools/what-is-ofac", "lastmod": today_iso, "changefreq": "monthly", "priority": "0.75"},
        {"loc": f"{base}/venezuela/transport", "lastmod": today_iso, "changefreq": "monthly", "priority": "0.5"},
        {"loc": f"{base}/venezuela/caracas-travel-advisory", "lastmod": today_iso, "changefreq": "monthly", "priority": "0.5"},
    ]


# ──────────────────────────────────────────────────────────────────────
# Sitemap split — see docs/scraper_research.md and the GSC indexation
# audit. We split one giant sitemap into a sitemap-index pointing at
# focused child sitemaps so we can submit only the high-value buckets
# to Google and let the long-tail archive sit in robots discovery.
#
# Submitted to GSC:  sitemap-core, sitemap-briefings-recent,
#                    sitemap-companies-priority, sitemap-sdn-priority,
#                    sitemap-cpal, sitemap-crl
# Listed in index but NOT submitted:  sitemap-archive
# ──────────────────────────────────────────────────────────────────────

_PRIORITY_BRIEFING_DAYS = 90
_PRIORITY_BRIEFING_LIMIT = 200
_PRIORITY_SDN_LIMIT = 100


@app.route("/sitemap.xml")
def sitemap_xml():
    """Sitemap index — points Google at the child sitemaps."""
    try:
        from xml.sax.saxutils import escape as _xml_escape

        base = settings.site_url.rstrip("/")
        today_iso = _sitemap_today_iso()
        children = [
            f"{base}/sitemap-core.xml",
            f"{base}/sitemap-briefings-recent.xml",
            f"{base}/sitemap-companies-priority.xml",
            f"{base}/sitemap-sdn-priority.xml",
            f"{base}/sitemap-cpal.xml",
            f"{base}/sitemap-crl.xml",
            f"{base}/sitemap-archive.xml",
        ]
        parts = ['<?xml version="1.0" encoding="UTF-8"?>']
        parts.append('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
        for url in children:
            parts.append("<sitemap>")
            parts.append(f"<loc>{_xml_escape(url)}</loc>")
            parts.append(f"<lastmod>{today_iso}</lastmod>")
            parts.append("</sitemap>")
        parts.append("</sitemapindex>")
        resp = Response("".join(parts), mimetype="application/xml")
        resp.headers["Cache-Control"] = "public, max-age=1800"
        return resp
    except Exception as exc:
        logger.exception("sitemap.xml generation failed: %s", exc)
        abort(500)


@app.route("/sitemap-core.xml")
def sitemap_core_xml():
    """Hand-curated home, hubs, tools, sector roots. Highest priority.
    Also walks the /people registry so every per-figure profile is in
    the submitted sitemap from the moment it ships."""
    try:
        return _emit_urlset(_core_static_urls() + _people_sitemap_urls())
    except Exception as exc:
        logger.exception("sitemap-core.xml generation failed: %s", exc)
        abort(500)


@app.route("/sitemap-briefings-recent.xml")
def sitemap_briefings_recent_xml():
    """BlogPost briefings published in the last 90 days, capped."""
    from datetime import date as _date, timedelta as _td
    base = settings.site_url.rstrip("/")
    cutoff = _date.today() - _td(days=_PRIORITY_BRIEFING_DAYS)
    urls: list[dict] = []
    try:
        from src.models import SessionLocal, init_db, BlogPost
        init_db()
        db = SessionLocal()
        try:
            posts = (
                db.query(BlogPost)
                .filter(BlogPost.published_date >= cutoff)
                .order_by(BlogPost.published_date.desc())
                .limit(_PRIORITY_BRIEFING_LIMIT)
                .all()
            )
            for p in posts:
                _path = f"/briefing/{p.slug}"
                if not _sitemap_route_exists(_path):
                    logger.warning("sitemap: %s has no matching route, skipping", _path)
                    continue
                lastmod_dt = p.updated_at or p.created_at
                lastmod = lastmod_dt.strftime("%Y-%m-%d") if lastmod_dt else p.published_date.isoformat()
                urls.append({
                    "loc": f"{base}{_path}",
                    "lastmod": lastmod,
                    "changefreq": "weekly",
                    "priority": "0.8",
                })
        finally:
            db.close()
    except Exception as exc:
        logger.warning("sitemap-briefings-recent failed: %s", exc)
    return _emit_urlset(urls)


@app.route("/sitemap-companies-priority.xml")
def sitemap_companies_priority_xml():
    """S&P 500 company pages with curated Cuba exposure or SDN matches.

    Companies with no curated entry and zero SDN matches are thin and
    go to the archive sitemap — Google has been refusing to crawl them.
    """
    base = settings.site_url.rstrip("/")
    today_iso = _sitemap_today_iso()
    urls: list[dict] = []
    try:
        from src.data.company_exposure import list_company_index_rows
        for row in list_company_index_rows():
            if not (row.has_curated or row.sdn_match_count > 0):
                continue
            urls.append({
                "loc": f"{base}/companies/{row.slug}/cuba-exposure",
                "lastmod": today_iso,
                "changefreq": "weekly",
                "priority": "0.7",
            })
    except Exception as exc:
        logger.warning("sitemap-companies-priority failed: %s", exc)
    return _emit_urlset(urls)


@app.route("/sitemap-sdn-priority.xml")
def sitemap_sdn_priority_xml():
    """SDN profile pages — entities only, capped.

    Individuals, vessels, and aircraft profiles go to the archive
    sitemap. Entity searches (`"trober s.a." sanctions`,
    `"hotel san alejandro" sanctions`) are what GSC shows actually
    drives impressions to this site.
    """
    base = settings.site_url.rstrip("/")
    today_iso = _sitemap_today_iso()
    urls: list[dict] = []
    try:
        from src.data.sdn_profiles import list_profiles
        for p in list_profiles("entities")[:_PRIORITY_SDN_LIMIT]:
            urls.append({
                "loc": f"{base}{p.url_path}",
                "lastmod": p.designation_date or today_iso,
                "changefreq": "monthly",
                "priority": "0.7",
            })
    except Exception as exc:
        logger.warning("sitemap-sdn-priority failed: %s", exc)
    return _emit_urlset(urls)


@app.route("/sitemap-cpal.xml")
def sitemap_cpal_xml():
    """Per-property pages from the Cuba Prohibited Accommodations List.

    Each entry is a strong-intent landing page for `[hotel name] sanctions`
    queries that GSC shows hitting the checker hub with 0% CTR.
    """
    base = settings.site_url.rstrip("/")
    today_iso = _sitemap_today_iso()
    urls: list[dict] = []
    try:
        for row in list_cpal_profiles():
            urls.append({
                "loc": f"{base}{row['url_path']}",
                "lastmod": today_iso,
                "changefreq": "monthly",
                "priority": "0.7",
            })
    except Exception as exc:
        logger.warning("sitemap-cpal failed: %s", exc)
    return _emit_urlset(urls)


@app.route("/sitemap-crl.xml")
def sitemap_crl_xml():
    """Per-entity pages from the Cuba Restricted List."""
    base = settings.site_url.rstrip("/")
    today_iso = _sitemap_today_iso()
    urls: list[dict] = []
    try:
        for row in list_crl_profiles():
            urls.append({
                "loc": f"{base}{row['url_path']}",
                "lastmod": today_iso,
                "changefreq": "weekly",
                "priority": "0.65",
            })
    except Exception as exc:
        logger.warning("sitemap-crl failed: %s", exc)
    return _emit_urlset(urls)


@app.route("/sitemap-archive.xml")
def sitemap_archive_xml():
    """Long-tail: older briefings, non-priority companies and SDN
    profiles, landing pages, discovered sector pages.

    Listed in the sitemap index so Google can find these via robots.txt
    discovery, but NOT submitted directly in Search Console — we want
    Google to spend crawl budget on the priority sitemaps first.
    """
    from datetime import date as _date, timedelta as _td
    base = settings.site_url.rstrip("/")
    today_iso = _sitemap_today_iso()
    urls: list[dict] = []
    seen: set[str] = set()

    def _add(loc: str, lastmod: str, changefreq: str, priority: str) -> None:
        if loc in seen:
            return
        seen.add(loc)
        urls.append({"loc": loc, "lastmod": lastmod, "changefreq": changefreq, "priority": priority})

    try:
        from src.models import (
            SessionLocal,
            init_db,
            BlogPost,
            ExternalArticleEntry,
            AssemblyNewsEntry,
            GazetteStatus,
            LandingPage,
        )

        init_db()
        db = SessionLocal()
        try:
            cutoff = _date.today() - _td(days=_PRIORITY_BRIEFING_DAYS)

            older_posts = (
                db.query(BlogPost)
                .filter(BlogPost.published_date < cutoff)
                .order_by(BlogPost.published_date.desc())
                .limit(500)
                .all()
            )
            for p in older_posts:
                _path = f"/briefing/{p.slug}"
                if not _sitemap_route_exists(_path):
                    logger.warning("sitemap: %s has no matching route, skipping", _path)
                    continue
                lastmod_dt = p.updated_at or p.created_at
                lastmod = lastmod_dt.strftime("%Y-%m-%d") if lastmod_dt else p.published_date.isoformat()
                _add(f"{base}{_path}", lastmod, "monthly", "0.4")

            for lp in db.query(LandingPage).all():
                if not _sitemap_route_exists(lp.canonical_path):
                    logger.warning("sitemap: %s has no matching route, skipping", lp.canonical_path)
                    continue
                lastmod_dt = lp.last_generated_at or lp.updated_at or lp.created_at
                lastmod = lastmod_dt.strftime("%Y-%m-%d") if lastmod_dt else today_iso
                _add(f"{base}{lp.canonical_path}", lastmod, "monthly", "0.5")

            sector_cutoff = _date.today() - _td(days=settings.report_lookback_days)
            ext = (
                db.query(ExternalArticleEntry)
                .filter(ExternalArticleEntry.status == GazetteStatus.ANALYZED)
                .filter(ExternalArticleEntry.published_date >= sector_cutoff)
                .order_by(ExternalArticleEntry.published_date.desc())
                .limit(500)
                .all()
            )
            asm = (
                db.query(AssemblyNewsEntry)
                .filter(AssemblyNewsEntry.status == GazetteStatus.ANALYZED)
                .filter(AssemblyNewsEntry.published_date >= sector_cutoff)
                .order_by(AssemblyNewsEntry.published_date.desc())
                .limit(500)
                .all()
            )
            import re as _re
            sector_set: set[str] = set()
            min_score = settings.analysis_min_relevance
            for item in list(ext) + list(asm):
                analysis = item.analysis_json or {}
                if analysis.get("relevance_score", 0) < min_score:
                    continue
                for sector in analysis.get("sectors", []) or []:
                    slug = _re.sub(r"[^a-z0-9]+", "-", str(sector).lower()).strip("-")
                    if slug:
                        sector_set.add(slug)
            # Only include sectors that have a LandingPage record — the
            # /sectors/<slug> route 404s without one.
            existing_sector_keys = {
                lp.page_key
                for lp in db.query(LandingPage.page_key)
                .filter(LandingPage.page_key.like("sector:%"))
                .all()
            }
            for slug in sorted(sector_set):
                if f"sector:{slug}" not in existing_sector_keys:
                    continue
                _path = f"/sectors/{slug}"
                _add(f"{base}{_path}", today_iso, "weekly", "0.5")
        finally:
            db.close()
    except Exception as exc:
        logger.warning("sitemap-archive (db section) failed: %s", exc)

    try:
        from src.data.sdn_profiles import list_profiles, ENTITY_BUCKETS
        priority_entity_paths = {
            f"{base}{p.url_path}"
            for p in list_profiles("entities")[:_PRIORITY_SDN_LIMIT]
        }
        for bucket in ENTITY_BUCKETS:
            for p in list_profiles(bucket):
                loc = f"{base}{p.url_path}"
                if loc in priority_entity_paths:
                    continue
                _add(loc, p.designation_date or today_iso, "monthly", "0.4")
    except Exception as exc:
        logger.warning("sitemap-archive (sdn section) failed: %s", exc)

    try:
        from src.data.company_exposure import list_company_index_rows
        for row in list_company_index_rows():
            if row.has_curated or row.sdn_match_count > 0:
                continue
            _add(f"{base}/companies/{row.slug}/cuba-exposure", today_iso, "monthly", "0.3")
    except Exception as exc:
        logger.warning("sitemap-archive (company section) failed: %s", exc)

    return _emit_urlset(urls)


@app.route("/tearsheet/latest.pdf")
def tearsheet_latest():
    """
    Stable URL for today's Daily Cuban Insights Investor Tearsheet PDF.
    302-redirects to the Supabase Storage public URL where the cron
    just-in-time uploads it. Cached briefly so a single Supabase
    request fans out across many website visits.
    """
    from src.distribution.tearsheet import latest_tearsheet_public_url

    url = latest_tearsheet_public_url()
    if not url:
        abort(404)
    resp = redirect(url, code=302)
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


@app.route("/tearsheet/<date_str>.pdf")
def tearsheet_dated(date_str: str):
    """Date-stamped permalink for a specific day's tearsheet (YYYY-MM-DD)."""
    from datetime import date as _date

    from src.distribution.tearsheet import tearsheet_url_for_date

    try:
        d = _date.fromisoformat(date_str)
    except ValueError:
        abort(404)
    url = tearsheet_url_for_date(d)
    if not url:
        abort(404)
    resp = redirect(url, code=302)
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp


@app.route("/og/briefing/<slug>.png")
def briefing_og_image(slug: str):
    """Serve the per-briefing Open Graph card.

    Each BlogPost has its own 1200x630 PNG (rendered at creation time
    by src/og_image.py and persisted on `BlogPost.og_image_bytes`) so
    every share preview shows the briefing's actual headline rather
    than one generic site-wide tile.

    Cached aggressively — these never change once written. If a post
    is missing bytes (e.g. an older row not yet backfilled), we fall
    back to the static homepage OG image so previews still render.
    """
    try:
        from src.models import BlogPost, SessionLocal, init_db

        init_db()
        db = SessionLocal()
        try:
            row = (
                db.query(BlogPost.og_image_bytes)
                .filter(BlogPost.slug == slug)
                .first()
            )
            if row is None:
                abort(404)
            png_bytes = row[0]
            if not png_bytes:
                fallback = f"{settings.site_url.rstrip('/')}/static/og-image.png?v=3"
                resp = redirect(fallback, code=302)
                resp.headers["Cache-Control"] = "public, max-age=300"
                return resp

            resp = Response(png_bytes, mimetype="image/png")
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return resp
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("og card serve failed for slug=%s: %s", slug, exc)
        abort(500)


@app.route("/<key>.txt")
def indexnow_key_file(key: str):
    """
    Serve the IndexNow ownership-proof key file at the domain root.
    The IndexNow protocol requires that GET https://example.com/<KEY>.txt
    return the literal key as plain text — that's how Bing / Yandex /
    Seznam / etc. verify we own the host before accepting our pushed URLs.

    We only serve our one known key; any other /<thing>.txt 404s.
    """
    from src.config import settings

    configured = (settings.indexnow_key or "").strip()
    if configured and key == configured:
        return Response(configured, mimetype="text/plain")
    abort(404)


@app.route("/news-sitemap.xml")
def news_sitemap_xml():
    """
    Google News-spec sitemap. Per Google's documentation
    (https://developers.google.com/search/docs/crawling-indexing/sitemaps/news-sitemap)
    this must:

      - include only URLs published within the last 48 hours
      - cap at 1,000 URLs
      - use the news: XML namespace
      - emit <news:publication>, <news:publication_date>, <news:title>
        for every entry, plus optional <news:keywords>

    We feed the news-eligible BlogPost rows. The standard /sitemap.xml
    keeps the full backlog for general web search; this one is the fast,
    Top-Stories-eligible feed Google News auto-discovery polls.

    Falls back to an empty (but well-formed) news sitemap if the DB is
    unavailable — Google prefers an empty sitemap to a 500.
    """
    from datetime import datetime as _datetime, timezone as _tz, timedelta as _td
    from xml.sax.saxutils import escape as _xml_escape

    base = settings.site_url.rstrip("/")
    publication_name = settings.site_name
    publication_lang = (settings.site_locale or "en_US").split("_", 1)[0] or "en"

    cutoff = _datetime.now(_tz.utc) - _td(hours=48)

    items: list[dict] = []
    try:
        from src.models import SessionLocal, init_db, BlogPost

        init_db()
        db = SessionLocal()
        try:
            recent_posts = (
                db.query(BlogPost)
                .order_by(BlogPost.published_date.desc(), BlogPost.id.desc())
                .limit(1000)
                .all()
            )
            for p in recent_posts:
                pub_dt = p.created_at or p.updated_at
                if pub_dt is None:
                    pub_dt = _datetime.combine(
                        p.published_date, _datetime.min.time()
                    )
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=_tz.utc)
                if pub_dt < cutoff:
                    continue

                kws = p.keywords_json or []
                if isinstance(kws, str):
                    kws = [k.strip() for k in kws.split(",") if k.strip()]
                kws_str = ", ".join(kws[:10]) if kws else ""

                items.append({
                    "loc": f"{base}/briefing/{p.slug}",
                    "publication_date": pub_dt.isoformat(),
                    "title": (p.title or "")[:300],
                    "keywords": kws_str,
                })
        finally:
            db.close()
    except Exception as exc:
        logger.warning("news-sitemap dynamic generation failed, returning empty: %s", exc)

    parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    parts.append(
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">'
    )
    for it in items:
        parts.append("<url>")
        parts.append(f"<loc>{_xml_escape(it['loc'])}</loc>")
        parts.append("<news:news>")
        parts.append("<news:publication>")
        parts.append(f"<news:name>{_xml_escape(publication_name)}</news:name>")
        parts.append(f"<news:language>{_xml_escape(publication_lang)}</news:language>")
        parts.append("</news:publication>")
        parts.append(f"<news:publication_date>{_xml_escape(it['publication_date'])}</news:publication_date>")
        parts.append(f"<news:title>{_xml_escape(it['title'])}</news:title>")
        if it["keywords"]:
            parts.append(f"<news:keywords>{_xml_escape(it['keywords'])}</news:keywords>")
        parts.append("</news:news>")
        parts.append("</url>")
    parts.append("</urlset>")
    resp = Response("".join(parts), mimetype="application/xml")
    resp.headers["Cache-Control"] = "public, max-age=900"
    return resp


@app.route("/curated-sitemap.xml")
def curated_sitemap():
    """
    Hand-curated sitemap of the ~100 highest-priority public URLs
    (pillars, tools, key hubs). Generated by
    `scripts/generate_curated_sitemap.py` and committed to `seo/`.
    Lets Search Console and crawlers treat this as a focused seed list
    alongside the full dynamic `/sitemap.xml`.
    """
    p = Path(__file__).resolve().parent / "seo" / "curated-sitemap.xml"
    if not p.is_file():
        abort(404)
    resp = Response(
        p.read_text(encoding="utf-8"), mimetype="application/xml; charset=utf-8"
    )
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@app.route("/health")
def health():
    report = OUTPUT_DIR / "report.html"
    return {
        "status": "ok",
        "report_exists_local": report.exists(),
        "supabase_storage_read_enabled": supabase_storage_read_enabled(),
        "supabase_storage_write_enabled": supabase_storage_enabled(),
        "report_cached": _REPORT_CACHE["html"] is not None,
    }, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=settings.server_port, debug=True)
