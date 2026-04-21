"""
Backfill per-briefing Open Graph cards for existing BlogPost rows.

For every BlogPost that doesn't yet have `og_image_bytes` populated,
render the Concept-3 card and persist the bytes. After this runs, the
/og/briefing/<slug>.png route will serve a unique tile for every
historical briefing — and the next Bluesky cron will use those tiles
as the rich-link-card thumbnail (replacing the now-stale single
shared image that was uploaded to Bluesky's blob store earlier).

Idempotent. Run as many times as you like — already-rendered rows are
skipped unless --overwrite is passed.

Usage (from the Render web shell, which has DATABASE_URL):
    python scripts/backfill_og_images.py
    python scripts/backfill_og_images.py --limit 50
    python scripts/backfill_og_images.py --overwrite
    python scripts/backfill_og_images.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Allow running as a top-level script (python scripts/backfill_og_images.py)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import BlogPost, SessionLocal, init_db  # noqa: E402
from src.og_image import latest_eltoque_usd, render_briefing_card  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("backfill_og")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum posts to render (default: all eligible)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-render even posts that already have og_image_bytes",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render in-memory but don't write back to the DB",
    )
    args = parser.parse_args()

    init_db()
    db = SessionLocal()

    # Snapshot the elTOQUE TRMI informal rate ONCE per run so every
    # backfilled card uses the same "as of" stat (consistent across the
    # batch and one fewer DB roundtrip per post).
    informal_usd = latest_eltoque_usd()
    if informal_usd is not None:
        logger.info("using elTOQUE TRMI USD = %.2f CUP", informal_usd)
    else:
        logger.info("no elTOQUE TRMI rate available; cards will omit the stat block")

    try:
        q = db.query(BlogPost).order_by(BlogPost.published_date.desc(), BlogPost.id.desc())
        if not args.overwrite:
            q = q.filter(BlogPost.og_image_bytes.is_(None))
        if args.limit:
            q = q.limit(args.limit)

        posts = q.all()
        logger.info("found %d post(s) to render", len(posts))

        rendered = 0
        failed = 0
        skipped = 0
        for i, post in enumerate(posts, start=1):
            if not args.overwrite and post.og_image_bytes:
                skipped += 1
                continue

            try:
                png = render_briefing_card(
                    title=post.title or "",
                    category=post.primary_sector,
                    published_date=post.published_date,
                    informal_usd=informal_usd,
                )
            except Exception as exc:
                logger.warning("[%d/%d] render failed for slug=%s: %s", i, len(posts), post.slug, exc)
                failed += 1
                continue

            if args.dry_run:
                logger.info(
                    "[%d/%d] (dry-run) %s -> %d bytes",
                    i, len(posts), post.slug, len(png),
                )
                rendered += 1
                continue

            post.og_image_bytes = png
            db.commit()
            rendered += 1
            logger.info(
                "[%d/%d] saved %d bytes -> %s",
                i, len(posts), len(png), post.slug,
            )
            # Tiny pause: keeps the DB happy on a long backfill on
            # Render's free-tier Postgres.
            if i % 25 == 0:
                time.sleep(0.5)

        logger.info(
            "done — rendered=%d skipped=%d failed=%d",
            rendered, skipped, failed,
        )
        return 0 if failed == 0 else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
