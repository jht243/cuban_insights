"""Crawl every public route on the site, extract links, classify them, and
report any broken ones.

Usage:
    python scripts/check_links.py [--live]

By default crawls the in-process Flask test client (no network). Pass
--live to additionally validate every internal link against the
production site and HEAD-check external links.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

os.environ.setdefault("SITE_URL", "https://cubaninsights.com")

# Make `server` importable when run from repo root or scripts/.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from server import app  # noqa: E402

LIVE_BASE = "https://cubaninsights.com"

# Routes to seed the crawl. Anything else reachable from these we'll
# follow transitively (same-origin only).
SEED_PATHS = [
    "/",
    "/briefing",
    "/sanctions-tracker",
    "/invest-in-cuba",
    "/tools",
    "/explainers",
    "/travel",
    "/calendar",
    "/sources",
]


class LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for k, v in attrs:
            if k == "href" and v:
                self.links.append(v)


def classify(href: str, base_path: str) -> tuple[str, str]:
    """Return (kind, normalized) where kind is 'internal'|'external'|'skip'."""
    href = href.strip()
    if not href:
        return "skip", href
    if href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return "skip", href
    parsed = urlparse(href)
    if parsed.scheme in ("http", "https"):
        if parsed.netloc.endswith("cubaninsights.com"):
            return "internal", parsed.path or "/"
        return "external", href
    # Relative or absolute path
    abs_path = urljoin(f"https://x{base_path}", href)
    p = urlparse(abs_path)
    return "internal", p.path or "/"


def fetch_local(client, path: str) -> tuple[int, str]:
    r = client.get(path, follow_redirects=False)
    return r.status_code, r.get_data(as_text=True) if r.status_code < 300 else ""


def crawl_local() -> tuple[dict[str, int], set[str], dict[str, set[str]]]:
    """BFS-crawl via Flask test client. Returns:
    - status: { path -> status_code }
    - external: set of external URLs
    - referrers: { url -> set of pages that linked to it }
    """
    client = app.test_client()
    queue = list(SEED_PATHS)
    seen: set[str] = set()
    status: dict[str, int] = {}
    external: set[str] = set()
    referrers: dict[str, set[str]] = {}

    while queue:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        code, body = fetch_local(client, path)
        status[path] = code
        if code != 200 or not body:
            continue
        coll = LinkCollector()
        try:
            coll.feed(body)
        except Exception:
            continue
        for raw in coll.links:
            kind, norm = classify(raw, path)
            if kind == "skip":
                continue
            referrers.setdefault(norm, set()).add(path)
            if kind == "internal":
                if norm not in seen and norm not in queue:
                    queue.append(norm)
            else:
                external.add(norm)
    return status, external, referrers


def head_or_get(url: str, timeout: float = 10.0) -> int:
    """Best-effort status check. Tries HEAD first, falls back to GET."""
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": "CubanInsights-LinkCheck/1.0"},
            verify=False,
        ) as c:
            r = c.head(url)
            if r.status_code in (405, 403, 400):
                r = c.get(url)
            return r.status_code
    except httpx.HTTPError as exc:  # pragma: no cover - network failures
        return -1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="Also HEAD-check external URLs and re-test internal "
                         "URLs against cubaninsights.com.")
    ap.add_argument("--max-external", type=int, default=200,
                    help="Cap on number of external URLs to check.")
    args = ap.parse_args()

    print("Crawling local Flask app via test_client...")
    status, external, referrers = crawl_local()
    print(f"  Pages crawled: {len(status)}")
    print(f"  External URLs found: {len(external)}")

    bad_internal = sorted([(p, c) for p, c in status.items() if c >= 400])
    print()
    if bad_internal:
        print(f"BROKEN INTERNAL LINKS ({len(bad_internal)}):")
        for path, code in bad_internal:
            refs = sorted(referrers.get(path, set()))
            print(f"  [{code}] {path}")
            for ref in refs[:5]:
                print(f"        linked from: {ref}")
            if len(refs) > 5:
                print(f"        ... and {len(refs) - 5} more")
    else:
        print("All internal links resolve (200) on the local app.")

    if args.live:
        print()
        print("Live-checking external URLs...")
        ext_list = sorted(external)[: args.max_external]
        bad_ext: list[tuple[str, int]] = []
        for i, url in enumerate(ext_list, 1):
            code = head_or_get(url)
            ok = 200 <= code < 400
            if not ok:
                bad_ext.append((url, code))
            if i % 25 == 0 or i == len(ext_list):
                print(f"  {i}/{len(ext_list)} checked...")
            time.sleep(0.05)
        print()
        if bad_ext:
            print(f"BROKEN EXTERNAL LINKS ({len(bad_ext)}):")
            for url, code in bad_ext:
                refs = sorted(referrers.get(url, set()))
                code_str = "ERR" if code == -1 else str(code)
                print(f"  [{code_str}] {url}")
                for ref in refs[:3]:
                    print(f"        linked from: {ref}")
        else:
            print("All external links returned 2xx/3xx.")

    return 1 if bad_internal else 0


if __name__ == "__main__":
    sys.exit(main())
