"""
Internal-linking topic-cluster topology — the single source of truth for
which page belongs to which cluster, who the pillar is, and the exact
anchor text every backlink should use.

Why a dedicated module:
  • Modern SEO ("topical authority", post-Helpful-Content / SGE-aware
    Google) rewards comprehensive topic coverage with a clear pillar +
    a mesh of cluster pages that link to the pillar AND to each other
    AND down to deeper child pages — with descriptive anchor text.
    The hub-and-spoke version is dated; mesh is current.
  • Hardcoding cluster lists in five different templates produces drift
    (one template gets a new link, the others don't, Google sees an
    inconsistent signal). Centralising here keeps every backlink
    coherent — and lets us audit programmatically (e.g. "how many
    pages link to /tools/ofac-cuba-general-licenses?").
  • Anchor text matters for SEO. We canonicalise it here so every
    inbound link to a cluster member uses the same searchable phrase.

Public API (kept tiny on purpose):
    cluster_for(path)           -> Cluster | None
    other_members(path)         -> list[ClusterLink]
    pillar_link_for(path)       -> ClusterLink | None
    sector_for_program(program) -> ClusterLink | None
    program_to_sector_links()   -> dict[str, ClusterLink]

Templates use these via _cluster_nav.html.j2 so the rendered nav is
always in lockstep with the topology defined here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# Map OFAC program code → most-relevant sector landing page slug.
#
# Cuba sanctions are governed primarily by the Cuban Assets Control
# Regulations (CACR, 31 CFR Part 515), authorised by the Trading With
# the Enemy Act and reinforced by the Helms-Burton (LIBERTAD) Act.
# There is no single "Cuba EO" — the regime predates the EO-based
# sanctions architecture — but Global Magnitsky designations against
# Cuban officials (EO 13818) and the State Department's Cuba Restricted
# List (CACR §515.209, the "NS-PIL" tag in the SDN) are the operative
# supplements layered on top of CACR.
#
# Bare "CUBA" is intentionally unmapped — a CACR designation can be
# anything from a hotel chain to a securocrat, and a wrong sector link
# is worse for both reader and SEO than no sector link.
_PROGRAM_TO_SECTOR_SLUG: dict[str, str] = {
    "CUBA-EO13818": "governance",   # Global Magnitsky designations on Cuban officials
    "CUBA-NS-PIL":  "economic",     # Cuba Restricted List — GAESA / CIMEX / state enterprises
    # Plain "CUBA" intentionally unmapped — too broad to map cleanly.
}

# Canonical anchor-text phrases for high-traffic pages. Every inbound
# link from any cluster nav uses these exact strings so Google sees a
# consistent topical signal (instead of "click here" / "learn more").
_ANCHOR: dict[str, str] = {
    "/sanctions-tracker": "OFAC Cuba Sanctions Tracker (live SDN list)",
    "/sanctions/individuals": "All sanctioned individuals on the Cuba SDN list",
    "/sanctions/entities": "All sanctioned entities (companies and orgs) on the Cuba SDN list",
    "/sanctions/vessels": "All sanctioned vessels under Cuba-related programs",
    "/sanctions/aircraft": "All sanctioned aircraft under Cuba-related programs",
    "/sanctions/by-sector": "OFAC Cuba SDN list by sector (military, economic, diplomatic, governance)",
    "/sanctions/sector/military": "Currently sanctioned Cuban military, intelligence & security officials (MINFAR, MININT, DI, DGCI)",
    "/sanctions/sector/economic": "Sanctioned Cuban economic & financial actors (GAESA, CIMEX, FINCIMEX, Gaviota, BFI)",
    "/sanctions/sector/diplomatic": "Sanctioned Cuban diplomatic officials (MINREX, ambassadors)",
    "/sanctions/sector/governance": "Sanctioned Cuban government & political officials (PCC, ANPP, Council of State, judiciary)",
    "/tools/ofac-cuba-sanctions-checker": "OFAC Cuba sanctions checker (search any name)",
    "/tools/ofac-cuba-general-licenses": "OFAC General Licenses for Cuba — CACR §515.560–.578 (full list)",
    "/tools/cuba-restricted-list-checker": "Cuba Restricted List entity checker — CACR §515.209 (GAESA, CIMEX, Gaviota, Habaguanex)",
    "/tools/cuba-prohibited-hotels-checker": "Cuba Prohibited Hotels checker — State Department CPAL (§515.210)",
    "/tools/can-i-travel-to-cuba": "Can I legally travel to Cuba? — OFAC 12-category travel decision tree",
    "/tools/public-company-cuba-exposure-check": "Public company Cuba exposure check (S&P 500)",
    "/tools/sec-edgar-cuba-impairment-search": "SEC EDGAR Cuba / Helms-Burton / Cuba Restricted List / impairment search (S&P 500)",
    "/export-to-cuba": "Export to Cuba — U.S. company opportunity and compliance hub",
    "/tools/cuba-trade-leads-for-us-companies": "Cuba trade leads for U.S. companies",
    "/tools/cuba-export-opportunity-finder": "Cuba export opportunity finder",
    "/tools/cuba-hs-code-opportunity-finder": "Cuba HS code opportunity finder",
    "/tools/cuba-export-controls-sanctions-process-map": "Cuba export controls and sanctions process map",
    "/tools/can-my-us-company-export-to-cuba": "Can my U.S. company export to Cuba?",
    "/tools/cuba-country-contacts-directory": "Cuba country contacts directory",
    "/tools/us-company-cuba-market-entry-checklist": "U.S. company Cuba market-entry checklist",
    "/tools/cuba-agricultural-medical-export-checker": "Cuba agricultural and medical export eligibility checker",
    "/tools/cuba-telecom-internet-export-checker": "Cuba telecom and internet services export checker",
    "/tools/cuba-mipyme-export-support-checklist": "Cuba MIPYME export support checklist",
    "/tools/cuba-trade-events-matchmaking-calendar": "Cuba trade events and matchmaking calendar",
    "/tools/cuba-trade-barriers-tracker": "Cuba trade barriers tracker",
    "/tools/cuba-export-compliance-checklist": "Cuba export compliance checklist",
    "/companies": "S&P 500 Cuba exposure register (every ticker, A-Z)",
    "/explainers": "Cuba investor explainers — OFAC, Helms-Burton, BCC, MLC, Mariel ZED, Ley 118",
    "/explainers/what-are-ofac-sanctions-on-cuba": "What are OFAC sanctions on Cuba? (plain-English guide to the embargo)",
    "/explainers/helms-burton-title-iii": "Helms-Burton Title III explained — confiscated-property lawsuits against US-listed companies",
    "/explainers/cuba-restricted-list": "The Cuba Restricted List explained — GAESA, CIMEX, Gaviota and the prohibited-counterparty regime",

    "/people": "Cuban power figures — verified profiles of who runs Cuba (executive, PCC, military, judiciary, opposition)",
    "/people/by-role/executive": "Cuba's executive & Council of Ministers — President, Prime Minister, Vice Presidents, ministers",
    "/people/by-role/pcc": "Communist Party of Cuba (PCC) — Politburo, Secretariat, Central Committee leadership",
    "/people/by-role/military": "Cuban military & MININT leadership — FAR, Interior Ministry, intelligence services",
    "/people/by-role/judiciary": "Cuban judiciary & prosecution — Fiscal General, Tribunal Supremo Popular",
    "/people/by-role/opposition": "Cuban opposition, dissident & exile leaders — UNPACU, Damas de Blanco",

    "/invest-in-cuba": "How to invest in Cuba (2026 sanctions-safe guide — CACR, Helms-Burton, Mariel ZED)",
    "/sectors/tourism": "Cuba tourism sector — cruise lines, airlines, hotels, OFAC Cuba Restricted List exposure",
    "/sectors/biotech": "Cuba biotech & pharma sector — BioCubaFarma, vaccines, OFAC medical-device licensing",
    "/sectors/mining": "Cuba mining sector — Moa nickel & cobalt, Sherritt JV, foreign-investment terms",
    "/sectors/telecom": "Cuba telecom sector — ETECSA, OFAC §515.578 telecom carve-out, infrastructure deals",
    "/sectors/agriculture": "Cuba agriculture & sugar sector — AzCuba, ALIMPORT food imports, US ag-export licensing",
    "/sectors/remittances": "Cuba remittances corridor — Western Union, FINCIMEX, MLC and the post-2020 routing problem",
    "/sectors/real-estate": "Cuba real estate sector — Habaguanex, joint-venture hotels, Mariel logistics",
    "/sectors/mariel-zedm": "Mariel Special Development Zone (ZEDM) — concessions, tax holiday, foreign-investment portfolio",
    "/sectors/private-sector": "Cuban private sector — MIPYMES, cuentapropistas and the post-2021 reform framework",
    "/sectors/energy": "Cuba energy sector — oil import dependency, electricity grid, blackouts, renewables",
    "/sectors/banking": "Cuba banking sector — BCC, MLC, CUP/USD spread, OFAC correspondent-banking risk",
    "/sectors/sanctions": "Cuba sanctions sector — OFAC general licenses, the compliance ecosystem, Title III risk",
    "/sectors/legal": "Cuba legal sector — Foreign Investment Law (Ley 118), arbitration, Helms-Burton defence",
    "/sectors/governance": "Cuba governance — PCC, ANPP, Council of Ministers, the post-2019 constitution",
    "/sectors/economic": "Cuban macro outlook — ONEI data, Tarea Ordenamiento, dolarización parcial, deal flow",
    "/sectors/diplomatic": "Cuba diplomatic sector — US-Cuba bilateral, EU PDCA, MINREX protocol",
    "/tools/cuba-investment-roi-calculator": "Cuba investment ROI calculator (sector-by-sector, MLC/CUP/USD-aware)",
    "/explainers/empresa-mixta-foreign-investment-law": "Empresa Mixta and Cuba's Foreign Investment Law (Ley 118) — joint-venture mechanics for foreign capital",
    "/explainers/doing-business-in-havana": "Doing business in Havana — operating manual for foreign investors",

    "/travel": "Cuba travel hub — embassies, hotels, safety, drivers, OFAC travel categories",
    "/travel/emergency-card": "Havana emergency contact card (printable PDF)",
    "/tools/cuba-visa-requirements": "Cuba visa & tourist card requirements by passport (2026)",
    "/tools/havana-safety-by-neighborhood": "Havana safety by neighborhood (interactive map — Vedado, Miramar, Centro, Habana Vieja)",

    "/tools/eltoque-trmi-rate": "elTOQUE TRMI — live CUP/USD/MLC informal exchange rate",
    "/explainers/cuban-mlc-explained": "Cuba's MLC virtual currency explained — what MLC is, how stores work, repatriation risk",
    "/explainers/cup-cuc-tarea-ordenamiento": "Tarea Ordenamiento (Jan 2021) — the CUP/CUC unification and what it broke",
    "/explainers/what-is-the-banco-central-de-cuba": "What is the Banco Central de Cuba (BCC)? — 2026 guide for foreign investors",
}


@dataclass(frozen=True)
class ClusterLink:
    """One link in a cluster nav block. Path + anchor text + a short
    description sentence rendered as supporting copy in the nav UI.
    """
    path: str
    anchor: str
    description: str = ""


@dataclass(frozen=True)
class Cluster:
    """A topic cluster: one pillar + N cluster members.

    `members` does NOT include the pillar — templates render the pillar
    distinctly (sticky, top-of-block) and other members alongside.
    """
    key: str            # internal id (e.g. "sanctions")
    name: str           # human label for the cluster nav title
    pillar: ClusterLink
    members: tuple[ClusterLink, ...]
    summary: str = ""   # One-sentence elevator pitch for the topic

    def all_paths(self) -> tuple[str, ...]:
        return (self.pillar.path,) + tuple(m.path for m in self.members)


def _ck(path: str, description: str = "") -> ClusterLink:
    """Construct a ClusterLink from a path using the canonical anchor."""
    return ClusterLink(
        path=path,
        anchor=_ANCHOR.get(path, path),
        description=description,
    )


# ──────────────────────────────────────────────────────────────────────
# The four clusters
# ──────────────────────────────────────────────────────────────────────

CLUSTERS: dict[str, Cluster] = {
    "sanctions": Cluster(
        key="sanctions",
        name="OFAC Cuba Sanctions",
        summary=(
            "The full Cuban Insights coverage of US Treasury OFAC "
            "Cuba-related sanctions — the embargo as codified in the "
            "Cuban Assets Control Regulations (CACR, 31 CFR Part 515), "
            "Helms-Burton Title III risk, the State Department's Cuba "
            "Restricted List, the live SDN tracker with per-name "
            "profiles, the active general licenses, and plain-English "
            "explainers for institutional investors."
        ),
        pillar=_ck(
            "/sanctions-tracker",
            "Live tracker of every active OFAC Cuba-program designation (CACR, EO 13818 Magnitsky, Cuba Restricted List).",
        ),
        members=(
            _ck("/sanctions/by-sector", "Pivot the SDN list by sector: military, economic, diplomatic, governance."),
            _ck("/sanctions/sector/military",   "All sanctioned Cuban military, intelligence and security officials (MINFAR, MININT, DI, DGCI)."),
            _ck("/sanctions/sector/economic",   "All sanctioned GAESA holdings, CIMEX, FINCIMEX, Gaviota and state-bank actors (BFI)."),
            _ck("/sanctions/sector/diplomatic", "All sanctioned Cuban ambassadors and MINREX foreign-ministry officials."),
            _ck("/sanctions/sector/governance", "All sanctioned Cuban political and judicial officials (PCC, ANPP, Council of State, TSP)."),
            _ck("/sanctions/individuals", "Browse every sanctioned Cuban individual A-Z, each with a full profile."),
            _ck("/sanctions/entities",    "Browse every sanctioned Cuban company, ministry and holding A-Z."),
            _ck("/sanctions/vessels",     "Every blocked vessel — IMO, MMSI, year of build, parent company (typically GAESA / Gaviota / Melfi)."),
            _ck("/sanctions/aircraft",    "Every blocked aircraft — model, MSN, tail number, registered owner (typically Cubana / AeroGaviota)."),
            _ck("/tools/ofac-cuba-sanctions-checker", "Paste any name to instantly check it against the live Cuba SDN list and the Cuba Restricted List."),
            _ck("/tools/cuba-restricted-list-checker", "Search the State Department Cuba Restricted List (§515.209) — GAESA, CIMEX, Gaviota, Habaguanex, every named subentity."),
            _ck("/tools/cuba-prohibited-hotels-checker", "Check any Cuban hotel or casa against the State Department CPAL (§515.210) before booking."),
            _ck("/tools/ofac-cuba-general-licenses",  "All active OFAC General Licenses under CACR §515.560–.578 that authorize otherwise-prohibited Cuba transactions."),
            _ck("/tools/public-company-cuba-exposure-check", "Type any S&P 500 name or ticker to surface OFAC + EDGAR + news Cuba exposure."),
            _ck("/tools/sec-edgar-cuba-impairment-search",   "Run a pre-canned EDGAR full-text search for Cuba, Helms-Burton, the Cuba Restricted List, CACR §515, ALIMPORT, GAESA, ETECSA, Mariel ZED, and impairment / contingent-liability disclosures across any S&P 500 ticker."),
            _ck("/companies", "A-Z directory of every S&P 500 company with a Cuba-exposure profile (cruise lines, airlines, hospitality, ag-exporters, telecom)."),
            _ck("/explainers/what-are-ofac-sanctions-on-cuba", "Plain-English overview of how the US embargo on Cuba actually works (CACR, Helms-Burton, the 12 travel categories)."),
            _ck("/explainers/helms-burton-title-iii", "Helms-Burton Title III — confiscated-property lawsuits, the suspension/activation history, and what US-listed companies disclose."),
            _ck("/explainers/cuba-restricted-list", "The State Department's Cuba Restricted List explained — what's on it, why GAESA dominates it, and the §515.209 prohibition."),
        ),
    ),

    "investment": Cluster(
        key="investment",
        name="Investing in Cuba",
        summary=(
            "How institutional investors can take sanctions-safe "
            "exposure to Cuba — sector landing pages spanning the "
            "Mariel ZED, BioCubaFarma, Moa nickel, ETECSA telecom, "
            "the MIPYMES private sector and the remittances corridor, "
            "plus an ROI calculator and an operating manual for doing "
            "business in Havana under Ley 118 and the post-2021 "
            "private-sector reforms."
        ),
        pillar=_ck(
            "/invest-in-cuba",
            "The 2026 sanctions-safe guide to taking exposure to Cuba — CACR, Helms-Burton, Mariel ZED, MIPYMES.",
        ),
        members=(
            _ck("/sectors/tourism",        "Cruise lines, airlines, hotels — Cuba Restricted List exposure and the post-2019 NSPM-5 cruise ban."),
            _ck("/sectors/biotech",        "BioCubaFarma — vaccines, monoclonals, OFAC medical-device licensing pathways for US partners."),
            _ck("/sectors/mining",         "Moa Joint Venture (Sherritt) nickel and cobalt — the only operating Cuba mining JV with Western capital."),
            _ck("/sectors/telecom",        "ETECSA, the §515.578 telecom carve-out, internet rollout (Nauta), submarine cable infrastructure."),
            _ck("/sectors/agriculture",    "AzCuba sugar, ALIMPORT food-import flows, the US Trade Sanctions Reform Act (TSRA) export channel."),
            _ck("/sectors/remittances",    "Western Union, FINCIMEX, MLC, and the post-2020 remittance-routing collapse."),
            _ck("/sectors/real-estate",    "Habaguanex hotel portfolio, Mariel logistics real estate, joint-venture title and concession risk."),
            _ck("/sectors/mariel-zedm",    "Mariel ZED — Cuba's flagship foreign-investment vehicle. Concession terms, tax holiday, current portfolio (DP World, Brescia, Unilever)."),
            _ck("/sectors/private-sector", "MIPYMES and cuentapropistas — the post-2021 private-sector reform, what foreign capital can actually do."),
            _ck("/sectors/energy",         "Cuba's oil-import dependency, electricity grid fragility (the apagones), and the renewables / solar-park tender pipeline."),
            _ck("/sectors/banking",        "BCC, MLC, the CUP/USD spread, the broken correspondent-banking layer for US persons."),
            _ck("/sectors/sanctions",      "Sanctions-as-a-sector — OFAC general licenses, the compliance ecosystem, Title III lawsuit risk."),
            _ck("/tools/cuba-investment-roi-calculator", "Calculate ROI for any Cuba sector — currency stack, country-risk premia, MLC vs CUP vs USD."),
            _ck("/explainers/empresa-mixta-foreign-investment-law", "How Empresa Mixta JVs work under Ley 118 — control, profit repatriation, dispute resolution."),
            _ck("/explainers/doing-business-in-havana",       "On-the-ground operating manual for foreign-investor teams in Havana."),
        ),
    ),

    "export": Cluster(
        key="export",
        name="Exporting to Cuba",
        summary=(
            "U.S. exporter hub for Cuba — ITA / Trade.gov opportunity "
            "signals, trade leads, market intelligence, HS-code triage, "
            "Commercial Service contacts, trade events, trade barriers, "
            "and a sanctions-aware OFAC + BIS + State CRL/CPAL process "
            "map for deciding whether an opportunity is actionable."
        ),
        pillar=_ck(
            "/export-to-cuba",
            "The U.S. company hub for exporting to Cuba — ITA opportunity data plus OFAC, BIS, State CRL/CPAL, payment, and counterparty screening.",
        ),
        members=(
            _ck("/tools/cuba-trade-leads-for-us-companies", "Find and screen Cuba trade leads for U.S. companies against sanctions, export controls, payments, and counterparties."),
            _ck("/tools/cuba-export-opportunity-finder", "Map Cuba sector demand to the authorization and counterparty checks a U.S. exporter needs."),
            _ck("/tools/cuba-hs-code-opportunity-finder", "Use HS-code thinking to triage product-level opportunity, licensing risk, and documentation."),
            _ck("/tools/cuba-export-controls-sanctions-process-map", "Walk a Cuba export through OFAC CACR, BIS, State CRL/CPAL, payment, logistics, and records steps."),
            _ck("/tools/can-my-us-company-export-to-cuba", "Quickly classify whether a Cuba export idea is likely authorized, blocked, or license-dependent."),
            _ck("/tools/cuba-country-contacts-directory", "Start with ITA Trade Americas, U.S. Commercial Service, sector specialists, and compliance-aware contact paths."),
            _ck("/tools/us-company-cuba-market-entry-checklist", "Pre-entry checklist for product fit, authorization, counterparty, payment, logistics, and recordkeeping."),
            _ck("/tools/cuba-agricultural-medical-export-checker", "Triage agricultural, food, medical, healthcare, and humanitarian exports to Cuba."),
            _ck("/tools/cuba-telecom-internet-export-checker", "Evaluate telecom, internet, software, cloud, and connectivity exports under Cuba carve-outs and controls."),
            _ck("/tools/cuba-mipyme-export-support-checklist", "Screen whether exports supporting Cuban private businesses avoid restricted state or military channels."),
            _ck("/tools/cuba-trade-events-matchmaking-calendar", "Track ITA, Trade Americas, Caribbean, and sector events that may generate Cuba-relevant leads."),
            _ck("/tools/cuba-trade-barriers-tracker", "Monitor sanctions, payment, logistics, Cuban import, and private-sector execution barriers."),
            _ck("/tools/cuba-export-compliance-checklist", "Combine ITA research with OFAC, BIS, State CRL/CPAL, payment, logistics, and records controls."),
            _ck("/tools/ofac-cuba-general-licenses", "Check the CACR general licenses that may authorize otherwise prohibited Cuba activity."),
            _ck("/tools/cuba-restricted-list-checker", "Screen Cuban counterparties against the State Department Cuba Restricted List."),
            _ck("/tools/ofac-cuba-sanctions-checker", "Search Cuban and third-country names against the live OFAC Cuba SDN list."),
        ),
    ),

    "travel": Cluster(
        key="travel",
        name="Cuba Travel & Logistics",
        summary=(
            "Travel hub for investors, journalists and diaspora — "
            "embassies, vetted hotels, vetted drivers, security, plus "
            "visa / tourist-card and Havana neighborhood-safety tools "
            "designed for travelers operating under the OFAC 12 travel "
            "categories rather than ordinary tourism."
        ),
        pillar=_ck(
            "/travel",
            "The Cuban Insights travel hub — embassies, hotels, drivers, safety.",
        ),
        members=(
            _ck("/travel/emergency-card",                   "Printable single-page emergency contact card for Havana trips."),
            _ck("/tools/cuba-visa-requirements",            "Visa and tourist-card requirements for Cuba by passport (live, 2026)."),
            _ck("/tools/havana-safety-by-neighborhood",     "Interactive Havana safety map by neighborhood (Vedado, Miramar, Centro Habana, La Habana Vieja, Mariel ZEDM corridor)."),
            _ck("/tools/can-i-travel-to-cuba",              "OFAC 12-category decision tree — figure out which general license your trip qualifies under and what records you must keep."),
            _ck("/tools/cuba-prohibited-hotels-checker",    "Check any Cuban hotel or casa against the State Department's CPAL before booking — U.S. travelers may not lodge at listed properties."),
        ),
    ),

    "people": Cluster(
        key="people",
        name="Cuban Power Figures",
        summary=(
            "The people inside the Cuban government, the Communist "
            "Party (PCC), the FAR and MININT security services, the "
            "judiciary, and the opposition — verified profiles built "
            "for name-search intent, with sanctions cross-references "
            "and bidirectional links into the wider Cuba coverage."
        ),
        pillar=_ck(
            "/people",
            "Verified profiles of the people who run Cuba — and those who oppose them.",
        ),
        members=(
            _ck("/people/by-role/executive",  "President, Prime Minister, Vice Presidents and ministers — the executive branch."),
            _ck("/people/by-role/pcc",        "PCC Politburo and Secretariat — the leading force of the Cuban state."),
            _ck("/people/by-role/military",   "FAR and MININT leadership — the security and intelligence apparatus."),
            _ck("/people/by-role/judiciary",  "Cuban prosecutors and judges — Fiscalía General, Tribunal Supremo Popular."),
            _ck("/people/by-role/opposition", "Opposition, dissident and exile leaders — UNPACU, Damas de Blanco."),
            _ck("/sanctions/sector/governance", "All sanctioned Cuban political and judicial officials (PCC, ANPP, Council of State, TSP)."),
            _ck("/sanctions/sector/military",   "All sanctioned Cuban military, intelligence and security officials."),
            _ck("/sanctions/individuals",       "Browse every sanctioned Cuban individual A-Z, each with a full profile."),
        ),
    ),

    "fx": Cluster(
        key="fx",
        name="Cuba FX, MLC & BCC",
        summary=(
            "Cuba's broken currency stack and central-bank coverage — "
            "the daily elTOQUE TRMI informal CUP/USD/MLC rate, what "
            "MLC actually is, what Tarea Ordenamiento (Jan 2021) "
            "broke, and a 2026 explainer of how the Banco Central de "
            "Cuba operates."
        ),
        pillar=_ck(
            "/tools/eltoque-trmi-rate",
            "The CUP-to-USD-to-MLC informal rate, live from elTOQUE TRMI (the de-facto reference rate inside Cuba).",
        ),
        members=(
            _ck("/explainers/cuban-mlc-explained",                   "What MLC (Moneda Libremente Convertible) is, how the MLC store network works, and the repatriation problem."),
            _ck("/explainers/cup-cuc-tarea-ordenamiento",            "Tarea Ordenamiento (Jan 2021) — the CUP/CUC unification, the official-rate devaluation, and the inflation that followed."),
            _ck("/explainers/what-is-the-banco-central-de-cuba",     "What the BCC does, who runs it, and why it matters for foreign investors."),
        ),
    ),
}


# Path-prefix → cluster key. Order matters — most-specific prefix first.
_PATH_TO_CLUSTER: tuple[tuple[str, str], ...] = (
    ("/sanctions-tracker",     "sanctions"),
    ("/sanctions/by-sector",   "sanctions"),
    ("/sanctions/sector/",     "sanctions"),
    ("/sanctions/",            "sanctions"),
    ("/tools/ofac-cuba-sanctions-checker", "sanctions"),
    ("/tools/ofac-cuba-general-licenses",  "sanctions"),
    ("/tools/cuba-restricted-list-checker", "sanctions"),
    ("/tools/cuba-prohibited-hotels-checker", "sanctions"),
    ("/tools/public-company-cuba-exposure-check", "sanctions"),
    ("/tools/sec-edgar-cuba-impairment-search",   "sanctions"),
    ("/companies",             "sanctions"),
    ("/explainers/what-are-ofac-sanctions-on-cuba", "sanctions"),
    ("/explainers/helms-burton-title-iii",          "sanctions"),
    ("/explainers/cuba-restricted-list",            "sanctions"),

    ("/invest-in-cuba",        "investment"),
    ("/sectors/",              "investment"),
    ("/tools/cuba-investment-roi-calculator", "investment"),
    ("/explainers/empresa-mixta-foreign-investment-law", "investment"),
    ("/explainers/doing-business-in-havana",   "investment"),

    ("/export-to-cuba",        "export"),
    ("/tools/cuba-trade-leads-for-us-companies", "export"),
    ("/tools/cuba-export-opportunity-finder", "export"),
    ("/tools/cuba-hs-code-opportunity-finder", "export"),
    ("/tools/cuba-export-controls-sanctions-process-map", "export"),
    ("/tools/can-my-us-company-export-to-cuba", "export"),
    ("/tools/cuba-country-contacts-directory", "export"),
    ("/tools/us-company-cuba-market-entry-checklist", "export"),
    ("/tools/cuba-agricultural-medical-export-checker", "export"),
    ("/tools/cuba-telecom-internet-export-checker", "export"),
    ("/tools/cuba-mipyme-export-support-checklist", "export"),
    ("/tools/cuba-trade-events-matchmaking-calendar", "export"),
    ("/tools/cuba-trade-barriers-tracker", "export"),
    ("/tools/cuba-export-compliance-checklist", "export"),

    ("/people/by-role/",       "people"),
    ("/people/",               "people"),
    ("/people",                "people"),

    ("/travel",                "travel"),
    ("/tools/cuba-visa-requirements",         "travel"),
    ("/tools/havana-safety-by-neighborhood",  "travel"),
    ("/tools/can-i-travel-to-cuba",           "travel"),

    ("/tools/eltoque-trmi-rate",                            "fx"),
    ("/explainers/cuban-mlc-explained",                     "fx"),
    ("/explainers/cup-cuc-tarea-ordenamiento",              "fx"),
    ("/explainers/what-is-the-banco-central-de-cuba",       "fx"),
)


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────


def cluster_for(path: str) -> Optional[Cluster]:
    """Return the Cluster a given URL path belongs to, or None.

    Strips trailing slash and treats prefix matches as the most-specific
    match per the _PATH_TO_CLUSTER order.
    """
    if not path:
        return None
    norm = "/" + path.lstrip("/").rstrip("/")
    if norm == "":
        norm = "/"
    for prefix, key in _PATH_TO_CLUSTER:
        if norm == prefix.rstrip("/") or norm.startswith(prefix):
            return CLUSTERS.get(key)
    return None


def other_members(path: str, *, limit: int = 12) -> list[ClusterLink]:
    """Return the cluster's other members (excluding `path` itself).

    Used to render "Continue exploring this topic →" lists. Caps at
    `limit` so the nav block stays scannable on mobile.
    """
    cluster = cluster_for(path)
    if cluster is None:
        return []
    norm = "/" + path.lstrip("/").rstrip("/")
    out: list[ClusterLink] = []
    for m in cluster.members:
        if m.path == norm:
            continue
        out.append(m)
        if len(out) >= limit:
            break
    return out


def pillar_link_for(path: str) -> Optional[ClusterLink]:
    """Return the pillar link for the given page's cluster, or None.

    If `path` IS the pillar, returns None (templates use this to decide
    whether to render the "back to pillar" callout).
    """
    cluster = cluster_for(path)
    if cluster is None:
        return None
    norm = "/" + path.lstrip("/").rstrip("/")
    if cluster.pillar.path == norm:
        return None
    return cluster.pillar


def sector_for_program(program: str) -> Optional[ClusterLink]:
    """Map an OFAC program code to its most-relevant sector landing
    page, returned as a ClusterLink (so templates get the canonical
    anchor text for free).

    Used by the SDN profile page to surface a "this {entity} operates
    in {sector}" backlink — which both serves the reader (one click to
    sector context) and serves SEO (descriptive anchor + reciprocal
    cluster signal between the sanctions and investment clusters).
    """
    if not program:
        return None
    slug = _PROGRAM_TO_SECTOR_SLUG.get(program.upper())
    if not slug:
        return None
    path = f"/sectors/{slug}"
    return ClusterLink(
        path=path,
        anchor=_ANCHOR.get(path, path),
        description="",
    )


def program_to_sector_links() -> dict[str, ClusterLink]:
    """Programmatic access to the full mapping (for tests / audits)."""
    out: dict[str, ClusterLink] = {}
    for prog, slug in _PROGRAM_TO_SECTOR_SLUG.items():
        path = f"/sectors/{slug}"
        out[prog] = ClusterLink(path=path, anchor=_ANCHOR.get(path, path))
    return out


def companion_links(paths: list[str]) -> list[ClusterLink]:
    """Resolve a hand-curated list of paths into ClusterLink objects
    using the canonical anchor text from ``_ANCHOR``.

    Used to render hub-page "companion tools" / "cross-hub" callout
    blocks where we want the visible anchor text to stay in lockstep
    with every other inbound link to those URLs across the site.
    Paths missing from ``_ANCHOR`` fall through with the path itself
    as anchor text — never silently dropped, so missing entries are
    visible in QA.
    """
    out: list[ClusterLink] = []
    for p in paths:
        if not p:
            continue
        norm = "/" + p.lstrip("/").rstrip("/")
        out.append(ClusterLink(path=norm, anchor=_ANCHOR.get(norm, norm)))
    return out


def build_cluster_ctx(path: str, *, limit: int = 3) -> dict:
    """One-shot helper: returns the dict every template needs to render
    `_cluster_nav.html.j2`'s cluster_nav() macro.

    UX choice: ``limit`` defaults to **3** so the visible nav stays
    scannable. The full cluster mesh (often 15–20 pages) lives on the
    pillar page, and the rendered nav exposes a "See all in this hub
    →" link that points there. This keeps human attention on the next
    one or two clicks while still giving Google a topical-mesh signal
    via consistent canonical anchors.

    Returning a plain dict (rather than a dataclass) is intentional —
    Jinja's autoescape + attribute access work uniformly on dicts, and
    we don't need Python-side typing for a pure render-time payload.

    Returns empty-ish ctx (cluster=None) when the path is not in any
    registered cluster, which causes the macro to render nothing.
    Templates can therefore unconditionally `{{ cluster_nav(ctx) }}`
    without guards.
    """
    cluster = cluster_for(path)
    if cluster is None:
        return {
            "cluster": None,
            "pillar": None,
            "others": [],
            "is_pillar": False,
            "total_members": 0,
            "hidden_count": 0,
        }
    pillar = pillar_link_for(path)
    norm = "/" + path.lstrip("/").rstrip("/")
    total_others = sum(1 for m in cluster.members if m.path != norm)
    visible = other_members(path, limit=limit)
    return {
        "cluster": cluster,
        "pillar": pillar,
        "others": visible,
        "is_pillar": pillar is None,
        # Total count of sister pages in this cluster (excludes
        # current page; includes the visible 3 plus everything beyond).
        "total_members": total_others,
        # Number of additional sister pages NOT shown in the visible
        # nav — drives the "See N more in this hub →" copy.
        "hidden_count": max(0, total_others - len(visible)),
    }


# ──────────────────────────────────────────────────────────────────────
# "Other tools" — per-tool related-tools graph
# ──────────────────────────────────────────────────────────────────────
#
# UX intent: every tool page renders a small "Other tools" strip
# pointing at 3 sibling tools that the same reader is likely to need
# next. This is intentionally separate from the topic-cluster nav
# (which mixes tools, explainers, and sector pages by topic). Tools
# are utilities — when someone is on the SDN checker, the most useful
# next click is usually another search/lookup tool, not an explainer.
#
# Each entry is curated for human-flow, not just topical adjacency:
#   • Sanctions-screening tools point at each other (SDN ↔ CRL ↔ CPAL).
#   • Travel-planning tools point at each other (CPAL ↔ travel
#     decision tree ↔ visa ↔ safety map).
#   • Investor research tools point at each other (public-company
#     exposure ↔ SEC EDGAR ↔ ROI calculator ↔ FX rate).
# Cross-cluster jumps are deliberate (e.g. CPAL also surfaces in the
# travel set) — that's the whole point: a CPAL user is often planning
# a trip, not just doing compliance.
_TOOL_META: dict[str, dict[str, str]] = {
    "/tools/ofac-cuba-sanctions-checker": {
        "name": "OFAC SDN checker",
        "tagline": "Search any name against the live Cuba SDN list.",
    },
    "/tools/cuba-restricted-list-checker": {
        "name": "Cuba Restricted List checker",
        "tagline": "Search the State Department CRL — GAESA, CIMEX, Gaviota, Habaguanex.",
    },
    "/tools/cuba-prohibited-hotels-checker": {
        "name": "Cuba prohibited hotels (CPAL)",
        "tagline": "Check any Cuban hotel or casa against the State Department CPAL.",
    },
    "/tools/can-i-travel-to-cuba": {
        "name": "Can I legally travel to Cuba?",
        "tagline": "OFAC 12-category travel decision tree.",
    },
    "/tools/cuba-visa-requirements": {
        "name": "Cuba visa requirements",
        "tagline": "Visa & tourist-card rules by passport (live, 2026).",
    },
    "/tools/havana-safety-by-neighborhood": {
        "name": "Havana safety map",
        "tagline": "Neighborhood-level safety map — Vedado, Miramar, Centro, Habana Vieja.",
    },
    "/tools/ofac-cuba-general-licenses": {
        "name": "OFAC General Licenses",
        "tagline": "All active CACR §515.560–.578 general licenses.",
    },
    "/tools/public-company-cuba-exposure-check": {
        "name": "Public company Cuba exposure",
        "tagline": "Check any S&P 500 ticker for Cuba exposure (OFAC + EDGAR + news).",
    },
    "/tools/sec-edgar-cuba-impairment-search": {
        "name": "SEC EDGAR Cuba search",
        "tagline": "Pre-canned EDGAR full-text searches for Cuba / Helms-Burton / Title III.",
    },
    "/tools/cuba-investment-roi-calculator": {
        "name": "Cuba investment ROI",
        "tagline": "Sector-by-sector ROI — currency stack, country-risk premia, MLC vs CUP vs USD.",
    },
    "/tools/eltoque-trmi-rate": {
        "name": "elTOQUE TRMI rate",
        "tagline": "Live CUP/USD/MLC informal exchange rate.",
    },
    "/tools/cuba-trade-leads-for-us-companies": {
        "name": "Cuba trade leads",
        "tagline": "Find ITA-style leads and screen them before follow-up.",
    },
    "/tools/cuba-export-opportunity-finder": {
        "name": "Cuba export opportunities",
        "tagline": "Map sector demand to authorization and counterparty checks.",
    },
    "/tools/cuba-hs-code-opportunity-finder": {
        "name": "Cuba HS code finder",
        "tagline": "Product-level triage for demand, controls, and records.",
    },
    "/tools/cuba-export-controls-sanctions-process-map": {
        "name": "Cuba export process map",
        "tagline": "OFAC + BIS + State CRL/CPAL steps for exporters.",
    },
    "/tools/can-my-us-company-export-to-cuba": {
        "name": "Can my company export?",
        "tagline": "Decision tree for allowed, blocked, or license-dependent Cuba exports.",
    },
    "/tools/cuba-country-contacts-directory": {
        "name": "Cuba contacts directory",
        "tagline": "ITA Trade Americas and Commercial Service contact paths.",
    },
    "/tools/us-company-cuba-market-entry-checklist": {
        "name": "Cuba market-entry checklist",
        "tagline": "Product, party, payment, logistics, and records checks.",
    },
    "/tools/cuba-agricultural-medical-export-checker": {
        "name": "Ag & medical exports",
        "tagline": "Triage food, medical, healthcare, and humanitarian channels.",
    },
    "/tools/cuba-telecom-internet-export-checker": {
        "name": "Telecom export checker",
        "tagline": "Connectivity, software, cloud, and information-flow exports.",
    },
    "/tools/cuba-mipyme-export-support-checklist": {
        "name": "MIPYME support checklist",
        "tagline": "Keep private-sector support clear of restricted channels.",
    },
    "/tools/cuba-trade-events-matchmaking-calendar": {
        "name": "Cuba trade events",
        "tagline": "Track ITA, Trade Americas, Caribbean, and sector events.",
    },
    "/tools/cuba-trade-barriers-tracker": {
        "name": "Cuba trade barriers",
        "tagline": "Monitor sanctions, payment, logistics, and import barriers.",
    },
    "/tools/cuba-export-compliance-checklist": {
        "name": "Export compliance checklist",
        "tagline": "ITA opportunity research plus OFAC, BIS, State, and records.",
    },
}

# Curated 3-tool recommendation set for each tool page. Keep at three
# so the "Other tools" strip stays scannable on a single row.
_RELATED_TOOLS: dict[str, tuple[str, ...]] = {
    # Sanctions-screening cluster — the three checkers + the
    # exposure-research tool point at each other.
    "/tools/ofac-cuba-sanctions-checker": (
        "/tools/cuba-restricted-list-checker",
        "/tools/cuba-prohibited-hotels-checker",
        "/tools/public-company-cuba-exposure-check",
    ),
    "/tools/cuba-restricted-list-checker": (
        "/tools/ofac-cuba-sanctions-checker",
        "/tools/cuba-prohibited-hotels-checker",
        "/tools/ofac-cuba-general-licenses",
    ),
    "/tools/cuba-prohibited-hotels-checker": (
        "/tools/can-i-travel-to-cuba",
        "/tools/cuba-restricted-list-checker",
        "/tools/cuba-visa-requirements",
    ),
    "/tools/ofac-cuba-general-licenses": (
        "/tools/ofac-cuba-sanctions-checker",
        "/tools/cuba-restricted-list-checker",
        "/tools/can-i-travel-to-cuba",
    ),

    # Travel-planning cluster — decision tree, CPAL, visa, safety
    # map. CPAL appears here too because most travelers reach it via
    # a hotel-booking flow, not a compliance audit.
    "/tools/can-i-travel-to-cuba": (
        "/tools/cuba-prohibited-hotels-checker",
        "/tools/cuba-visa-requirements",
        "/tools/havana-safety-by-neighborhood",
    ),
    "/tools/cuba-visa-requirements": (
        "/tools/can-i-travel-to-cuba",
        "/tools/havana-safety-by-neighborhood",
        "/tools/cuba-prohibited-hotels-checker",
    ),
    "/tools/havana-safety-by-neighborhood": (
        "/tools/can-i-travel-to-cuba",
        "/tools/cuba-visa-requirements",
        "/tools/cuba-prohibited-hotels-checker",
    ),

    # Investor research cluster — exposure check, EDGAR, ROI, FX.
    "/tools/public-company-cuba-exposure-check": (
        "/tools/sec-edgar-cuba-impairment-search",
        "/tools/ofac-cuba-sanctions-checker",
        "/tools/cuba-investment-roi-calculator",
    ),
    "/tools/sec-edgar-cuba-impairment-search": (
        "/tools/public-company-cuba-exposure-check",
        "/tools/ofac-cuba-sanctions-checker",
        "/tools/cuba-investment-roi-calculator",
    ),
    "/tools/cuba-investment-roi-calculator": (
        "/tools/public-company-cuba-exposure-check",
        "/tools/eltoque-trmi-rate",
        "/tools/sec-edgar-cuba-impairment-search",
    ),
    "/tools/eltoque-trmi-rate": (
        "/tools/cuba-investment-roi-calculator",
        "/tools/public-company-cuba-exposure-check",
        "/tools/sec-edgar-cuba-impairment-search",
    ),

    # Export / ITA cluster — opportunity tools point at the process map
    # and checklist so lead-gen traffic converts into compliance-aware
    # workflows instead of dead-end pages.
    "/tools/cuba-trade-leads-for-us-companies": (
        "/tools/cuba-export-opportunity-finder",
        "/tools/cuba-export-controls-sanctions-process-map",
        "/tools/cuba-export-compliance-checklist",
    ),
    "/tools/cuba-export-opportunity-finder": (
        "/tools/cuba-trade-leads-for-us-companies",
        "/tools/cuba-hs-code-opportunity-finder",
        "/tools/us-company-cuba-market-entry-checklist",
    ),
    "/tools/cuba-hs-code-opportunity-finder": (
        "/tools/cuba-export-opportunity-finder",
        "/tools/cuba-export-controls-sanctions-process-map",
        "/tools/cuba-export-compliance-checklist",
    ),
    "/tools/cuba-export-controls-sanctions-process-map": (
        "/tools/can-my-us-company-export-to-cuba",
        "/tools/cuba-export-compliance-checklist",
        "/tools/ofac-cuba-general-licenses",
    ),
    "/tools/can-my-us-company-export-to-cuba": (
        "/tools/cuba-export-controls-sanctions-process-map",
        "/tools/cuba-export-compliance-checklist",
        "/tools/cuba-restricted-list-checker",
    ),
    "/tools/cuba-country-contacts-directory": (
        "/tools/cuba-trade-leads-for-us-companies",
        "/tools/cuba-trade-events-matchmaking-calendar",
        "/tools/us-company-cuba-market-entry-checklist",
    ),
    "/tools/us-company-cuba-market-entry-checklist": (
        "/tools/cuba-export-compliance-checklist",
        "/tools/cuba-export-opportunity-finder",
        "/tools/cuba-country-contacts-directory",
    ),
    "/tools/cuba-agricultural-medical-export-checker": (
        "/tools/cuba-export-compliance-checklist",
        "/tools/cuba-hs-code-opportunity-finder",
        "/tools/cuba-trade-leads-for-us-companies",
    ),
    "/tools/cuba-telecom-internet-export-checker": (
        "/tools/cuba-export-compliance-checklist",
        "/tools/cuba-export-controls-sanctions-process-map",
        "/tools/cuba-mipyme-export-support-checklist",
    ),
    "/tools/cuba-mipyme-export-support-checklist": (
        "/tools/cuba-export-compliance-checklist",
        "/tools/cuba-telecom-internet-export-checker",
        "/tools/cuba-trade-barriers-tracker",
    ),
    "/tools/cuba-trade-events-matchmaking-calendar": (
        "/tools/cuba-trade-leads-for-us-companies",
        "/tools/cuba-country-contacts-directory",
        "/tools/cuba-export-opportunity-finder",
    ),
    "/tools/cuba-trade-barriers-tracker": (
        "/tools/cuba-export-controls-sanctions-process-map",
        "/tools/cuba-export-compliance-checklist",
        "/tools/us-company-cuba-market-entry-checklist",
    ),
    "/tools/cuba-export-compliance-checklist": (
        "/tools/cuba-export-controls-sanctions-process-map",
        "/tools/ofac-cuba-general-licenses",
        "/tools/cuba-restricted-list-checker",
    ),
}


def build_related_tools_ctx(path: str) -> dict:
    """Return the dict the `_related_tools.html.j2` macro expects.

    Resolves the 3 curated sibling tools for the given page path and
    enriches each with its short name + tagline from ``_TOOL_META``.
    Returns ``{"items": []}`` (which the macro renders as nothing) for
    pages that aren't registered as tools — so callers can safely pass
    the ctx unconditionally.
    """
    # NOTE: the dict key is intentionally `tools`, not `items` —
    # Jinja's attribute lookup (`ctx.items`) resolves to the dict's
    # built-in `.items()` method first, masking the value. Using
    # `tools` sidesteps that footgun entirely.
    if not path:
        return {"tools": []}
    norm = "/" + path.lstrip("/").rstrip("/")
    related = _RELATED_TOOLS.get(norm)
    if not related:
        return {"tools": []}
    tools: list[dict[str, str]] = []
    for tool_path in related:
        meta = _TOOL_META.get(tool_path)
        if not meta:
            continue
        tools.append({
            "path": tool_path,
            "name": meta["name"],
            "tagline": meta["tagline"],
        })
    return {"tools": tools}


# ──────────────────────────────────────────────────────────────────────
# Backwards-compatibility aliases
# ──────────────────────────────────────────────────────────────────────
#
# Old VENEZUELA_-prefixed imports continue to resolve. New code should
# use the unprefixed CLUSTERS (or the explicit CUBA_CLUSTERS alias).
VENEZUELA_CLUSTERS = CLUSTERS
CUBA_CLUSTERS = CLUSTERS
