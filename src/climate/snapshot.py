"""
Quarter math and ClimateSnapshot persistence.

The framework is built around calendar quarters because that's what the
displayed scorecard period claims ("Q2 2026 vs. Q1 2026"). Snapshots
are upserted weekly, so the *current* quarter's row evolves over the
13 weeks it represents and then freezes when the calendar rolls over,
becoming the QoQ baseline for the next quarter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.models import ClimateSnapshot


@dataclass(frozen=True)
class Quarter:
    """A calendar quarter, e.g. Q2 2026 = (2026, 2)."""

    year: int
    q: int  # 1..4

    @property
    def label(self) -> str:
        return f"Q{self.q} {self.year}"

    @property
    def start_date(self) -> date:
        first_month = (self.q - 1) * 3 + 1
        return date(self.year, first_month, 1)

    @property
    def end_date(self) -> date:
        # Exclusive — first day of the next quarter.
        if self.q == 4:
            return date(self.year + 1, 1, 1)
        return date(self.year, self.q * 3 + 1, 1)

    def previous(self) -> "Quarter":
        if self.q == 1:
            return Quarter(self.year - 1, 4)
        return Quarter(self.year, self.q - 1)


def quarter_for(d: date) -> Quarter:
    """Calendar quarter containing the given date."""
    return Quarter(d.year, (d.month - 1) // 3 + 1)


def period_label(current: Quarter, prior: Optional[Quarter]) -> str:
    """Header subtitle, e.g. 'Q2 2026 vs. Q1 2026' or 'Q2 2026 (baseline)'."""
    if prior is None:
        return f"{current.label} (baseline)"
    return f"{current.label} vs. {prior.label}"


def get_latest_snapshot(db: Session) -> Optional[ClimateSnapshot]:
    """Most recent quarter we have a snapshot for (current or prior)."""
    return (
        db.query(ClimateSnapshot)
        .order_by(ClimateSnapshot.quarter_start.desc())
        .first()
    )


def get_snapshot_for(db: Session, quarter: Quarter) -> Optional[ClimateSnapshot]:
    return (
        db.query(ClimateSnapshot)
        .filter(ClimateSnapshot.quarter_label == quarter.label)
        .one_or_none()
    )


def get_prior_snapshot(db: Session, current: Quarter) -> Optional[ClimateSnapshot]:
    """The snapshot for the quarter immediately before `current`."""
    return get_snapshot_for(db, current.previous())


def upsert_snapshot(
    db: Session,
    *,
    quarter: Quarter,
    bars: list[dict],
    evidence: dict,
    composite_score: float,
    period_label_text: str,
    methodology: str,
) -> ClimateSnapshot:
    """
    Insert or update the row for `quarter`. The current-quarter row is
    rewritten on every weekly run; rows for past quarters are normally
    left alone, but we tolerate updating them too (e.g. a backfill).
    """
    row = get_snapshot_for(db, quarter)
    if row is None:
        row = ClimateSnapshot(
            quarter_label=quarter.label,
            quarter_start=quarter.start_date,
        )
        db.add(row)

    row.composite_score = composite_score
    row.period_label = period_label_text
    row.methodology = methodology
    row.bars_json = bars
    row.evidence_json = evidence
    row.computed_at = datetime.utcnow()

    db.commit()
    db.refresh(row)
    return row
