"""
Bluesky (atproto) client.

Posts new briefings to a Bluesky account using the official atproto
HTTP API. We deliberately avoid the `atproto` Python SDK to keep the
dependency surface small — Bluesky's posting API is just two HTTP calls
(createSession + createRecord) and the SDK pulls in pydantic v2 +
multiple transitive packages we don't need elsewhere.

Authentication: handle + app password. The app password is generated in
Bluesky Settings → Privacy and Security → App Passwords and is
revocable independently of the account password. Never use the actual
account password here — Bluesky explicitly warns against it for
automation.

Rate limits: Bluesky publishes per-account write limits of ~5,000
points/hour where a createRecord costs 3 points. We're nowhere near
that. The runner caps us at bluesky_max_per_run (default 5) per cron.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import httpx

from src.config import settings


logger = logging.getLogger(__name__)


_BASE = "https://bsky.social/xrpc"
_CREATE_SESSION = f"{_BASE}/com.atproto.server.createSession"
_CREATE_RECORD = f"{_BASE}/com.atproto.repo.createRecord"

# Bluesky post text limit (graphemes — for ASCII this == characters).
# We leave a small safety margin because byte/grapheme counting differs
# slightly from char counting for emoji and accented characters.
_MAX_POST_CHARS = 290


@dataclass
class BlueskyResult:
    success: bool
    status_code: int | None
    response_snippet: str
    post_uri: str | None = None  # at://did:plc:.../app.bsky.feed.post/<rkey>
    post_url: str | None = None  # https://bsky.app/profile/<handle>/post/<rkey>


class BlueskyClient:
    """Thin atproto client. One instance per cron run is fine — sessions
    are valid for ~2 hours; we don't bother refreshing because each
    cron run finishes in seconds."""

    def __init__(self, handle: str, app_password: str):
        self.handle = handle
        self.app_password = app_password
        self._access_jwt: str | None = None
        self._did: str | None = None

    def _login(self) -> bool:
        try:
            resp = httpx.post(
                _CREATE_SESSION,
                json={"identifier": self.handle, "password": self.app_password},
                timeout=15,
            )
        except Exception as exc:
            logger.error("bluesky: login HTTP error: %s", exc)
            return False

        if resp.status_code != 200:
            logger.error("bluesky: login failed %d -- %s", resp.status_code, (resp.text or "")[:300])
            return False

        data = resp.json()
        self._access_jwt = data.get("accessJwt")
        self._did = data.get("did")
        if not self._access_jwt or not self._did:
            logger.error("bluesky: login response missing accessJwt/did: %s", data)
            return False

        logger.info("bluesky: logged in as %s (did=%s)", self.handle, self._did)
        return True

    def ensure_session(self) -> bool:
        if self._access_jwt and self._did:
            return True
        return self._login()

    def post(self, text: str, link_url: str | None = None) -> BlueskyResult:
        """Create a single post. If link_url is provided, builds a facet
        so the URL is rendered as a clickable link inline (Bluesky
        doesn't auto-linkify; you have to declare facets explicitly)."""
        if not self.ensure_session():
            return BlueskyResult(success=False, status_code=None, response_snippet="login failed")

        text = (text or "").strip()
        if not text:
            return BlueskyResult(success=False, status_code=None, response_snippet="empty text")

        record: dict = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "langs": ["en"],
        }

        facets = _build_facets(text, link_url)
        if facets:
            record["facets"] = facets

        try:
            resp = httpx.post(
                _CREATE_RECORD,
                headers={"Authorization": f"Bearer {self._access_jwt}"},
                json={
                    "repo": self._did,
                    "collection": "app.bsky.feed.post",
                    "record": record,
                },
                timeout=15,
            )
        except Exception as exc:
            logger.error("bluesky: createRecord HTTP error: %s", exc)
            return BlueskyResult(success=False, status_code=None, response_snippet=f"http error: {exc}"[:500])

        body = resp.text or ""
        snippet = body[:500]

        if resp.status_code == 200:
            data = resp.json()
            uri = data.get("uri")  # at://did:plc:xxx/app.bsky.feed.post/<rkey>
            rkey = uri.rsplit("/", 1)[-1] if uri else None
            post_url = f"https://bsky.app/profile/{self.handle}/post/{rkey}" if rkey else None
            logger.info("bluesky: posted -> %s", post_url or uri)
            return BlueskyResult(
                success=True,
                status_code=200,
                response_snippet=snippet,
                post_uri=uri,
                post_url=post_url,
            )

        logger.warning("bluesky: %d -- %s", resp.status_code, snippet)
        return BlueskyResult(success=False, status_code=resp.status_code, response_snippet=snippet)


# ---------------------------------------------------------------------------
# Post composition
# ---------------------------------------------------------------------------


def compose_post(*, title: str, summary: str | None, url: str, keywords: Iterable[str] | None) -> str:
    """Compose a Bluesky post body from a briefing.

    Layout:
        <title>
        <one-line hook from summary, if room>
        <url>
        <hashtags from keywords, if room>

    Sized to fit within 290 chars (Bluesky's effective limit with
    safety margin). The URL is preserved at full length because Bluesky
    renders it as a rich link card via OpenGraph — we never truncate it.
    """
    title = (title or "").strip()
    summary = (summary or "").strip()
    url = (url or "").strip()

    hashtags = _make_hashtags(keywords or [], limit=3)
    hashtag_str = " ".join(hashtags)

    # Reserve url + (hashtags + 1 separator) + 2 line breaks
    fixed_overhead = len(url) + (len(hashtag_str) + 2 if hashtag_str else 0) + 2
    text_budget = max(0, _MAX_POST_CHARS - fixed_overhead)

    title_line = title[:text_budget].rstrip()
    remaining = max(0, text_budget - len(title_line) - 2)  # -2 for "\n\n" between title and summary

    summary_line = ""
    if summary and remaining > 40:  # only include hook if we have meaningful room
        summary_line = summary[:remaining].rstrip()
        # Avoid mid-sentence truncation if possible — clip to last period or comma
        if len(summary_line) < len(summary) and "." in summary_line:
            summary_line = summary_line[: summary_line.rfind(".") + 1]
        elif len(summary_line) < len(summary) and " " in summary_line:
            summary_line = summary_line[: summary_line.rfind(" ")] + "…"

    parts = [title_line]
    if summary_line:
        parts.append(summary_line)
    parts.append(url)
    if hashtag_str:
        parts.append(hashtag_str)

    return "\n\n".join(parts)


def _make_hashtags(keywords: Iterable[str], *, limit: int) -> list[str]:
    """Convert raw LLM keywords into Bluesky-safe hashtags. Strips
    punctuation, capitalizes intelligently, drops anything that doesn't
    survive the cleanup."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in keywords:
        if not raw:
            continue
        cleaned = re.sub(r"[^A-Za-z0-9]+", "", str(raw))
        if len(cleaned) < 3 or len(cleaned) > 30:
            continue
        # Capitalize each word in the original to make multi-word tags
        # readable: "ofac sanctions" -> "OfacSanctions"
        words = re.split(r"[^A-Za-z0-9]+", str(raw))
        camel = "".join(w[:1].upper() + w[1:].lower() for w in words if w)
        if not camel:
            continue
        tag_lower = camel.lower()
        if tag_lower in seen:
            continue
        seen.add(tag_lower)
        out.append(f"#{camel}")
        if len(out) >= limit:
            break
    return out


def _build_facets(text: str, link_url: str | None) -> list[dict]:
    """Return atproto facets for clickable links. Bluesky requires
    explicit byte-offset annotations to render URLs as links — without
    a facet, the URL appears as plain text."""
    facets: list[dict] = []
    encoded = text.encode("utf-8")

    if link_url:
        url_bytes = link_url.encode("utf-8")
        idx = encoded.find(url_bytes)
        if idx >= 0:
            facets.append({
                "index": {"byteStart": idx, "byteEnd": idx + len(url_bytes)},
                "features": [{"$type": "app.bsky.richtext.facet#link", "uri": link_url}],
            })

    # Hashtag facets (so #OfacSanctions becomes a clickable tag search)
    for match in re.finditer(rb"#([A-Za-z0-9]+)", encoded):
        facets.append({
            "index": {"byteStart": match.start(), "byteEnd": match.end()},
            "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": match.group(1).decode("utf-8")}],
        })

    return facets


# ---------------------------------------------------------------------------
# Module-level loader
# ---------------------------------------------------------------------------


def is_enabled() -> bool:
    return bool(settings.bluesky_handle.strip() and settings.bluesky_app_password.strip())


def get_client() -> BlueskyClient | None:
    if not is_enabled():
        return None
    return BlueskyClient(
        handle=settings.bluesky_handle.strip(),
        app_password=settings.bluesky_app_password.strip(),
    )
