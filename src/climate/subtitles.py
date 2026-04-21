"""
Deterministic, evidence-driven "why" subtitle generator for each bar
of the Havana Climate Index (the Cuba edition of the Investment
Climate Tracker scorecard).

We deliberately avoid an LLM here: the subtitle's job is to faithfully
restate the inputs that drove the score so readers can reverse-engineer
the methodology. An LLM would summarise prettier but at the cost of
verifiability.

Keys in `SUBTITLE_FUNCS` must match the labels in
`src.climate.rubric.PILLARS` exactly (the runner uses these as a
lookup table).
"""

from __future__ import annotations

from typing import Optional

from src.climate.evidence import Evidence


def _fmt_int(n: Optional[float]) -> str:
    if n is None:
        return "n/a"
    return f"{int(n)}"


def _fmt_pct(p: Optional[float]) -> str:
    if p is None:
        return "n/a"
    return f"{p:+.1f}%"


def subtitle_sanctions(ev: Evidence) -> str:
    """Subtitle for the Embargo Posture pillar."""
    parts: list[str] = []
    net = ev.sdn_removals_q - ev.sdn_additions_q
    parts.append(
        f"OFAC SDN (Cuba program) net change {net:+d} this quarter "
        f"({ev.sdn_removals_q} removals, {ev.sdn_additions_q} additions)."
    )
    if ev.ofac_doc_count_q:
        parts.append(
            f"{ev.ofac_doc_count_q} OFAC / Federal Register documents observed "
            f"(CACR amendments, GL renewals, Cuba Restricted List updates)."
        )
    if ev.travel_advisory_level is not None:
        parts.append(f"US State Dept Cuba travel advisory: Level {ev.travel_advisory_level}.")
    return " ".join(parts)


def subtitle_diplomatic(ev: Evidence) -> str:
    """Subtitle for the Diplomatic Engagement pillar."""
    parts = [
        f"{ev.diplomatic_article_count_q} US-Cuba / EU / MINREX diplomatic-track "
        f"articles indexed via GDELT this quarter."
    ]
    if ev.diplomatic_avg_tone_q is not None:
        tone = ev.diplomatic_avg_tone_q
        descriptor = "constructive" if tone > 0 else "neutral" if tone > -2 else "negative"
        parts.append(f"Average tone {tone:+.2f} ({descriptor}).")
    return " ".join(parts)


def subtitle_legal(ev: Evidence) -> str:
    """Subtitle for the MIPYME & FDI Framework pillar."""
    parts = [
        f"{ev.legal_positive_count_q} pro-MIPYME / pro-FDI items observed",
        f"(MIPYME authorisations, ZEDM approvals, Ley 118 / cartera de oportunidades),",
        f"{ev.legal_negative_count_q} restrictive items.",
    ]
    samples = ev._samples.get("legal_positive") or ev._samples.get("legal_negative") or []
    if samples:
        parts.append(f'Notable: "{samples[0][:90]}".')
    return " ".join(parts)


def subtitle_political(ev: Evidence) -> str:
    """Subtitle for the Political Stability pillar."""
    parts = [
        f"{ev.amnesty_signal_q} prisoner-release / electoral-calendar / reform mentions,",
        f"{ev.protest_signal_q} 11J / apagón / shortage / mass-migration mentions.",
    ]
    if ev.political_avg_tone_q is not None:
        parts.append(f"Tone {ev.political_avg_tone_q:+.2f}.")
    return " ".join(parts)


def subtitle_property(ev: Evidence) -> str:
    """Subtitle for the Property Rights pillar (Helms-Burton lens)."""
    parts = [
        f"{ev.property_negative_count_q} fresh Helms-Burton Title III filings / "
        f"expropriation items,",
        f"{ev.property_positive_count_q} dismissals / settlements / FCSC items.",
    ]
    samples = ev._samples.get("property_negative") or []
    if samples:
        parts.append(f'Driver: "{samples[0][:90]}".')
    return " ".join(parts)


def subtitle_macro(ev: Evidence) -> str:
    """Subtitle for the Macro Stability pillar."""
    bits: list[str] = []
    if ev.parallel_premium_pct is not None:
        bits.append(
            f"elTOQUE TRMI vs BCC reference premium {ev.parallel_premium_pct:+.1f}%."
        )
    if ev.inflation_annualized_pct is not None:
        bits.append(f"Inflation {ev.inflation_annualized_pct:.0f}% annualised.")
    if ev.official_usd is not None:
        bits.append(f"BCC reference {ev.official_usd:.2f} CUP/USD.")
    bits.append(f"Coface country grade: {ev.coface_grade}.")
    return " ".join(bits)


SUBTITLE_FUNCS = {
    "Embargo Posture": subtitle_sanctions,
    "Diplomatic Engagement": subtitle_diplomatic,
    "MIPYME & FDI Framework": subtitle_legal,
    "Political Stability": subtitle_political,
    "Property Rights": subtitle_property,
    "Macro Stability": subtitle_macro,
}


METHODOLOGY_TEXT = (
    "Sub-scores derived weekly from data in our daily pipeline: BCC "
    "reference CUP/USD vs. elTOQUE TRMI informal rate (live scrape), "
    "US State Dept Cuba travel advisory level, OFAC SDN list diffs "
    "(Cuba program) and Federal Register OFAC document count "
    "(CACR amendments, GL renewals, Cuba Restricted / Prohibited "
    "Accommodations List updates), GDELT global news tone "
    "(US-Cuba diplomatic and political subsets), Gaceta Oficial CU + "
    "ANPP / Granma keyword counts on MIPYME, FDI, "
    "Helms-Burton Title III, 11J / apagón, and migration themes, plus "
    "Coface country grade. QoQ comparison is the integer-point delta "
    "vs. the previous calendar quarter's stored snapshot."
)
