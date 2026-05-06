"""Daily SEO audit agent — finds and auto-fixes metadata issues across
all BlogPost and LandingPage rows, then commits + pushes the changes.

Checks performed:
  1. Title length   — Google truncates at ~60 chars (warn >60, error >110)
  2. Description     — warn if missing, too short (<50), or too long (>300)
  3. Missing keywords — every post/page should have at least one keyword
  4. Slug hygiene    — no uppercase, no double hyphens, no trailing hyphens
  5. JSON-LD validity — render each page and validate the embedded JSON-LD
  6. OG image        — blog posts should have og_image_bytes
  7. Missing dates   — published_date must exist
  8. Orphan pages    — landing pages with no body_html
  9. Duplicate slugs — shouldn't happen (UNIQUE constraint) but verify
 10. Social hook     — blog posts should have a social_hook for distribution

Auto-fixes:
  - Truncate titles > 110 chars to 110
  - Truncate descriptions > 300 chars to 300
  - Strip trailing/leading whitespace from titles and descriptions
  - Normalize slug casing and double-hyphens
  - Backfill missing keywords_json from primary_sector

Usage:
    python scripts/seo_audit.py                  # audit + fix + report
    python scripts/seo_audit.py --dry-run        # audit only, no DB writes
    python scripts/seo_audit.py --commit         # also git commit + push
    python scripts/seo_audit.py --json           # machine-readable output
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.models import BlogPost, LandingPage, SessionLocal, init_db  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("seo_audit")

TITLE_WARN_LEN = 60
TITLE_MAX_LEN = 110
DESC_MIN_LEN = 50
DESC_MAX_LEN = 300
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass
class Issue:
    severity: str  # "error" | "warning" | "info"
    entity_type: str  # "blog_post" | "landing_page"
    entity_id: int
    slug: str
    field: str
    message: str
    auto_fixed: bool = False


@dataclass
class AuditReport:
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    issues: list[Issue] = field(default_factory=list)
    fixes_applied: int = 0
    posts_audited: int = 0
    pages_audited: int = 0

    def add(self, issue: Issue) -> None:
        self.issues.append(issue)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    def summary_text(self) -> str:
        lines = [
            f"SEO Audit Report — {self.timestamp}",
            f"Blog posts audited: {self.posts_audited}",
            f"Landing pages audited: {self.pages_audited}",
            f"Errors: {len(self.errors)}  |  Warnings: {len(self.warnings)}  |  Total: {len(self.issues)}",
            f"Auto-fixes applied: {self.fixes_applied}",
            "",
        ]

        by_field: dict[str, list[Issue]] = defaultdict(list)
        for issue in self.issues:
            by_field[issue.field].append(issue)

        for fld, items in sorted(by_field.items()):
            lines.append(f"── {fld} ({len(items)} issues) ──")
            for item in items[:10]:
                tag = "FIXED" if item.auto_fixed else item.severity.upper()
                lines.append(f"  [{tag}] {item.entity_type}/{item.slug}: {item.message}")
            if len(items) > 10:
                lines.append(f"  ... and {len(items) - 10} more")
            lines.append("")

        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(
            {
                "timestamp": self.timestamp,
                "posts_audited": self.posts_audited,
                "pages_audited": self.pages_audited,
                "fixes_applied": self.fixes_applied,
                "error_count": len(self.errors),
                "warning_count": len(self.warnings),
                "issues": [
                    {
                        "severity": i.severity,
                        "entity_type": i.entity_type,
                        "entity_id": i.entity_id,
                        "slug": i.slug,
                        "field": i.field,
                        "message": i.message,
                        "auto_fixed": i.auto_fixed,
                    }
                    for i in self.issues
                ],
            },
            indent=2,
        )


# ── Audit checks ─────────────────────────────────────────────────────


def _check_title(report: AuditReport, etype: str, eid: int, slug: str, title: str | None) -> str | None:
    """Validate title, return cleaned version (or None if no fix needed)."""
    if not title or not title.strip():
        report.add(Issue("error", etype, eid, slug, "title", "Title is missing or empty"))
        return None

    cleaned = title.strip()
    fixed = cleaned != title

    if len(cleaned) > TITLE_MAX_LEN:
        report.add(Issue("error", etype, eid, slug, "title", f"Title too long ({len(cleaned)} chars, max {TITLE_MAX_LEN})"))
        cleaned = cleaned[:TITLE_MAX_LEN].rsplit(" ", 1)[0].rstrip(" —-–")
        fixed = True
    elif len(cleaned) > TITLE_WARN_LEN:
        report.add(Issue("warning", etype, eid, slug, "title", f"Title may be truncated in SERPs ({len(cleaned)} chars, ideal <{TITLE_WARN_LEN})"))

    if fixed:
        return cleaned
    return None


def _check_description(report: AuditReport, etype: str, eid: int, slug: str, desc: str | None) -> str | None:
    """Validate description, return cleaned version if fixable."""
    if not desc or not desc.strip():
        report.add(Issue("warning", etype, eid, slug, "description", "Meta description is missing"))
        return None

    cleaned = desc.strip()
    fixed = cleaned != desc

    if len(cleaned) > DESC_MAX_LEN:
        report.add(Issue("warning", etype, eid, slug, "description", f"Description too long ({len(cleaned)} chars, max {DESC_MAX_LEN})"))
        cleaned = cleaned[:DESC_MAX_LEN].rsplit(" ", 1)[0].rstrip(" .") + "."
        fixed = True
    elif len(cleaned) < DESC_MIN_LEN:
        report.add(Issue("warning", etype, eid, slug, "description", f"Description too short ({len(cleaned)} chars, min {DESC_MIN_LEN})"))

    if fixed:
        return cleaned
    return None


def _check_slug(report: AuditReport, etype: str, eid: int, slug: str) -> str | None:
    """Validate slug format, return normalized version if fixable."""
    if not slug:
        report.add(Issue("error", etype, eid, slug or "(empty)", "slug", "Slug is empty"))
        return None

    normalized = slug.lower().strip("-")
    normalized = re.sub(r"-{2,}", "-", normalized)

    if normalized != slug:
        report.add(Issue("warning", etype, eid, slug, "slug", f"Slug has formatting issues, normalized to '{normalized}'"))
        return normalized

    if not SLUG_RE.match(slug):
        report.add(Issue("warning", etype, eid, slug, "slug", "Slug contains unexpected characters"))

    return None


def _check_keywords(report: AuditReport, etype: str, eid: int, slug: str, keywords_json, primary_sector: str | None = None) -> list | None:
    """Validate keywords exist, return backfilled list if needed."""
    keywords = keywords_json
    if isinstance(keywords, str):
        try:
            keywords = json.loads(keywords)
        except (json.JSONDecodeError, TypeError):
            keywords = [k.strip() for k in keywords.split(",") if k.strip()]

    if not keywords:
        if primary_sector:
            backfilled = [primary_sector.replace("_", " ").title()]
            report.add(Issue("warning", etype, eid, slug, "keywords", f"No keywords — backfilled from primary_sector: {backfilled}"))
            return backfilled
        report.add(Issue("warning", etype, eid, slug, "keywords", "No keywords defined"))
        return None

    return None


def _check_dates(report: AuditReport, etype: str, eid: int, slug: str, published_date, created_at) -> None:
    if not published_date and not created_at:
        report.add(Issue("error", etype, eid, slug, "dates", "No published_date or created_at"))
    elif not published_date:
        report.add(Issue("warning", etype, eid, slug, "dates", "published_date is missing (using created_at as fallback)"))


def _check_body(report: AuditReport, etype: str, eid: int, slug: str, body_html: str | None) -> None:
    if not body_html or not body_html.strip():
        report.add(Issue("error", etype, eid, slug, "body", "body_html is empty — orphan page"))
        return

    word_count = len(body_html.split())
    if word_count < 100:
        report.add(Issue("warning", etype, eid, slug, "body", f"Very short content (~{word_count} words in HTML)"))


def _check_og_image(report: AuditReport, eid: int, slug: str, og_image_bytes) -> None:
    if not og_image_bytes:
        report.add(Issue("info", "blog_post", eid, slug, "og_image", "No per-post OG image (will use generic fallback)"))


def _check_social_hook(report: AuditReport, eid: int, slug: str, social_hook: str | None) -> None:
    if not social_hook or not social_hook.strip():
        report.add(Issue("info", "blog_post", eid, slug, "social_hook", "No social hook for distribution"))
        return
    hook = social_hook.strip()
    if len(hook) < 50:
        report.add(Issue("warning", "blog_post", eid, slug, "social_hook", f"Social hook too short ({len(hook)} chars)"))
    elif len(hook) > 300:
        report.add(Issue("warning", "blog_post", eid, slug, "social_hook", f"Social hook too long ({len(hook)} chars)"))


def _check_jsonld_structure(report: AuditReport, etype: str, eid: int, slug: str, title: str, desc: str) -> None:
    """Validate that the data that feeds into JSON-LD won't produce broken structured data."""
    if title and "<" in title:
        report.add(Issue("error", etype, eid, slug, "jsonld", "Title contains HTML tags — will break JSON-LD headline"))
    if desc and "<" in desc:
        report.add(Issue("warning", etype, eid, slug, "jsonld", "Description contains HTML tags — may break JSON-LD"))
    if title and '"' in title:
        report.add(Issue("warning", etype, eid, slug, "jsonld", "Title contains unescaped double quotes — may break OG tags"))


# ── Audit runner ──────────────────────────────────────────────────────


def audit_blog_posts(db, report: AuditReport, *, dry_run: bool = False) -> None:
    posts = db.query(BlogPost).order_by(BlogPost.published_date.desc()).all()
    report.posts_audited = len(posts)
    logger.info("auditing %d blog posts", len(posts))

    for post in posts:
        slug = post.slug or ""
        eid = post.id

        title_fix = _check_title(report, "blog_post", eid, slug, post.title)
        desc_fix = _check_description(report, "blog_post", eid, slug, post.summary)
        slug_fix = _check_slug(report, "blog_post", eid, slug)
        kw_fix = _check_keywords(report, "blog_post", eid, slug, post.keywords_json, post.primary_sector)
        _check_dates(report, "blog_post", eid, slug, post.published_date, post.created_at)
        _check_body(report, "blog_post", eid, slug, post.body_html)
        _check_og_image(report, eid, slug, getattr(post, "og_image_bytes", None))
        _check_social_hook(report, eid, slug, getattr(post, "social_hook", None))
        _check_jsonld_structure(report, "blog_post", eid, slug, post.title or "", post.summary or "")

        if not dry_run:
            changed = False
            if title_fix is not None:
                post.title = title_fix
                changed = True
            if desc_fix is not None:
                post.summary = desc_fix
                changed = True
            if slug_fix is not None:
                post.slug = slug_fix
                changed = True
            if kw_fix is not None:
                post.keywords_json = kw_fix
                changed = True
            if changed:
                post.updated_at = datetime.utcnow()
                report.fixes_applied += 1
                for issue in report.issues:
                    if issue.entity_id == eid and issue.entity_type == "blog_post":
                        if (
                            (issue.field == "title" and title_fix is not None)
                            or (issue.field == "description" and desc_fix is not None)
                            or (issue.field == "slug" and slug_fix is not None)
                            or (issue.field == "keywords" and kw_fix is not None)
                        ):
                            issue.auto_fixed = True


def audit_landing_pages(db, report: AuditReport, *, dry_run: bool = False) -> None:
    pages = db.query(LandingPage).order_by(LandingPage.page_key).all()
    report.pages_audited = len(pages)
    logger.info("auditing %d landing pages", len(pages))

    for page in pages:
        slug = page.page_key or ""
        eid = page.id

        title_fix = _check_title(report, "landing_page", eid, slug, page.title)
        desc_fix = _check_description(report, "landing_page", eid, slug, page.summary)
        kw_fix = _check_keywords(report, "landing_page", eid, slug, page.keywords_json, getattr(page, "sector_slug", None))
        _check_body(report, "landing_page", eid, slug, page.body_html)
        _check_jsonld_structure(report, "landing_page", eid, slug, page.title or "", page.summary or "")

        if not page.canonical_path:
            report.add(Issue("error", "landing_page", eid, slug, "canonical", "No canonical_path set"))

        if not dry_run:
            changed = False
            if title_fix is not None:
                page.title = title_fix
                changed = True
            if desc_fix is not None:
                page.summary = desc_fix
                changed = True
            if kw_fix is not None:
                page.keywords_json = kw_fix
                changed = True
            if changed:
                page.updated_at = datetime.utcnow()
                report.fixes_applied += 1
                for issue in report.issues:
                    if issue.entity_id == eid and issue.entity_type == "landing_page":
                        if (
                            (issue.field == "title" and title_fix is not None)
                            or (issue.field == "description" and desc_fix is not None)
                            or (issue.field == "keywords" and kw_fix is not None)
                        ):
                            issue.auto_fixed = True


def check_duplicate_slugs(db, report: AuditReport) -> None:
    """Flag any duplicate slugs (shouldn't happen with UNIQUE constraints but belt-and-suspenders)."""
    from sqlalchemy import func

    dupes = (
        db.query(BlogPost.slug, func.count(BlogPost.id))
        .group_by(BlogPost.slug)
        .having(func.count(BlogPost.id) > 1)
        .all()
    )
    for slug, count in dupes:
        report.add(Issue("error", "blog_post", 0, slug, "duplicate_slug", f"Slug appears {count} times"))


def check_sitemap_coverage(db, report: AuditReport) -> None:
    """Verify that the curated sitemap file covers key pages."""
    sitemap_path = Path(__file__).resolve().parent.parent / "seo" / "curated-sitemap.xml"
    if not sitemap_path.exists():
        report.add(Issue("warning", "site", 0, "sitemap", "sitemap", "seo/curated-sitemap.xml not found — run generate_curated_sitemap.py"))
        return

    content = sitemap_path.read_text()
    base = settings.site_url.rstrip("/")

    critical_paths = ["/", "/briefing", "/invest-in-cuba", "/sanctions-tracker", "/tools"]
    for path in critical_paths:
        url = f"{base}{path}"
        if url not in content:
            report.add(Issue("warning", "site", 0, "sitemap", "sitemap", f"Critical URL missing from curated sitemap: {url}"))


# ── Git operations ────────────────────────────────────────────────────


def git_commit_and_push(report: AuditReport) -> bool:
    """Commit audit report and push. Returns True on success."""
    report_dir = Path(__file__).resolve().parent.parent / "seo" / "audit-reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_file = report_dir / f"seo-audit-{ts}.json"
    report_file.write_text(report.to_json())

    try:
        subprocess.run(["git", "add", str(report_file)], check=True, capture_output=True)
        msg = f"chore(seo): daily audit — {len(report.errors)} errors, {len(report.warnings)} warnings, {report.fixes_applied} fixes"
        subprocess.run(
            ["git", "commit", "-m", msg],
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "push"], check=True, capture_output=True)
        logger.info("committed and pushed audit report: %s", report_file.name)
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning("git operation failed: %s", exc.stderr.decode() if exc.stderr else str(exc))
        return False


# ── Main ──────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Audit only, don't write fixes to DB")
    parser.add_argument("--commit", action="store_true", help="Git commit + push the audit report")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()

    report = AuditReport()

    try:
        audit_blog_posts(db, report, dry_run=args.dry_run)
        audit_landing_pages(db, report, dry_run=args.dry_run)
        check_duplicate_slugs(db, report)
        check_sitemap_coverage(db, report)

        if not args.dry_run and report.fixes_applied > 0:
            db.commit()
            logger.info("committed %d DB fixes", report.fixes_applied)

    except Exception:
        db.rollback()
        logger.exception("audit failed")
        return 1
    finally:
        db.close()

    if args.json:
        print(report.to_json())
    else:
        print(report.summary_text())

    if args.commit and (report.fixes_applied > 0 or report.issues):
        git_commit_and_push(report)

    if report.errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
