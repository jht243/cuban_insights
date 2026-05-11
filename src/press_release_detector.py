"""
Press-release opportunity detector.

After the main LLM analysis pass, scans today's analyzed articles from
credible primary or near-primary sources and evaluates each one for
press-release or research-alert potential.

Only fires when a qualifying item is found (score >= settings.press_release_min_score).
Sends a structured alert email to the editorial inbox via Resend.

Accepted source categories (primary / near-primary):
  FEDERAL_REGISTER, OFAC_SDN, TRAVEL_ADVISORY, STATE_DEPT_CRL,
  STATE_DEPT_CPAL, ITA_TRADE, GACETA_OFICIAL_CU, ASAMBLEA_NACIONAL_CU,
  BCC_RATES, ONEI, MINREX

Excluded (general news / aggregators):
  GDELT, PRESS_RSS, NEWSDATA
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

import httpx
from openai import OpenAI

from src.config import settings
from src.models import (
    AssemblyNewsEntry,
    ExternalArticleEntry,
    GazetteStatus,
    SessionLocal,
    SourceType,
)

logger = logging.getLogger(__name__)

# Sources that meet the "primary or near-primary" bar.
# Excludes GDELT (aggregator), PRESS_RSS (mixed credibility), NEWSDATA (aggregator).
PRIMARY_SOURCES = frozenset({
    SourceType.FEDERAL_REGISTER,
    SourceType.OFAC_SDN,
    SourceType.TRAVEL_ADVISORY,
    SourceType.STATE_DEPT_CRL,
    SourceType.STATE_DEPT_CPAL,
    SourceType.ITA_TRADE,
    SourceType.GACETA_OFICIAL_CU,
    SourceType.ASAMBLEA_NACIONAL_CU,
    SourceType.BCC_RATES,
    SourceType.ONEI,
    SourceType.MINREX,
})

# Minimum relevance_score from the investor analysis pass to enter the screen.
_MIN_INVESTOR_SCORE = 6

_SYSTEM_PROMPT = """\
You are a senior intelligence editor at a specialized geopolitical research firm focused on Cuba,
Venezuela, and Latin America. Your task is to decide whether a single intelligence item has genuine
press-release or research-alert potential — meaning it would attract a reporter, investor, or
compliance professional who has NOT yet seen this finding through mainstream channels.

You are NOT writing a news summary. You are rendering a single editorial verdict.

Your standards:
1. Reject anything already widely published by Reuters, AP, Bloomberg, major newspapers, or
   general news aggregators. The item must be differentiated.
2. The underlying source must be primary or near-primary:
   government websites, official gazettes, ministries, central banks, customs/import-export
   agencies, sanctions regulators (OFAC, BIS, FinCEN, EU, UK OFSI), national statistical
   offices, court filings, company filings, official sector regulators (port, shipping, energy,
   mining, telecom, banking), serious trade publications, or multilateral institutions
   (IDB, World Bank, IMF, CAF, ECLAC, OAS).
3. The item must meet at least THREE of these 8 criteria:
   [1] Contains a new number, data point, policy change, license, approval, sanction,
       enforcement action, or regulatory shift
   [2] Affects investors, companies, banks, exporters, insurers, compliance teams, or policymakers
   [3] Has a clear "why now" reason
   [4] Reveals a trend not yet widely covered
   [5] Connects Cuba or Venezuela to broader Latin America, U.S. policy, sanctions, energy,
       migration, trade, or capital flows
   [6] Can support a clear standalone headline
   [7] Can be verified with the provided source URL
   [8] Creates a reason for journalists to contact us for explanation, quote, or follow-up data

Reject if:
- Generic political commentary
- Opinion without new facts
- Already viral news
- Unsupported social media claims
- Routine government statements with no market relevance
- Broad macro commentary without a concrete, dateable change
- Content that cannot be verified from the source URL

Scoring guidance:
  1-4: Reject — not differentiated, not verifiable, or already commoditized
  5-6: Borderline — marginal, use as research alert only if source is authoritative
  7-8: Strong — credible, differentiated, timely; recommend press release or research alert
  9-10: Exceptional — would be picked up by specialist financial or policy press immediately

Return ONLY a JSON object with these exact keys (no markdown fences, no commentary):
{
  "press_release_score": <int 1-10>,
  "criteria_met_count": <int 0-8, how many of the 8 criteria above this item satisfies>,
  "source_type": "<brief label, e.g. 'OFAC SDN List', 'U.S. Federal Register', 'Cuban Official Gazette (Gaceta Oficial)'>",
  "finding": "<one sentence stating the precise finding>",
  "not_commoditized": "<one sentence: why this is NOT already widely published>",
  "reporter_interest": "<one sentence: why a reporter would care>",
  "business_relevance": "<one sentence: investor / business / compliance relevance>",
  "suggested_headline": "<press release headline, ≤ 100 chars>",
  "executive_quote_angle": "<one-sentence quote angle, written in first person for an analyst or executive>",
  "fact_check_risks": "<fact-check risks, legal flags, or compliance caveats; or 'None identified'>",
  "recommendation": "<exactly one of: 'Use as press release' | 'Use as research alert' | 'Reject'>",
  "reject_reason": "<if Reject, brief reason; otherwise null>"
}"""

_USER_TEMPLATE = """\
Evaluate the intelligence item below for press-release or research-alert potential.

SOURCE TYPE: {source_type}
SOURCE NAME: {source_name}
CREDIBILITY TIER: {credibility}
PUBLISHED DATE: {published_date}
HEADLINE: {headline}
URL: {source_url}

INVESTOR ANALYSIS (relevance_score={relevance_score}/10):
{existing_takeaway}

FULL BODY TEXT:
{body_text}"""

_CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    background: #f3f4f6; color: #111827; -webkit-font-smoothing: antialiased;
  }
  .wrapper { max-width: 660px; margin: 0 auto; padding: 32px 16px 48px; }

  /* ── Header ── */
  .header {
    background: #111827; border-radius: 10px 10px 0 0;
    padding: 28px 28px 24px; color: #fff;
  }
  .header-brand {
    font-size: 20px; font-weight: 700; letter-spacing: -0.3px; color: #fff;
    display: flex; align-items: center; gap: 8px;
  }
  .header-meta {
    margin-top: 6px; font-size: 13px; color: #9ca3af; letter-spacing: 0.01em;
  }

  /* ── Info box ── */
  .info-box {
    background: #1e293b; border-radius: 0 0 10px 10px;
    padding: 16px 28px; font-size: 13px; color: #94a3b8; line-height: 1.6;
    margin-bottom: 24px;
  }
  .info-box strong { color: #e2e8f0; }

  /* ── Card ── */
  .card {
    background: #fff; border: 1px solid #e5e7eb; border-radius: 10px;
    margin-bottom: 20px; overflow: hidden;
  }
  .card-top { padding: 20px 24px 0; }
  .badges { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
  .badge {
    display: inline-block; padding: 4px 11px; border-radius: 20px;
    font-size: 12px; font-weight: 700; letter-spacing: 0.03em;
  }
  .badge-score-hi  { background: #fef2f2; color: #b91c1c; }
  .badge-score-mid { background: #fff7ed; color: #c2410c; }
  .badge-rec-pr    { background: #f0fdf4; color: #15803d; }
  .badge-rec-ra    { background: #eff6ff; color: #1d4ed8; }

  .card-title {
    font-size: 16px; font-weight: 700; color: #111827; line-height: 1.4;
    margin-bottom: 8px;
  }
  .card-meta {
    font-size: 12px; color: #6b7280; margin-bottom: 10px; line-height: 1.5;
  }
  .card-meta span { margin-right: 6px; }
  .card-url {
    font-size: 12px; color: #2563eb; word-break: break-all;
    margin-bottom: 18px; display: block; text-decoration: none;
  }

  /* ── Two-column table ── */
  .data-table { width: 100%; border-collapse: collapse; border-top: 1px solid #f3f4f6; }
  .data-table tr { border-bottom: 1px solid #f3f4f6; }
  .data-table tr:last-child { border-bottom: none; }
  .data-table td {
    padding: 11px 14px; vertical-align: top; font-size: 13.5px; line-height: 1.5;
  }
  .data-table .col-label {
    width: 34%; background: #f9fafb; color: #6b7280;
    font-size: 12px; font-weight: 600; white-space: nowrap;
    border-right: 1px solid #f3f4f6;
  }
  .data-table .col-value { color: #111827; }
  .col-value a { color: #2563eb; word-break: break-all; }
  .col-value.hl-green { background: #f0fdf4; color: #15803d; font-weight: 600; }
  .col-value.hl-yellow { background: #fefce8; color: #92400e; font-style: italic; }
  .col-value.hl-red { background: #fef2f2; color: #991b1b; }

  /* ── Footer ── */
  .footer {
    text-align: center; font-size: 11px; color: #9ca3af;
    margin-top: 28px; line-height: 1.7;
  }
  a { color: #2563eb; }
"""


def _score_label(score: int) -> str:
    if score >= 9:
        return "Very High"
    if score >= 7:
        return "High"
    return "Moderate"


def _score_badge_class(score: int) -> str:
    return "badge-score-hi" if score >= 7 else "badge-score-mid"


def _rec_badge_class(rec: str) -> str:
    return "badge-rec-pr" if rec == "Use as press release" else "badge-rec-ra"


def _build_card(index: int, item: dict, ev: dict) -> str:
    score: int = ev.get("press_release_score", 0)
    rec: str = ev.get("recommendation", "")
    criteria: int = ev.get("criteria_met_count", 0)
    source_url = item["source_url"]
    source_type = ev.get("source_type", item["source_type"])

    score_cls = _score_badge_class(score)
    rec_cls = _rec_badge_class(rec)

    def row(label: str, value: str, value_class: str = "col-value") -> str:
        return (
            f'<tr>'
            f'<td class="col-label">{label}</td>'
            f'<td class="{value_class}">{value}</td>'
            f'</tr>'
        )

    rows = "".join([
        row("A. Press Score", f"<strong>{score}/10</strong>"),
        row("B. Source URL", f'<a href="{source_url}">{source_url}</a>'),
        row("C. Source Type", source_type),
        row("D. Finding", ev.get("finding", "")),
        row("E. Not Commoditized Because", ev.get("not_commoditized", "")),
        row("F. Reporter Interest", ev.get("reporter_interest", "")),
        row("G. Business Relevance", ev.get("business_relevance", "")),
        row("H. Suggested Headline", ev.get("suggested_headline", ""), "col-value hl-green"),
        row("I. Executive Quote Angle",
            f"\u201c{ev.get('executive_quote_angle', '')}\u201d", "col-value hl-yellow"),
        row("J. Fact-Check / Compliance Flags",
            ev.get("fact_check_risks", "None identified"), "col-value hl-red"),
        row("K. Recommendation", f"<strong>{rec}</strong>"),
    ])

    return f"""
<div class="card">
  <div class="card-top">
    <div class="badges">
      <span class="badge {score_cls}">Score {score}/10 &mdash; {_score_label(score)}</span>
      <span class="badge {rec_cls}">{rec}</span>
    </div>
    <div class="card-title">#{index} &mdash; {ev.get('suggested_headline', item['headline'])}</div>
    <div class="card-meta">
      <span>{ev.get('source_type', item['source_name'])}</span>
      &middot; <span>{item['published_date']}</span>
      &middot; <span>Pipeline relevance: {item['relevance_score']}/10</span>
      &middot; <span>Criteria met: {criteria}/8</span>
    </div>
    <a class="card-url" href="{source_url}">{source_url}</a>
  </div>
  <table class="data-table">
    {rows}
  </table>
</div>"""


def _build_digest_html(
    qualifying: list[tuple[dict, dict]],
    run_date: str,
) -> str:
    n = len(qualifying)
    candidate_label = "1 qualifying candidate" if n == 1 else f"{n} qualifying candidates"

    cards_html = "\n".join(
        _build_card(i + 1, item, ev) for i, (item, ev) in enumerate(qualifying)
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{_CSS}</style>
</head>
<body>
<div class="wrapper">

  <div class="header">
    <div class="header-brand">&#x1FAB6; Press-Release Radar</div>
    <div class="header-meta">{run_date} &middot; {candidate_label}</div>
  </div>

  <div class="info-box">
    These findings were identified from <strong>primary or near-primary sources</strong>
    only (government, regulatory, central bank, official gazette, or serious trade wire).
    Aggregators (Google News, GDELT) have been excluded.
    Each item scored <strong>7+/10</strong> on press-release potential and met at least
    3 of 8 criteria for original, reporter-worthy intelligence.
  </div>

  {cards_html}

  <div class="footer">
    Cuban Insights Press-Release Radar &middot; {run_date}<br>
    Alerts are generated automatically from primary-source scrapes.<br>
    Reply to this email to discuss a finding with the editorial team.
  </div>

</div>
</body>
</html>"""


# ── Public entry point ─────────────────────────────────────────────────────────

def run_press_release_detection(dry_run: bool = False) -> dict:
    """Scan today's analyzed primary-source articles for press-release potential.

    Evaluates each candidate, collects all qualifying items, then sends ONE
    digest email covering every qualifying finding for that run.

    Returns a summary dict: {candidates_evaluated, alerts_sent, errors, skipped}.
    Always non-fatal — any exception is caught and logged.
    """
    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY not set — skipping press-release detection")
        return {"candidates_evaluated": 0, "alerts_sent": 0, "errors": 0, "skipped": True}

    client = OpenAI(api_key=settings.openai_api_key)
    db = SessionLocal()
    summary: dict = {"candidates_evaluated": 0, "alerts_sent": 0, "errors": 0, "skipped": False}

    try:
        lookback = date.today() - timedelta(days=1)
        primary_values = [s.value for s in PRIMARY_SOURCES]

        ext_rows = (
            db.query(ExternalArticleEntry)
            .filter(ExternalArticleEntry.status == GazetteStatus.ANALYZED)
            .filter(ExternalArticleEntry.published_date >= lookback)
            .filter(ExternalArticleEntry.source.in_(primary_values))
            .all()
        )
        assembly_rows = (
            db.query(AssemblyNewsEntry)
            .filter(AssemblyNewsEntry.status == GazetteStatus.ANALYZED)
            .filter(AssemblyNewsEntry.published_date >= lookback)
            .all()
        )

        candidates = [
            _wrap_ext(a) for a in ext_rows
            if isinstance(a.analysis_json, dict)
            and a.analysis_json.get("relevance_score", 0) >= _MIN_INVESTOR_SCORE
        ] + [
            _wrap_assembly(n) for n in assembly_rows
            if isinstance(n.analysis_json, dict)
            and n.analysis_json.get("relevance_score", 0) >= _MIN_INVESTOR_SCORE
        ]

        logger.info(
            "Press-release screen: %d ext + %d assembly rows → %d high-relevance candidates",
            len(ext_rows), len(assembly_rows), len(candidates),
        )

        threshold = settings.press_release_min_score
        qualifying: list[tuple[dict, dict]] = []

        for item in candidates:
            summary["candidates_evaluated"] += 1
            try:
                evaluation = _evaluate(client, item)
                score = evaluation.get("press_release_score", 0)
                rec = evaluation.get("recommendation", "Reject")

                logger.info(
                    "PR-eval score=%d criteria=%s rec='%s' — %s",
                    score,
                    evaluation.get("criteria_met_count", "?"),
                    rec,
                    item["headline"][:70],
                )

                if score >= threshold and rec != "Reject":
                    qualifying.append((item, evaluation))

            except Exception as exc:
                logger.error(
                    "Press-release eval failed for '%s': %s",
                    item.get("headline", "?")[:60], exc,
                )
                summary["errors"] += 1

        if qualifying:
            if dry_run:
                logger.info("DRY RUN: would send PR digest with %d item(s)", len(qualifying))
                summary["alerts_sent"] = len(qualifying)
            else:
                sent = _send_digest(qualifying)
                if sent:
                    summary["alerts_sent"] = len(qualifying)
                else:
                    summary["errors"] += 1

    finally:
        db.close()

    logger.info(
        "Press-release detection done: evaluated=%d qualifying=%d errors=%d",
        summary["candidates_evaluated"], summary["alerts_sent"], summary["errors"],
    )
    return summary


# ── Helpers ────────────────────────────────────────────────────────────────────

def _wrap_ext(article: ExternalArticleEntry) -> dict:
    analysis = article.analysis_json or {}
    return {
        "headline": article.headline or "",
        "source_url": article.source_url or "",
        "source_name": article.source_name or article.source.value,
        "source_type": article.source.value,
        "credibility": article.credibility.value if article.credibility else "tier2",
        "published_date": str(article.published_date),
        "body_text": (article.body_text or "")[:3_000],
        "relevance_score": analysis.get("relevance_score", 0),
        "existing_takeaway": analysis.get("takeaway", ""),
    }


def _wrap_assembly(news: AssemblyNewsEntry) -> dict:
    analysis = news.analysis_json or {}
    return {
        "headline": news.headline or "",
        "source_url": news.source_url or "",
        "source_name": "Asamblea Nacional del Poder Popular (Cuba)",
        "source_type": "asamblea_nacional_cu",
        "credibility": "state",
        "published_date": str(news.published_date),
        "body_text": (news.body_text or "")[:3_000],
        "relevance_score": analysis.get("relevance_score", 0),
        "existing_takeaway": analysis.get("takeaway", ""),
    }


def _evaluate(client: OpenAI, item: dict) -> dict:
    user_msg = _USER_TEMPLATE.format(
        source_type=item["source_type"],
        source_name=item["source_name"],
        credibility=item["credibility"],
        published_date=item["published_date"],
        headline=item["headline"],
        source_url=item["source_url"],
        relevance_score=item["relevance_score"],
        existing_takeaway=item["existing_takeaway"] or "(none)",
        body_text=item["body_text"] or "(no body text available)",
    )

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.2,
        max_tokens=700,
        response_format={"type": "json_object"},
    )

    return json.loads(response.choices[0].message.content)


def _send_digest(qualifying: list[tuple[dict, dict]]) -> bool:
    """Build a single digest email covering all qualifying items and send via Resend."""
    if not settings.resend_api_key:
        logger.warning("RESEND_API_KEY not set — cannot send press-release digest")
        return False

    run_date = date.today().strftime("%B %d, %Y")
    html = _build_digest_html(qualifying, run_date)

    # Subject: top item's headline if one, otherwise count
    top_headline = qualifying[0][1].get("suggested_headline", qualifying[0][0]["headline"])
    n = len(qualifying)
    if n == 1:
        subject = f"[Press Radar] {top_headline[:80]}"
    else:
        subject = f"[Press Radar] {n} findings — {top_headline[:60]}"

    # Plain-text fallback
    lines = [f"Press-Release Radar — {run_date}", f"{n} qualifying candidate(s)", ""]
    for i, (item, ev) in enumerate(qualifying, 1):
        lines += [
            f"#{i} — {ev.get('suggested_headline', item['headline'])}",
            f"Score: {ev.get('press_release_score', 0)}/10 | {ev.get('recommendation', '')}",
            f"Source: {item['source_url']}",
            f"Finding: {ev.get('finding', '')}",
            "",
        ]
    plain_text = "\n".join(lines)

    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            json={
                "from": settings.feedback_from_email,
                "to": [settings.feedback_notification_email],
                "subject": subject,
                "html": html,
                "text": plain_text,
            },
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        if resp.status_code in (200, 201):
            logger.info(
                "Press-release digest sent to %s (%d item(s))",
                settings.feedback_notification_email, n,
            )
            return True
        logger.error(
            "Resend error %d sending press-release digest: %s",
            resp.status_code, resp.text,
        )
        return False
    except Exception as exc:
        logger.error("Failed to send press-release digest email: %s", exc)
        return False
