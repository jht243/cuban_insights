"""One-shot repair: clean up broken internal links in stored LandingPage
bodies that LLM-generated content baked in (literal /tools/* and
/sectors/* placeholders, plus mistyped /sectors/realestate).

Run once. Safe to re-run — it's idempotent (string replace).

    python scripts/fix_broken_landing_links.py [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import re
import sys

os.environ.setdefault("SITE_URL", "https://cubaninsights.com")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.models import LandingPage, SessionLocal, init_db  # noqa: E402

# Each entry: (regex, replacement, description). Order matters — fix the
# specific cases first, then the general placeholders.
FIXES: list[tuple[str, str, str]] = [
    # Mistyped slug — the real sector is real-estate (with a hyphen).
    (r'href="/sectors/realestate"',
     'href="/sectors/real-estate"',
     "/sectors/realestate -> /sectors/real-estate"),
    # Bare /sectors/ index doesn't exist; route the user to the parent pillar.
    (r'href="/sectors/?"',
     'href="/invest-in-cuba"',
     "/sectors/ -> /invest-in-cuba"),
    # Literal placeholders the LLM didn't expand.
    (r'href="/sectors/\*"',
     'href="/invest-in-cuba"',
     "/sectors/* -> /invest-in-cuba"),
    (r'href="/tools/\*"',
     'href="/tools"',
     "/tools/* -> /tools"),
    # Belt-and-suspenders: also fix any unquoted/escaped variants.
    (r"/sectors/realestate\b", "/sectors/real-estate", "bare /sectors/realestate"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()
    try:
        pages = db.query(LandingPage).all()
        print(f"Scanning {len(pages)} landing pages...")
        total_changes = 0
        changed_pages = 0
        for page in pages:
            html = page.body_html or ""
            new_html = html
            page_changes = 0
            for pattern, repl, desc in FIXES:
                fixed, n = re.subn(pattern, repl, new_html, flags=re.IGNORECASE)
                if n > 0:
                    page_changes += n
                    print(f"  [{page.page_key}] {desc}: {n} fix(es)")
                    new_html = fixed
            if page_changes:
                changed_pages += 1
                total_changes += page_changes
                if not args.dry_run:
                    page.body_html = new_html
        if not args.dry_run and total_changes:
            db.commit()
            print(f"\nCommitted {total_changes} fix(es) across {changed_pages} page(s).")
        elif args.dry_run:
            print(f"\nDRY RUN: would fix {total_changes} link(s) across {changed_pages} page(s).")
        else:
            print("\nNo fixes needed.")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
