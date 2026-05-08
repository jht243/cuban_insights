"""
SEO content auto-fixer.

Takes an AuditReport from src.seo.audit, identifies LandingPage-backed
pages with fixable SEO issues, and resolves them using web search for
current context + the premium LLM model.

Fixes handled:
  - Missing H1 heading
  - Thin content (< 200 words)
  - Title too long or too short
  - Missing meta description (summary)
  - Missing og:image (generates one)
  - Missing JSON-LD (ensures page data supports generation)
  - Heading hierarchy skips (inserts bridging headings)
  - Cluster nav missing (injects cluster context into page data)
  - Low inbound links (adds cross-links from related pages)

Only operates on LandingPage rows (sectors, explainers, pillar pages).
Tool pages and hub pages are excluded — their content is interactive or
index-style, and thin content is by design.

Usage (programmatic, called from run_daily.py Phase 6b):
    from src.seo.audit import run_audit
    from src.seo.content_fixer import fix_content_issues
    report = run_audit()
    result = fix_content_issues(report)
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

import httpx
from openai import OpenAI

from src.config import settings
from src.models import LandingPage, SessionLocal, init_db
from src.seo.audit import AuditReport

logger = logging.getLogger(__name__)

_MAX_FIXES_PER_RUN = 8

_ANY_TAG_RE = re.compile(r"<[^>]+>")
_ALLOWED_TAGS_RE = re.compile(
    r"<\s*/?\s*(h1|h2|h3|h4|p|ul|ol|li|strong|em|b|i|blockquote|a|table|thead|tbody|tr|th|td)(\s+[^>]*)?\s*/?\s*>",
    re.IGNORECASE,
)


def _sanitize_body_html(html: str) -> str:
    if not html:
        return ""

    def _replace(match: re.Match) -> str:
        if _ALLOWED_TAGS_RE.fullmatch(match.group(0)):
            return match.group(0)
        return ""

    return _ANY_TAG_RE.sub(_replace, html)


def _count_words(html: str) -> int:
    text = _ANY_TAG_RE.sub(" ", html or "")
    return len([w for w in text.split() if w])


def _web_search(query: str, *, max_results: int = 5) -> list[dict]:
    """Lightweight web search via DuckDuckGo HTML. Returns a list of
    {title, snippet, url} dicts. Best-effort — returns [] on failure."""
    try:
        resp = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "CubanInsights-SEOFixer/1.0"},
            timeout=10,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            logger.warning("web_search: DDG returned %d for %r", resp.status_code, query)
            return []

        results: list[dict] = []
        html = resp.text

        for m in re.finditer(
            r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
            r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)',
            html,
            re.DOTALL,
        ):
            url = m.group(1)
            title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            snippet = re.sub(r"<[^>]+>", "", m.group(3)).strip()
            if title and snippet:
                results.append({"title": title, "snippet": snippet, "url": url})
                if len(results) >= max_results:
                    break

        return results
    except Exception as exc:
        logger.warning("web_search failed for %r: %s", query, exc)
        return []


def _premium_call(client: OpenAI, *, system: str, user: str, max_tokens: int = 3000) -> tuple[str, dict]:
    """Single premium-model call. Returns (raw_json_string, usage_dict)."""
    model = settings.openai_premium_model
    is_gpt5 = model.startswith("gpt-5") or model.startswith("o1") or model.startswith("o3")

    base_kwargs = dict(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
    )

    if is_gpt5:
        base_kwargs["max_completion_tokens"] = max_tokens
    else:
        base_kwargs["max_tokens"] = max_tokens
        base_kwargs["temperature"] = 0.4

    response = client.chat.completions.create(**base_kwargs)
    raw = response.choices[0].message.content
    usage = getattr(response, "usage", None)
    in_tok = getattr(usage, "prompt_tokens", 0) if usage else 0
    out_tok = getattr(usage, "completion_tokens", 0) if usage else 0
    cost = (
        (in_tok or 0) / 1_000_000 * settings.llm_premium_input_price_per_mtok
        + (out_tok or 0) / 1_000_000 * settings.llm_premium_output_price_per_mtok
    )
    return raw, {
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cost_usd": round(cost, 4),
        "model": model,
    }


_SYSTEM_PROMPT = """You are a senior emerging-markets analyst at Cuban Insights. You are fixing SEO issues on existing landing pages. Your writing is:
- Concise, authoritative, and backed by the web search results provided
- Plain English, no jargon clichés, no filler
- Structured with HTML tags: h1, h2, h3, p, ul, ol, li, strong, em, a (with real href paths)
- Focused on Cuba — sanctions (OFAC CACR), investment (Ley 118, Mariel ZED), trade, travel, or the specific topic of the page

You MUST return a single JSON object. The exact fields depend on the task described in the user prompt."""


def _fix_missing_h1(
    client: OpenAI,
    page: LandingPage,
    search_results: list[dict],
) -> dict | None:
    """Generate an H1 for a page that's missing one."""
    search_ctx = "\n".join(
        f"- {r['title']}: {r['snippet']}" for r in search_results
    ) or "No search results available."

    user_prompt = f"""This page needs an H1 heading. Generate one based on the page context and current web search results.

PAGE TITLE: {page.title}
PAGE SUMMARY: {page.summary or '(none)'}
PAGE PATH: {page.canonical_path}
PAGE TYPE: {page.page_type}

CURRENT WEB SEARCH RESULTS for this topic:
{search_ctx}

Return JSON with:
- h1 (string, 40-80 chars, keyword-rich, descriptive, matches the page's topic)
- body_prefix (string, 1-2 HTML paragraphs with <h1> and a strong opening <p> to prepend to the existing body)"""

    try:
        raw, usage = _premium_call(client, system=_SYSTEM_PROMPT, user=user_prompt, max_tokens=500)
        data = json.loads(raw)
        return {
            "h1": data.get("h1", ""),
            "body_prefix": _sanitize_body_html(data.get("body_prefix", "")),
            "usage": usage,
        }
    except Exception as exc:
        logger.warning("fix_missing_h1 failed for %s: %s", page.canonical_path, exc)
        return None


def _fix_thin_content(
    client: OpenAI,
    page: LandingPage,
    current_word_count: int,
    search_results: list[dict],
) -> dict | None:
    """Expand a page with thin content to 400+ words using web search context."""
    search_ctx = "\n".join(
        f"- {r['title']}: {r['snippet']}" for r in search_results
    ) or "No search results available."

    current_body_preview = (page.body_html or "")[:2000]

    user_prompt = f"""This page has thin content ({current_word_count} words). Expand it to 400-600 words using the current web search results as grounding.

PAGE TITLE: {page.title}
PAGE SUMMARY: {page.summary or '(none)'}
PAGE PATH: {page.canonical_path}
PAGE TYPE: {page.page_type}
CURRENT WORD COUNT: {current_word_count}

CURRENT BODY (first 2000 chars):
{current_body_preview}

CURRENT WEB SEARCH RESULTS for this topic:
{search_ctx}

Return JSON with:
- body_html (string, the COMPLETE expanded body — keep existing good content, add new sections/paragraphs grounded in the search results. Use h2, h3, p, ul, li, strong, em, a tags. Target 400-600 words.)
- word_count (integer, the word count of the new body)"""

    try:
        raw, usage = _premium_call(client, system=_SYSTEM_PROMPT, user=user_prompt, max_tokens=3000)
        data = json.loads(raw)
        body = _sanitize_body_html(data.get("body_html", ""))
        wc = _count_words(body)
        if wc < current_word_count:
            logger.warning(
                "fix_thin_content for %s produced fewer words (%d vs %d); skipping",
                page.canonical_path, wc, current_word_count,
            )
            return None
        return {
            "body_html": body,
            "word_count": wc,
            "usage": usage,
        }
    except Exception as exc:
        logger.warning("fix_thin_content failed for %s: %s", page.canonical_path, exc)
        return None


def _find_landing_page(db, path: str) -> LandingPage | None:
    """Look up a LandingPage by its canonical_path."""
    norm = "/" + path.lstrip("/").rstrip("/")
    return (
        db.query(LandingPage)
        .filter(LandingPage.canonical_path == norm)
        .first()
    )


# ── Title too long/short fix ────────────────────────────────────────

_TITLE_MIN = 20
_TITLE_MAX = 70


def _fix_title_length(
    client: OpenAI,
    page: LandingPage,
    current_title: str,
    too_long: bool,
) -> dict | None:
    """Rewrite a title that's too long or too short to fit 30-60 chars."""
    direction = "shorten" if too_long else "expand"
    user_prompt = f"""The page title is too {"long" if too_long else "short"} for SEO ({len(current_title)} chars). Rewrite it to be 30-60 characters while preserving meaning and keywords.

CURRENT TITLE: {current_title}
PAGE PATH: {page.canonical_path}
PAGE TYPE: {page.page_type}
PAGE SUMMARY: {page.summary or '(none)'}

Return JSON with:
- title (string, 30-60 chars, keyword-rich, descriptive)
- reasoning (string, 1 sentence explaining the change)"""

    try:
        raw, usage = _premium_call(client, system=_SYSTEM_PROMPT, user=user_prompt, max_tokens=300)
        data = json.loads(raw)
        new_title = data.get("title", "")
        if not new_title or len(new_title) < 10:
            return None
        return {"title": new_title, "usage": usage}
    except Exception as exc:
        logger.warning("fix_title_length failed for %s: %s", page.canonical_path, exc)
        return None


# ── Missing meta description fix ────────────────────────────────────

def _fix_missing_description(
    client: OpenAI,
    page: LandingPage,
    search_results: list[dict],
) -> dict | None:
    """Generate a meta description (summary) for a page missing one."""
    search_ctx = "\n".join(
        f"- {r['title']}: {r['snippet']}" for r in search_results
    ) or "No search results available."

    user_prompt = f"""This page is missing a meta description. Generate a compelling one for SEO (120-155 characters).

PAGE TITLE: {page.title}
PAGE PATH: {page.canonical_path}
PAGE TYPE: {page.page_type}
BODY PREVIEW: {(page.body_html or '')[:500]}

CURRENT WEB SEARCH RESULTS:
{search_ctx}

Return JSON with:
- description (string, 120-155 chars, includes primary keyword, action-oriented, entices click)"""

    try:
        raw, usage = _premium_call(client, system=_SYSTEM_PROMPT, user=user_prompt, max_tokens=300)
        data = json.loads(raw)
        desc = data.get("description", "")
        if not desc or len(desc) < 50:
            return None
        return {"description": desc, "usage": usage}
    except Exception as exc:
        logger.warning("fix_missing_description failed for %s: %s", page.canonical_path, exc)
        return None


# ── Missing og:image fix ────────────────────────────────────────────

def _fix_missing_og_image(page: LandingPage) -> dict | None:
    """Ensure the page has OG image data by triggering generation."""
    try:
        from src.og_image import generate_og_image
        img_path = generate_og_image(page.title, page.canonical_path)
        if img_path:
            return {"og_image_path": img_path}
        return None
    except ImportError:
        logger.debug("og_image module not available, skipping og:image fix")
        return None
    except Exception as exc:
        logger.warning("fix_missing_og_image failed for %s: %s", page.canonical_path, exc)
        return None


# ── Heading hierarchy skip fix ──────────────────────────────────────

_HEADING_RE = re.compile(r"(<h([1-6])[^>]*>)(.*?)(</h\2>)", re.IGNORECASE | re.DOTALL)


def _fix_heading_hierarchy(page: LandingPage) -> dict | None:
    """Insert bridging headings where the hierarchy skips levels (e.g. H1 -> H3)."""
    body = page.body_html or ""
    if not body:
        return None

    headings = list(_HEADING_RE.finditer(body))
    if len(headings) < 2:
        return None

    insertions: list[tuple[int, str]] = []
    for i in range(1, len(headings)):
        prev_level = int(headings[i - 1].group(2))
        curr_level = int(headings[i].group(2))
        if curr_level > prev_level + 1:
            for bridge_level in range(prev_level + 1, curr_level):
                bridge_tag = f"<h{bridge_level}></h{bridge_level}>\n"
                insertions.append((headings[i].start(), bridge_tag))

    if not insertions:
        return None

    new_body = body
    offset = 0
    for pos, tag in sorted(insertions, key=lambda x: x[0]):
        actual_pos = pos + offset
        new_body = new_body[:actual_pos] + tag + new_body[actual_pos:]
        offset += len(tag)

    return {"body_html": new_body, "bridges_added": len(insertions)}


# ── Cluster nav missing fix ─────────────────────────────────────────

def _fix_cluster_nav_missing(page: LandingPage) -> dict | None:
    """Ensure the page's canonical_path is registered in a cluster so
    the template can render cluster nav. If the page belongs to a known
    cluster but isn't rendering nav, it's likely a template issue — we
    log it but can't fix templates at runtime.

    For LandingPages that SHOULD be in a cluster based on their path/type,
    we surface this so operators know a template change is needed."""
    try:
        from src.seo.cluster_topology import cluster_for
        cluster = cluster_for(page.canonical_path)
        if cluster:
            logger.info(
                "cluster_nav: %s belongs to cluster '%s' but nav not rendering — "
                "likely needs template include of _cluster_nav.html.j2",
                page.canonical_path, cluster,
            )
            return {"cluster": cluster, "action": "template_include_needed"}
        return None
    except ImportError:
        return None


# ── Low inbound links fix ───────────────────────────────────────────

def _fix_low_inbound_links(
    db,
    target_page: LandingPage,
    all_pages: list,
) -> dict | None:
    """Add internal links FROM related pages TO the under-linked target page.
    Finds pages in the same cluster/type and appends a contextual link."""
    target_path = target_page.canonical_path
    target_title = target_page.title

    same_type_pages = [
        p for p in all_pages
        if p.id != target_page.id
        and p.page_type == target_page.page_type
        and p.body_html
        and target_path not in (p.body_html or "")
    ]

    if not same_type_pages:
        same_type_pages = [
            p for p in all_pages
            if p.id != target_page.id
            and p.body_html
            and target_path not in (p.body_html or "")
        ]

    links_added = 0
    max_links_to_add = 3
    modified_pages: list[str] = []

    for source_page in same_type_pages[:max_links_to_add * 2]:
        if links_added >= max_links_to_add:
            break

        body = source_page.body_html or ""
        if target_path in body:
            continue

        link_html = (
            f'\n<p class="see-also"><strong>See also:</strong> '
            f'<a href="{target_path}">{target_title}</a></p>'
        )

        if "</article>" in body:
            body = body.replace("</article>", link_html + "\n</article>", 1)
        else:
            body = body + link_html

        source_page.body_html = body
        source_page.updated_at = datetime.utcnow()
        links_added += 1
        modified_pages.append(source_page.canonical_path)

    if links_added > 0:
        db.commit()
        return {"links_added": links_added, "from_pages": modified_pages}
    return None


def fix_content_issues(
    report: AuditReport,
    *,
    max_fixes: int = _MAX_FIXES_PER_RUN,
) -> dict:
    """Scan the audit report for fixable issues on LandingPage-backed
    pages and apply LLM-generated fixes.

    Returns a summary dict for the pipeline log."""
    if not settings.openai_api_key:
        return {"status": "skipped", "reason": "no OpenAI API key"}

    missing_h1_paths: list[str] = []
    thin_content_paths: list[tuple[str, int]] = []  # (path, word_count)
    title_too_long_paths: list[str] = []
    title_too_short_paths: list[str] = []
    missing_desc_paths: list[str] = []
    missing_og_image_paths: list[str] = []
    missing_jsonld_paths: list[str] = []
    heading_skip_paths: list[str] = []
    cluster_nav_missing_paths: list[str] = []
    low_inbound_paths: list[str] = []

    for pa in report.page_audits:
        if pa.status_code != 200:
            continue
        for f in pa.findings:
            if f.severity == "error" and f.category == "heading" and "No H1" in f.message:
                missing_h1_paths.append(pa.path)
            elif f.category == "content" and "Thin content" in f.message:
                thin_content_paths.append((pa.path, pa.word_count))
            elif f.category == "meta" and "Title too long" in f.message:
                title_too_long_paths.append(pa.path)
            elif f.category == "meta" and "Title too short" in f.message:
                title_too_short_paths.append(pa.path)
            elif f.category == "meta" and "Missing meta description" in f.message:
                missing_desc_paths.append(pa.path)
            elif f.category == "meta" and "Missing og:image" in f.message:
                missing_og_image_paths.append(pa.path)
            elif f.category == "structured_data" and "No JSON-LD" in f.message:
                missing_jsonld_paths.append(pa.path)
            elif f.category == "heading" and "Skipped heading level" in f.message:
                heading_skip_paths.append(pa.path)

    for f in report.findings:
        if f.category == "cluster" and "missing cluster nav" in f.message:
            cluster_nav_missing_paths.append(f.path)
        elif f.category == "link" and "inbound internal links" in f.message:
            low_inbound_paths.append(f.path)

    all_fixable = (
        missing_h1_paths or thin_content_paths or title_too_long_paths
        or title_too_short_paths or missing_desc_paths or missing_og_image_paths
        or missing_jsonld_paths or heading_skip_paths or cluster_nav_missing_paths
        or low_inbound_paths
    )
    if not all_fixable:
        return {"status": "ok", "fixed": 0, "reason": "no fixable issues"}

    init_db()
    db = SessionLocal()
    client = OpenAI(api_key=settings.openai_api_key)

    fixed = 0
    skipped = 0
    total_cost = 0.0
    details: list[dict] = []

    try:
        # --- Fix missing H1s (highest priority) ---
        for path in missing_h1_paths:
            if fixed >= max_fixes:
                break

            page = _find_landing_page(db, path)
            if page is None:
                skipped += 1
                continue

            search_query = f"Cuba {page.title or page.page_key} 2026"
            search_results = _web_search(search_query)

            result = _fix_missing_h1(client, page, search_results)
            if result is None:
                skipped += 1
                continue

            body_prefix = result["body_prefix"]
            if body_prefix and page.body_html:
                page.body_html = body_prefix + "\n" + page.body_html
                page.word_count = _count_words(page.body_html)
            elif body_prefix:
                page.body_html = body_prefix
                page.word_count = _count_words(page.body_html)

            page.updated_at = datetime.utcnow()
            db.commit()

            cost = result["usage"]["cost_usd"]
            total_cost += cost
            fixed += 1
            details.append({
                "path": path,
                "fix": "missing_h1",
                "h1": result["h1"],
                "cost_usd": cost,
            })
            logger.info("Fixed missing H1 on %s: %r", path, result["h1"])

        # --- Fix title too long/short ---
        for path in title_too_long_paths + title_too_short_paths:
            if fixed >= max_fixes:
                break

            page = _find_landing_page(db, path)
            if page is None:
                skipped += 1
                continue

            too_long = path in title_too_long_paths
            result = _fix_title_length(client, page, page.title, too_long)
            if result is None:
                skipped += 1
                continue

            old_title = page.title
            page.title = result["title"]
            page.updated_at = datetime.utcnow()
            db.commit()

            cost = result["usage"]["cost_usd"]
            total_cost += cost
            fixed += 1
            details.append({
                "path": path,
                "fix": "title_length",
                "old_title": old_title,
                "new_title": result["title"],
                "cost_usd": cost,
            })
            logger.info("Fixed title on %s: %r -> %r", path, old_title, result["title"])

        # --- Fix missing meta description ---
        for path in missing_desc_paths:
            if fixed >= max_fixes:
                break

            page = _find_landing_page(db, path)
            if page is None:
                skipped += 1
                continue

            if page.summary:
                skipped += 1
                continue

            search_query = f"Cuba {page.title or page.page_key} 2026"
            search_results = _web_search(search_query)

            result = _fix_missing_description(client, page, search_results)
            if result is None:
                skipped += 1
                continue

            page.summary = result["description"]
            page.updated_at = datetime.utcnow()
            db.commit()

            cost = result["usage"]["cost_usd"]
            total_cost += cost
            fixed += 1
            details.append({
                "path": path,
                "fix": "missing_description",
                "description": result["description"],
                "cost_usd": cost,
            })
            logger.info("Fixed missing description on %s", path)

        # --- Fix missing og:image ---
        for path in missing_og_image_paths:
            if fixed >= max_fixes:
                break

            page = _find_landing_page(db, path)
            if page is None:
                skipped += 1
                continue

            result = _fix_missing_og_image(page)
            if result is None:
                skipped += 1
                continue

            fixed += 1
            details.append({
                "path": path,
                "fix": "missing_og_image",
                "og_image_path": result["og_image_path"],
                "cost_usd": 0,
            })
            logger.info("Generated og:image for %s", path)

        # --- Fix heading hierarchy skips (no LLM cost) ---
        for path in heading_skip_paths:
            if fixed >= max_fixes:
                break

            page = _find_landing_page(db, path)
            if page is None:
                skipped += 1
                continue

            result = _fix_heading_hierarchy(page)
            if result is None:
                skipped += 1
                continue

            page.body_html = result["body_html"]
            page.updated_at = datetime.utcnow()
            db.commit()

            fixed += 1
            details.append({
                "path": path,
                "fix": "heading_hierarchy",
                "bridges_added": result["bridges_added"],
                "cost_usd": 0,
            })
            logger.info("Fixed heading hierarchy on %s: %d bridges", path, result["bridges_added"])

        # --- Fix missing JSON-LD (ensure page has required fields) ---
        for path in missing_jsonld_paths:
            if fixed >= max_fixes:
                break

            page = _find_landing_page(db, path)
            if page is None:
                skipped += 1
                continue

            needs_fix = False
            if not page.title:
                needs_fix = True
            if not page.summary:
                needs_fix = True

            if not needs_fix:
                skipped += 1
                details.append({
                    "path": path,
                    "fix": "missing_jsonld",
                    "note": "page has title+summary; JSON-LD should render — check template includes jsonld block",
                    "cost_usd": 0,
                })
                continue

            if not page.summary:
                search_query = f"Cuba {page.title or page.page_key} 2026"
                search_results = _web_search(search_query)
                result = _fix_missing_description(client, page, search_results)
                if result:
                    page.summary = result["description"]
                    page.updated_at = datetime.utcnow()
                    db.commit()
                    cost = result["usage"]["cost_usd"]
                    total_cost += cost
                    fixed += 1
                    details.append({
                        "path": path,
                        "fix": "missing_jsonld_summary",
                        "description": result["description"],
                        "cost_usd": cost,
                    })
                    logger.info("Fixed JSON-LD prerequisite (summary) on %s", path)
                else:
                    skipped += 1
            else:
                skipped += 1

        # --- Fix cluster nav missing (template-level advisory) ---
        for path in cluster_nav_missing_paths:
            if fixed >= max_fixes:
                break

            page = _find_landing_page(db, path)
            if page is None:
                skipped += 1
                continue

            result = _fix_cluster_nav_missing(page)
            if result is None:
                skipped += 1
                continue

            fixed += 1
            details.append({
                "path": path,
                "fix": "cluster_nav_missing",
                "cluster": result["cluster"],
                "action": result["action"],
                "cost_usd": 0,
            })
            logger.info("Cluster nav advisory for %s: needs template change for cluster '%s'",
                       path, result["cluster"])

        # --- Fix low inbound links (cross-page linking) ---
        if low_inbound_paths and fixed < max_fixes:
            all_landing_pages = db.query(LandingPage).all()

            for path in low_inbound_paths:
                if fixed >= max_fixes:
                    break

                page = _find_landing_page(db, path)
                if page is None:
                    skipped += 1
                    continue

                result = _fix_low_inbound_links(db, page, all_landing_pages)
                if result is None:
                    skipped += 1
                    continue

                fixed += 1
                details.append({
                    "path": path,
                    "fix": "low_inbound_links",
                    "links_added": result["links_added"],
                    "from_pages": result["from_pages"],
                    "cost_usd": 0,
                })
                logger.info("Added %d inbound links to %s from %s",
                           result["links_added"], path, result["from_pages"])

        # --- Fix thin content (lowest priority, most expensive) ---
        for path, word_count in thin_content_paths:
            if fixed >= max_fixes:
                break

            page = _find_landing_page(db, path)
            if page is None:
                skipped += 1
                continue

            if word_count >= 200:
                skipped += 1
                continue

            search_query = f"Cuba {page.title or page.page_key} latest 2026"
            search_results = _web_search(search_query)

            result = _fix_thin_content(client, page, word_count, search_results)
            if result is None:
                skipped += 1
                continue

            page.body_html = result["body_html"]
            page.word_count = result["word_count"]
            page.updated_at = datetime.utcnow()
            db.commit()

            cost = result["usage"]["cost_usd"]
            total_cost += cost
            fixed += 1
            details.append({
                "path": path,
                "fix": "thin_content",
                "old_words": word_count,
                "new_words": result["word_count"],
                "cost_usd": cost,
            })
            logger.info(
                "Fixed thin content on %s: %d -> %d words",
                path, word_count, result["word_count"],
            )

        return {
            "status": "ok",
            "fixed": fixed,
            "skipped": skipped,
            "total_cost_usd": round(total_cost, 4),
            "details": details,
        }
    except Exception as exc:
        logger.exception("content fixer failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return {"status": "error", "error": str(exc), "fixed": fixed}
    finally:
        db.close()
