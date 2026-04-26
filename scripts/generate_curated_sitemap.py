"""Generate a hand-curated 100-URL sitemap and a 20-URL priority
indexing list — for one-shot submission to Google Search Console,
Bing Webmaster Tools, and the Google Indexing API.

Why a curated sitemap (vs the dynamic /sitemap.xml the server already
emits)? The dynamic sitemap includes everything (every blog post,
every long-tail SDN profile, every company even with no exposure),
which dilutes crawl budget on a brand-new property. For initial
submission and the "Request Indexing" workflow, the engines benefit
from a tight list of the most important top-level / hub pages.

Outputs:
  seo/curated-sitemap.xml      — top ~100 URLs, sitemaps.org schema
  seo/priority-indexing.txt    — top ~20 URLs, one per line

Usage:
  python scripts/generate_curated_sitemap.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("SITE_URL", "https://cubaninsights.com")

from src.config import settings  # noqa: E402
from src.data.curated_cuba_exposure import _CURATED  # noqa: E402
from src.data.sp500_companies import list_sp500_companies  # noqa: E402

OUT_DIR = os.path.join(ROOT, "seo")
SITEMAP_PATH = os.path.join(OUT_DIR, "curated-sitemap.xml")
INDEXING_PATH = os.path.join(OUT_DIR, "priority-indexing.txt")


# ── Tier 1: top-level static hubs (highest priority) ────────────────
# These are the pages that should be indexed first; they collectively
# describe the whole site and give crawlers an anchor for everything
# else they discover via internal links.
STATIC_TOP_LEVEL: list[tuple[str, str, str]] = [
    # (path, changefreq, priority)
    ("/",                                              "daily",   "1.0"),
    ("/invest-in-cuba",                                "weekly",  "0.95"),
    ("/sanctions-tracker",                             "daily",   "0.95"),
    ("/briefing",                                      "daily",   "0.9"),
    ("/tools",                                         "weekly",  "0.9"),
    ("/companies",                                     "weekly",  "0.9"),
    ("/explainers",                                    "weekly",  "0.85"),
    ("/travel",                                        "weekly",  "0.85"),
    ("/export-to-cuba",                                "weekly",  "0.9"),
    ("/calendar",                                      "daily",   "0.75"),
    ("/sources",                                       "weekly",  "0.65"),
    ("/travel/emergency-card",                         "monthly", "0.7"),
    ("/tearsheet/latest.pdf",                          "daily",   "0.85"),
    ("/briefing/feed.xml",                             "daily",   "0.7"),
]


# ── Tier 2: sanctions hubs (sector + bucket) ────────────────────────
SANCTIONS_HUBS: list[tuple[str, str, str]] = [
    ("/sanctions/by-sector",                           "daily", "0.9"),
    ("/sanctions/sector/military",                     "daily", "0.85"),
    ("/sanctions/sector/economic",                     "daily", "0.85"),
    ("/sanctions/sector/diplomatic",                   "daily", "0.85"),
    ("/sanctions/sector/governance",                   "daily", "0.85"),
    ("/sanctions/individuals",                         "daily", "0.85"),
    ("/sanctions/entities",                            "daily", "0.85"),
    ("/sanctions/vessels",                             "daily", "0.8"),
    ("/sanctions/aircraft",                            "daily", "0.8"),
]


# ── Tier 3: tools (each is a standalone landing page that ranks) ────
TOOLS: list[tuple[str, str, str]] = [
    ("/tools/eltoque-trmi-rate",                       "daily",   "0.85"),
    ("/tools/ofac-cuba-sanctions-checker",             "weekly",  "0.85"),
    ("/tools/cuba-restricted-list-checker",            "weekly",  "0.85"),
    ("/tools/cuba-prohibited-hotels-checker",          "weekly",  "0.85"),
    ("/tools/can-i-travel-to-cuba",                    "monthly", "0.8"),
    ("/tools/public-company-cuba-exposure-check",      "weekly",  "0.85"),
    ("/tools/sec-edgar-cuba-impairment-search",        "weekly",  "0.85"),
    ("/tools/ofac-cuba-general-licenses",              "weekly",  "0.8"),
    ("/tools/cuba-trade-leads-for-us-companies",       "daily",   "0.85"),
    ("/tools/cuba-export-opportunity-finder",          "weekly",  "0.85"),
    ("/tools/cuba-hs-code-opportunity-finder",         "weekly",  "0.8"),
    ("/tools/cuba-export-controls-sanctions-process-map", "weekly", "0.85"),
    ("/tools/can-my-us-company-export-to-cuba",        "weekly",  "0.85"),
    ("/tools/cuba-country-contacts-directory",         "monthly", "0.75"),
    ("/tools/us-company-cuba-market-entry-checklist",  "monthly", "0.8"),
    ("/tools/cuba-agricultural-medical-export-checker", "weekly", "0.8"),
    ("/tools/cuba-telecom-internet-export-checker",    "weekly",  "0.8"),
    ("/tools/cuba-mipyme-export-support-checklist",    "weekly",  "0.8"),
    ("/tools/cuba-trade-events-matchmaking-calendar",  "weekly",  "0.75"),
    ("/tools/cuba-trade-barriers-tracker",             "weekly",  "0.75"),
    ("/tools/cuba-export-compliance-checklist",        "weekly",  "0.85"),
    ("/tools/havana-safety-by-neighborhood",           "weekly",  "0.7"),
    ("/tools/cuba-investment-roi-calculator",          "monthly", "0.7"),
    ("/tools/cuba-visa-requirements",                  "monthly", "0.75"),
]


# ── Tier 4: thematic sector hubs (LandingPage page_type='sector') ───
# These may or may not exist as generated landing pages yet. They are
# real routes (/sectors/<slug>) handled by the dynamic sector view.
# Including them in the curated sitemap is a soft nudge for crawlers
# to discover them as we publish.
SECTOR_HUBS: list[str] = [
    "tourism",
    "energy",
    "telecom",
    "banking",
    "mining",
    "agriculture",
    "biotech",
    "transportation",
    "real-estate",
    "construction",
    "remittances",
    "shipping",
    "rum-and-tobacco",
    "media",
    "healthcare",
]


def _site_base() -> str:
    return settings.site_url.rstrip("/")


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _company_urls() -> list[tuple[str, str, str]]:
    """Resolve curated S&P 500 tickers to /companies/<slug>/cuba-exposure
    URLs. Skip tickers not present in the cached S&P 500 snapshot."""
    by_ticker = {c.ticker: c for c in list_sp500_companies()}
    out: list[tuple[str, str, str]] = []
    # Sort: direct exposure first (highest editorial priority), then
    # historical, indirect, none.
    rank = {"direct": 0, "historical": 1, "indirect": 2, "none": 3}
    items = sorted(
        _CURATED.items(),
        key=lambda kv: (rank.get(kv[1].exposure_level, 9), kv[0]),
    )
    for ticker, exp in items:
        c = by_ticker.get(ticker)
        if not c:
            continue
        if exp.exposure_level == "direct":
            priority = "0.8"
        elif exp.exposure_level == "historical":
            priority = "0.75"
        elif exp.exposure_level == "indirect":
            priority = "0.7"
        else:
            priority = "0.55"
        out.append((f"/companies/{c.slug}/cuba-exposure", "weekly", priority))
    return out


def _sdn_urls() -> list[tuple[str, str, str]]:
    """Top SDN profile URLs (highest-recognition Cuba-program designees)."""
    try:
        from src.data.sdn_profiles import list_all_profiles
    except Exception:
        return []
    profiles = list_all_profiles()
    # Prioritize individuals over entities (faces > orgs for SEO),
    # then by alphabetical slug for determinism.
    individuals = sorted(
        [p for p in profiles if p.bucket == "individuals"],
        key=lambda p: p.slug,
    )
    entities = sorted(
        [p for p in profiles if p.bucket == "entities"],
        key=lambda p: p.slug,
    )
    out: list[tuple[str, str, str]] = []
    for p in individuals[:10]:
        out.append((p.url_path, "monthly", "0.7"))
    for p in entities[:25]:
        out.append((p.url_path, "monthly", "0.65"))
    return out


def build_url_list(target: int = 100) -> list[tuple[str, str, str, str]]:
    """Return [(loc, lastmod, changefreq, priority), ...] capped at `target`."""
    today = _today_iso()
    base = _site_base()

    bag: list[tuple[str, str, str]] = []
    bag += STATIC_TOP_LEVEL
    bag += SANCTIONS_HUBS
    bag += TOOLS
    bag += [(f"/sectors/{s}", "weekly", "0.7") for s in SECTOR_HUBS]
    bag += _company_urls()
    bag += _sdn_urls()

    # Dedupe while preserving order & first-seen priority/changefreq.
    seen: set[str] = set()
    final: list[tuple[str, str, str, str]] = []
    for path, changefreq, priority in bag:
        loc = f"{base}{path}"
        if loc in seen:
            continue
        seen.add(loc)
        final.append((loc, today, changefreq, priority))
        if len(final) >= target:
            break
    return final


def build_priority_indexing(target: int = 20) -> list[str]:
    """The 20 URLs to manually 'Request Indexing' in GSC and submit
    one-by-one to the Bing URL Submission tool. Curated for highest
    business value (pillars + hero tools + flagship sanctions hubs)."""
    base = _site_base()
    paths = [
        "/",
        "/invest-in-cuba",
        "/sanctions-tracker",
        "/briefing",
        "/tools",
        "/companies",
        "/explainers",
        "/travel",
        "/export-to-cuba",
        "/calendar",
        "/tools/cuba-trade-leads-for-us-companies",
        "/tools/cuba-export-controls-sanctions-process-map",
        "/tools/can-my-us-company-export-to-cuba",
        "/tools/eltoque-trmi-rate",
        "/tools/ofac-cuba-sanctions-checker",
        "/tools/cuba-restricted-list-checker",
        "/tools/cuba-prohibited-hotels-checker",
        "/tools/public-company-cuba-exposure-check",
        "/tools/sec-edgar-cuba-impairment-search",
        "/tools/ofac-cuba-general-licenses",
        "/tools/can-i-travel-to-cuba",
        "/tools/cuba-visa-requirements",
        "/sanctions/by-sector",
        "/sanctions/individuals",
    ]
    return [f"{base}{p}" for p in paths[:target]]


def write_sitemap(urls: list[tuple[str, str, str, str]], path: str) -> None:
    from xml.sax.saxutils import escape as _esc

    parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    parts.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for loc, lastmod, changefreq, priority in urls:
        parts.append("  <url>")
        parts.append(f"    <loc>{_esc(loc)}</loc>")
        parts.append(f"    <lastmod>{lastmod}</lastmod>")
        parts.append(f"    <changefreq>{changefreq}</changefreq>")
        parts.append(f"    <priority>{priority}</priority>")
        parts.append("  </url>")
    parts.append("</urlset>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts) + "\n")


def write_indexing_list(urls: list[str], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(urls) + "\n")


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    urls = build_url_list(target=100)
    write_sitemap(urls, SITEMAP_PATH)

    priority = build_priority_indexing(target=20)
    write_indexing_list(priority, INDEXING_PATH)

    print(f"Wrote {len(urls)} URLs to {SITEMAP_PATH}")
    print(f"Wrote {len(priority)} URLs to {INDEXING_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
