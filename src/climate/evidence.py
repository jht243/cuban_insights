"""
Evidence collector for the Investment Climate Tracker.

Pulls raw inputs out of the DB and packages them into an Evidence dataclass.
This module is read-only and contains no scoring decisions; the rubric
module turns Evidence into scores.

Inputs the scorer needs, and where they come from in our existing data
model (all populated by the daily pipeline):

    pillar              field on Evidence              source rows
    ----------------------------------------------------------------------
    Sanctions           sdn_additions_q                external_articles
                        sdn_removals_q                   source = ofac_sdn
                        ofac_doc_count_q               external_articles
                                                         source = federal_register
                        travel_advisory_level          external_articles
                                                         source = travel_advisory
    Diplomatic          diplomatic_article_count_q     external_articles
                        diplomatic_avg_tone_q            source = gdelt + keyword filter
    Legal               legal_positive_count_q         gazette_entries + assembly_news
                        legal_negative_count_q          + keyword filter
    Political           amnesty_signal_q               gazette_entries + assembly_news
                        protest_signal_q                + keyword/tone filter
                        political_avg_tone_q           gdelt subset
    Property Rights     property_negative_count_q      gazette_entries + assembly_news
                        property_positive_count_q       + keyword filter
    Macro               parallel_premium_pct           latest bcv_rates row
                        official_usd                   latest bcv_rates row
                        coface_grade                   static config (E for now)
                        inflation_annualized_pct       optional, from bcv extra_metadata
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.climate.snapshot import Quarter
from src.models import (
    AssemblyNewsEntry,
    ExternalArticleEntry,
    GazetteEntry,
    SourceType,
)


# Coface country grade is published quarterly; we read it from a small
# config map rather than scrape it. Update this dict when Coface changes
# its rating. "E" is the worst grade Coface issues; lower letters are
# better (D, C, B, A4, A3, A2, A1).
COFACE_GRADE_DEFAULT = "E"


# Keyword catalogues used by the Evidence collector. Tuned conservatively
# so that the score isn't dominated by a single overactive keyword. Spanish
# and English variants are both listed because gazette/assembly text is
# Spanish and external articles are mixed.
DIPLOMATIC_KEYWORDS = (
    "embassy", "ambassador", "charg", "diplomat",
    "sanction relief", "talks resume", "negotiation",
    "embajada", "diplom", "encargado de negocios", "negociaci",
)

LEGAL_POSITIVE_KEYWORDS = (
    "empresa mixta", "joint venture", "investment law",
    "ley de inversi", "hidrocarburos", "hydrocarbons",
    "tax incentive", "incentivo fiscal", "decreto de promoci",
)
LEGAL_NEGATIVE_KEYWORDS = (
    "expropriaci", "expropriation", "nacionalizaci", "nationalization",
    "control de cambio", "exchange control", "intervenci",
)

AMNESTY_KEYWORDS = (
    "amnistía", "amnesty", "indulto", "pardon",
    "elecciones", "elections", "calendario electoral",
)
PROTEST_KEYWORDS = (
    "protesta", "protest", "manifestaci", "represi",
    "detenci", "detention", "violenc", "huelga", "strike",
)

PROPERTY_NEGATIVE_KEYWORDS = (
    "expropriaci", "expropriation", "nacionalizaci", "nationalization",
    "confiscaci", "confiscation", "estatizaci", "ocupaci forzosa",
    "subsuelo", "subsoil", "estado venezolano",
)
PROPERTY_POSITIVE_KEYWORDS = (
    "icsid", "arbitraje", "arbitration", "settlement", "indemnizaci",
    "compensation", "registro de propiedad", "title registry",
)


def _matches_any(text: Optional[str], needles: tuple[str, ...]) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(n in t for n in needles)


@dataclass
class Evidence:
    """All inputs the rubric needs, computed for a specific quarter window."""

    quarter: Quarter

    # Sanctions
    sdn_additions_q: int = 0
    sdn_removals_q: int = 0
    ofac_doc_count_q: int = 0
    travel_advisory_level: Optional[int] = None  # 1..4, lower = safer
    travel_advisory_observed_at: Optional[str] = None

    # Diplomatic
    diplomatic_article_count_q: int = 0
    diplomatic_avg_tone_q: Optional[float] = None  # GDELT tone, -10..+10

    # Legal
    legal_positive_count_q: int = 0
    legal_negative_count_q: int = 0

    # Political
    amnesty_signal_q: int = 0
    protest_signal_q: int = 0
    political_avg_tone_q: Optional[float] = None

    # Property
    property_negative_count_q: int = 0
    property_positive_count_q: int = 0

    # Macro
    parallel_premium_pct: Optional[float] = None
    official_usd: Optional[float] = None
    inflation_annualized_pct: Optional[float] = None
    coface_grade: str = COFACE_GRADE_DEFAULT

    # Audit trail (sample of headlines that drove the count, capped).
    _samples: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["quarter"] = self.quarter.label
        return d


def collect_evidence(db: Session, quarter: Quarter) -> Evidence:
    """Read every input the rubric needs for `quarter` from the DB."""
    ev = Evidence(quarter=quarter)
    qstart = quarter.start_date
    qend = quarter.end_date

    _collect_sanctions(db, ev, qstart, qend)
    _collect_diplomatic(db, ev, qstart, qend)
    _collect_legal(db, ev, qstart, qend)
    _collect_political(db, ev, qstart, qend)
    _collect_property(db, ev, qstart, qend)
    _collect_macro(db, ev)

    return ev


# ---------------------------------------------------------------------------
# Pillar collectors
# ---------------------------------------------------------------------------


# Cold-start guard: the OFAC SDN scraper diffs the live list against the
# most recent local snapshot file. The very first time it runs (or after
# the snapshot file is wiped) every existing Venezuela-program entry shows
# up as an "addition", which can be hundreds of rows. Any single quarter
# with this much net SDN activity is implausible — treat it as no signal.
SDN_COLD_START_THRESHOLD = 80


def _collect_sanctions(db: Session, ev: Evidence, qstart: date, qend: date) -> None:
    sdn_rows = (
        db.query(ExternalArticleEntry)
        .filter(ExternalArticleEntry.source == SourceType.OFAC_SDN)
        .filter(ExternalArticleEntry.published_date >= qstart)
        .filter(ExternalArticleEntry.published_date < qend)
        .all()
    )
    additions = removals = 0
    for r in sdn_rows:
        atype = (r.article_type or "").lower()
        if "addition" in atype:
            additions += 1
        elif "removal" in atype:
            removals += 1

    if additions + removals > SDN_COLD_START_THRESHOLD:
        # Likely cold-start backfill; suppress and record the fact in samples.
        ev._samples["sdn_cold_start_suppressed"] = {
            "raw_additions": additions,
            "raw_removals": removals,
            "threshold": SDN_COLD_START_THRESHOLD,
        }
    else:
        ev.sdn_additions_q = additions
        ev.sdn_removals_q = removals

    ev.ofac_doc_count_q = (
        db.query(ExternalArticleEntry)
        .filter(ExternalArticleEntry.source == SourceType.FEDERAL_REGISTER)
        .filter(ExternalArticleEntry.published_date >= qstart)
        .filter(ExternalArticleEntry.published_date < qend)
        .count()
    )

    # Latest travel advisory reading (any date — the level is a level,
    # not an event count, so we want "where it sits today").
    ta_row = (
        db.query(ExternalArticleEntry)
        .filter(ExternalArticleEntry.source == SourceType.TRAVEL_ADVISORY)
        .order_by(ExternalArticleEntry.published_date.desc())
        .first()
    )
    if ta_row:
        meta = ta_row.extra_metadata or {}
        if isinstance(meta, dict):
            lvl = meta.get("level")
            if isinstance(lvl, (int, float)):
                ev.travel_advisory_level = int(lvl)
                ev.travel_advisory_observed_at = (
                    ta_row.published_date.isoformat()
                    if ta_row.published_date else None
                )


def _collect_diplomatic(db: Session, ev: Evidence, qstart: date, qend: date) -> None:
    rows = (
        db.query(ExternalArticleEntry)
        .filter(ExternalArticleEntry.source == SourceType.GDELT)
        .filter(ExternalArticleEntry.published_date >= qstart)
        .filter(ExternalArticleEntry.published_date < qend)
        .all()
    )
    matched = []
    tones = []
    for r in rows:
        if _matches_any(r.headline, DIPLOMATIC_KEYWORDS) or _matches_any(
            r.body_text, DIPLOMATIC_KEYWORDS
        ):
            matched.append(r)
            if r.tone_score is not None:
                tones.append(r.tone_score)

    ev.diplomatic_article_count_q = len(matched)
    if tones:
        ev.diplomatic_avg_tone_q = round(sum(tones) / len(tones), 2)
    ev._samples["diplomatic"] = [m.headline for m in matched[:5]]


def _collect_legal(db: Session, ev: Evidence, qstart: date, qend: date) -> None:
    pos = neg = 0
    samples_pos: list[str] = []
    samples_neg: list[str] = []

    gz = (
        db.query(GazetteEntry)
        .filter(GazetteEntry.published_date >= qstart)
        .filter(GazetteEntry.published_date < qend)
        .all()
    )
    for g in gz:
        text = " ".join(filter(None, [g.title, g.sumario_raw, g.ocr_text or ""]))
        if _matches_any(text, LEGAL_POSITIVE_KEYWORDS):
            pos += 1
            if len(samples_pos) < 5:
                samples_pos.append(g.title or "(no title)")
        if _matches_any(text, LEGAL_NEGATIVE_KEYWORDS):
            neg += 1
            if len(samples_neg) < 5:
                samples_neg.append(g.title or "(no title)")

    an = (
        db.query(AssemblyNewsEntry)
        .filter(AssemblyNewsEntry.published_date >= qstart)
        .filter(AssemblyNewsEntry.published_date < qend)
        .all()
    )
    for n in an:
        text = " ".join(filter(None, [n.headline, n.body_text or ""]))
        if _matches_any(text, LEGAL_POSITIVE_KEYWORDS):
            pos += 1
            if len(samples_pos) < 5:
                samples_pos.append(n.headline)
        if _matches_any(text, LEGAL_NEGATIVE_KEYWORDS):
            neg += 1
            if len(samples_neg) < 5:
                samples_neg.append(n.headline)

    ev.legal_positive_count_q = pos
    ev.legal_negative_count_q = neg
    ev._samples["legal_positive"] = samples_pos
    ev._samples["legal_negative"] = samples_neg


def _collect_political(db: Session, ev: Evidence, qstart: date, qend: date) -> None:
    amnesty = protest = 0
    samples_a: list[str] = []
    samples_p: list[str] = []

    for table in (GazetteEntry, AssemblyNewsEntry):
        text_attr = "title" if table is GazetteEntry else "headline"
        body_attr = "sumario_raw" if table is GazetteEntry else "body_text"
        rows = (
            db.query(table)
            .filter(table.published_date >= qstart)
            .filter(table.published_date < qend)
            .all()
        )
        for r in rows:
            txt = " ".join(filter(None, [
                getattr(r, text_attr, None),
                getattr(r, body_attr, None),
            ]))
            if _matches_any(txt, AMNESTY_KEYWORDS):
                amnesty += 1
                if len(samples_a) < 5:
                    samples_a.append(getattr(r, text_attr) or "(no title)")
            if _matches_any(txt, PROTEST_KEYWORDS):
                protest += 1
                if len(samples_p) < 5:
                    samples_p.append(getattr(r, text_attr) or "(no title)")

    # Tone: average GDELT tone on the political subset
    tones = []
    gdelt_rows = (
        db.query(ExternalArticleEntry)
        .filter(ExternalArticleEntry.source == SourceType.GDELT)
        .filter(ExternalArticleEntry.published_date >= qstart)
        .filter(ExternalArticleEntry.published_date < qend)
        .all()
    )
    for r in gdelt_rows:
        if r.tone_score is None:
            continue
        if _matches_any(r.headline, AMNESTY_KEYWORDS + PROTEST_KEYWORDS):
            tones.append(r.tone_score)

    ev.amnesty_signal_q = amnesty
    ev.protest_signal_q = protest
    if tones:
        ev.political_avg_tone_q = round(sum(tones) / len(tones), 2)
    ev._samples["amnesty"] = samples_a
    ev._samples["protest"] = samples_p


def _collect_property(db: Session, ev: Evidence, qstart: date, qend: date) -> None:
    pos = neg = 0
    samples_pos: list[str] = []
    samples_neg: list[str] = []

    for table in (GazetteEntry, AssemblyNewsEntry):
        text_attr = "title" if table is GazetteEntry else "headline"
        body_attr = "sumario_raw" if table is GazetteEntry else "body_text"
        rows = (
            db.query(table)
            .filter(table.published_date >= qstart)
            .filter(table.published_date < qend)
            .all()
        )
        for r in rows:
            txt = " ".join(filter(None, [
                getattr(r, text_attr, None),
                getattr(r, body_attr, None),
            ]))
            if _matches_any(txt, PROPERTY_NEGATIVE_KEYWORDS):
                neg += 1
                if len(samples_neg) < 5:
                    samples_neg.append(getattr(r, text_attr) or "(no title)")
            if _matches_any(txt, PROPERTY_POSITIVE_KEYWORDS):
                pos += 1
                if len(samples_pos) < 5:
                    samples_pos.append(getattr(r, text_attr) or "(no title)")

    ev.property_negative_count_q = neg
    ev.property_positive_count_q = pos
    ev._samples["property_positive"] = samples_pos
    ev._samples["property_negative"] = samples_neg


def _collect_macro(db: Session, ev: Evidence) -> None:
    """
    Macro is intentionally NOT quarter-windowed: investors care about
    where the FX/inflation prints sit *now*, not the average over Q. We
    take the most recent BCV row.
    """
    bcv = (
        db.query(ExternalArticleEntry)
        .filter(ExternalArticleEntry.source == SourceType.BCC_RATES)
        .order_by(ExternalArticleEntry.published_date.desc())
        .first()
    )
    if bcv:
        meta = bcv.extra_metadata or {}
        if isinstance(meta, dict):
            usd = meta.get("usd")
            if isinstance(usd, (int, float)):
                ev.official_usd = float(usd)
            premium = meta.get("parallel_premium_pct")
            if isinstance(premium, (int, float)):
                ev.parallel_premium_pct = float(premium)
            inflation = meta.get("inflation_annualized_pct")
            if isinstance(inflation, (int, float)):
                ev.inflation_annualized_pct = float(inflation)
