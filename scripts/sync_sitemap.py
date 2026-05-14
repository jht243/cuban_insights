#!/usr/bin/env python3
"""Nightly sitemap audit & sync for Cuban Insights.

Fetches all live child sitemaps, extracts Flask route declarations from
server.py, diffs the two sets, auto-patches missing static URLs into
_core_static_urls(), verifies every hardcoded URL is live, removes dead
or redirecting entries, spot-checks a sample of dynamic URLs, and pushes
all fixes in a single commit.

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
SYNC_SCRIPT = os.path.abspath(__file__)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")

SPOT_CHECK_SAMPLE = 25

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
    # Redirect aliases — only the canonical target belongs in the sitemap.
    "/briefing/us-cuba-diplomatic-meeting-2026",
    "/sanctions/hotel-san-alejandro",
    "/sanctions/hotel-san-fernando",
    "/travel/cuba-prohibited-accommodations-list",
})
EXCLUDE_CONTAINS = ("noindex", "debug", "test")

# Regex to find the closing bracket of _core_static_urls()'s return list.
# New entries are inserted just before the closing `]`.
_CORE_LIST_END_RE = re.compile(
    r'(        \{"loc": f"\{base\}/[^"]+",\s*"lastmod":[^}]+\},?\s*\n)'
    r'(\s*\]\s*\n)',
)

# Regex to extract paths from _core_static_urls() dict literals
_HARDCODED_LOC_RE = re.compile(
    r'\{\s*"loc"\s*:\s*f"\{base\}(/[^"]+)"\s*,'
)

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


# ── (c) Diff & auto-patch (add missing) ──────────────────────────────

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
    """Find routes in code not in the sitemap, auto-insert if possible."""
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

    # Find the end of _core_static_urls()'s return list
    fn_start = content.find("def _core_static_urls()")
    if fn_start < 0:
        log.error("Cannot find _core_static_urls() in %s", APP_FILE)
        return missing

    # Find the closing ] of the return list
    fn_body = content[fn_start:]
    bracket_match = re.search(r'\n(\s*\]\s*\n)', fn_body)
    if not bracket_match:
        log.error("Cannot find closing ] of _core_static_urls() return list")
        return missing

    insert_pos = fn_start + bracket_match.start() + 1  # after the \n before ]

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
    content = content[:insert_pos] + insert_block + content[insert_pos:]

    with open(APP_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    log.info("Inserted %d new entries into _core_static_urls()", len(missing))
    return missing


# ── (d) Verify hardcoded URLs & remove bad ones ─────────────────────

def _extract_hardcoded_paths() -> list[str]:
    """Parse _core_static_urls() in server.py and return every hardcoded path."""
    with open(APP_FILE, encoding="utf-8") as f:
        source = f.read()
    # Find the function body
    start = source.find("def _core_static_urls()")
    if start < 0:
        return []
    end = source.find("\n\n", start)
    if end < 0:
        end = len(source)
    block = source[start:end]
    return _HARDCODED_LOC_RE.findall(block)


def verify_hardcoded_urls() -> tuple[list[tuple[str, int]], list[tuple[str, int, str]]]:
    """HTTP-check every hardcoded URL in _core_static_urls().

    Returns (dead_links, redirects) where each item is
    (path, status_code) or (path, status_code, location).
    """
    paths = _extract_hardcoded_paths()
    if not paths:
        log.warning("Could not extract hardcoded paths from _core_static_urls()")
        return [], []

    log.info("Verifying %d hardcoded URLs from _core_static_urls()...", len(paths))
    dead: list[tuple[str, int]] = []
    redirects: list[tuple[str, int, str]] = []

    with httpx.Client(
        timeout=15,
        follow_redirects=False,
        headers={"User-Agent": "CubanInsights-SitemapAudit/1.0"},
    ) as client:
        for path in paths:
            url = f"{CANONICAL_BASE}{path}"
            try:
                resp = client.get(url)
                code = resp.status_code
            except Exception:
                code = -1
            if code >= 400 or code < 0:
                dead.append((path, code))
                log.warning("DEAD hardcoded URL: %s → %d", path, code)
            elif 300 <= code < 400:
                loc = resp.headers.get("location", "")
                redirects.append((path, code, loc))
                log.warning("REDIRECT hardcoded URL: %s → %d (%s)", path, code, loc)

    return dead, redirects


def remove_hardcoded_urls(paths_to_remove: list[str], dry_run: bool) -> int:
    """Remove entries from _core_static_urls() in server.py for the given paths."""
    if not paths_to_remove:
        return 0
    if dry_run:
        log.info("Dry-run: would remove %d hardcoded URL(s)", len(paths_to_remove))
        return len(paths_to_remove)

    with open(APP_FILE, encoding="utf-8") as f:
        lines = f.readlines()

    removed = 0
    filtered: list[str] = []
    for line in lines:
        skip = False
        for path in paths_to_remove:
            # Match the dict literal line for this path
            if f'f"{{base}}{path}"' in line or f'f"{{base}}{path}/"' in line:
                log.info("Removing hardcoded entry: %s", path)
                skip = True
                removed += 1
                break
        if not skip:
            filtered.append(line)

    if removed:
        with open(APP_FILE, "w", encoding="utf-8") as f:
            f.writelines(filtered)
        log.info("Removed %d dead/redirect entries from _core_static_urls()", removed)
    return removed


# ── (e) Spot-check dynamic URLs ──────────────────────────────────────

def spot_check_dynamic(
    sitemap_paths: set[str],
    hardcoded_paths: set[str],
    count: int = SPOT_CHECK_SAMPLE,
) -> list[tuple[str, int]]:
    """GET-check a random sample of dynamic (non-hardcoded) sitemap URLs."""
    dynamic = sorted(sitemap_paths - hardcoded_paths)
    if not dynamic:
        return []

    sample = random.sample(dynamic, min(count, len(dynamic)))
    issues: list[tuple[str, int]] = []

    with httpx.Client(
        timeout=15,
        follow_redirects=False,
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
                issues.append((path, code))
                log.warning("DEAD dynamic URL: %s → %d", path, code)
            elif 300 <= code < 400:
                issues.append((path, code))
                loc = resp.headers.get("location", "")
                log.warning("REDIRECT dynamic URL: %s → %d (%s)", path, code, loc)
            else:
                log.debug("OK: %s → %d", path, code)

    if issues:
        log.warning("Spot-check found %d issue(s) out of %d dynamic URLs sampled", len(issues), len(sample))
    else:
        log.info("Spot-check: all %d dynamic URLs returned 2xx", len(sample))
    return issues


# ── (f) Auto-add redirect aliases to EXCLUDE_EXACT ──────────────────

def auto_update_exclude_exact(redirect_paths: list[str], dry_run: bool) -> int:
    """Append newly-discovered redirect aliases to EXCLUDE_EXACT in this script."""
    if not redirect_paths:
        return 0

    with open(SYNC_SCRIPT, encoding="utf-8") as f:
        content = f.read()

    already_excluded = set()
    for p in redirect_paths:
        if f'"{p}"' in content:
            already_excluded.add(p)

    new_excludes = [p for p in redirect_paths if p not in already_excluded]
    if not new_excludes:
        return 0

    if dry_run:
        log.info("Dry-run: would add %d path(s) to EXCLUDE_EXACT", len(new_excludes))
        return len(new_excludes)

    # Insert before the closing })
    anchor = "})\nEXCLUDE_CONTAINS"
    if anchor not in content:
        log.warning("Could not find EXCLUDE_EXACT closing anchor — skipping auto-update")
        return 0

    new_lines = "\n".join(f'    "{p}",' for p in sorted(new_excludes))
    replacement = f"{new_lines}\n}})\nEXCLUDE_CONTAINS"
    content = content.replace(anchor, replacement)

    with open(SYNC_SCRIPT, "w", encoding="utf-8") as f:
        f.write(content)

    log.info("Added %d redirect alias(es) to EXCLUDE_EXACT", len(new_excludes))
    return len(new_excludes)


# ── Git commit & push ────────────────────────────────────────────────

def git_commit_and_push(message: str, files: list[str]) -> bool:
    """Commit the specified files and push to origin/main."""
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
        for f in files:
            _run(["git", "add", f])
        _run(["git", "commit", "-m", message])
        _run(["git", "push", "origin", "HEAD:main"])
        log.info("Committed and pushed: %s", message)
        return True
    except subprocess.CalledProcessError as exc:
        log.error("Git operation failed: %s\nstdout: %s\nstderr: %s", exc.cmd, exc.stdout, exc.stderr)
        return False


# ── Orchestrator ─────────────────────────────────────────────────────

def run_sync(*, dry_run: bool = False, spot_check_enabled: bool = True) -> dict:
    """Run the full sitemap audit & sync. Returns a summary dict."""
    log.info("=== Cuban Insights Sitemap Sync ===")
    log.info("Canonical base: %s", CANONICAL_BASE)

    result: dict = {
        "added": 0, "removed": 0, "dead_links": 0,
        "excludes_added": 0, "fixes": [],
    }
    files_changed: set[str] = set()

    # (a) Fetch live sitemap
    sitemap_paths = fetch_sitemap_urls()
    if not sitemap_paths:
        log.error("Could not fetch any sitemap URLs — aborting.")
        return {"error": "Could not fetch any sitemap URLs"}

    # (b) Extract source routes
    source_routes = extract_source_routes()
    result["live_urls"] = len(sitemap_paths)
    result["source_routes"] = len(source_routes)

    # (c) Add missing routes
    added = diff_and_patch(source_routes, sitemap_paths, dry_run=dry_run)
    result["added"] = len(added)
    if added and not dry_run:
        files_changed.add(APP_FILE)
        result["fixes"].append(f"added {len(added)} missing route(s)")

    # (d) Verify ALL hardcoded URLs — remove dead & redirect entries
    dead_hardcoded, redirect_hardcoded = verify_hardcoded_urls()

    paths_to_remove: list[str] = []
    redirect_paths: list[str] = []

    for path, code in dead_hardcoded:
        paths_to_remove.append(path)
        log.info("AUTO-FIX: removing dead hardcoded URL %s (HTTP %d)", path, code)
    for path, code, loc in redirect_hardcoded:
        paths_to_remove.append(path)
        redirect_paths.append(path)
        log.info("AUTO-FIX: removing redirect alias %s → %s from sitemap", path, loc)

    removed = remove_hardcoded_urls(paths_to_remove, dry_run=dry_run)
    result["removed"] = removed
    if removed and not dry_run:
        files_changed.add(APP_FILE)
        result["fixes"].append(f"removed {removed} dead/redirect URL(s)")

    # Auto-add redirect aliases to EXCLUDE_EXACT so they stay excluded
    excludes_added = auto_update_exclude_exact(redirect_paths, dry_run=dry_run)
    result["excludes_added"] = excludes_added
    if excludes_added and not dry_run:
        files_changed.add(SYNC_SCRIPT)
        result["fixes"].append(f"added {excludes_added} path(s) to EXCLUDE_EXACT")

    # (e) Spot-check dynamic URLs
    hardcoded_set = set(_extract_hardcoded_paths())
    dynamic_issues: list[tuple[str, int]] = []
    if spot_check_enabled:
        dynamic_issues = spot_check_dynamic(sitemap_paths, hardcoded_set)
    result["dead_links"] = len(dead_hardcoded) + len(redirect_hardcoded) + len(dynamic_issues)
    result["dead_link_details"] = (
        [(p, c) for p, c in dead_hardcoded]
        + [(p, c) for p, c, _ in redirect_hardcoded]
        + dynamic_issues
    )
    result["dynamic_issues"] = dynamic_issues

    # Report stale sitemap-only paths
    sitemap_only = sorted(sitemap_paths - source_routes)
    _dynamic_prefixes = ("/briefing/", "/companies/", "/sanctions/", "/people/", "/sectors/", "/explainers/")
    truly_stale = [
        p for p in sitemap_only
        if not any(p.startswith(dp) and p.count("/") > dp.count("/") - 1 for dp in _dynamic_prefixes)
        and p not in EXCLUDE_EXACT
        and not any(p.endswith(s) for s in EXCLUDE_SUFFIXES)
    ]
    if truly_stale:
        log.info("Sitemap-only URLs (DB-dynamic, not auto-fixable):")
        for p in truly_stale[:30]:
            log.info("  SITEMAP-ONLY: %s", p)
    result["sitemap_only"] = len(sitemap_only)

    # Git push if anything changed
    if files_changed and not dry_run:
        parts = []
        if added:
            parts.append(f"add {len(added)} missing")
        if removed:
            parts.append(f"remove {removed} dead/redirect")
        if excludes_added:
            parts.append(f"update {excludes_added} exclusion(s)")
        msg = f"sitemap: auto-fix — {', '.join(parts)}"
        pushed = git_commit_and_push(msg, sorted(files_changed))
        result["pushed"] = pushed
    elif added and dry_run:
        result["fixes"].append(f"(dry-run) would add {len(added)} missing route(s)")
    if removed and dry_run:
        result["fixes"].append(f"(dry-run) would remove {removed} dead/redirect URL(s)")

    result["all_fixed"] = len(dynamic_issues) == 0
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
    parser.add_argument("--no-spot-check", action="store_true", help="Skip HTTP spot-checking dynamic URLs")
    args = parser.parse_args()

    result = run_sync(dry_run=args.dry_run, spot_check_enabled=not args.no_spot_check)

    if "error" in result:
        return 1

    print()
    print("=" * 60)
    print("SITEMAP SYNC SUMMARY")
    print("=" * 60)
    print(f"  Live sitemap URLs:       {result['live_urls']}")
    print(f"  Source static routes:     {result['source_routes']}")
    print(f"  Added (missing→sitemap): {result['added']}")
    print(f"  Removed (dead/redirect): {result['removed']}")
    print(f"  Exclusions updated:      {result['excludes_added']}")
    print(f"  Sitemap-only (dynamic):  {result['sitemap_only']}")
    if result.get("dynamic_issues"):
        print(f"  Dynamic URL issues:      {len(result['dynamic_issues'])}")
        for path, code in result["dynamic_issues"]:
            code_str = "ERR" if code < 0 else str(code)
            print(f"    [{code_str}] {path}")
    else:
        print(f"  Dynamic URL issues:      0")
    if result.get("fixes"):
        print(f"  Fixes applied:")
        for fix in result["fixes"]:
            print(f"    • {fix}")
    if "pushed" in result:
        print(f"  Git push:                {'OK' if result['pushed'] else 'FAILED'}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
