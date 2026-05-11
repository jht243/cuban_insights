"""
Generate or regenerate evergreen landing pages (pillar + sectors).

These pages use the premium model (settings.openai_premium_model) so
each generation costs more than a daily blog post — but they're
generated weekly at most, not per-request.

Usage:
    python scripts/generate_landing_pages.py --pillar
    python scripts/generate_landing_pages.py --sector mining
    python scripts/generate_landing_pages.py --all-sectors
    python scripts/generate_landing_pages.py --pillar --force
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


EXPLAINERS = [
    {
        "slug": "what-are-ofac-sanctions-on-cuba",
        "title": "What Are OFAC Sanctions on Cuba? A Plain-English Guide to the Embargo",
        "intent": "what are OFAC sanctions on Cuba / how does the US embargo on Cuba work / CACR 31 CFR 515 explained",
    },
    {
        "slug": "helms-burton-title-iii",
        "title": "Helms-Burton Title III Explained: Confiscated-Property Lawsuits Against US-Listed Companies",
        "intent": "Helms-Burton Title III / LIBERTAD Act Title III lawsuits / trafficking in confiscated Cuban property",
    },
    {
        "slug": "cuba-restricted-list",
        "title": "The Cuba Restricted List Explained: GAESA, CIMEX, Gaviota and the §515.209 Prohibition",
        "intent": "Cuba Restricted List / State Department prohibited counterparty list / §515.209",
    },
    {
        "slug": "what-is-the-banco-central-de-cuba",
        "title": "What Is the Banco Central de Cuba (BCC)? A 2026 Guide for Foreign Investors",
        "intent": "what is the BCC / Banco Central de Cuba explained / Cuba official exchange rate",
    },
    {
        "slug": "cuban-mlc-explained",
        "title": "Cuba's MLC Virtual Currency Explained: What MLC Is, How Stores Work, Repatriation Risk",
        "intent": "what is MLC Cuba / moneda libremente convertible / MLC stores Cuba",
    },
    {
        "slug": "cup-cuc-tarea-ordenamiento",
        "title": "Tarea Ordenamiento (Jan 2021): The CUP/CUC Unification and What It Broke",
        "intent": "Tarea Ordenamiento Cuba / CUP CUC unification / Cuban monetary reform 2021",
    },
    {
        "slug": "empresa-mixta-foreign-investment-law",
        "title": "Empresa Mixta and Cuba's Foreign Investment Law (Ley 118): Joint-Venture Mechanics",
        "intent": "empresa mixta Cuba / Ley 118 foreign investment / Cuban joint venture structure",
    },
    {
        "slug": "doing-business-in-havana",
        "title": "Doing Business in Havana: An Operating Manual for Foreign Investors",
        "intent": "doing business in Havana / Cuba business etiquette / how to set up a company in Cuba",
    },
]


DEFAULT_SECTORS = [
    "tourism",
    "biotech",
    "mining",
    "telecom",
    "agriculture",
    "remittances",
    "real-estate",
    "mariel-zedm",
    "private-sector",
    "energy",
    "banking",
    "sanctions",
    "legal",
    "governance",
    "economic",
    "diplomatic",
    "shipping",
    "healthcare",
    "construction",
    "transportation",
    "security",
    "fiscal",
    "media",
    "rum-and-tobacco",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pillar", action="store_true", help="Generate the /invest-in-cuba pillar page")
    parser.add_argument("--sector", type=str, default=None, help="Generate one /sectors/{slug} page")
    parser.add_argument("--all-sectors", action="store_true", help="Generate all sector pages")
    parser.add_argument("--explainer", type=str, default=None, help="Generate one /explainers/{slug} page")
    parser.add_argument("--all-explainers", action="store_true", help="Generate all evergreen explainers")
    parser.add_argument("--force", action="store_true", help="Force regeneration even if recently updated")
    args = parser.parse_args()

    if not (args.pillar or args.sector or args.all_sectors or args.explainer or args.all_explainers):
        parser.error("must pass at least one of --pillar / --sector / --all-sectors / --explainer / --all-explainers")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)-30s  %(levelname)-8s  %(message)s",
    )
    log = logging.getLogger("generate_landing_pages")

    from src.landing_generator import generate_explainer, generate_pillar_page, generate_sector_page

    total_cost = 0.0

    if args.pillar:
        log.info("generating pillar page (premium model)")
        page = generate_pillar_page(force=args.force)
        log.info("pillar -> %s (%d words, $%.4f)", page.canonical_path, page.word_count or 0, page.llm_cost_usd or 0.0)
        total_cost += page.llm_cost_usd or 0.0

    sectors_to_generate: list[str] = []
    if args.sector:
        sectors_to_generate.append(args.sector)
    if args.all_sectors:
        sectors_to_generate.extend(DEFAULT_SECTORS)

    for slug in sectors_to_generate:
        log.info("generating sector page: %s (premium model)", slug)
        page = generate_sector_page(slug, force=args.force)
        log.info("sector %s -> %s (%d words, $%.4f)", slug, page.canonical_path, page.word_count or 0, page.llm_cost_usd or 0.0)
        total_cost += page.llm_cost_usd or 0.0

    explainers_to_run: list[dict] = []
    if args.explainer:
        match = next((e for e in EXPLAINERS if e["slug"] == args.explainer), None)
        if not match:
            parser.error(f"unknown explainer slug: {args.explainer}. Known: {[e['slug'] for e in EXPLAINERS]}")
        explainers_to_run.append(match)
    if args.all_explainers:
        explainers_to_run.extend(EXPLAINERS)

    for ex in explainers_to_run:
        log.info("generating explainer: %s (premium model)", ex["slug"])
        page = generate_explainer(ex["slug"], topic_title=ex["title"], search_intent=ex["intent"], force=args.force)
        log.info("explainer %s -> %s (%d words, $%.4f)", ex["slug"], page.canonical_path, page.word_count or 0, page.llm_cost_usd or 0.0)
        total_cost += page.llm_cost_usd or 0.0

    log.info("done. total cost: $%.4f", total_cost)


if __name__ == "__main__":
    main()
