"""
LLM-powered investor analysis for scraped articles.

Reads entries with status=SCRAPED from the database, sends each to GPT-4o
with an investor-focused prompt, and stores structured analysis in analysis_json.
Only entries scoring above the relevance threshold make it into the report.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, timedelta

from openai import OpenAI

from src.config import settings
from src.models import (
    SessionLocal,
    ExternalArticleEntry,
    AssemblyNewsEntry,
    GazetteEntry,
    GazetteStatus,
    SourceType,
)

logger = logging.getLogger(__name__)

LLM_CALL_BUDGET_PER_RUN = 30
GDELT_TONE_THRESHOLD = 3.0
RELEVANCE_KEYWORDS = (
    "sanction", "sanctions", "ofac", "treasury", "executive order",
    "license", "oil", "pdvsa", "chevron", "mining", "real estate",
    "property", "expropriat", "nationaliz", "bcv", "bond", "debt",
    "amnesty", "election", "maduro", "guaido", "machado",
    "investor", "investment", "fdi", "imf", "world bank",
    "bilateral", "ambassador", "diplomatic", "consulate",
)

SYSTEM_PROMPT = """You are a senior investment analyst specializing in Venezuela.
You work for an intelligence service that helps international investors navigate
Venezuela's political and economic transition (post-January 2026).

Your audience: sophisticated institutional investors evaluating opportunities in
Non-Oil Commercial Business, Mining, Real Estate, Energy, and Financial Services.

For each article, produce a JSON object with these fields:
{
  "relevance_score": <int 1-10, where 10 = directly changes investment thesis>,
  "sectors": [<list of applicable sectors from: "realestate", "security", "economic", "fiscal", "sanctions", "diplomatic", "governance", "legal", "mining", "energy", "banking">],
  "sentiment": "<one of: positive, negative, mixed>",
  "status": "<one of: passed, in_progress, announced, in_effect, monitoring>",
  "status_label": "<short label for the status pill, e.g. 'Passed — In Effect', 'In Progress — 2nd Discussion'>",
  "category_label": "<display label, e.g. 'Sanctions', 'Energy & Oil', 'US Relations'>",
  "headline_short": "<concise headline, max 80 chars>",
  "takeaway": "<2-4 sentence investor impact analysis. Be specific about what this means for foreign capital. Bold the single most important sentence using <strong> tags.>",
  "is_breaking": <true if this is a major development that materially changes the investment landscape>,
  "source_trust": "<one of: official, tier1, state, tier2>"
}

Guidelines:
- Score 1-3: routine administrative, no investment relevance
- Score 4-5: background context, minor policy signals
- Score 6-7: meaningful policy change, watch closely
- Score 8-10: directly affects foreign investment, sanctions, or property rights
- Be concise but specific. Name the law, entity, or mechanism.
- Write in English regardless of source language.
- If the article is noise (social media recap, sports, weather), score it 1.
- For OFAC/sanctions changes, always score 7+.
- For travel advisory level changes, always score 8+.

Return ONLY the JSON object, no markdown fences or explanation."""

USER_PROMPT_TEMPLATE = """Analyze this article for Venezuela investment relevance:

SOURCE: {source_name} ({credibility})
DATE: {published_date}
HEADLINE: {headline}
URL: {source_url}

BODY:
{body_text}"""


def run_analysis() -> dict:
    """
    Analyze all unprocessed entries in the database.
    Returns a summary dict with counts.
    """
    if not settings.openai_api_key:
        logger.error("OPENAI_API_KEY not set — skipping analysis")
        return {"analyzed": 0, "skipped": 0, "errors": 0}

    client = OpenAI(api_key=settings.openai_api_key)
    db = SessionLocal()

    summary = {"analyzed": 0, "skipped": 0, "errors": 0}

    try:
        ext_articles = (
            db.query(ExternalArticleEntry)
            .filter(ExternalArticleEntry.status == GazetteStatus.SCRAPED)
            .filter(
                ExternalArticleEntry.published_date
                >= date.today() - timedelta(days=settings.report_lookback_days)
            )
            .all()
        )

        assembly_news = (
            db.query(AssemblyNewsEntry)
            .filter(AssemblyNewsEntry.status == GazetteStatus.SCRAPED)
            .filter(
                AssemblyNewsEntry.published_date
                >= date.today() - timedelta(days=settings.report_lookback_days)
            )
            .all()
        )

        logger.info(
            "Analysis queue: %d external articles, %d assembly news",
            len(ext_articles),
            len(assembly_news),
        )

        rule_based, llm_candidates = _partition_articles(ext_articles)
        logger.info(
            "Partitioned: %d rule-based (no LLM), %d LLM candidates (cap=%d)",
            len(rule_based),
            len(llm_candidates),
            LLM_CALL_BUDGET_PER_RUN,
        )

        for article in rule_based:
            try:
                article.analysis_json = _rule_based_analysis(article)
                article.status = GazetteStatus.ANALYZED
                summary["analyzed"] += 1
            except Exception as e:
                logger.error("Rule-based analysis failed for article %d: %s", article.id, e)
                summary["errors"] += 1
        db.commit()
        logger.info("Rule-based pass: %d entries marked analyzed (no LLM cost)", len(rule_based))

        llm_budget = LLM_CALL_BUDGET_PER_RUN
        for article in llm_candidates:
            if llm_budget <= 0:
                logger.info("LLM budget exhausted; remaining %d articles skipped", len(llm_candidates) - summary["analyzed"])
                summary["skipped"] += 1
                continue
            try:
                analysis = _analyze_article(
                    client,
                    headline=article.headline,
                    body_text=article.body_text or "",
                    source_name=article.source_name or "Unknown",
                    credibility=article.credibility.value if article.credibility else "tier2",
                    published_date=str(article.published_date),
                    source_url=article.source_url,
                )
                article.analysis_json = analysis
                article.status = GazetteStatus.ANALYZED
                db.commit()
                summary["analyzed"] += 1
                llm_budget -= 1
                logger.info(
                    "LLM analyzed [%d/%d, budget %d left]: %s (score=%s)",
                    summary["analyzed"],
                    len(llm_candidates),
                    llm_budget,
                    article.headline[:60],
                    analysis.get("relevance_score", "?"),
                )
            except Exception as e:
                logger.error("Analysis failed for article %d: %s", article.id, e)
                summary["errors"] += 1
                db.rollback()

            time.sleep(0.5)

        for news in assembly_news:
            try:
                analysis = _analyze_article(
                    client,
                    headline=news.headline,
                    body_text=news.body_text or "",
                    source_name="Asamblea Nacional",
                    credibility="state",
                    published_date=str(news.published_date),
                    source_url=news.source_url,
                )
                news.analysis_json = analysis
                news.status = GazetteStatus.ANALYZED
                db.commit()
                summary["analyzed"] += 1
                logger.info(
                    "Analyzed assembly news: %s (score=%s)",
                    news.headline[:60],
                    analysis.get("relevance_score", "?"),
                )
            except Exception as e:
                logger.error("Analysis failed for news %d: %s", news.id, e)
                summary["errors"] += 1
                db.rollback()

            time.sleep(0.5)

    finally:
        db.close()

    logger.info("Analysis complete: %s", summary)
    return summary


def _partition_articles(articles: list) -> tuple[list, list]:
    """Split articles into (rule_based, llm_candidates).

    Rule-based: handled with cheap templates (no LLM call). Currently OFAC SDN.
    LLM candidates: must clear a keyword/tone pre-screen and are sorted so the
    most likely high-impact items get the LLM budget first.
    """
    rule_based = []
    llm_candidates = []

    for a in articles:
        if a.source == SourceType.OFAC_SDN:
            rule_based.append(a)
            continue

        if not _passes_prefilter(a):
            rule_based.append(a)
            continue

        llm_candidates.append(a)

    llm_candidates.sort(key=_llm_priority, reverse=True)
    return rule_based, llm_candidates


def _passes_prefilter(article) -> bool:
    """Cheap heuristic: must look investor-relevant before we pay for an LLM call."""
    text = f"{article.headline or ''} {article.body_text or ''}".lower()
    if not any(kw in text for kw in RELEVANCE_KEYWORDS):
        return False

    if article.source == SourceType.GDELT:
        tone = article.tone_score
        if tone is not None and abs(tone) < GDELT_TONE_THRESHOLD:
            return False

    return True


def _llm_priority(article) -> tuple:
    """Higher tuple = analyzed first when budget is tight."""
    source_rank = {
        SourceType.FEDERAL_REGISTER: 4,
        SourceType.TRAVEL_ADVISORY: 3,
        SourceType.GDELT: 2,
    }.get(article.source, 1)
    tone_magnitude = abs(article.tone_score) if article.tone_score is not None else 0
    return (source_rank, tone_magnitude)


def _rule_based_analysis(article) -> dict:
    """Templated analysis for high-volume, low-variance sources.

    Avoids paying GPT-4o per row when the structure is identical (e.g. OFAC SDN
    additions/removals — 410 entries that all decode to "person/entity sanctioned
    under Venezuela program"). Templated entries land in the DB so they're
    queryable, but get a low relevance score so they don't flood the report.
    """
    if article.source == SourceType.OFAC_SDN:
        meta = article.extra_metadata or {}
        name = meta.get("name") or "Unknown entity"
        program = meta.get("program") or "Venezuela program"
        entity_type = (meta.get("type") or "Entity").lower()
        is_addition = "addition" in (article.article_type or "").lower()
        action = "added to" if is_addition else "removed from"
        return {
            "relevance_score": 4,
            "sectors": ["sanctions"],
            "sentiment": "negative" if is_addition else "positive",
            "status": "in_effect",
            "status_label": "OFAC SDN — In Effect",
            "category_label": "Sanctions",
            "headline_short": f"OFAC {'adds' if is_addition else 'removes'} {name[:50]}",
            "takeaway": (
                f"<strong>{name}</strong> ({entity_type}) {action} the OFAC SDN List "
                f"under {program}. US persons are prohibited from dealings with this entity."
            ),
            "is_breaking": False,
            "source_trust": "official",
            "_rule_based": True,
        }

    return {
        "relevance_score": 2,
        "sectors": [],
        "sentiment": "mixed",
        "status": "monitoring",
        "status_label": "Monitoring",
        "category_label": "Background",
        "headline_short": (article.headline or "")[:80],
        "takeaway": "Routine entry — flagged below relevance threshold by pre-screen.",
        "is_breaking": False,
        "source_trust": "tier2",
        "_rule_based": True,
    }


def _analyze_article(
    client: OpenAI,
    headline: str,
    body_text: str,
    source_name: str,
    credibility: str,
    published_date: str,
    source_url: str,
) -> dict:
    body_truncated = body_text[:3000] if body_text else "(no body text available)"

    user_msg = USER_PROMPT_TEMPLATE.format(
        source_name=source_name,
        credibility=credibility,
        published_date=published_date,
        headline=headline,
        source_url=source_url,
        body_text=body_truncated,
    )

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.3,
        max_tokens=600,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    return json.loads(raw)
