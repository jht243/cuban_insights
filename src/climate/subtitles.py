"""
Deterministic, evidence-driven "why" subtitle generator for each bar.

We deliberately avoid an LLM here: the subtitle's job is to faithfully
restate the inputs that drove the score so readers can reverse-engineer
the methodology. An LLM would summarise prettier but at the cost of
verifiability.
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
    parts: list[str] = []
    net = ev.sdn_removals_q - ev.sdn_additions_q
    parts.append(
        f"OFAC SDN net change {net:+d} this quarter "
        f"({ev.sdn_removals_q} removals, {ev.sdn_additions_q} additions)."
    )
    if ev.ofac_doc_count_q:
        parts.append(f"{ev.ofac_doc_count_q} OFAC/Federal Register documents observed.")
    if ev.travel_advisory_level is not None:
        parts.append(f"US travel advisory: Level {ev.travel_advisory_level}.")
    return " ".join(parts)


def subtitle_diplomatic(ev: Evidence) -> str:
    parts = [
        f"{ev.diplomatic_article_count_q} diplomatic-track articles indexed via GDELT this quarter."
    ]
    if ev.diplomatic_avg_tone_q is not None:
        tone = ev.diplomatic_avg_tone_q
        descriptor = "constructive" if tone > 0 else "neutral" if tone > -2 else "negative"
        parts.append(f"Average tone {tone:+.2f} ({descriptor}).")
    return " ".join(parts)


def subtitle_legal(ev: Evidence) -> str:
    parts = [
        f"{ev.legal_positive_count_q} investor-friendly legal-framework items observed,",
        f"{ev.legal_negative_count_q} restrictive items.",
    ]
    samples = ev._samples.get("legal_positive") or ev._samples.get("legal_negative") or []
    if samples:
        parts.append(f'Notable: "{samples[0][:90]}".')
    return " ".join(parts)


def subtitle_political(ev: Evidence) -> str:
    parts = [
        f"{ev.amnesty_signal_q} amnesty/electoral-calendar mentions,",
        f"{ev.protest_signal_q} protest/repression mentions.",
    ]
    if ev.political_avg_tone_q is not None:
        parts.append(f"Tone {ev.political_avg_tone_q:+.2f}.")
    return " ".join(parts)


def subtitle_property(ev: Evidence) -> str:
    parts = [
        f"{ev.property_negative_count_q} expropriation/state-ownership items,",
        f"{ev.property_positive_count_q} protective/arbitration items.",
    ]
    samples = ev._samples.get("property_negative") or []
    if samples:
        parts.append(f'Driver: "{samples[0][:90]}".')
    return " ".join(parts)


def subtitle_macro(ev: Evidence) -> str:
    bits: list[str] = []
    if ev.parallel_premium_pct is not None:
        bits.append(f"Parallel premium {ev.parallel_premium_pct:+.1f}%.")
    if ev.inflation_annualized_pct is not None:
        bits.append(f"Inflation {ev.inflation_annualized_pct:.0f}% annualized.")
    if ev.official_usd is not None:
        bits.append(f"BCV official {ev.official_usd:.2f} VES/USD.")
    bits.append(f"Coface country grade: {ev.coface_grade}.")
    return " ".join(bits)


SUBTITLE_FUNCS = {
    "Sanctions Trajectory": subtitle_sanctions,
    "Diplomatic Progress": subtitle_diplomatic,
    "Legal Framework": subtitle_legal,
    "Political Stability": subtitle_political,
    "Property Rights": subtitle_property,
    "Macro Stability": subtitle_macro,
}


METHODOLOGY_TEXT = (
    "Sub-scores derived weekly from data in our daily pipeline: BCV "
    "official+parallel FX (live scrape), US travel advisory level, "
    "OFAC SDN list diffs and Federal Register OFAC document count, "
    "GDELT global news tone (diplomatic and political subsets), "
    "Gaceta Oficial + Asamblea Nacional keyword counts on legal, "
    "property, and political-stability themes, and Coface country grade. "
    "QoQ comparison is the integer-point delta vs the previous calendar "
    "quarter's stored snapshot."
)
