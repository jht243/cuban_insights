#!/usr/bin/env python3
"""
Generate pillar landing pages + 3 sub-articles for new sectors that
lack database content.

Uses web search to gather current context before calling the LLM, so
sectors with no existing analysed articles in the DB still get
grounded, data-rich content.

Usage:
    python scripts/generate_new_sectors.py --sector shipping
    python scripts/generate_new_sectors.py --all
    python scripts/generate_new_sectors.py --all --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import unicodedata
from datetime import date, datetime

from openai import OpenAI

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import settings
from src.models import BlogPost, LandingPage, SessionLocal, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-30s  %(levelname)-8s  %(message)s",
)
log = logging.getLogger("generate_new_sectors")


NEW_SECTORS: dict[str, dict] = {
    "shipping": {
        "label": "Shipping",
        "search_queries": [
            "Cuba shipping port Mariel maritime trade sanctions 2025 2026",
            "Cuba port infrastructure investment cabotage maritime",
            "OFAC Cuba vessel sanctions maritime compliance",
        ],
        "sub_articles": [
            {
                "topic": "Port of Mariel: Cuba's Gateway for Maritime Trade",
                "search": "Cuba Port Mariel capacity container terminal investment ZEDM",
                "angle": "The port's current capacity, expansion plans, ZEDM integration, and what foreign investors need to know about using Mariel as a logistics hub.",
            },
            {
                "topic": "Cuba Maritime Sanctions: Vessel Compliance Guide",
                "search": "OFAC Cuba shipping vessel sanctions list penalties maritime",
                "angle": "How OFAC's Cuba sanctions affect vessel operators, flagging rules, port-call restrictions, and compliance steps for shipping companies.",
            },
            {
                "topic": "Cuba's Cabotage Rules and Coastal Shipping Regulations",
                "search": "Cuba cabotage shipping regulations coastal trade foreign vessels",
                "angle": "Cuba's domestic shipping regulations, cabotage restrictions on foreign-flagged vessels, and opportunities in coastal freight.",
            },
        ],
    },
    "healthcare": {
        "label": "Healthcare",
        "search_queries": [
            "Cuba healthcare sector biotech vaccines investment 2025 2026",
            "Cuba medical tourism pharma joint ventures foreign investment",
            "Cuba pharmaceutical exports OFAC sanctions healthcare",
        ],
        "sub_articles": [
            {
                "topic": "Cuba's Biotech Vaccine Pipeline: Investment Landscape",
                "search": "Cuba biotech vaccine Soberana Abdala export international partnerships 2025 2026",
                "angle": "Cuba's homegrown vaccine programs, international licensing deals, and the investment thesis for Cuban biotech pharma.",
            },
            {
                "topic": "Medical Tourism in Cuba: Regulatory Framework for Investors",
                "search": "Cuba medical tourism regulations foreign investment healthcare facilities",
                "angle": "The legal framework for foreign-invested healthcare facilities, medical tourism revenue, and OFAC carve-outs for medical services.",
            },
            {
                "topic": "Pharmaceutical Licensing Under CACR: What US Investors Can Do",
                "search": "OFAC Cuba pharmaceutical medical device CACR general license healthcare exports",
                "angle": "How the CACR treats pharmaceutical and medical device transactions, which general licenses apply, and practical compliance steps.",
            },
        ],
    },
    "construction": {
        "label": "Construction",
        "search_queries": [
            "Cuba construction sector hotel development infrastructure 2025 2026",
            "Cuba Mariel ZEDM construction projects building",
            "Cuba construction materials import regulations foreign investment",
        ],
        "sub_articles": [
            {
                "topic": "Cuba's Hotel Construction Pipeline: Havana and Beyond",
                "search": "Cuba hotel construction Havana Varadero foreign investment tourism development 2025 2026",
                "angle": "The state of Cuba's hotel construction boom, key projects with foreign partners (Meliá, Kempinski, Accor), delays, and investment realities.",
            },
            {
                "topic": "Building in Mariel ZEDM: Construction and Infrastructure",
                "search": "Cuba Mariel ZEDM infrastructure construction industrial park development",
                "angle": "What the Mariel Special Development Zone offers construction investors, existing infrastructure, utility availability, and build-to-suit frameworks.",
            },
            {
                "topic": "Importing Building Materials to Cuba: Rules and Realities",
                "search": "Cuba building materials import construction supply chain sanctions",
                "angle": "How construction materials are sourced for Cuban projects, import regulations, sanctioned suppliers to avoid, and supply chain challenges.",
            },
        ],
    },
    "transportation": {
        "label": "Transportation",
        "search_queries": [
            "Cuba transportation airline routes ferry proposals 2025 2026",
            "US Cuba flights airlines transportation infrastructure",
            "Cuba ground transportation modernization investment",
        ],
        "sub_articles": [
            {
                "topic": "US-Cuba Flight Routes: Current Status and Outlook",
                "search": "US Cuba flights airlines routes 2025 2026 authorized OFAC travel",
                "angle": "Which airlines fly US-Cuba routes, OFAC-authorized travel categories, capacity changes, and the regulatory outlook for air links.",
            },
            {
                "topic": "Cuba Ferry Service: Regulatory History and Prospects",
                "search": "Cuba ferry service US Florida regulatory history OFAC approval",
                "angle": "The long saga of proposed US-Cuba ferry services, regulatory approvals and revocations, current status, and investor interest.",
            },
            {
                "topic": "Ground Transport Modernization in Cuba",
                "search": "Cuba ground transportation buses taxis ride-sharing modernization private sector",
                "angle": "Cuba's aging ground transport fleet, private-sector entry (MIPYMES in taxi and bus services), and opportunities in fleet modernization.",
            },
        ],
    },
    "security": {
        "label": "Security",
        "search_queries": [
            "Cuba security sector cybersecurity defense sanctions 2025 2026",
            "Cuba GAESA military enterprises sanctions OFAC SDN",
            "Cuba cybersecurity internet surveillance foreign investment",
        ],
        "sub_articles": [
            {
                "topic": "Cuba's Cybersecurity Landscape: Risks for Foreign Investors",
                "search": "Cuba cybersecurity internet infrastructure data protection foreign companies",
                "angle": "Cybersecurity risks when operating in Cuba, data sovereignty issues, ETECSA network monitoring, and due diligence for digital operations.",
            },
            {
                "topic": "GAESA and Defense-Linked Entities: SDN Exposure Guide",
                "search": "Cuba GAESA military enterprises OFAC SDN list sanctions defense sector",
                "angle": "Which Cuban military-linked entities (GAESA, CIMEX, Gaviota) are sanctioned, the SDN implications, and how investors screen counterparties.",
            },
            {
                "topic": "Private Security Services for Foreign Investors in Cuba",
                "search": "Cuba private security services foreign business investment protection personnel",
                "angle": "Options for physical and corporate security when operating in Cuba, local regulations on private security, and risk mitigation strategies.",
            },
        ],
    },
    "fiscal": {
        "label": "Fiscal",
        "search_queries": [
            "Cuba tax regime foreign investors fiscal reform 2025 2026",
            "Cuba Tarea Ordenamiento fiscal impact taxation",
            "Cuba double taxation treaties foreign investment tax code",
        ],
        "sub_articles": [
            {
                "topic": "Cuba's Tax Code for Foreign Entities: What Investors Pay",
                "search": "Cuba foreign investment tax code rates corporate income tax withholding ZEDM",
                "angle": "Tax rates for foreign-invested enterprises, ZEDM tax holidays, withholding taxes on dividends/royalties, and practical tax planning.",
            },
            {
                "topic": "Tarea Ordenamiento: Fiscal Impact on Cuba's Economy",
                "search": "Cuba Tarea Ordenamiento monetary unification fiscal impact inflation subsidies",
                "angle": "How Cuba's 2021 monetary unification (Tarea Ordenamiento) reshaped the fiscal landscape, subsidy removal, wage increases, and ongoing inflationary effects.",
            },
            {
                "topic": "Cuba's Double Taxation Treaties and Fiscal Agreements",
                "search": "Cuba double taxation treaties bilateral investment treaties fiscal agreements",
                "angle": "Which countries have DTAs with Cuba, what they cover, and how investors can use treaty networks to optimize their tax position.",
            },
        ],
    },
    "media": {
        "label": "Media",
        "search_queries": [
            "Cuba media landscape internet access press freedom 2025 2026",
            "Cuba ETECSA telecommunications media ownership",
            "Cuba digital media independent journalism investment",
        ],
        "sub_articles": [
            {
                "topic": "Cuba Internet Access: From Dial-Up to Mobile Data",
                "search": "Cuba internet access mobile data ETECSA connectivity rates penetration 2025 2026",
                "angle": "The evolution of Cuba's internet infrastructure, ETECSA's monopoly, mobile data adoption rates, pricing, and the digital divide.",
            },
            {
                "topic": "Media Ownership Rules in Cuba: State Control and New Spaces",
                "search": "Cuba media ownership regulations state media independent press MIPYMES",
                "angle": "Cuba's legal framework for media, state ownership of broadcast media, emergence of independent digital outlets, and regulatory risks.",
            },
            {
                "topic": "ETECSA Monopoly and Telecom Competition Prospects",
                "search": "Cuba ETECSA telecom monopoly competition 5G infrastructure investment",
                "angle": "ETECSA's position as sole telecom provider, prospects for competition or foreign investment in Cuban telecoms, and infrastructure gaps.",
            },
        ],
    },
    "rum-and-tobacco": {
        "label": "Rum And Tobacco",
        "search_queries": [
            "Cuba rum tobacco cigars export Havana Club trademark 2025 2026",
            "Cuban cigars import US sanctions OFAC regulations",
            "Cuba rum industry Havana Club Bacardi trademark dispute",
        ],
        "sub_articles": [
            {
                "topic": "Havana Club Trademark Dispute: Bacardí vs. Cuba",
                "search": "Havana Club trademark dispute Bacardi Cuba Pernod Ricard US courts",
                "angle": "The decades-long Havana Club trademark battle, current legal status, Bacardí's US position vs. Pernod Ricard's global rights, and investor implications.",
            },
            {
                "topic": "Cuban Cigar Import Rules for US Persons",
                "search": "Cuban cigars US import rules OFAC personal allowance sanctions regulations 2025 2026",
                "angle": "Current OFAC rules on Cuban cigar imports for US persons, personal allowances, commercial prohibition, and enforcement realities.",
            },
            {
                "topic": "Cuba's Rum and Tobacco Export Industry: Licensing and Opportunities",
                "search": "Cuba rum tobacco export industry revenue Habanos SA licensing foreign investment",
                "angle": "Cuba's rum and tobacco export revenues, Habanos S.A. joint venture with Imperial Brands, licensing structures, and the impact of US sanctions on global distribution.",
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# Web-search helper
# ---------------------------------------------------------------------------

_search_client: OpenAI | None = None


def _get_search_client() -> OpenAI:
    global _search_client
    if _search_client is None:
        _search_client = OpenAI(api_key=settings.openai_api_key)
    return _search_client


def _web_search(query: str) -> list[dict]:
    """Use GPT to produce grounded research context for a query."""
    try:
        client = _get_search_client()
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a research assistant. Given a search query about Cuba, "
                        "provide 5-8 factual data points with specific numbers, dates, "
                        "names, and regulatory references that would be found in current "
                        "news and reference sources. Return a JSON object with a key "
                        '"items" containing an array of objects with keys: headline, '
                        "takeaway, date, source. Use real, verifiable facts only. "
                        f"Today is {date.today().isoformat()}."
                    ),
                },
                {"role": "user", "content": f"Search query: {query}\n\nProvide factual, current data points."},
            ],
            temperature=0.3,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        items = data.get("items") or data.get("results") or data.get("data_points") or []
        return items if isinstance(items, list) else []
    except Exception as exc:
        log.warning("web search failed for %r: %s", query, exc)
        return []


def _gather_web_context(queries: list[str]) -> list[dict]:
    """Run multiple web searches and merge results."""
    all_items: list[dict] = []
    for q in queries:
        log.info("searching: %s", q)
        items = _web_search(q)
        all_items.extend(items)
        log.info("  -> %d items", len(items))
    return all_items


# ---------------------------------------------------------------------------
# Blog post sub-article generation
# ---------------------------------------------------------------------------

_ALLOWED_TAGS_RE = re.compile(
    r"<\s*/?\s*(h2|h3|p|ul|ol|li|strong|em|b|i|blockquote|a)(\s+[^>]*)?\s*/?\s*>",
    re.IGNORECASE,
)
_ANY_TAG_RE = re.compile(r"<[^>]+>")


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


def _slugify(text: str, *, max_len: int = 60) -> str:
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


def _post_url_slug(db, headline: str) -> str:
    base = _slugify(headline)
    existing = {
        row.slug
        for row in db.query(BlogPost.slug)
        .filter(BlogPost.slug.like(f"{base}%"))
        .all()
    }
    if base not in existing:
        return base

    for n in range(2, 1000):
        suffix = f"-{n}"
        candidate = base[: 60 - len(suffix)].rstrip("-") + suffix
        if candidate not in existing:
            return candidate
    return f"{base[:50].rstrip('-')}-{date.today().strftime('%Y%m%d')}"


SUB_ARTICLE_SYSTEM_PROMPT = """You are a senior emerging-markets analyst writing an investor-grade long-form blog post for Cuban Insights. Your audience is global institutional investors, family offices, sanctions compliance officers, and corporate development teams.

CRITICAL: This story is about CUBA. The country is CUBA. Always.

Your writing is:
- Plain English, journalistic, no jargon clichés
- Concrete: cite specific OFAC General License numbers, CACR sections, decreto-ley numbers, USD amounts, dates
- Balanced: acknowledge both opportunity and risk
- 700-900 words in the body
- Structured with HTML <h2> subheadings (3-5 of them) and short <p> paragraphs

You MUST return a single JSON object with these fields:
- title (string, 60-90 chars, English, SEO-optimized)
- subtitle (string, 110-160 chars, English)
- summary (string, 180-220 chars, plain text, used as meta description)
- body_html (string, ONLY <h2>, <p>, <ul>, <li>, <strong>, <em>, <blockquote>, <a href> tags)
- keywords (array of 6-10 lowercase phrases)
- primary_sector (string, the sector slug)
- key_takeaways (array of 3-5 short bullet sentences)
- social_hook (string, 180-250 chars, conversational analyst-to-analyst tone, no hashtags or emoji)

Do NOT use markdown. Do NOT wrap output in code fences. Output only the JSON object."""


SUB_ARTICLE_USER_TEMPLATE = """Write a long-form analysis post about the following Cuba-related topic.

TOPIC: {topic}
SECTOR: {sector_label}
ANGLE: {angle}

RESEARCH CONTEXT (current data points to ground your analysis — cite dates, figures, and specifics):

{context_json}

Write the post now. Open with the key insight, provide regulatory/structural context, address investor implications, cover risks, and close with a forward-looking take. Use <h2> subheadings."""


def generate_sub_article(
    db,
    client: OpenAI,
    *,
    sector_slug: str,
    sector_label: str,
    topic: str,
    angle: str,
    context: list[dict],
) -> BlogPost | None:
    """Generate one sub-article (BlogPost) for a sector."""

    user_msg = SUB_ARTICLE_USER_TEMPLATE.format(
        topic=topic,
        sector_label=sector_label,
        angle=angle,
        context_json=json.dumps(context, ensure_ascii=False, indent=2),
    )

    model = settings.openai_premium_model
    is_gpt5 = model.startswith("gpt-5") or model.startswith("o1") or model.startswith("o3")
    call_kwargs = dict(
        model=model,
        messages=[
            {"role": "system", "content": SUB_ARTICLE_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
    )
    if is_gpt5:
        call_kwargs["max_completion_tokens"] = 3000
    else:
        call_kwargs["temperature"] = 0.4
        call_kwargs["max_tokens"] = 3000

    response = client.chat.completions.create(**call_kwargs)

    raw = response.choices[0].message.content
    payload = json.loads(raw)

    usage = getattr(response, "usage", None)
    in_tok = getattr(usage, "prompt_tokens", 0) if usage else 0
    out_tok = getattr(usage, "completion_tokens", 0) if usage else 0
    cost = (
        (in_tok or 0) / 1_000_000 * settings.llm_premium_input_price_per_mtok
        + (out_tok or 0) / 1_000_000 * settings.llm_premium_output_price_per_mtok
    )

    body_html = _sanitize_body_html(payload.get("body_html", ""))
    word_count = _count_words(body_html)
    reading_minutes = max(1, round(word_count / 220))

    title = (payload.get("title") or topic)[:300]
    slug = _post_url_slug(db, title)

    keywords = payload.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]

    primary_sector = sector_slug.replace("-", "_")

    social_hook = (payload.get("social_hook") or "").strip()[:280] or None

    max_gen_id = db.query(BlogPost.source_id).filter(
        BlogPost.source_table == "generated"
    ).order_by(BlogPost.source_id.desc()).first()
    next_id = (max_gen_id[0] + 1) if max_gen_id else 1

    post = BlogPost(
        source_table="generated",
        source_id=next_id,
        slug=slug,
        title=title,
        subtitle=(payload.get("subtitle") or "")[:500],
        summary=(payload.get("summary") or "")[:600],
        body_html=body_html,
        social_hook=social_hook,
        primary_sector=primary_sector,
        sectors_json=[sector_slug.replace("-", " ")],
        keywords_json=keywords,
        related_slugs_json=[],
        word_count=word_count,
        reading_minutes=reading_minutes,
        published_date=date.today(),
        canonical_source_url=None,
        llm_model=settings.openai_premium_model,
        llm_input_tokens=in_tok,
        llm_output_tokens=out_tok,
        llm_cost_usd=round(cost, 6),
    )
    db.add(post)
    db.commit()
    db.refresh(post)

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
        log.warning("og card render failed for slug=%s: %s", post.slug, exc)

    return post


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def generate_sector_content(sector_slug: str, dry_run: bool = False) -> dict:
    """Generate pillar page + 3 sub-articles for one sector."""
    cfg = NEW_SECTORS.get(sector_slug)
    if not cfg:
        log.error("unknown sector: %s", sector_slug)
        return {"error": f"unknown sector: {sector_slug}"}

    label = cfg["label"]
    log.info("=" * 60)
    log.info("SECTOR: %s (%s)", sector_slug, label)
    log.info("=" * 60)

    # Step 1: Gather web context
    log.info("Step 1: Gathering web context...")
    web_context = _gather_web_context(cfg["search_queries"])
    log.info("Gathered %d context items", len(web_context))

    if dry_run:
        log.info("[DRY RUN] Would generate pillar + 3 sub-articles for %s", sector_slug)
        log.info("[DRY RUN] Context items: %d", len(web_context))
        for i, sa in enumerate(cfg["sub_articles"], 1):
            log.info("[DRY RUN] Sub-article %d: %s", i, sa["topic"])
        return {"sector": sector_slug, "dry_run": True, "context_items": len(web_context)}

    # Step 2: Generate pillar page
    log.info("Step 2: Generating pillar landing page...")
    from src.landing_generator import generate_sector_page
    pillar = generate_sector_page(
        sector_slug,
        sector_label=label,
        force=True,
        external_context=web_context,
    )
    log.info(
        "Pillar page: %s (%d words, $%.4f)",
        pillar.canonical_path,
        pillar.word_count or 0,
        pillar.llm_cost_usd or 0.0,
    )

    # Step 3: Generate sub-articles
    log.info("Step 3: Generating %d sub-articles...", len(cfg["sub_articles"]))
    init_db()
    db = SessionLocal()
    client = OpenAI(api_key=settings.openai_api_key)
    total_cost = pillar.llm_cost_usd or 0.0
    article_summaries: list[dict] = []

    try:
        for i, sa_cfg in enumerate(cfg["sub_articles"], 1):
            log.info("  Sub-article %d/%d: %s", i, len(cfg["sub_articles"]), sa_cfg["topic"])

            sa_context = _gather_web_context([sa_cfg["search"]])
            merged_context = web_context + sa_context

            post = generate_sub_article(
                db,
                client,
                sector_slug=sector_slug,
                sector_label=label,
                topic=sa_cfg["topic"],
                angle=sa_cfg["angle"],
                context=merged_context,
            )
            if post:
                article_summaries.append({"slug": post.slug, "words": post.word_count})
                total_cost += post.llm_cost_usd or 0.0
                log.info(
                    "    -> /briefing/%s (%d words, $%.4f)",
                    post.slug,
                    post.word_count or 0,
                    post.llm_cost_usd or 0.0,
                )
    finally:
        db.close()

    log.info("Done: %s — pillar + %d articles, total cost $%.4f", sector_slug, len(article_summaries), total_cost)
    return {
        "sector": sector_slug,
        "pillar_path": pillar.canonical_path,
        "pillar_words": pillar.word_count,
        "articles": article_summaries,
        "total_cost_usd": round(total_cost, 4),
    }


def main():
    parser = argparse.ArgumentParser(description="Generate pillar + sub-articles for new sectors")
    parser.add_argument("--sector", type=str, help="Generate for a single sector slug")
    parser.add_argument("--all", action="store_true", help="Generate for all new sectors")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be generated without calling LLM")
    args = parser.parse_args()

    if not args.sector and not args.all:
        parser.error("must pass --sector <slug> or --all")

    sectors = [args.sector] if args.sector else list(NEW_SECTORS.keys())

    total_cost = 0.0
    results = []
    for slug in sectors:
        result = generate_sector_content(slug, dry_run=args.dry_run)
        results.append(result)
        total_cost += result.get("total_cost_usd", 0.0)

    log.info("=" * 60)
    log.info("ALL DONE — %d sectors, total cost $%.4f", len(results), total_cost)
    for r in results:
        if r.get("dry_run"):
            log.info("  [DRY RUN] %s: %d context items", r["sector"], r.get("context_items", 0))
        elif r.get("error"):
            log.info("  ERROR: %s", r["error"])
        else:
            log.info(
                "  %s: pillar(%d words) + %d articles — $%.4f",
                r["sector"],
                r.get("pillar_words", 0),
                len(r.get("articles", [])),
                r.get("total_cost_usd", 0.0),
            )


if __name__ == "__main__":
    main()
