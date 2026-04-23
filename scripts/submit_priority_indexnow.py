"""Submit URLs listed in `seo/priority-indexing.txt` to IndexNow (Bing,
Yandex, Seznam, Naver, Mojeek). Complements the full
`indexnow_submit.py` backfill; use for a small priority set after deploy.

Usage (from project root, with .env or INDEXNOW_KEY in env):
  python scripts/submit_priority_indexnow.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("SITE_URL", "https://cubaninsights.com")

from src.config import settings  # noqa: E402
from src.distribution import indexnow  # noqa: E402

PRIORITY_FILE = os.path.join(ROOT, "seo", "priority-indexing.txt")


def main() -> int:
    if not (settings.indexnow_key or "").strip():
        print("ERROR: INDEXNOW_KEY is not set.")
        return 2
    if not os.path.isfile(PRIORITY_FILE):
        print(f"ERROR: {PRIORITY_FILE} not found.")
        return 2
    urls: list[str] = []
    with open(PRIORITY_FILE, encoding="utf-8") as f:
        for line in f:
            u = (line or "").strip()
            if u and u.startswith("http"):
                urls.append(u)
    if not urls:
        print("No URLs in priority file.")
        return 0
    print(f"Submitting {len(urls)} URL(s) to IndexNow…")
    result = indexnow.submit_urls(urls)
    print(f"status={result.status_code} success={result.success} n={result.submitted}")
    print(result.response_snippet[:500])
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
