#!/usr/bin/env python3
"""Nightly sitemap audit & sync for Cuban Insights.

Fetches all live child sitemaps, extracts Flask route declarations from
server.py, diffs the two sets, auto-patches missing static URLs into
_core_static_urls(), and spot-checks random live URLs for dead links.

Usage:
    python scripts/sync_sitemap.py --dry-run                # audit only
    python scripts/sync_sitemap.py --dry-run --no-spot-check  # fast offline audit
    python scripts/sync_sitemap.py                          # full: patch + push
"""
from __future__ import annotations

import argparse
import logging
import os
import random
import re
import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import httpx

# ── Configuration ─────────────────────────────────────────────────────
CANONICAL_BASE = os.getenv("SITE_URL", "https://cubaninsights.com").rstrip("/")

LIVE_SITEMAP_INDEX_URL = f"{CANONICAL_BASE}/sitemap.xml"
LIVE_CHILD_SITEMAPS = [
    f"{CANONICAL_BASE}/sitemap-core.xml",
    f"{CANONICAL_BASE}/sitemap-briefings-recent.xml",
    f"{CANONICAL_BASE}/sitemap-companies-priority.xml",
    f"{CANONICAL_BASE}/sitemap-sdn-priority.xml",
    f"{CANONICAL_BASE}/sitemap-cpal.xml",
    f"{CANONICAL_BASE}/sitemap-crl.xml",
    f"{CANONICAL_BASE}/sitemap-archive.xml",
    f"{CANONICAL_BASE}/news-sitemap.xml",
    f"{CANONICAL_BASE}/curated-sitemap.xml",
]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_FILE = os.path.join(ROOT, "server.py")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")

SPOT_CHECK_COUNT = 25

# ── Exclusion rules ──────────────────────────────────────────────────
EXCLUDE_PREFIXES = (
    "/api/", "/health", "/admin", "/webhook", "/internal",
    "/static/", "/og/", "/tearsheet/",
)
EXCLUDE_SUFFIXES = (".txt", ".xml", ".pdf", ".json", ".png", ".jpg")
EXCLUDE_EXACT = frozenset({
    "/robots.txt", "/sitemap.xml", "/sitemap-core.xml",
    "/sitemap-briefings-recent.xml", "/sitemap-companies-priority.xml",
    "/sitemap-sdn-priority.xml", "/sitemap-cpal.xml", "/sitemap-crl.xml",
    "/sitemap-archive.xml", "/news-sitemap.xml", "/curated-sitemap.xml",
    "/briefing/feed.xml",
})
EXCLUDE_CONTAINS = ("noindex", "debug", "test")

# Insertion anchor: the last entry in _core_static_urls() + closing bracket.
# The script inserts new entries BEFORE this line.
INSERTION_ANCHOR = '        {"loc": f"{base}/tools/public-company-venezuela-exposure-check", "lastmod": today_iso, "changefreq": "weekly", "priority": "0.45"},'

# ── Priority heuristics ──────────────────────────────────────────────
_PRIORITY_MAP = [
    ("/tools/", "0.7"),
    ("/explainers/", "0.7"),
    ("/sanctions/", "0.75"),
    ("/travel/", "0.7"),
    ("/companies/", "0.7"),
    ("/people/", "0.7"),
    ("/sectors/", "0.65"),
    ("/venezuela/", "0.5"),
    ("/briefing/", "0.7"),
]
_DEFAULT_PRIORITY = "0.6"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-24s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sync_sitemap")


# ── (a) Fetch live sitemap URLs ──────────────────────────────────────

def fetch_sitemap_urls() -> set[str]:
    """Download every child sitemap, parse <loc> tags, return normalised paths."""
    paths: set[str] = set()
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for url in LIVE_CHILD_SITEMAPS:
            try:
                resp = client.get(url)
                resp.raise_for_status()
            except Exception as exc:
                log.warning("Could not fetch %s: %s", url, exc)
                continue
            try:
                root = ET.fromstring(resp.text)
            except ET.ParseError as exc:
                log.warning("Could not parse %s: %s", url, exc)
                continue
            ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            for loc_el in root.findall(".//s:loc", ns):
                raw = (loc_el.text or "").strip()
                if not raw:
                    continue
                parsed = urlparse(raw)
                path = parsed.path.rstrip("/") or "/"
                paths.add(path)
    log.info("Fetched %d unique paths from live sitemaps", len(paths))
    return paths


# ── (b) Extract routes from server.py ────────────────────────────────

_ROUTE_RE = re.compile(r'@app\.route\(\s*"(/[^"]*)"')
_PARAM_RE = re.compile(r"<[^>]+>|:[a-zA-Z_]+|\[[a-zA-Z_]+\]")


def _should_exclude(path: str) -> bool:
    if path in EXCLUDE_EXACT:
        return True
    if any(path.startswith(p) for p in EXCLUDE_PREFIXES):
        return True
    if any(path.endswith(s) for s in EXCLUDE_SUFFIXES):
        return True
    if any(tok in path for tok in EXCLUDE_CONTAINS):
        return True
    return False


def extract_source_routes() -> set[str]:
    """Regex-extract all @app.route paths from server.py, filtering out
    parametric, internal, and excluded routes."""
    with open(APP_FILE, encoding="utf-8") as f:
        source = f.read()
    raw_paths = _ROUTE_RE.findall(source)
    routes: set[str] = set()
    for p in raw_paths:
        norm = p.rstrip("/") or "/"
        if _PARAM_RE.search(norm):
            continue
        if _should_exclude(norm):
            continue
        routes.add(norm)
    log.info("Extracted %d eligible static routes from server.py", len(routes))
    return routes


# ── (c) Diff & auto-patch ────────────────────────────────────────────

def _heuristic_priority(path: str) -> str:
    for prefix, prio in _PRIORITY_MAP:
        if path.startswith(prefix):
            return prio
    return _DEFAULT_PRIORITY


def _heuristic_changefreq(path: str) -> str:
    if any(path.startswith(p) for p in ("/sanctions/", "/briefing", "/calendar")):
        return "daily"
    return "weekly"


def diff_and_patch(
    source_routes: set[str],
    sitemap_paths: set[str],
    dry_run: bool,
) -> list[str]:
    """Find routes in code not in the sitemap, auto-insert if possible.

    Returns the list of newly added paths.
    """
    missing = sorted(source_routes - sitemap_paths)
    if not missing:
        log.info("No missing routes — sitemap is in sync with source routes.")
        return []

    log.info("Found %d routes in code but NOT in any sitemap:", len(missing))
    for p in missing:
        log.info("  MISSING: %s", p)

    if dry_run:
        log.info("Dry-run mode — not modifying %s", APP_FILE)
        return missing

    with open(APP_FILE, encoding="utf-8") as f:
        content = f.read()

    if INSERTION_ANCHOR not in content:
        log.error(
            "Cannot find insertion anchor in %s. Update INSERTION_ANCHOR in "
            "sync_sitemap.py to match the last entry in _core_static_urls().",
            APP_FILE,
        )
        return missing

    new_entries = []
    for p in missing:
        prio = _heuristic_priority(p)
        freq = _heuristic_changefreq(p)
        entry = (
            f'        {{"loc": f"{{base}}{p}", '
            f'"lastmod": today_iso, '
            f'"changefreq": "{freq}", '
            f'"priority": "{prio}"}},'
        )
        new_entries.append(entry)

    insert_block = "\n".join(new_entries) + "\n"
    content = content.replace(INSERTION_ANCHOR, insert_block + INSERTION_ANCHOR)

    with open(APP_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    log.info("Inserted %d new entries into _core_static_urls()", len(missing))
    return missing


# ── (d) Spot-check live URLs ─────────────────────────────────────────

def spot_check(sitemap_paths: set[str], count: int = SPOT_CHECK_COUNT) -> list[tuple[str, int]]:
    """GET-request a random sample of sitemap URLs, return dead ones."""
    sample = random.sample(sorted(sitemap_paths), min(count, len(sitemap_paths)))
    dead: list[tuple[str, int]] = []
    with httpx.Client(
        timeout=15,
        follow_redirects=True,
        headers={"User-Agent": "CubanInsights-SitemapAudit/1.0"},
    ) as client:
        for path in sample:
            url = f"{CANONICAL_BASE}{path}"
            try:
                resp = client.get(url)
                code = resp.status_code
            except Exception:
                code = -1
            if code >= 400 or code < 0:
                dead.append((path, code))
                log.warning("DEAD LINK: %s → %s", path, code)
            else:
                log.debug("OK: %s → %d", path, code)
    if dead:
        log.warning("Spot-check found %d dead link(s) out of %d sampled", len(dead), len(sample))
    else:
        log.info("Spot-check: all %d sampled URLs returned 2xx/3xx", len(sample))
    return dead


# ── Git commit & push ────────────────────────────────────────────────

def git_commit_and_push(added_count: int) -> bool:
    """Commit the patched server.py and push to origin/main."""
    if not GITHUB_TOKEN:
        log.warning("GITHUB_TOKEN not set — skipping git push (audit-only mode).")
        return False
    if not GITHUB_REPO:
        log.warning("GITHUB_REPO not set — skipping git push.")
        return False

    try:
        _run = lambda cmd: subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True, text=True)
        _run(["git", "config", "user.email", "sitemap-bot@cubaninsights.com"])
        _run(["git", "config", "user.name", "Sitemap Sync Bot"])
        remote_url = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
        _run(["git", "remote", "set-url", "origin", remote_url])
        _run(["git", "pull", "--rebase", "origin", "main"])
        _run(["git", "add", APP_FILE])
        msg = f"sitemap: auto-add {added_count} missing static URL(s)"
        _run(["git", "commit", "-m", msg])
        _run(["git", "push", "origin", "HEAD:main"])
        log.info("Committed and pushed: %s", msg)
        return True
    except subprocess.CalledProcessError as exc:
        log.error("Git operation failed: %s\nstdout: %s\nstderr: %s", exc.cmd, exc.stdout, exc.stderr)
        return False


# ── CLI entry point ──────────────────────────────────────────────────

def run_sync(*, dry_run: bool = False, spot_check_enabled: bool = True) -> dict:
    """Run the full sitemap audit & sync. Returns a summary dict.

    Callable from run_daily.py or standalone CLI.
    """
    log.info("=== Cuban Insights Sitemap Sync ===")
    log.info("Canonical base: %s", CANONICAL_BASE)

    result: dict = {}

    # (a) Fetch live sitemap
    sitemap_paths = fetch_sitemap_urls()
    if not sitemap_paths:
        log.error("Could not fetch any sitemap URLs — aborting.")
        return {"error": "Could not fetch any sitemap URLs"}

    # (b) Extract source routes
    source_routes = extract_source_routes()

    result["live_urls"] = len(sitemap_paths)
    result["source_routes"] = len(source_routes)

    # (c) Diff and patch
    added = diff_and_patch(source_routes, sitemap_paths, dry_run=dry_run)
    result["missing"] = len(added)
    result["missing_paths"] = added

    # Report sitemap URLs that have no source route (might be stale)
    sitemap_only = sorted(sitemap_paths - source_routes)
    _dynamic_prefixes = ("/briefing/", "/companies/", "/sanctions/", "/people/", "/sectors/", "/explainers/")
    truly_stale = [
        p for p in sitemap_only
        if not any(p.startswith(dp) and p.count("/") > dp.count("/") - 1 for dp in _dynamic_prefixes)
        and p not in EXCLUDE_EXACT
        and not any(p.endswith(s) for s in EXCLUDE_SUFFIXES)
    ]
    if truly_stale:
        log.info("Sitemap URLs with no obvious source route (may be DB-dynamic):")
        for p in truly_stale[:30]:
            log.info("  SITEMAP-ONLY: %s", p)
    result["sitemap_only"] = len(sitemap_only)

    # (d) Spot-check
    dead_links: list[tuple[str, int]] = []
    if spot_check_enabled:
        dead_links = spot_check(sitemap_paths)
    else:
        log.info("Spot-check skipped")
    result["dead_links"] = len(dead_links)
    result["dead_link_details"] = [(p, c) for p, c in dead_links]

    # Git push if we patched anything
    pushed = False
    if added and not dry_run:
        pushed = git_commit_and_push(len(added))
        result["pushed"] = pushed

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cuban Insights — Nightly Sitemap Audit & Sync",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python scripts/sync_sitemap.py --dry-run                 # audit only
              python scripts/sync_sitemap.py --dry-run --no-spot-check # fast offline audit
              python scripts/sync_sitemap.py                           # full: patch + push
        """),
    )
    parser.add_argument("--dry-run", action="store_true", help="Audit only, no file changes or git push")
    parser.add_argument("--no-spot-check", action="store_true", help="Skip HTTP spot-checking live URLs")
    args = parser.parse_args()

    result = run_sync(dry_run=args.dry_run, spot_check_enabled=not args.no_spot_check)

    if "error" in result:
        return 1

    # Summary
    print()
    print("=" * 60)
    print("SITEMAP SYNC SUMMARY")
    print("=" * 60)
    print(f"  Live sitemap URLs:       {result['live_urls']}")
    print(f"  Source static routes:     {result['source_routes']}")
    print(f"  Missing (code→sitemap):  {result['missing']}")
    print(f"  Sitemap-only (dynamic):  {result['sitemap_only']}")
    if result["dead_links"]:
        print(f"  Dead links (spot-check): {result['dead_links']}")
        for path, code in result["dead_link_details"]:
            code_str = "ERR" if code < 0 else str(code)
            print(f"    [{code_str}] {path}")
    else:
        print(f"  Dead links (spot-check): 0")
    if "pushed" in result:
        print(f"  Git push:                {'OK' if result['pushed'] else 'FAILED'}")
    print("=" * 60)

    return 1 if result["dead_links"] else 0


if __name__ == "__main__":
    sys.exit(main())
