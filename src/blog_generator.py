"""
Long-form blog post generator.

For each high-relevance briefing entry (ExternalArticle / AssemblyNews)
that doesn't yet have a corresponding BlogPost row, runs a single LLM
call that produces an investor-grade analysis post (700-900 words),
ready to render at /briefing/{slug}.

This is on its own LLM budget (settings.blog_gen_budget_per_run) so
the daily report can stay cheap; blog posts are nice-to-have for SEO
but not blocking.

Costs:
    ~2.5k input tokens + ~1.8k output tokens per post
    -> ~ $0.025 input + $0.018 output = ~$0.04/post
    -> default budget 6/run = ~$0.25/run
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Iterable

from openai import OpenAI

from src.analyzer import _LLM_USAGE
from src.config import settings
from src.models import (
    AssemblyNewsEntry,
    BlogPost,
    ExternalArticleEntry,
    GazetteStatus,
    SessionLocal,
    SourceType,
    init_db,
)


logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a senior emerging-markets analyst writing an investor-grade long-form blog post about Cuban business, investment, sanctions, and embargo news. Your audience is global institutional investors, family offices, sanctions compliance officers, and corporate development teams considering or already exposed to Cuba (or evaluating whether the US embargo (CACR), Helms-Burton (LIBERTAD Act), and the State Sponsors of Terrorism designation make Cuban exposure tractable for them).

CRITICAL COUNTRY ANCHOR — READ BEFORE WRITING:
Every story you write is about CUBA. The country is CUBA. Always.
- When the upstream Spanish source says "el país", "la nación", "nuestro país", "el gobierno", "el Estado", "la patria", "la Isla", "la Mayor de las Antillas" — it means CUBA. Translate as "Cuba" or "the country" (meaning Cuba). Never translate it as Venezuela, Mexico, Nicaragua, or any other country.
- "Russian oil donations" in a Cuban source describe oil shipped to CUBA. "Energy crisis" in a Cuban source is Cuba's grid crisis. "The 2026 Economic Program" in a Cuban source is Cuba's program.
- The TITLE, SUBTITLE, BODY, KEYWORDS, and SOCIAL_HOOK must place the story in Cuba. Never write "Venezuela's energy crisis", "Venezuela's economic program", "implications for Venezuelan energy" — even if the topic is famously associated with Venezuela in the real world. The source is Cuban; the story is Cuban.
- The ONLY time another country may appear is when the source explicitly names it as a counterparty (e.g. "Cuba and Russia signed an agreement", "OFAC sanctions on Cuba"). The actor / subject is still Cuba.
- If you find yourself writing a headline that names another country in the protagonist position, stop and rewrite. The protagonist is Cuba.

You write with sharp awareness that:
- The US embargo (Cuban Assets Control Regulations, 31 CFR Part 515) prohibits most US-person dealings with Cuba; OFAC General Licenses (CACR §515.xxx) carve narrow lanes (telecom, agricultural commodities, medicine, authorized travel categories, remittances, professional research).
- Helms-Burton Title III enables US-court lawsuits against entities "trafficking" in property confiscated from US nationals after 1959; Title IV restricts visas of executives benefiting from confiscated assets.
- Cuba's State Sponsor of Terrorism (SST) listing layers additional sanctions (correspondent banking, secondary-sanction risk for non-US entities).
- Foreign (non-US) investors operate via Empresas Mixtas under Law 118/2014 (Foreign Investment Law) and ANEC contracts, mostly through CIMEX, CUBANACAN, GAESA-linked counterparties — counterparty selection drives most of the deal risk.
- The Mariel Special Development Zone (ZEDM) is the on-island concession framework most accessible to foreign capital.
- Cuba's macro picture is dominated by chronic FX scarcity (the unified peso, the MLC card, and the persistent informal TRMI rate), grid instability, and a fast-growing but still under-capitalized non-state private sector (MIPYMES, cuentapropistas).
- Independent reporting is rare on the island; treat Granma / Cubadebate / Juventud Rebelde as state communications and weight independent diaspora outlets (14ymedio, El Toque, CiberCuba, ADN Cuba, DIARIO DE CUBA) accordingly.

Your writing is:
- Plain English, journalistic, no jargon clichés
- Concrete: cite specific OFAC General License numbers (e.g. GL 6, GL 8), CACR sections, decreto-ley numbers, Gaceta Oficial issue numbers, USD amounts, sectors, agencies, ministries
- Balanced: acknowledge both opportunity and risk; never cheerlead a regime narrative; never write US-policy advocacy
- 700-900 words total in the body
- Structured with HTML <h2> subheadings (3-5 of them) and short <p> paragraphs (2-4 sentences each)

You MUST return a single JSON object with these fields:
- title (string, 60-90 chars, English, optimized for "invest in Cuba / Cuba embargo / OFAC Cuba / Mariel ZEDM / Cuba sanctions / sector" search intent)
- subtitle (string, 110-160 chars, English, expands the title)
- summary (string, 180-220 chars, plain text, used as meta description)
- body_html (string, the full post body — ONLY <h2>, <p>, <ul>, <li>, <strong>, <em>, <blockquote>, and <a href> tags allowed)
- keywords (array of 6-10 lowercase phrases, English, mix of head terms and long-tail; favor "cuba" / "havana" / "ofac cuba" / "cacr" / "helms-burton" / "mariel zedm" / "empresa mixta" / specific sector terms)
- primary_sector (string, one of: tourism, mining, energy, biotech, agriculture, remittances, real_estate, banking, sanctions, governance, fiscal, diplomatic, legal, telecom, mariel_zedm, private_sector, other)
- key_takeaways (array of 3-5 short bullet sentences, plain text)
- investor_implications (string, 80-160 chars, plain text, "what this means for capital deployment")
- social_hook (string, 180-250 chars, plain text — the OPENING LINE of a social-media post about this story. Voice: one analyst messaging another over Slack. Surfaces the tension, the surprise, or the "why this matters" in a single beat. NEVER restate the title verbatim. NEVER use hashtags, emoji, exclamation marks, or marketing clichés like "game-changing", "groundbreaking", "must-read". Conversational but precise. Examples of the right register: "Havana just quietly let the Mariel terminal stevedoring concession lapse — most of the dry-bulk desk hasn't noticed yet.", "OFAC re-issued GL 6 with the medical-device line item carved out. Western Union is in scope again, but Stripe still isn't.")

Do NOT use markdown. Do NOT wrap output in code fences. Output only the JSON object."""


USER_PROMPT_TEMPLATE = """Write a long-form analysis post about the following Cuban business / investment / embargo / sanctions development.

REMINDER: This story concerns CUBA. Every reference to "el país" / "the country" / "the nation" / "the government" in the source refers to CUBA. The title, subtitle, body, keywords, and social_hook must place the story in Cuba — do not relocate it to Venezuela, Nicaragua, Mexico, or any other country, even if the topic (Russian oil, sanctions, blackouts, dollarization) is famously associated with another country in the real world.

SOURCE: {source_name} ({credibility})
PUBLISHED: {published_date}
URL: {source_url}
HEADLINE (original language): {headline}
ENGLISH HEADLINE (analyst summary): {headline_short}

ANALYST SUMMARY:
{takeaway}

DETECTED SECTORS: {sectors}
SENTIMENT: {sentiment}
RELEVANCE SCORE: {relevance}/10

SOURCE BODY (truncated):
{body_text}

Write the post now. Open with the news in the lead paragraph (do not bury the lede), then provide context, then concrete investor implications, then risk factors, then a forward-looking close. Use <h2> subheadings to break up the body."""


_ALLOWED_TAGS_RE = re.compile(
    r"<\s*/?\s*(h2|h3|p|ul|ol|li|strong|em|b|i|blockquote|a)(\s+[^>]*)?\s*/?\s*>",
    re.IGNORECASE,
)
_ANY_TAG_RE = re.compile(r"<[^>]+>")


def _slugify(text: str, *, max_len: int = 110) -> str:
    """Build a clean, keyword-preserving URL slug.

    Briefing slugs used to append date + source id to every post, which
    prevented collisions but produced noisy URLs and sometimes cut the
    final keyword mid-word. New posts should keep the readable headline
    slug unless a collision actually exists.
    """
    if not text:
        return "briefing"
    normalized = (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rsplit("-", 1)[0].strip("-") or slug[:max_len].strip("-")
    return slug or "briefing"


def _count_words(html: str) -> int:
    text = _ANY_TAG_RE.sub(" ", html or "")
    return len([w for w in text.split() if w])


def _sanitize_body_html(html: str) -> str:
    """
    Drop any tags that aren't on our allow-list. Cheap defense against
    the LLM occasionally emitting <script>, <style>, raw <html> or
    other unwanted markup.
    """
    if not html:
        return ""

    def _replace(match: re.Match) -> str:
        if _ALLOWED_TAGS_RE.fullmatch(match.group(0)):
            return match.group(0)
        return ""

    return _ANY_TAG_RE.sub(_replace, html)


def _candidate_external(db) -> list[ExternalArticleEntry]:
    cutoff = date.today() - timedelta(days=settings.blog_gen_lookback_days)
    rows = (
        db.query(ExternalArticleEntry)
        .filter(ExternalArticleEntry.status == GazetteStatus.ANALYZED)
        .filter(ExternalArticleEntry.published_date >= cutoff)
        .order_by(ExternalArticleEntry.published_date.desc())
        .all()
    )
    out = []
    for r in rows:
        analysis = r.analysis_json or {}
        relevance = analysis.get("relevance_score", 0)
        if relevance < settings.blog_gen_min_relevance:
            continue
        # Safety net for Federal Register: the API does full-text
        # "cuba" search and can surface generic OFAC rules where
        # Cuba is just one of many sanctioned jurisdictions. Require
        # a higher relevance bar before spending an LLM call on a
        # long-form post.
        source = getattr(r, "source", None)
        source_value = getattr(source, "value", source)
        if source_value == "federal_register" and relevance < 7:
            continue
        out.append(r)
    return out


def _candidate_assembly(db) -> list[AssemblyNewsEntry]:
    cutoff = date.today() - timedelta(days=settings.blog_gen_lookback_days)
    rows = (
        db.query(AssemblyNewsEntry)
        .filter(AssemblyNewsEntry.status == GazetteStatus.ANALYZED)
        .filter(AssemblyNewsEntry.published_date >= cutoff)
        .order_by(AssemblyNewsEntry.published_date.desc())
        .all()
    )
    out = []
    for r in rows:
        analysis = r.analysis_json or {}
        if analysis.get("relevance_score", 0) < settings.blog_gen_min_relevance:
            continue
        out.append(r)
    return out


def _existing_blog_keys(db) -> set[tuple[str, int]]:
    return {
        (row.source_table, row.source_id)
        for row in db.query(BlogPost.source_table, BlogPost.source_id).all()
    }


def _build_post_payload(
    client: OpenAI,
    *,
    source_name: str,
    credibility: str,
    published_date: str,
    source_url: str,
    headline: str,
    headline_short: str,
    takeaway: str,
    sectors: list[str],
    sentiment: str,
    relevance: int,
    body_text: str,
) -> tuple[dict, dict]:
    """Single LLM call. Returns (parsed_payload, usage_dict)."""
    body_truncated = (body_text or "")[:6000] or "(no body text available)"

    user_msg = USER_PROMPT_TEMPLATE.format(
        source_name=source_name,
        credibility=credibility,
        published_date=published_date,
        source_url=source_url,
        headline=headline,
        headline_short=headline_short or headline,
        takeaway=takeaway or "(none)",
        sectors=", ".join(sectors) if sectors else "(none)",
        sentiment=sentiment or "mixed",
        relevance=relevance,
        body_text=body_truncated,
    )

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.4,
        max_tokens=2400,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    parsed = json.loads(raw)

    usage = getattr(response, "usage", None)
    in_tok = getattr(usage, "prompt_tokens", 0) if usage else 0
    out_tok = getattr(usage, "completion_tokens", 0) if usage else 0
    if usage is not None:
        _LLM_USAGE["calls"] += 1
        _LLM_USAGE["input_tokens"] += in_tok or 0
        _LLM_USAGE["output_tokens"] += out_tok or 0

    cost = (
        (in_tok or 0) / 1_000_000 * settings.llm_input_price_per_mtok
        + (out_tok or 0) / 1_000_000 * settings.llm_output_price_per_mtok
    )
    return parsed, {
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cost_usd": round(cost, 6),
        "model": settings.openai_model,
    }


def _entry_metadata(item, source_table: str) -> dict:
    analysis = item.analysis_json or {}
    if source_table == "external_articles":
        if item.source == SourceType.FEDERAL_REGISTER:
            source_name = "Federal Register"
            credibility = "OFFICIAL"
        elif item.source == SourceType.OFAC_SDN:
            source_name = "OFAC SDN List"
            credibility = "OFFICIAL"
        elif item.source == SourceType.TRAVEL_ADVISORY:
            source_name = "US State Department"
            credibility = "OFFICIAL"
        elif item.source == SourceType.GDELT:
            source_name = (item.extra_metadata or {}).get("domain") or item.source_name or "International Press"
            credibility = "TIER2"
        else:
            source_name = item.source_name or item.source.value
            credibility = "TIER1"
    else:
        source_name = "Asamblea Nacional del Poder Popular (Cuba)"
        credibility = "STATE"

    return {
        "source_name": source_name,
        "credibility": credibility,
        "headline_short": analysis.get("headline_short", ""),
        "takeaway": analysis.get("takeaway", ""),
        "sectors": analysis.get("sectors", []) or [],
        "sentiment": analysis.get("sentiment", "mixed"),
        "relevance": analysis.get("relevance_score", 0),
    }


def _post_url_slug(db, headline: str, source_table: str, source_id: int, published: date) -> str:
    """Resolve the public /briefing slug for a new post.

    The default is now the SEO slug itself:

        /briefing/cuba-develops-technology-to-refine-its-own-crude-oil

    Only if that slug is already taken do we append a compact numeric
    suffix (`-2`, `-3`, ...). This keeps new URLs readable while
    preserving the unique constraint on BlogPost.slug.
    """
    base = _slugify(headline)
    existing = {
        row.slug
        for row in db.query(BlogPost.slug)
        .filter(BlogPost.slug.like(f"{base}%"))
        .all()
    }
    if base not in existing:
        return base

    max_len = 110
    for n in range(2, 1000):
        suffix = f"-{n}"
        candidate_base = base[: max_len - len(suffix)].rstrip("-")
        candidate = f"{candidate_base}{suffix}"
        if candidate not in existing:
            return candidate

    # Extremely defensive fallback; should never happen, but keeps
    # generation from failing if a title has hundreds of duplicates.
    return f"{base[:96].rstrip('-')}-{published.strftime('%Y%m%d')}-{source_id}"


def _persist_post(
    db,
    *,
    source_table: str,
    source_id: int,
    item,
    payload: dict,
    usage: dict,
) -> BlogPost:
    body_html = _sanitize_body_html(payload.get("body_html", ""))
    word_count = _count_words(body_html)
    reading_minutes = max(1, round(word_count / 220))

    title = (payload.get("title") or item.headline)[:300]
    slug = _post_url_slug(db, title, source_table, source_id, item.published_date)

    keywords = payload.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]

    sectors = payload.get("sectors") or item.analysis_json.get("sectors", []) or []
    primary_sector = (payload.get("primary_sector") or (sectors[0] if sectors else None))
    if isinstance(primary_sector, str):
        primary_sector = primary_sector[:80]

    social_hook = (payload.get("social_hook") or "").strip()
    if social_hook:
        social_hook = social_hook[:280]

    post = BlogPost(
        source_table=source_table,
        source_id=source_id,
        slug=slug,
        title=title,
        subtitle=(payload.get("subtitle") or "")[:500],
        summary=(payload.get("summary") or "")[:600],
        body_html=body_html,
        social_hook=social_hook or None,
        primary_sector=primary_sector,
        sectors_json=sectors,
        keywords_json=keywords,
        related_slugs_json=[],
        word_count=word_count,
        reading_minutes=reading_minutes,
        published_date=item.published_date,
        canonical_source_url=item.source_url,
        llm_model=usage.get("model"),
        llm_input_tokens=usage.get("input_tokens"),
        llm_output_tokens=usage.get("output_tokens"),
        llm_cost_usd=usage.get("cost_usd"),
    )
    db.add(post)
    db.commit()
    db.refresh(post)

    # Render the per-briefing OG card and persist its bytes on the row.
    # Best-effort: a render failure should never block the blog itself
    # from being saved (a missing card just falls back to the generic
    # site-wide OG image at request time).
    try:
        from src.og_image import latest_eltoque_usd, render_briefing_card

        png = render_briefing_card(
            title=post.title or "",
            category=post.primary_sector,
            published_date=post.published_date,
            informal_usd=latest_eltoque_usd(),
        )
        if png:
            post.og_image_bytes = png
            db.commit()
            db.refresh(post)
    except Exception as exc:
        logger.warning("blog_generator: og card render failed for slug=%s: %s", post.slug, exc)

    return post


def run_blog_generation(*, budget: int | None = None) -> dict:
    """
    Find candidate entries with no blog post yet, write up to `budget`
    posts, persist, return a summary dict.
    """
    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY not set; skipping blog generation")
        return {"generated": 0, "skipped": "no_api_key"}

    init_db()
    db = SessionLocal()
    try:
        budget = budget if budget is not None else settings.blog_gen_budget_per_run
        if budget <= 0:
            return {"generated": 0, "skipped": "budget_zero"}

        existing = _existing_blog_keys(db)

        ext_candidates = [
            r for r in _candidate_external(db) if ("external_articles", r.id) not in existing
        ]
        asm_candidates = [
            r for r in _candidate_assembly(db) if ("assembly_news", r.id) not in existing
        ]

        ranked: list[tuple[int, str, object]] = []
        for r in ext_candidates:
            ranked.append((
                int((r.analysis_json or {}).get("relevance_score", 0)),
                "external_articles",
                r,
            ))
        for r in asm_candidates:
            ranked.append((
                int((r.analysis_json or {}).get("relevance_score", 0)),
                "assembly_news",
                r,
            ))
        ranked.sort(key=lambda t: (t[0], t[2].published_date), reverse=True)

        client = OpenAI(api_key=settings.openai_api_key)

        generated = 0
        failed = 0
        total_cost = 0.0
        slugs: list[str] = []

        for relevance, source_table, item in ranked[:budget]:
            meta = _entry_metadata(item, source_table)
            try:
                payload, usage = _build_post_payload(
                    client,
                    source_name=meta["source_name"],
                    credibility=meta["credibility"],
                    published_date=item.published_date.isoformat(),
                    source_url=item.source_url,
                    headline=item.headline,
                    headline_short=meta["headline_short"],
                    takeaway=meta["takeaway"],
                    sectors=meta["sectors"],
                    sentiment=meta["sentiment"],
                    relevance=meta["relevance"],
                    body_text=item.body_text or "",
                )
                post = _persist_post(
                    db,
                    source_table=source_table,
                    source_id=item.id,
                    item=item,
                    payload=payload,
                    usage=usage,
                )
                generated += 1
                total_cost += usage.get("cost_usd") or 0.0
                slugs.append(post.slug)
                logger.info(
                    "blog_generator: wrote %s (relevance=%d, %d words, $%.4f)",
                    post.slug, relevance, post.word_count, usage.get("cost_usd") or 0.0,
                )
            except Exception as exc:
                logger.exception("blog_generator failed on %s/%d: %s", source_table, item.id, exc)
                failed += 1
                db.rollback()

        return {
            "generated": generated,
            "failed": failed,
            "candidates": len(ranked),
            "budget": budget,
            "estimated_cost_usd": round(total_cost, 4),
            "slugs": slugs,
        }
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)-30s  %(levelname)-8s  %(message)s",
    )
    print(run_blog_generation())
