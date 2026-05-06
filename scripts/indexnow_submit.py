"""One-shot IndexNow backfill — submit every public URL on the site to
Bing/Yandex/Seznam/Naver/Mojeek in a single batched POST.

Use after first activating IndexNow (i.e. after setting INDEXNOW_KEY in
production env) so the engines have your full corpus immediately,
instead of waiting on twice-daily cron pings to drip-feed them.

Usage (run locally; does NOT need to run on Render):
    python scripts/indexnow_submit.py             # submit everything
    python scripts/indexnow_submit.py --dry-run   # list URLs only

Idempotent — IndexNow accepts re-submissions cheaply, so re-running is
safe. Records every submitted URL in distribution_logs so subsequent
cron runs respect the 23-hour cooldown.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

os.environ.setdefault("SITE_URL", "https://cubaninsights.com")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.config import settings  # noqa: E402
from src.distribution import indexnow  # noqa: E402
from src.distribution.runner import CHANNEL_INDEXNOW, _record  # noqa: E402
from src.models import BlogPost, LandingPage, SessionLocal, init_db  # noqa: E402


# Fallback static, evergreen routes. The primary path below reads the
# live sitemap-core helper from server.py so IndexNow submissions do not
# drift when new public routes are added.
STATIC_PATHS: tuple[str, ...] = (
    "/",
    "/briefing",
    "/sanctions-tracker",
    "/invest-in-cuba",
    "/tools",
    "/tools/can-i-travel-to-cuba",
    "/tools/cuba-prohibited-hotels-checker",
    "/tools/cuba-restricted-list-checker",
    "/tools/havana-safety-by-neighborhood",
    "/tools/cuba-visa-requirements",
    "/tools/cuba-investment-roi-calculator",
    "/tools/eltoque-trmi-rate",
    "/tools/ofac-cuba-sanctions-checker",
    "/tools/ofac-cuba-general-licenses",
    "/tools/public-company-cuba-exposure-check",
    "/tools/sec-edgar-cuba-impairment-search",
    "/tools/helms-burton-act-explained",
    "/tools/cuba-embargo-explained",
    "/tools/cuba-travel-advisory",
    "/tools/what-is-ofac",
    "/explainers",
    "/travel",
    "/calendar",
    "/sources",
    "/sanctions/individuals",
    "/sanctions/entities",
    "/sanctions/vessels",
    "/sanctions/aircraft",
    "/companies",
)


def _site_base() -> str:
    return settings.site_url.rstrip("/")


def collect_urls() -> list[tuple[str, str, int | None]]:
    """Return [(url, entity_type, entity_id), ...] for every public URL."""
    base = _site_base()
    out: list[tuple[str, str, int | None]] = []

    try:
        from server import _core_static_urls, _people_sitemap_urls
        for entry in _core_static_urls() + _people_sitemap_urls():
            loc = (entry.get("loc") or "").strip()
            if loc:
                out.append((loc, "static", None))
    except Exception as exc:
        print(f"WARN: could not read sitemap-core URLs for IndexNow: {exc}")
        for path in STATIC_PATHS:
            out.append((f"{base}{path}", "static", None))

    init_db()
    db = SessionLocal()
    try:
        for post in db.query(BlogPost).order_by(BlogPost.created_at.desc()).all():
            if not post.slug:
                continue
            out.append((f"{base}/briefing/{post.slug}", "blog_post", post.id))

        for page in db.query(LandingPage).all():
            path = (page.canonical_path or "").strip()
            if not path or not path.startswith("/"):
                continue
            out.append((f"{base}{path}", "landing_page", page.id))
    finally:
        db.close()

    # Per-SDN profile pages — every OFAC Cuba-program designation
    # (CACR / Cuba Restricted List / EO 13818 Magnitsky on Cubans) is
    # its own indexable URL. We submit them all so Bing/Yandex discover
    # the corpus immediately rather than waiting on link-walking.
    try:
        from src.data.sdn_profiles import list_all_profiles
        for p in list_all_profiles():
            out.append((f"{base}{p.url_path}", "sdn_profile", p.db_id))
    except Exception as exc:
        print(f"WARN: could not enumerate SDN profiles for IndexNow: {exc}")

    # Per-State Department CPAL and CRL pages. These live outside the
    # database-backed LandingPage table, so enumerate the same helpers
    # used by the submitted CPAL/CRL sitemaps.
    try:
        from server import list_cpal_profiles, list_crl_profiles
        for row in list_cpal_profiles():
            path = (row.get("url_path") or "").strip()
            if path:
                out.append((f"{base}{path}", "cpal_profile", None))
        for row in list_crl_profiles():
            path = (row.get("url_path") or "").strip()
            if path:
                out.append((f"{base}{path}", "crl_profile", None))
    except Exception as exc:
        print(f"WARN: could not enumerate CPAL/CRL profiles for IndexNow: {exc}")

    # Per-company Cuba-exposure pages — one per S&P 500 ticker.
    # Same rationale as SDN profiles: long-tail SEO bet that only pays
    # off if Bing/Yandex see the URLs early. Use the dedicated helper
    # so this stays in lock-step with /sitemap.xml.
    try:
        from src.data.company_exposure import companies_for_sitemap
        for entry in companies_for_sitemap():
            out.append((f"{base}{entry['url_path']}", "company_profile", None))
    except Exception as exc:
        print(f"WARN: could not enumerate company profiles for IndexNow: {exc}")

    # Dedupe while preserving order.
    seen: set[str] = set()
    unique: list[tuple[str, str, int | None]] = []
    for u, t, i in out:
        if u in seen:
            continue
        seen.add(u)
        unique.append((u, t, i))
    return unique


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="List URLs without submitting.")
    ap.add_argument("--batch-size", type=int, default=500,
                    help="URLs per IndexNow POST. Protocol allows 10k; "
                         "smaller batches give more readable logs.")
    args = ap.parse_args()

    if not (settings.indexnow_key or "").strip():
        print("ERROR: INDEXNOW_KEY is not set in your environment.")
        print("       Set it in .env (and Render env vars), then re-run.")
        return 2

    urls = collect_urls()
    print(f"Collected {len(urls)} unique public URLs.")
    print(f"Site: {_site_base()}")
    print(f"Key file: {_site_base()}/{settings.indexnow_key}.txt")
    print()

    if args.dry_run:
        for u, t, _ in urls:
            print(f"  [{t:13}] {u}")
        print(f"\nDRY RUN: would submit {len(urls)} URL(s).")
        return 0

    init_db()
    db = SessionLocal()
    try:
        total_ok = 0
        total_fail = 0
        for i in range(0, len(urls), args.batch_size):
            chunk = urls[i : i + args.batch_size]
            urls_only = [u for u, _, _ in chunk]
            print(f"Submitting batch {i // args.batch_size + 1} "
                  f"({len(urls_only)} URLs)...")
            result = indexnow.submit_urls(urls_only)
            print(f"  -> status={result.status_code} "
                  f"submitted={result.submitted} success={result.success}")
            print(f"  -> response: {result.response_snippet[:200]}")

            for url, entity_type, entity_id in chunk:
                _record(
                    db,
                    channel=CHANNEL_INDEXNOW,
                    url=url,
                    success=result.success,
                    response_code=result.status_code,
                    response_snippet=result.response_snippet,
                    entity_type=entity_type,
                    entity_id=entity_id,
                )
            if result.success:
                total_ok += len(chunk)
            else:
                total_fail += len(chunk)
        db.commit()
        print()
        print(f"Done at {datetime.utcnow().isoformat()}Z — "
              f"{total_ok} submitted, {total_fail} failed.")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
