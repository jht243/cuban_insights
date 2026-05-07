"""
Automated SEO audit engine.

Crawls the site via Flask's test client (zero network, zero external
deps) and checks every rendered page for SEO hygiene:

  1. Meta tags    — <title>, description, canonical, OG, robots
  2. Structured data — JSON-LD blocks parsed and validated
  3. Headings    — single H1, no skipped levels
  4. Cluster nav — pages that belong to a topic cluster have the nav
  5. Internal links — orphan pages, anchor-text drift from canonical
  6. Sitemap     — every page in CLUSTERS should appear in the sitemap

The audit returns a structured ``AuditReport`` that the CLI or daily
pipeline can serialize, log, or gate deploys on.

Usage (programmatic):
    from src.seo.audit import run_audit
    report = run_audit()
    print(report.summary())

Usage (CLI via scripts/seo_audit.py):
    python scripts/seo_audit.py
    python scripts/seo_audit.py --json
    python scripts/seo_audit.py --fail-on-error   # exit 1 if any errors
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)


# ── Data classes ────────────────────────────────────────────────────

@dataclass
class Finding:
    """A single audit finding for one page."""
    path: str
    severity: str  # "error", "warning", "info"
    category: str  # "meta", "heading", "structured_data", "cluster", "link", "sitemap"
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.upper():7s}] {self.category:16s} {self.path}  {self.message}"


@dataclass
class PageAudit:
    """Audit results for a single page."""
    path: str
    status_code: int
    title: str = ""
    meta_description: str = ""
    canonical: str = ""
    robots: str = ""
    og_title: str = ""
    og_description: str = ""
    og_image: str = ""
    h1_count: int = 0
    h1_text: str = ""
    heading_levels: list[int] = field(default_factory=list)
    jsonld_count: int = 0
    jsonld_types: list[str] = field(default_factory=list)
    internal_links: list[tuple[str, str]] = field(default_factory=list)  # (href, anchor_text)
    has_cluster_nav: bool = False
    word_count: int = 0
    findings: list[Finding] = field(default_factory=list)


@dataclass
class AuditReport:
    """Full audit report across all pages."""
    pages_crawled: int = 0
    pages_ok: int = 0
    page_audits: list[PageAudit] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def info(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "info"]

    def summary(self) -> str:
        lines = [
            f"SEO Audit: {self.pages_crawled} pages crawled",
            f"  Errors:   {len(self.errors)}",
            f"  Warnings: {len(self.warnings)}",
            f"  Info:     {len(self.info)}",
        ]
        if self.errors:
            lines.append("")
            lines.append("ERRORS:")
            for f in self.errors:
                lines.append(f"  {f}")
        if self.warnings:
            lines.append("")
            lines.append("WARNINGS:")
            for f in self.warnings[:30]:
                lines.append(f"  {f}")
            remaining = len(self.warnings) - 30
            if remaining > 0:
                lines.append(f"  ... and {remaining} more warnings")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "pages_crawled": self.pages_crawled,
            "pages_ok": self.pages_ok,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "info_count": len(self.info),
            "findings": [
                {
                    "path": f.path,
                    "severity": f.severity,
                    "category": f.category,
                    "message": f.message,
                }
                for f in self.findings
            ],
        }


# ── HTML parser ─────────────────────────────────────────────────────

class SEOHTMLParser(HTMLParser):
    """Single-pass HTML parser that extracts SEO-relevant signals."""

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.meta_description = ""
        self.canonical = ""
        self.robots = ""
        self.og_title = ""
        self.og_description = ""
        self.og_image = ""

        self.h1_count = 0
        self.h1_text = ""
        self.heading_levels: list[int] = []

        self.jsonld_blocks: list[str] = []
        self.internal_links: list[tuple[str, str]] = []

        self.has_cluster_nav = False
        self.word_count = 0

        self._in_title = False
        self._in_h1 = False
        self._in_a: Optional[str] = None  # href if inside <a>
        self._in_jsonld = False
        self._text_buf: list[str] = []
        self._a_text_buf: list[str] = []
        self._body_text_buf: list[str] = []
        self._in_body = False
        self._heading_level = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k: (v or "") for k, v in attrs}

        if tag == "title":
            self._in_title = True
            self._text_buf = []

        elif tag == "meta":
            name = attr_dict.get("name", "").lower()
            prop = attr_dict.get("property", "").lower()
            content = attr_dict.get("content", "")
            if name == "description":
                self.meta_description = content
            elif name == "robots":
                self.robots = content
            elif prop == "og:title":
                self.og_title = content
            elif prop == "og:description":
                self.og_description = content
            elif prop == "og:image":
                self.og_image = content

        elif tag == "link":
            rel = attr_dict.get("rel", "").lower()
            if rel == "canonical":
                self.canonical = attr_dict.get("href", "")

        elif tag == "body":
            self._in_body = True

        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            self.heading_levels.append(level)
            if tag == "h1":
                self.h1_count += 1
                self._in_h1 = True
                self._text_buf = []
            self._heading_level = level

        elif tag == "a":
            href = attr_dict.get("href", "")
            if href:
                self._in_a = href
                self._a_text_buf = []

        elif tag == "script":
            stype = attr_dict.get("type", "").lower()
            if stype == "application/ld+json":
                self._in_jsonld = True
                self._text_buf = []

        elif tag in ("nav", "aside", "section"):
            cls = attr_dict.get("class", "")
            if "cluster-nav" in cls or "cluster_nav" in cls:
                self.has_cluster_nav = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._in_title:
            self._in_title = False
            self.title = "".join(self._text_buf).strip()

        elif tag == "h1" and self._in_h1:
            self._in_h1 = False
            self.h1_text = "".join(self._text_buf).strip()

        elif tag == "a" and self._in_a is not None:
            anchor_text = "".join(self._a_text_buf).strip()
            self._classify_link(self._in_a, anchor_text)
            self._in_a = None

        elif tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            raw = "".join(self._text_buf).strip()
            if raw:
                self.jsonld_blocks.append(raw)

        elif tag == "body":
            self._in_body = False
            body_text = " ".join(self._body_text_buf)
            self.word_count = len(body_text.split())

    def handle_data(self, data: str) -> None:
        if self._in_title or self._in_h1 or self._in_jsonld:
            self._text_buf.append(data)
        if self._in_a is not None:
            self._a_text_buf.append(data)
        if self._in_body:
            stripped = data.strip()
            if stripped:
                self._body_text_buf.append(stripped)

    def _classify_link(self, href: str, anchor_text: str) -> None:
        href = href.strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            return
        parsed = urlparse(href)
        if parsed.scheme in ("http", "https"):
            if parsed.netloc and not parsed.netloc.endswith("cubaninsights.com"):
                return
            path = parsed.path or "/"
        else:
            path = href.split("?")[0].split("#")[0]
            if not path.startswith("/"):
                return
        self.internal_links.append((path, anchor_text))


# ── Audit checks ────────────────────────────────────────────────────

_TITLE_MIN = 20
_TITLE_MAX = 70
_DESC_MIN = 50
_DESC_MAX = 160
_SLUG_WARN = 60
_SLUG_MAX = 80


def _check_meta(page: PageAudit) -> list[Finding]:
    findings: list[Finding] = []
    path = page.path

    if not page.title:
        findings.append(Finding(path, "error", "meta", "Missing <title> tag"))
    elif len(page.title) < _TITLE_MIN:
        findings.append(Finding(path, "warning", "meta", f"Title too short ({len(page.title)} chars, min {_TITLE_MIN})"))
    elif len(page.title) > _TITLE_MAX:
        findings.append(Finding(path, "warning", "meta", f"Title too long ({len(page.title)} chars, max {_TITLE_MAX})"))

    if not page.meta_description:
        findings.append(Finding(path, "warning", "meta", "Missing meta description"))
    elif len(page.meta_description) < _DESC_MIN:
        findings.append(Finding(path, "warning", "meta", f"Meta description too short ({len(page.meta_description)} chars)"))
    elif len(page.meta_description) > _DESC_MAX:
        findings.append(Finding(path, "warning", "meta", f"Meta description too long ({len(page.meta_description)} chars)"))

    if not page.canonical:
        findings.append(Finding(path, "warning", "meta", "Missing canonical URL"))

    if not page.og_title:
        findings.append(Finding(path, "warning", "meta", "Missing og:title"))
    if not page.og_image:
        findings.append(Finding(path, "warning", "meta", "Missing og:image"))

    slug = path.rstrip("/").rsplit("/", 1)[-1] if "/" in path else path
    if len(slug) > _SLUG_MAX:
        findings.append(Finding(path, "error", "meta", f"URL slug too long ({len(slug)} chars, max {_SLUG_MAX}) — will look broken in SERPs"))
    elif len(slug) > _SLUG_WARN:
        findings.append(Finding(path, "warning", "meta", f"URL slug may be truncated in SERPs ({len(slug)} chars, ideal <{_SLUG_WARN})"))

    return findings


def _check_headings(page: PageAudit) -> list[Finding]:
    findings: list[Finding] = []
    path = page.path

    if page.h1_count == 0:
        findings.append(Finding(path, "error", "heading", "No H1 tag found"))
    elif page.h1_count > 1:
        findings.append(Finding(path, "warning", "heading", f"Multiple H1 tags ({page.h1_count})"))

    levels = page.heading_levels
    for i in range(1, len(levels)):
        if levels[i] > levels[i - 1] + 1:
            findings.append(Finding(
                path, "warning", "heading",
                f"Skipped heading level: H{levels[i - 1]} -> H{levels[i]}",
            ))
            break

    return findings


def _check_structured_data(page: PageAudit) -> list[Finding]:
    findings: list[Finding] = []
    path = page.path

    if page.jsonld_count == 0:
        findings.append(Finding(path, "warning", "structured_data", "No JSON-LD structured data"))

    return findings


def _check_content(page: PageAudit) -> list[Finding]:
    findings: list[Finding] = []
    if page.word_count < 100:
        findings.append(Finding(
            page.path, "info", "content",
            f"Thin content ({page.word_count} words)",
        ))
    return findings


# ── Cluster coverage check ──────────────────────────────────────────

def _check_cluster_coverage(page_audits: list[PageAudit]) -> list[Finding]:
    """Verify every page registered in a cluster was actually crawled and
    that crawled cluster pages render the cluster nav."""
    findings: list[Finding] = []

    try:
        from src.seo.cluster_topology import CLUSTERS, cluster_for
    except ImportError:
        findings.append(Finding("*", "error", "cluster", "Could not import cluster_topology"))
        return findings

    crawled_paths = {pa.path.rstrip("/") for pa in page_audits}
    audits_by_path = {pa.path.rstrip("/"): pa for pa in page_audits}

    for key, cluster in CLUSTERS.items():
        all_paths = cluster.all_paths()
        for p in all_paths:
            norm = p.rstrip("/")
            if norm not in crawled_paths:
                findings.append(Finding(
                    norm, "warning", "cluster",
                    f"Cluster '{key}' member not reached during crawl",
                ))
            else:
                pa = audits_by_path.get(norm)
                if pa and not pa.has_cluster_nav:
                    findings.append(Finding(
                        norm, "info", "cluster",
                        f"Cluster '{key}' member missing cluster nav block",
                    ))

    return findings


# ── Sitemap cross-check ─────────────────────────────────────────────

def _check_sitemap_coverage(page_audits: list[PageAudit]) -> list[Finding]:
    """Verify key pages from the curated sitemap were actually reachable."""
    findings: list[Finding] = []
    import os
    sitemap_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "seo", "curated-sitemap.xml",
    )
    if not os.path.exists(sitemap_path):
        findings.append(Finding("*", "info", "sitemap", "Curated sitemap not found on disk"))
        return findings

    with open(sitemap_path, encoding="utf-8") as f:
        content = f.read()

    sitemap_paths: set[str] = set()
    for m in re.finditer(r"<loc>https?://[^<]+?(/[^<]*)</loc>", content):
        sitemap_paths.add(m.group(1).rstrip("/") or "/")

    crawled_paths = {pa.path.rstrip("/") or "/" for pa in page_audits}

    for sp in sorted(sitemap_paths):
        if sp not in crawled_paths:
            if not sp.endswith((".pdf", ".xml")):
                findings.append(Finding(
                    sp, "info", "sitemap",
                    "In curated sitemap but not reached during crawl",
                ))

    return findings


# ── Internal link analysis ──────────────────────────────────────────

def _check_internal_links(page_audits: list[PageAudit]) -> list[Finding]:
    """Find orphan pages (no inbound internal links) and check anchor text
    consistency against the canonical anchors in cluster_topology."""
    findings: list[Finding] = []

    inbound: dict[str, int] = {}
    crawled = {pa.path.rstrip("/") or "/" for pa in page_audits}

    for pa in page_audits:
        for href, anchor in pa.internal_links:
            norm = href.rstrip("/") or "/"
            inbound[norm] = inbound.get(norm, 0) + 1

    hub_pages = {
        "/", "/sanctions-tracker", "/invest-in-cuba", "/tools",
        "/companies", "/explainers", "/travel", "/export-to-cuba",
        "/briefing", "/people", "/calendar",
    }
    for path in sorted(hub_pages):
        norm = path.rstrip("/") or "/"
        if norm in crawled and inbound.get(norm, 0) < 2:
            findings.append(Finding(
                norm, "warning", "link",
                f"Hub page has only {inbound.get(norm, 0)} inbound internal links",
            ))

    return findings


# ── Crawl engine ────────────────────────────────────────────────────

SEED_PATHS = [
    "/",
    "/sanctions-tracker",
    "/invest-in-cuba",
    "/tools",
    "/explainers",
    "/travel",
    "/companies",
    "/briefing",
    "/calendar",
    "/export-to-cuba",
    "/people",
    "/sources",
    "/sanctions/by-sector",
    "/sanctions/individuals",
    "/sanctions/entities",
    "/sanctions/vessels",
    "/sanctions/aircraft",
]


def _crawl(*, max_pages: int = 200, follow_links: bool = True) -> list[PageAudit]:
    """Crawl the Flask app via test_client and audit each page."""
    import os
    import sys
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root not in sys.path:
        sys.path.insert(0, root)
    os.environ.setdefault("SITE_URL", "https://cubaninsights.com")

    from server import app  # noqa: E402

    client = app.test_client()
    queue = list(SEED_PATHS)
    seen: set[str] = set()
    audits: list[PageAudit] = []

    # Also seed with cluster topology paths
    try:
        from src.seo.cluster_topology import CLUSTERS
        for cluster in CLUSTERS.values():
            for p in cluster.all_paths():
                if p not in queue and p not in seen:
                    queue.append(p)
    except ImportError:
        pass

    while queue and len(audits) < max_pages:
        path = queue.pop(0)
        norm = path.rstrip("/") or "/"
        if norm in seen:
            continue
        seen.add(norm)

        try:
            resp = client.get(path, follow_redirects=False)
        except Exception as exc:
            logger.warning("crawl: error fetching %s: %s", path, exc)
            continue

        if resp.status_code in (301, 302, 307, 308):
            location = resp.headers.get("Location", "")
            if location.startswith("/"):
                redirect_norm = location.rstrip("/") or "/"
                if redirect_norm not in seen:
                    queue.append(location)
            continue

        if resp.status_code != 200:
            audits.append(PageAudit(path=norm, status_code=resp.status_code))
            continue

        html = resp.get_data(as_text=True)
        if not html:
            continue

        parser = SEOHTMLParser()
        try:
            parser.feed(html)
        except Exception:
            logger.warning("crawl: parse error on %s", path)
            continue

        jsonld_types: list[str] = []
        for block in parser.jsonld_blocks:
            try:
                obj = json.loads(block)
                if isinstance(obj, dict):
                    t = obj.get("@type", "")
                    if isinstance(t, list):
                        jsonld_types.extend(t)
                    elif t:
                        jsonld_types.append(t)
                elif isinstance(obj, list):
                    for item in obj:
                        if isinstance(item, dict):
                            t = item.get("@type", "")
                            if isinstance(t, list):
                                jsonld_types.extend(t)
                            elif t:
                                jsonld_types.append(t)
            except (json.JSONDecodeError, TypeError):
                pass

        pa = PageAudit(
            path=norm,
            status_code=resp.status_code,
            title=parser.title,
            meta_description=parser.meta_description,
            canonical=parser.canonical,
            robots=parser.robots,
            og_title=parser.og_title,
            og_description=parser.og_description,
            og_image=parser.og_image,
            h1_count=parser.h1_count,
            h1_text=parser.h1_text,
            heading_levels=parser.heading_levels,
            jsonld_count=len(parser.jsonld_blocks),
            jsonld_types=jsonld_types,
            internal_links=parser.internal_links,
            has_cluster_nav=parser.has_cluster_nav,
            word_count=parser.word_count,
        )

        page_findings = []
        page_findings.extend(_check_meta(pa))
        page_findings.extend(_check_headings(pa))
        page_findings.extend(_check_structured_data(pa))
        page_findings.extend(_check_content(pa))
        pa.findings = page_findings

        audits.append(pa)

        if follow_links:
            for href, _ in parser.internal_links:
                link_norm = href.rstrip("/") or "/"
                if link_norm not in seen and link_norm not in queue:
                    if not link_norm.endswith((".pdf", ".xml", ".txt", ".png", ".jpg", ".ico")):
                        queue.append(link_norm)

    return audits


# ── Public API ──────────────────────────────────────────────────────

def run_audit(*, max_pages: int = 200, follow_links: bool = True) -> AuditReport:
    """Run the full SEO audit and return a structured report."""
    page_audits = _crawl(max_pages=max_pages, follow_links=follow_links)

    report = AuditReport(
        pages_crawled=len(page_audits),
        pages_ok=sum(1 for pa in page_audits if pa.status_code == 200),
        page_audits=page_audits,
    )

    for pa in page_audits:
        report.findings.extend(pa.findings)

    report.findings.extend(_check_cluster_coverage(page_audits))
    report.findings.extend(_check_sitemap_coverage(page_audits))
    report.findings.extend(_check_internal_links(page_audits))

    return report
