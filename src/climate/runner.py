"""
Weekly Investment Climate Tracker refresh.

This is the orchestration entry point invoked by the weekly cron and by
the daily pipeline as a Monday safety net. It is idempotent: running it
twice in the same week leaves the DB in the same state.

Flow
----
1. Determine the current calendar quarter.
2. Collect Evidence from the DB for that quarter.
3. Score every pillar via the rubric.
4. Look up the prior quarter's snapshot, compute QoQ deltas.
5. Generate deterministic subtitle text from the same Evidence.
6. Upsert the current quarter's ClimateSnapshot row.
7. Return a small summary dict for logs / pipeline reporting.

If anything inside this function raises, the caller should swallow it
and continue: the report generator falls back to the most recent
snapshot or to the static literal, so the daily pipeline never breaks
because of a climate refresh failure.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from src.climate.evidence import collect_evidence
from src.climate.rubric import PILLARS
from src.climate.snapshot import (
    Quarter,
    get_prior_snapshot,
    get_snapshot_for,
    period_label,
    quarter_for,
    upsert_snapshot,
)
from src.climate.subtitles import METHODOLOGY_TEXT, SUBTITLE_FUNCS
from src.models import SessionLocal, init_db

logger = logging.getLogger(__name__)


def _trend_for(current: int, prior: Optional[int]) -> tuple[str, str]:
    """Return (trend_dir, trend_value) for the current vs prior bar score.

    The template renders an em-dash for the flat case, so when there is
    no prior snapshot we emit an empty trend_value to avoid the
    "— —" doubling that would otherwise appear in the trend pill.
    """
    if prior is None:
        return "flat", ""
    delta = current - prior
    if delta > 0:
        return "up", f"+{delta}"
    if delta < 0:
        # Use a real minus sign for visual parity with the historical literal.
        return "down", f"−{abs(delta)}"
    return "flat", "0"


def run_weekly_climate_refresh(
    *,
    today: Optional[date] = None,
    db_session=None,
) -> dict:
    """
    Compute and persist the climate snapshot for the current quarter.

    Args:
        today: override "today" for testing/backfill.
        db_session: pre-existing SQLAlchemy session; if omitted, a new one
            is opened and closed by this function.

    Returns:
        Summary dict with quarter label, composite score, and per-pillar
        score+delta. Suitable for printing from a CLI.
    """
    init_db()
    today = today or date.today()
    current_q = quarter_for(today)
    prior_q = current_q.previous()

    own_session = db_session is None
    db = db_session or SessionLocal()

    try:
        ev = collect_evidence(db, current_q)
        prior_snap = get_prior_snapshot(db, current_q)

        prior_bars_by_label: dict[str, int] = {}
        if prior_snap and isinstance(prior_snap.bars_json, list):
            for b in prior_snap.bars_json:
                if isinstance(b, dict) and "label" in b and "score" in b:
                    prior_bars_by_label[b["label"]] = int(b["score"])

        bars: list[dict] = []
        composite_total = 0
        for label, scorer in PILLARS:
            score, color, signals = scorer(ev)
            prior_score = prior_bars_by_label.get(label)
            trend_dir, trend_value = _trend_for(score, prior_score)
            why_fn = SUBTITLE_FUNCS[label]
            bars.append({
                "label": label,
                "score": score,
                "trend_dir": trend_dir,
                "trend_value": trend_value,
                "bar_color": color,
                "why": why_fn(ev),
                "signals": signals,
            })
            composite_total += score

        composite = round(composite_total / len(PILLARS), 2)
        period = period_label(current_q, prior_q if prior_snap else None)

        snap = upsert_snapshot(
            db,
            quarter=current_q,
            bars=bars,
            evidence=ev.to_dict(),
            composite_score=composite,
            period_label_text=period,
            methodology=METHODOLOGY_TEXT,
        )

        summary = {
            "quarter": current_q.label,
            "period_label": period,
            "composite_score": composite,
            "snapshot_id": snap.id,
            "had_prior": prior_snap is not None,
            "bars": [
                {
                    "label": b["label"],
                    "score": b["score"],
                    "trend": b["trend_value"],
                    "color": b["bar_color"],
                }
                for b in bars
            ],
        }
        logger.info("Climate refresh complete: %s", summary)
        return summary

    finally:
        if own_session:
            db.close()
