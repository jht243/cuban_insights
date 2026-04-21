"""
Backfill `social_hook` for every existing BlogPost that doesn't have
one yet. Self-contained LLM call per post — uses only the post's own
title / summary / body (no need to reach back to the source row).

Cost envelope:
    ~600 input tokens + ~80 output tokens per post
    -> ~ $0.0023 / post at gpt-4o pricing
    -> 100 posts ≈ $0.23, 1000 posts ≈ $2.30

Usage:
    # On Render (web shell — has OPENAI_API_KEY + DATABASE_URL):
    python scripts/backfill_social_hooks.py

    # Limit to 50 at a time and only re-run for empty hooks:
    python scripts/backfill_social_hooks.py --limit 50

    # Force-overwrite even if a hook already exists:
    python scripts/backfill_social_hooks.py --overwrite

    # Inspect without writing:
    python scripts/backfill_social_hooks.py --dry-run --limit 5
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys

from openai import OpenAI

from src.config import settings
from src.models import BlogPost, SessionLocal, init_db


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("backfill_social_hooks")


_TAG_RE = re.compile(r"<[^>]+>")


SYSTEM_PROMPT = """You write social-media opening lines for a Cuba-focused investment-research publication. Voice: one analyst messaging another over Slack — concrete, calm, slightly conspiratorial, never marketing. NEVER restate the headline. NEVER use hashtags, emoji, exclamation marks, or words like "groundbreaking", "must-read", "game-changing", "alert". Surface the tension, the surprise, or the "why this matters in one beat".

Return a single JSON object: {"social_hook": "<180-250 char line>"}.

Examples of the right register:
- "Havana just walked back a MIPYME licensing freeze nobody on the desk noticed last quarter — the second quiet reversal on private-sector rules in six weeks."
- "OFAC let a CACR §515 GL drift inside its renewal window. The cruise lines have been calling counsel since Tuesday."
- "The new MLC re-pricing decree reads procedural, but it shifts where Western Union's settlement risk actually lives."
"""


USER_PROMPT_TEMPLATE = """TITLE: {title}

SUMMARY: {summary}

BODY (truncated):
{body}

Write the social_hook now. JSON only."""


def _strip_html(html: str | None) -> str:
    if not html:
        return ""
    return _TAG_RE.sub(" ", html)


def _generate_hook(client: OpenAI, post: BlogPost) -> str | None:
    body_text = _strip_html(post.body_html)[:2000]
    user_msg = USER_PROMPT_TEMPLATE.format(
        title=post.title or "",
        summary=post.summary or post.subtitle or "",
        body=body_text or "(no body)",
    )
    try:
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.6,
            max_tokens=200,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        logger.warning("post id=%s: LLM call failed: %s", post.id, exc)
        return None

    try:
        payload = json.loads(response.choices[0].message.content)
    except Exception as exc:
        logger.warning("post id=%s: JSON parse failed: %s", post.id, exc)
        return None

    hook = (payload.get("social_hook") or "").strip()
    if not hook:
        return None
    if len(hook) > 280:
        hook = hook[:280].rstrip()
    return hook


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Max posts to process (0 = all).")
    parser.add_argument("--overwrite", action="store_true", help="Regenerate even if a hook exists.")
    parser.add_argument("--dry-run", action="store_true", help="Generate hooks but don't write.")
    args = parser.parse_args()

    if not settings.openai_api_key:
        logger.error("OPENAI_API_KEY not set; cannot generate hooks.")
        return 2

    init_db()
    db = SessionLocal()
    try:
        q = db.query(BlogPost).order_by(BlogPost.published_date.desc())
        if not args.overwrite:
            q = q.filter((BlogPost.social_hook.is_(None)) | (BlogPost.social_hook == ""))
        if args.limit > 0:
            q = q.limit(args.limit)
        posts = q.all()

        if not posts:
            logger.info("Nothing to backfill — all posts already have a social_hook.")
            return 0

        logger.info("Backfilling social_hook for %d post(s)…", len(posts))

        client = OpenAI(api_key=settings.openai_api_key)

        ok = 0
        skipped = 0
        for post in posts:
            hook = _generate_hook(client, post)
            if not hook:
                skipped += 1
                continue
            logger.info("post id=%s slug=%s\n  -> %s", post.id, post.slug, hook)
            if not args.dry_run:
                post.social_hook = hook
                db.add(post)
                ok += 1

        if not args.dry_run:
            db.commit()

        logger.info("Done. updated=%d skipped=%d dry_run=%s", ok, skipped, args.dry_run)
        return 0
    except Exception as exc:
        logger.exception("Backfill failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return 3
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
