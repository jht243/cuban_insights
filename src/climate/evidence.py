"""
Evidence collector for the Investment Climate Tracker — Cuba edition.

Pulls raw inputs out of the DB and packages them into an Evidence dataclass.
This module is read-only and contains no scoring decisions; the rubric
module turns Evidence into scores.

Inputs the scorer needs, and where they come from in our existing data
model (all populated by the daily pipeline):

    pillar              field on Evidence              source rows
    ----------------------------------------------------------------------
    Embargo             sdn_additions_q                external_articles
                        sdn_removals_q                   source = ofac_sdn (Cuba program)
                        ofac_doc_count_q               external_articles
                                                         source = federal_register
                                                         (CACR amendments, GL renewals, FR notices)
                        travel_advisory_level          external_articles
                                                         source = travel_advisory (Cuba)
    Diplomatic          diplomatic_article_count_q     external_articles
                        diplomatic_avg_tone_q            source = gdelt + Cuba diplomatic keywords
    MIPYME & FDI        legal_positive_count_q         gazette_entries (Gaceta Oficial CU)
                        legal_negative_count_q          + assembly_news (ANPP / Granma legislative)
                                                         + Cuba-specific keyword filter
    Political           amnesty_signal_q               gazette_entries + assembly_news
                        protest_signal_q                + 11J / apagones / migración keywords
                        political_avg_tone_q           gdelt subset
    Property Rights     property_negative_count_q      gazette_entries + assembly_news
                                                         + external_articles
                                                         (Reuters, OnCuba, Cubadebate)
                        property_positive_count_q       + Helms-Burton Title III / FCSC keywords
    Macro               parallel_premium_pct           latest bcc_rates row (TRMI vs BCC)
                        official_usd                   latest bcc_rates row (CUP/USD)
                        coface_grade                   static config ("E" for now — Coface
                                                         country-rating; Cuba has been at "E"
                                                         throughout the post-2020 stress)
                        inflation_annualized_pct       optional, from bcc_rates extra_metadata
                                                         (ONEI prints when available)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Optional

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
# better (D, C, B, A4, A3, A2, A1). Cuba has been held at "E" since the
# post-2020 BoP / fuel-import crisis began.
COFACE_GRADE_DEFAULT = "E"


# Keyword catalogues used by the Evidence collector. Tuned conservatively
# so that the score isn't dominated by a single overactive keyword. Spanish
# and English variants are both listed because Gaceta Oficial CU and
# ANPP (the Cuban Asamblea / Poder Popular) text is Spanish, Granma is
# Spanish, and external articles (Reuters, OnCuba, Cubadebate, Diario de
# Cuba, 14ymedio, Inter-American Dialogue, OFAC, US State Dept) are
# mixed Spanish/English.

# --- Diplomatic Engagement -------------------------------------------------
# Captures bilateral and multilateral channel activity: US-Cuba talks
# (migration, law-enforcement, postal, FAA), EU PDCA dialogue rounds,
# Mexico/Russia/China/Vatican/CARICOM/Mercosur engagement, and MINREX
# press activity. Excludes pure tourism/cultural items (too noisy).
DIPLOMATIC_KEYWORDS = (
    # English
    "embassy", "ambassador", "charg", "diplomat",
    "minrex", "us-cuba", "cuba-us", "havana talks",
    "migration talks", "law enforcement dialogue", "pdca",
    "sanction relief", "embargo lifted", "embargo eased",
    "normalization", "normalisation", "bilateral",
    "state department", "vatican", "caricom", "mercosur",
    # Spanish
    "embajada", "embajador", "encargado de negocios",
    "diplom", "negociaci", "diálogo bilateral", "dialogo bilateral",
    "minrex", "cancillería", "cancilleria", "estados unidos-cuba",
    "cuba-estados unidos", "rusia", "china", "méxico", "mexico",
    "vaticano", "unión europea", "union europea",
)

# --- MIPYME & FDI Framework (positive) -------------------------------------
# Items that *expand* the private-sector / foreign-investment opportunity
# surface: new MIPYME authorisations, ZEDM (Mariel Special Development
# Zone) project approvals, Foreign Investment Law amendments, cartera
# de oportunidades updates, MLC / dollarisation moves that ease imports
# for private actors, OFAC general licenses.
LEGAL_POSITIVE_KEYWORDS = (
    # Spanish
    "mipyme", "mipymes", "micro, pequeñ", "micro, pequen",
    "cuentapropista", "trabajador por cuenta propia",
    "cooperativa no agropecuaria", "cna",
    "cartera de oportunidades", "ley de inversi", "ley 118",
    "ley 118 inversi", "inversión extranjera", "inversion extranjera",
    "empresa mixta", "asociación económica internacional",
    "asociacion economica internacional", "aei",
    "zona especial de desarrollo", "mariel", "zedm",
    "decreto-ley aprobado", "ley aprobada por la asamblea",
    "incentivo fiscal", "exención arancelaria", "exencion arancelaria",
    "liberalización", "liberalizacion",
    # English
    "mipyme", "private sector reform", "small private business",
    "cuban private sector", "joint venture", "foreign investment law",
    "law 118", "mariel special development zone",
    "portfolio of opportunities", "ofac general license", "cacr amendment",
    "remittance corridor", "western union resumed",
)

# --- MIPYME & FDI Framework (negative) -------------------------------------
# Items that *tighten* state control over the private sector or foreign
# capital: MIPYME revocations, sector restrictions, import bans,
# price-cap decrees, MLC retreats, forced-divestiture rules.
LEGAL_NEGATIVE_KEYWORDS = (
    # Spanish
    "intervención estatal", "intervencion estatal",
    "monopolio estatal", "estatización", "estatizacion",
    "expropiaci", "nacionalizaci", "confiscaci",
    "control de precios", "precio tope", "tope de precio",
    "prohibición de importar", "prohibicion de importar",
    "restricción a mipyme", "restriccion a mipyme",
    "cierre de mipyme", "revocación de licencia", "revocacion de licencia",
    "límite a actividades por cuenta propia", "limite a actividades por cuenta propia",
    "control cambiario", "control de cambio",
    # English
    "mipyme revocation", "private sector crackdown",
    "expropriation", "nationalization", "intervention",
    "exchange control", "price cap", "import ban",
)

# --- Political Stability (amnesty / normalisation signal) ------------------
# Positive political-normalisation flags: prisoner releases, ANPP
# constitutional reforms, calendared elections (municipal/ANPP),
# diálogo nacional, US humanitarian-parole renewals (eases pressure
# valve), papal visit prisoner-release packages.
AMNESTY_KEYWORDS = (
    # Spanish
    "amnistía", "amnistia", "indulto", "liberación de presos",
    "liberacion de presos", "presos liberados",
    "diálogo nacional", "dialogo nacional",
    "reforma constitucional", "elecciones municipales",
    "elecciones a la asamblea", "congreso del pcc",
    "calendario electoral",
    # English
    "amnesty", "pardon", "prisoner release", "political prisoner released",
    "national dialogue", "constitutional reform",
    "municipal elections", "anpp elections",
    "humanitarian parole", "cuban parole program",
)

# --- Political Stability (protest / repression signal) ---------------------
# Negative political-stability flags: 11J anniversary protests,
# apagón-driven cacerolazos, fuel/food shortage demonstrations,
# detentions of activists, mass-out-migration spikes (Darién,
# maritime Florida-Strait), and high-profile defections.
PROTEST_KEYWORDS = (
    # Spanish
    "protesta", "manifestaci", "represi", "detenci",
    "preso político", "preso politico", "presos políticos",
    "11j", "11 de julio", "cacerolazo",
    "apagón", "apagon", "apagones",
    "escasez", "racionamiento", "desabastecimiento",
    "huelga", "éxodo", "exodo", "migración masiva", "migracion masiva",
    "balsero", "balseros", "deserción", "desercion",
    # English
    "protest", "demonstration", "repression", "detention",
    "political prisoner", "11j", "july 11",
    "blackout", "rolling blackouts", "power outage",
    "shortage", "rationing", "food rationing",
    "exodus", "mass migration", "rafter", "darien",
    "florida strait", "defection",
)

# --- Property Rights (negative — fresh trafficking / expropriation) --------
# New Helms-Burton Title III lawsuits filed against firms "trafficking"
# in confiscated property (hotels, port concessions, agricultural
# estates), fresh expropriation/intervention decrees in Gaceta CU,
# and forced-asset-transfer items.
PROPERTY_NEGATIVE_KEYWORDS = (
    # Spanish
    "título iii", "titulo iii",
    "demanda título iii", "demanda titulo iii",
    "helms-burton", "helms burton", "ley helms-burton",
    "tráfico de bienes confiscados", "trafico de bienes confiscados",
    "expropiaci", "nacionalizaci", "confiscaci",
    "intervención de empresa", "intervencion de empresa",
    "ocupación forzosa", "ocupacion forzosa",
    "estatización", "estatizacion",
    # English
    "title iii lawsuit", "title iii suit", "title iii filing",
    "title iii complaint",
    "helms-burton title iii", "trafficking in confiscated property",
    "expropriation", "nationalization", "confiscation",
    "forced takeover", "state intervention",
)

# --- Property Rights (positive — dismissals / settlements / FCSC) ----------
# Title III suits dismissed or settled, Foreign Claims Settlement
# Commission certified-claim activity, ICSID-equivalent arbitration
# wins, restitution decrees.
PROPERTY_POSITIVE_KEYWORDS = (
    # Spanish
    "título iii desestimad", "titulo iii desestimad",
    "demanda desestimada", "acuerdo extrajudicial",
    "indemnizaci", "compensaci", "restitución", "restitucion",
    "registro de propiedad", "comisión de reclamaciones",
    "comision de reclamaciones",
    # English
    "title iii dismissed", "title iii settlement",
    "title iii lawsuit dismissed", "claim dismissed",
    "settlement reached", "fcsc", "foreign claims settlement commission",
    "certified claim", "icsid", "arbitration award",
    "compensation", "indemnification", "title insurance",
    "property registry",
)


def _matches_any(text: Optional[str], needles: tuple[str, ...]) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(n in t for n in needles)


@dataclass
class Evidence:
    """All inputs the rubric needs, computed for a specific quarter window.

    Field names are intentionally generic (sdn_*, legal_*, property_*,
    parallel_premium_pct, official_usd, ...) so that downstream
    consumers — snapshot JSON, runner, subtitles — keep working
    unchanged. Cuba-specific semantics:

      * ``parallel_premium_pct`` — elTOQUE TRMI informal CUP/USD vs.
        BCC reference rate.
      * ``official_usd`` — BCC reference CUP/USD.
      * ``sdn_additions_q`` / ``sdn_removals_q`` — OFAC SDN Cuba
        program diffs.
      * ``ofac_doc_count_q`` — Federal Register OFAC docs (CACR
        amendments, GL renewals, CRL / CPAL updates).
      * ``legal_*`` — MIPYME / FDI framework activity in Gaceta CU
        and ANPP coverage.
      * ``property_*`` — Helms-Burton Title III filings/dismissals
        plus Gaceta-side expropriation/intervention items.
      * ``coface_grade`` — Coface country grade for Cuba (default "E").
    """

    quarter: Quarter

    # Embargo
    sdn_additions_q: int = 0
    sdn_removals_q: int = 0
    ofac_doc_count_q: int = 0
    travel_advisory_level: Optional[int] = None  # 1..4, lower = safer
    travel_advisory_observed_at: Optional[str] = None

    # Diplomatic
    diplomatic_article_count_q: int = 0
    diplomatic_avg_tone_q: Optional[float] = None  # GDELT tone, -10..+10

    # MIPYME & FDI Framework
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


# Cold-start guard: the OFAC SDN scraper diffs the live list against
# the most recent local snapshot file. The very first time it runs (or
# after the snapshot file is wiped) every existing Cuba-program entry
# shows up as an "addition", which can be a couple hundred rows. A
# 50-row threshold is enough to detect cold-start backfill while
# leaving headroom for genuinely active enforcement quarters on the
# Cuba program.
SDN_COLD_START_THRESHOLD = 50


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
    # not an event count, so we want "where it sits today"). For Cuba
    # this is the State Dept Cuba travel advisory (level 2 most years).
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

    # Tone: average GDELT tone on the political subset.
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

    # Title III lawsuit headlines also surface from external_articles
    # (Reuters / OnCuba / Cubadebate cover U.S. district-court filings
    # that never appear in Gaceta CU). Fold those in as well.
    ext_rows = (
        db.query(ExternalArticleEntry)
        .filter(ExternalArticleEntry.published_date >= qstart)
        .filter(ExternalArticleEntry.published_date < qend)
        .all()
    )
    for r in ext_rows:
        text = " ".join(filter(None, [r.headline, r.body_text or ""]))
        if _matches_any(text, PROPERTY_NEGATIVE_KEYWORDS):
            neg += 1
            if len(samples_neg) < 5:
                samples_neg.append(r.headline or "(no headline)")
        if _matches_any(text, PROPERTY_POSITIVE_KEYWORDS):
            pos += 1
            if len(samples_pos) < 5:
                samples_pos.append(r.headline or "(no headline)")

    ev.property_negative_count_q = neg
    ev.property_positive_count_q = pos
    ev._samples["property_positive"] = samples_pos
    ev._samples["property_negative"] = samples_neg


def _collect_macro(db: Session, ev: Evidence) -> None:
    """
    Macro is intentionally NOT quarter-windowed: investors care about
    where the FX/inflation prints sit *now*, not the average over Q. We
    take the most recent BCC row (Banco Central de Cuba — the official
    CUP/USD reference; the parallel premium is computed against the
    elTOQUE TRMI by the BCC scraper before persisting).
    """
    bcc = (
        db.query(ExternalArticleEntry)
        .filter(ExternalArticleEntry.source == SourceType.BCC_RATES)
        .order_by(ExternalArticleEntry.published_date.desc())
        .first()
    )
    if bcc:
        meta = bcc.extra_metadata or {}
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
