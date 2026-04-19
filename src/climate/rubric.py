"""
Investment Climate Tracker scoring rubric.

Pure functions. (Evidence) -> (score: int 0..10, color: str, signals: dict).
All thresholds live in this file as named constants so any one of them
can be re-tuned in isolation, with the rationale documented inline.

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
# Sanctions Trajectory
# ---------------------------------------------------------------------------
# Sanctions are the only pillar where the *direction of travel* is the
# dominant signal for investors, so the score combines a stock measure
# (where the SDN list and travel advisory sit today) with a flow measure
# (net change this quarter, count of OFAC actions).
#
# Anchors:
#   base 5.0
#     + clamp((removals - additions) / 2, -3, +3)        # SDN net delta
#     + clamp(min(ofac_doc_count_q, 6) / 3, 0, 2)        # OFAC GL/FR activity
#     + (5 - travel_advisory_level)                      # 4 -> +1, 3 -> +2, 2 -> +3
#
# A pure renewal-only quarter on a Level 4 advisory with zero net SDN
# movement = 5.0 + 0 + (~0.7 if a few docs) + 1 = ~6.7 -> still green-leaning
# (one notch above neutral). We accept that bias because OFAC publishing
# anything tends to mean something is being clarified, not tightened.
# ---------------------------------------------------------------------------

SANCTIONS_BASE = 4.0  # neutral baseline reflects "sanctions still on"
SANCTIONS_NET_SDN_CAP = 2.0
SANCTIONS_NET_DIVISOR = 3.0
SANCTIONS_DOC_CAP = 1.5
SANCTIONS_DOC_DIVISOR = 4.0


def score_sanctions(ev: Evidence) -> tuple[int, str, dict]:
    net = ev.sdn_removals_q - ev.sdn_additions_q
    net_component = _clamp(
        net / SANCTIONS_NET_DIVISOR,
        -SANCTIONS_NET_SDN_CAP,
        SANCTIONS_NET_SDN_CAP,
    )

    doc_component = _clamp(
        min(ev.ofac_doc_count_q, 8) / SANCTIONS_DOC_DIVISOR,
        0,
        SANCTIONS_DOC_CAP,
    )

    if ev.travel_advisory_level is None:
        ta_component = 0.0
    else:
        # Level 4 -> 0, Level 3 -> +1, Level 2 -> +2, Level 1 -> +3.
        ta_component = float(max(0, 4 - ev.travel_advisory_level))

    raw = SANCTIONS_BASE + net_component + doc_component + ta_component
    score = int(round(_clamp(raw)))
    return score, _color_for(score), {
        "base": SANCTIONS_BASE,
        "net_sdn": net,
        "net_component": net_component,
        "ofac_doc_count_q": ev.ofac_doc_count_q,
        "doc_component": doc_component,
        "travel_advisory_level": ev.travel_advisory_level,
        "ta_component": ta_component,
        "raw": round(raw, 2),
    }


# ---------------------------------------------------------------------------
# Diplomatic Progress
# ---------------------------------------------------------------------------
# Anchored on observable signal volume (GDELT articles touching diplomatic
# keywords) and average tone. Volume alone isn't enough — the embassy
# question is binary in the real world — but it correlates well with the
# kind of formal contact that moves the needle.
#
#   base 3.0
#     + min(count / 8, 4.0)             # max +4 once you see 32+ articles
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
# Legal Framework
# ---------------------------------------------------------------------------
# Counts gazette + assembly entries that mention legal-framework keywords
# split into "gives investors more certainty" vs "tightens state control".
# A neutral quarter (no legislation) keeps the prior level intact via the
# base; a busy positive quarter adds, a busy negative quarter subtracts.
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
# Combines amnesty/election-calendar signal (positive normalization) with
# protest/repression signal (negative). Tone provides a gentle modifier.
#
#   base 3.0
#     + min(amnesty / 4, 3)
#     - min(protest / 4, 3)
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
# Asymmetric: one expropriation-style law erases years of arbitration wins.
# Negative items hit harder per item than positive items.
#
#   base 4.0
#     - min(negative / 2, 3)            # one big mining law (3+ items) -> -1.5
#     + min(positive / 4, 2)            # ICSID/settlement movement
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
# Piecewise, mostly determined by the parallel premium and (when present)
# inflation print. Coface acts as a ceiling: while Coface holds the country
# at "E" the pillar can't exceed 4.
#
#   start 5.0
#   parallel premium:
#     <  5%  no penalty
#     <= 15% -1
#     <= 30% -2
#     <= 50% -3
#     >  50% -4
#   inflation (annualized, when reported):
#     <  50% no penalty
#     <= 200% -1
#     <= 500% -2
#     <= 1000% -3
#     > 1000% -4
#   coface ceiling: grade "E" -> cap at 4; "D" -> cap at 5; "C" -> 6;
#   "B" -> 7; "A4" -> 8; "A3"/"A2"/"A1" -> 10
# ---------------------------------------------------------------------------

MACRO_START = 5.0
COFACE_CEILINGS = {"E": 4, "D": 5, "C": 6, "B": 7, "A4": 8, "A3": 10, "A2": 10, "A1": 10}


def _premium_penalty(p: Optional[float]) -> float:
    """Parallel-vs-official FX premium in pct. Tuned for Venezuela:
    sub-10% is healthy, 10-20% is the long-running steady state, 20-35%
    signals stress, 35-60% is acute, >60% is collapse.
    """
    if p is None:
        return 0.0
    p = abs(p)
    if p < 10: return 0.0
    if p <= 20: return 1.0
    if p <= 35: return 2.0
    if p <= 60: return 3.0
    return 4.0


def _inflation_penalty(i: Optional[float]) -> float:
    """Annualized inflation in pct. Tuned for Venezuela: hyper-inflation
    is the historical norm, so the steps are wider than they would be
    for a normal-economy scorecard.
    """
    if i is None:
        return 0.0
    if i < 100: return 0.0
    if i <= 300: return 1.0
    if i <= 700: return 1.5
    if i <= 1500: return 2.5
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
# ---------------------------------------------------------------------------

PILLARS = [
    ("Sanctions Trajectory", score_sanctions),
    ("Diplomatic Progress", score_diplomatic),
    ("Legal Framework", score_legal),
    ("Political Stability", score_political),
    ("Property Rights", score_property),
    ("Macro Stability", score_macro),
]
