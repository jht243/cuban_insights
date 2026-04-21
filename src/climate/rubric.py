"""
Investment Climate Tracker scoring rubric — Cuba edition.

Pure functions. (Evidence) -> (score: int 0..10, color: str, signals: dict).
All thresholds live in this file as named constants so any one of them
can be re-tuned in isolation, with the rationale documented inline.

Pillars (six bars, top-to-bottom on the rendered scorecard):
    Embargo Posture
    Diplomatic Engagement
    MIPYME & FDI Framework
    Political Stability
    Property Rights
    Macro Stability

Categories deliberately omitted (not meaningful Cuba investor signals):
    - Sovereign-debt restructuring (Cuba has no public sovereign bond
      market; Paris/London Club work is multi-decade and barely moves
      QoQ).
    - Oil-sector regulation (Cuba is an oil importer, not an exporter;
      hydrocarbon licensing is not a meaningful investor signal).
    - Electoral risk in the contestable sense (one-party system; ANPP
      cycles are scored under Political Stability instead).

Score interpretation (consistent across all six pillars):
    9-10  Normalized / OECD-equivalent, low-friction
    7-8   Materially improving / open for business with caveats
    5-6   Mixed; selective opportunities under specific conditions
    3-4   Hostile but navigable for specialists with high risk tolerance
    0-2   Effectively closed / capital-destructive

Color buckets (for the bar fill on the rendered scorecard):
    >= 6.5  green
    >= 4.0  yellow
    < 4.0   red
"""

from __future__ import annotations

from typing import Optional

from src.climate.evidence import Evidence


def _clamp(x: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, x))


def _color_for(score: float) -> str:
    if score >= 6.5:
        return "green"
    if score >= 4.0:
        return "yellow"
    return "red"


# ---------------------------------------------------------------------------
# Embargo Posture
# ---------------------------------------------------------------------------
# Cuba's US sanctions architecture is structural: a codified embargo
# (Helms-Burton, CACR, TWEA), the SST relisting (2021), the Cuba
# Restricted List, and the Cuba Prohibited Accommodations List. The
# *direction of travel* — whether the current administration is
# tightening (CACR rollbacks, new CRL entries, Helms-Burton Title III
# activations, SST keep-on) or loosening (GL renewals, CACR amendments
# easing remittances or MIPYME transactions, SST delisting talk, Title
# III suspensions) — is the dominant investor signal.
#
# Uses the Evidence embargo fields (sdn_additions/removals,
# ofac_doc_count, travel_advisory_level), which populate from OFAC SDN
# diffs (Cuba program), Federal Register OFAC docs, and the US State
# Dept travel advisory level for Cuba.
#
# Anchors:
#   base 3.0   (low — the embargo is structural, not cyclical)
#     + clamp((removals - additions) / 3, -2, +2)        # SDN net delta
#     + clamp(min(ofac_doc_count_q, 8) / 4, 0, 1.5)      # OFAC GL/FR activity
#     + (4 - travel_advisory_level)                      # 4 -> 0, 3 -> +1, 2 -> +2, 1 -> +3
# ---------------------------------------------------------------------------

EMBARGO_BASE = 3.0
EMBARGO_NET_SDN_CAP = 2.0
EMBARGO_NET_DIVISOR = 3.0
EMBARGO_DOC_CAP = 1.5
EMBARGO_DOC_DIVISOR = 4.0

# Backwards-compatible aliases; some downstream tests/import paths may
# still reference SANCTIONS_*. Safe to remove once nothing imports them.
SANCTIONS_BASE = EMBARGO_BASE
SANCTIONS_NET_SDN_CAP = EMBARGO_NET_SDN_CAP
SANCTIONS_NET_DIVISOR = EMBARGO_NET_DIVISOR
SANCTIONS_DOC_CAP = EMBARGO_DOC_CAP
SANCTIONS_DOC_DIVISOR = EMBARGO_DOC_DIVISOR


def score_sanctions(ev: Evidence) -> tuple[int, str, dict]:
    """Embargo Posture pillar score.

    Function name kept for backwards compatibility with the runner's
    PILLARS list and external imports — the *meaning* is the Cuba
    embargo posture (CACR / Helms-Burton / SST / CRL / CPAL).
    """
    net = ev.sdn_removals_q - ev.sdn_additions_q
    net_component = _clamp(
        net / EMBARGO_NET_DIVISOR,
        -EMBARGO_NET_SDN_CAP,
        EMBARGO_NET_SDN_CAP,
    )

    doc_component = _clamp(
        min(ev.ofac_doc_count_q, 8) / EMBARGO_DOC_DIVISOR,
        0,
        EMBARGO_DOC_CAP,
    )

    if ev.travel_advisory_level is None:
        ta_component = 0.0
    else:
        # Cuba sits at Level 2 ("exercise increased caution") most years.
        # Level 4 -> 0, Level 3 -> +1, Level 2 -> +2, Level 1 -> +3.
        ta_component = float(max(0, 4 - ev.travel_advisory_level))

    raw = EMBARGO_BASE + net_component + doc_component + ta_component
    score = int(round(_clamp(raw)))
    return score, _color_for(score), {
        "base": EMBARGO_BASE,
        "net_sdn": net,
        "net_component": net_component,
        "ofac_doc_count_q": ev.ofac_doc_count_q,
        "doc_component": doc_component,
        "travel_advisory_level": ev.travel_advisory_level,
        "ta_component": ta_component,
        "raw": round(raw, 2),
    }


# ---------------------------------------------------------------------------
# Diplomatic Engagement
# ---------------------------------------------------------------------------
# Anchored on observable signal volume (GDELT articles touching Cuba
# diplomatic keywords — US/EU/Mexico/Russia/China/Vatican/CARICOM
# channels, MINREX statements) and average tone. The structural ceiling
# is the embassy-staffing question (US Embassy Havana resumed full
# consular services 2023; reciprocal accreditation is the binary
# observable in the real world).
#
#   base 3.0
#     + min(count / 12, 3.0)            # max +3 once you see ~36+ articles
#     + clamp((tone + 2) / 2, -2, +2)   # GDELT tone roughly -10..+10
# ---------------------------------------------------------------------------

DIPLOMATIC_BASE = 3.0
DIPLOMATIC_VOLUME_DIVISOR = 12.0
DIPLOMATIC_VOLUME_CAP = 3.0


def score_diplomatic(ev: Evidence) -> tuple[int, str, dict]:
    vol_component = min(ev.diplomatic_article_count_q / DIPLOMATIC_VOLUME_DIVISOR,
                        DIPLOMATIC_VOLUME_CAP)

    if ev.diplomatic_avg_tone_q is None:
        tone_component = 0.0
    else:
        tone_component = _clamp((ev.diplomatic_avg_tone_q + 2) / 2.0, -2.0, 2.0)

    raw = DIPLOMATIC_BASE + vol_component + tone_component
    score = int(round(_clamp(raw)))
    return score, _color_for(score), {
        "base": DIPLOMATIC_BASE,
        "article_count_q": ev.diplomatic_article_count_q,
        "vol_component": round(vol_component, 2),
        "avg_tone": ev.diplomatic_avg_tone_q,
        "tone_component": round(tone_component, 2),
        "raw": round(raw, 2),
    }


# ---------------------------------------------------------------------------
# MIPYME & FDI Framework
# ---------------------------------------------------------------------------
# Counts Gaceta Oficial CU + ANPP legislative coverage (parlamento
# cubano + Granma) entries that mention the small-private-sector /
# foreign-investment framework — split into "expands the opportunity
# surface"
# (new MIPYME authorizations, ZEDM project approvals, Ley 118 amendments,
# cartera de oportunidades updates, MLC liberalisation) vs "tightens
# state control" (MIPYME revocations, sector restrictions, price caps,
# import-bans, MLC retreats).
#
# A neutral quarter (no new framework activity) keeps the prior level
# intact via the base; a busy positive quarter adds, a busy negative
# quarter subtracts.
#
#   base 3.0
#     + min(positive / 3, 4)            # +4 by 12+ positive items
#     - min(negative / 3, 2)            # capped downside (don't double-count)
# ---------------------------------------------------------------------------

LEGAL_BASE = 3.0
LEGAL_POS_DIVISOR = 3.0
LEGAL_POS_CAP = 4.0
LEGAL_NEG_DIVISOR = 3.0
LEGAL_NEG_CAP = 2.0


def score_legal(ev: Evidence) -> tuple[int, str, dict]:
    """MIPYME & FDI Framework pillar score (function name preserved)."""
    pos_component = min(ev.legal_positive_count_q / LEGAL_POS_DIVISOR, LEGAL_POS_CAP)
    neg_component = min(ev.legal_negative_count_q / LEGAL_NEG_DIVISOR, LEGAL_NEG_CAP)
    raw = LEGAL_BASE + pos_component - neg_component
    score = int(round(_clamp(raw)))
    return score, _color_for(score), {
        "base": LEGAL_BASE,
        "positive_count_q": ev.legal_positive_count_q,
        "negative_count_q": ev.legal_negative_count_q,
        "pos_component": round(pos_component, 2),
        "neg_component": round(neg_component, 2),
        "raw": round(raw, 2),
    }


# ---------------------------------------------------------------------------
# Political Stability
# ---------------------------------------------------------------------------
# Combines ANPP/PCC/Council-of-State activity and prisoner-release /
# constitutional-reform signal (positive normalisation) with the protest
# / repression / mass-out-migration signal (negative). Tone provides a
# gentle modifier. The 11J anniversary window (every July) is the
# natural seasonal stress test.
#
#   base 3.0
#     + min(amnesty_signal / 4, 3)
#     - min(protest_signal / 4, 3)
#     + clamp((tone + 1) / 2, -1, +1)
# ---------------------------------------------------------------------------

POLITICAL_BASE = 3.0


def score_political(ev: Evidence) -> tuple[int, str, dict]:
    amn = min(ev.amnesty_signal_q / 4.0, 3.0)
    pro = min(ev.protest_signal_q / 4.0, 3.0)
    if ev.political_avg_tone_q is None:
        tone = 0.0
    else:
        tone = _clamp((ev.political_avg_tone_q + 1) / 2.0, -1.0, 1.0)

    raw = POLITICAL_BASE + amn - pro + tone
    score = int(round(_clamp(raw)))
    return score, _color_for(score), {
        "base": POLITICAL_BASE,
        "amnesty_signal_q": ev.amnesty_signal_q,
        "protest_signal_q": ev.protest_signal_q,
        "amnesty_component": round(amn, 2),
        "protest_component": round(pro, 2),
        "tone_component": round(tone, 2),
        "raw": round(raw, 2),
    }


# ---------------------------------------------------------------------------
# Property Rights
# ---------------------------------------------------------------------------
# Cuba's property-rights story is dominated by Helms-Burton Title III:
# since the 2019 activation, US plaintiffs have been able to sue any
# entity "trafficking" in property confiscated from US nationals after
# 1959. New filings, dismissals, and settlements are the dominant
# observable signal. We also count fresh expropriation / forced-asset-
# transfer items in Gaceta CU as negative.
#
# Asymmetric: one new Title III filing or fresh expropriation decree
# erases years of arbitration progress. Negative items hit harder per
# item than positive items.
#
#   base 4.5
#     - min(negative / 2, 3)            # one big intervention (3+ items) -> -1.5
#     + min(positive / 4, 2)            # FCSC / dismissal / settlement movement
# ---------------------------------------------------------------------------

PROPERTY_BASE = 4.5


def score_property(ev: Evidence) -> tuple[int, str, dict]:
    neg = min(ev.property_negative_count_q / 2.0, 3.0)
    pos = min(ev.property_positive_count_q / 4.0, 2.0)
    raw = PROPERTY_BASE - neg + pos
    score = int(round(_clamp(raw)))
    return score, _color_for(score), {
        "base": PROPERTY_BASE,
        "negative_count_q": ev.property_negative_count_q,
        "positive_count_q": ev.property_positive_count_q,
        "neg_component": round(neg, 2),
        "pos_component": round(pos, 2),
        "raw": round(raw, 2),
    }


# ---------------------------------------------------------------------------
# Macro Stability
# ---------------------------------------------------------------------------
# Piecewise, mostly determined by the informal-vs-official FX premium
# (elTOQUE TRMI vs BCC reference rate) and (when present) the inflation
# print. Coface acts as a ceiling: while Coface holds Cuba at "E" the
# pillar can't exceed 4.
#
# Cuba FX context (mid-2020s, post-Tarea Ordenamiento):
#   - BCC official rate: ~120 CUP/USD (frozen for retail, with a
#     floating MLC market for state imports).
#   - elTOQUE TRMI informal rate: ~300-500 CUP/USD, i.e. a routine
#     150-300% premium over the official rate.
#   - 100% premium would be an unusually *good* quarter.
#
# Cuba inflation context:
#   - ONEI official annualised CPI: ~30% in recent years.
#   - Independent estimates (Inter-American Dialogue, Cuba Study Group,
#     Pavel Vidal): closer to 100-300% real, including informal market.
#
#   start 5.0
#   parallel premium (TRMI vs BCC):
#     <= 50%   no penalty   (would be remarkable improvement)
#     <= 100%  -1
#     <= 200%  -2           (long-running steady state)
#     <= 300%  -3
#     >  300%  -4           (acute monetary stress)
#   inflation (annualised, when reported):
#     <  30%   no penalty
#     <= 60%   -1
#     <= 100%  -1.5
#     <= 200%  -2.5
#     >  200%  -3.5
#   coface ceiling: grade "E" -> cap at 4; "D" -> cap at 5; "C" -> 6;
#   "B" -> 7; "A4" -> 8; "A3"/"A2"/"A1" -> 10
# ---------------------------------------------------------------------------

MACRO_START = 5.0
COFACE_CEILINGS = {"E": 4, "D": 5, "C": 6, "B": 7, "A4": 8, "A3": 10, "A2": 10, "A1": 10}


def _premium_penalty(p: Optional[float]) -> float:
    """Informal-vs-official FX premium in pct (elTOQUE TRMI vs BCC).

    Tuned for Cuba's post-Tarea-Ordenamiento monetary regime: any
    premium under 50% would be a structural improvement, 100-200% is
    the long-running steady state, 300%+ signals acute monetary stress
    (typically alongside fuel/food shortages and remittance-corridor
    breakdowns).
    """
    if p is None:
        return 0.0
    p = abs(p)
    if p <= 50: return 0.0
    if p <= 100: return 1.0
    if p <= 200: return 2.0
    if p <= 300: return 3.0
    return 4.0


def _inflation_penalty(i: Optional[float]) -> float:
    """Annualised inflation in pct.

    Tuned for Cuba: ONEI publishes mild official numbers (~30% recent
    years) but real inflation incl. informal markets is materially
    higher (Inter-American Dialogue and academic estimates put it at
    100-300%). Steps reflect that gap so we don't over-penalise the
    official print or under-penalise the lived reality.
    """
    if i is None:
        return 0.0
    if i < 30: return 0.0
    if i <= 60: return 1.0
    if i <= 100: return 1.5
    if i <= 200: return 2.5
    return 3.5


def score_macro(ev: Evidence) -> tuple[int, str, dict]:
    prem = _premium_penalty(ev.parallel_premium_pct)
    infl = _inflation_penalty(ev.inflation_annualized_pct)
    raw = MACRO_START - prem - infl

    ceiling = COFACE_CEILINGS.get(ev.coface_grade.upper(), 10)
    capped = min(raw, ceiling)
    score = int(round(_clamp(capped)))
    return score, _color_for(score), {
        "start": MACRO_START,
        "parallel_premium_pct": ev.parallel_premium_pct,
        "premium_penalty": prem,
        "inflation_annualized_pct": ev.inflation_annualized_pct,
        "inflation_penalty": infl,
        "coface_grade": ev.coface_grade,
        "coface_ceiling": ceiling,
        "raw": round(raw, 2),
        "after_ceiling": round(capped, 2),
    }


# ---------------------------------------------------------------------------
# Ordered list — matches the displayed scorecard top-to-bottom.
#
# The internal score_* function names (score_sanctions, score_legal)
# are intentionally generic so the runner / subtitles modules stay
# wired through unchanged. Only the labels surfaced to the template
# and the Evidence semantics differ from the previous rubric.
# ---------------------------------------------------------------------------

PILLARS = [
    ("Embargo Posture", score_sanctions),
    ("Diplomatic Engagement", score_diplomatic),
    ("MIPYME & FDI Framework", score_legal),
    ("Political Stability", score_political),
    ("Property Rights", score_property),
    ("Macro Stability", score_macro),
]
