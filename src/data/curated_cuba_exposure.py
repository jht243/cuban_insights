"""
Curated, hand-maintained map of well-known Cuba exposures for S&P 500
companies. This is the high-precision layer of the exposure engine — it
lets us assert "Carnival settled a Helms-Burton Title III claim over its
use of the Havana cruise terminal" instead of relying on string-match
heuristics alone.

Cuba's investor-exposure footprint among US-listed companies is
materially smaller than Venezuela's, because the US embargo (Cuban
Assets Control Regulations, 31 CFR Part 515) prohibits most US-person
dealings with Cuba. The handful of S&P 500 names with real exposure
mostly fall into one of these buckets:

  1. Telecom carriers operating direct-dial / roaming agreements with
     ETECSA under the OFAC General License at 31 CFR §515.542
     (T, VZ, TMUS).
  2. Air carriers operating scheduled service to Havana / Santiago /
     Camagüey / Varadero under DOT route awards and OFAC authorized
     travel categories (AAL, DAL, JBLU, UAL, ALK, LUV).
  3. Cruise lines that operated Havana itineraries 2016-2019 and
     became defendants in Helms-Burton Title III lawsuits over their
     use of confiscated port property (CCL, RCL, NCLH).
  4. Agricultural / pharmaceutical exporters authorized under the
     Trade Sanctions Reform and Export Enhancement Act of 2000 / GL 4
     (ADM, BG, TSN, PFE, MRK, JNJ, BAX, ABT).
  5. Hospitality operators that ran Havana hotels under a 2016-era
     specific license — Marriott / Starwood ran the Four Points by
     Sheraton Habana before the license was revoked in 2020 (MAR).
  6. Payments / remittance infrastructure historically routing
     remittances to Cuba (MA, V — limited and intermittent under
     successive CACR amendments).

For each ticker we list:
  - exposure_level: "direct" | "indirect" | "historical" | "none"
  - summary: a 1-2 sentence analyst note
  - subsidiaries: known Cuba-related operating entities, brands, or
    counterparties associated with the parent (used as additional
    fuzzy-match terms against the OFAC SDN list / Cuba Restricted List
    and EDGAR / FR / our corpus)
  - ofac_licenses: relevant OFAC General Licenses (CACR section)
  - notes: internal extra context (not always rendered)

When a ticker is NOT in this map, the engine falls back to algorithmic
signals only and the page reads "no direct exposure on the public
record" — which is the answer most analysts come for, because for the
vast majority of US-listed companies, that IS the answer.

This map is small on purpose. We keep it artisanal because false
positives (claiming a company is Cuba-exposed when it isn't) are much
more harmful than false negatives, especially in a sanctions-compliance
context. Add entries as research surfaces them, not speculatively.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CuratedExposure:
    ticker: str
    exposure_level: str  # "direct" | "indirect" | "historical" | "none"
    summary: str
    subsidiaries: tuple[str, ...] = field(default_factory=tuple)
    ofac_licenses: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""


_CURATED: dict[str, CuratedExposure] = {
    # ── Cruise lines: Helms-Burton Title III defendants ───────────────
    "CCL": CuratedExposure(
        ticker="CCL",
        exposure_level="historical",
        summary=(
            "Carnival was the lead defendant in the first Helms-Burton Title III "
            "lawsuit to go to trial (Havana Docks Corp. v. Carnival, S.D. Fla.), "
            "involving the company's use of the Port of Havana cruise terminal "
            "(2016-2019) which had been confiscated by the Cuban government in 1960. "
            "Carnival has since exited Cuba itineraries."
        ),
        subsidiaries=("Carnival Corporation Cuba", "Havana Docks"),
        notes=(
            "$110M judgment in 2022 against Carnival, MSC, Norwegian, and Royal "
            "Caribbean (later partly vacated and remanded on appeal). Sets the "
            "precedent for Title III liability."
        ),
    ),
    "RCL": CuratedExposure(
        ticker="RCL",
        exposure_level="historical",
        summary=(
            "Royal Caribbean co-defendant alongside Carnival in the Havana Docks "
            "Title III litigation over use of the confiscated Havana cruise "
            "terminal during 2016-2019 itineraries. Cuba calls suspended."
        ),
        subsidiaries=("Royal Caribbean Cruises Cuba",),
        ofac_licenses=("CACR §515.572 (people-to-people, since rescinded)",),
    ),
    "NCLH": CuratedExposure(
        ticker="NCLH",
        exposure_level="historical",
        summary=(
            "Norwegian Cruise Line co-defendant in the Havana Docks Title III "
            "lawsuit over Havana port use during the brief 2016-2019 US-Cuba "
            "cruise window. No active Cuba operations."
        ),
        subsidiaries=("Norwegian Cruise Line Cuba",),
    ),
    # ── Air carriers: scheduled service under DOT/OFAC authorizations ─
    "AAL": CuratedExposure(
        ticker="AAL",
        exposure_level="direct",
        summary=(
            "American Airlines is the largest US carrier to Cuba by frequency, "
            "operating scheduled service from Miami (MIA) to Havana (HAV), "
            "Camagüey, Holguín, Santa Clara, and Varadero under DOT route awards "
            "and the OFAC authorized-travel framework at 31 CFR §515.560-§515.567."
        ),
        subsidiaries=("American Airlines Cuba routes",),
        ofac_licenses=("CACR §515.560-567 (12 authorized travel categories)",),
        notes=(
            "Route allocations periodically reduced by DOT under successive "
            "administrations. Operational continuity depends on travel-category "
            "guidance from OFAC."
        ),
    ),
    "DAL": CuratedExposure(
        ticker="DAL",
        exposure_level="direct",
        summary=(
            "Delta operates scheduled MIA/JFK/ATL–HAV service under DOT route "
            "awards and OFAC authorized-travel categories. Cuba routes are a "
            "small but symbolic piece of Delta's Latin America network."
        ),
        ofac_licenses=("CACR §515.560-567",),
    ),
    "JBLU": CuratedExposure(
        ticker="JBLU",
        exposure_level="direct",
        summary=(
            "JetBlue has been one of the most consistent US carriers to Cuba "
            "since the 2016 reopening, with scheduled service from FLL/JFK to "
            "HAV / Santa Clara / Camagüey / Holguín under OFAC authorized travel."
        ),
        ofac_licenses=("CACR §515.560-567",),
    ),
    "UAL": CuratedExposure(
        ticker="UAL",
        exposure_level="direct",
        summary=(
            "United operates EWR/IAH–HAV scheduled service under DOT route "
            "awards and OFAC authorized travel categories."
        ),
        ofac_licenses=("CACR §515.560-567",),
    ),
    "ALK": CuratedExposure(
        ticker="ALK",
        exposure_level="historical",
        summary=(
            "Alaska Airlines operated LAX-HAV scheduled service after the 2016 "
            "reopening but exited Cuba routes in 2018 citing weak demand and "
            "tightening travel restrictions."
        ),
    ),
    "LUV": CuratedExposure(
        ticker="LUV",
        exposure_level="historical",
        summary=(
            "Southwest operated FLL/TPA–HAV scheduled service 2016-2019 under "
            "DOT route awards before exiting Cuba routes when authorized-"
            "travel demand fell after CACR amendments."
        ),
    ),
    # ── Hospitality: licensed Havana hotel operations ─────────────────
    "MAR": CuratedExposure(
        ticker="MAR",
        exposure_level="historical",
        summary=(
            "Marriott / Starwood operated the Four Points by Sheraton Habana "
            "from 2016 under a US Treasury specific license — the first US "
            "hotel operation in Cuba since 1959. The license was revoked in "
            "2020 and Marriott exited the property."
        ),
        subsidiaries=("Four Points by Sheraton Habana", "Starwood Cuba"),
        ofac_licenses=("Specific license (revoked 2020)",),
        notes=(
            "Property is owned by GAESA-affiliated Gaviota S.A.; Helms-Burton "
            "Title IV exposure considered when license was active."
        ),
    ),
    # ── Telecom: ETECSA roaming / direct-dial under §515.542 ──────────
    "T": CuratedExposure(
        ticker="T",
        exposure_level="direct",
        summary=(
            "AT&T maintains direct-dial and roaming interconnection with ETECSA "
            "(Cuba's state telecom monopoly) under the OFAC general license at "
            "31 CFR §515.542 authorizing telecommunications-related "
            "transactions with Cuba."
        ),
        subsidiaries=("ETECSA roaming agreement",),
        ofac_licenses=("CACR §515.542",),
    ),
    "VZ": CuratedExposure(
        ticker="VZ",
        exposure_level="direct",
        summary=(
            "Verizon was the first US carrier to launch direct roaming with "
            "ETECSA in 2015 under §515.542 authorization. Continues to maintain "
            "the interconnection."
        ),
        ofac_licenses=("CACR §515.542",),
    ),
    "TMUS": CuratedExposure(
        ticker="TMUS",
        exposure_level="direct",
        summary=(
            "T-Mobile operates roaming with ETECSA under §515.542 telecom "
            "general license. Cuba traffic is a tiny share of revenue."
        ),
        ofac_licenses=("CACR §515.542",),
    ),
    # ── Agricultural exports under TSRA / GL ──────────────────────────
    "ADM": CuratedExposure(
        ticker="ADM",
        exposure_level="direct",
        summary=(
            "Archer Daniels Midland is one of the largest US agricultural "
            "exporters to Cuba under the Trade Sanctions Reform and Export "
            "Enhancement Act of 2000 (TSRA), which authorizes cash-in-advance "
            "sales of agricultural commodities to Cuban government buyers "
            "(primarily ALIMPORT)."
        ),
        subsidiaries=("ALIMPORT counterparty",),
        ofac_licenses=("TSRA / CACR §515.533",),
    ),
    "BG": CuratedExposure(
        ticker="BG",
        exposure_level="direct",
        summary=(
            "Bunge ships soybean meal, wheat, and other agricultural "
            "commodities to ALIMPORT under TSRA cash-in-advance terms. Cuba "
            "buys ~$200-400M/yr of US ag exports in normal years; Bunge is a "
            "recurring supplier."
        ),
        subsidiaries=("ALIMPORT counterparty",),
        ofac_licenses=("TSRA / CACR §515.533",),
    ),
    "TSN": CuratedExposure(
        ticker="TSN",
        exposure_level="direct",
        summary=(
            "Tyson Foods is among the recurring US chicken exporters to Cuba "
            "under TSRA. Frozen chicken parts have been the single largest US "
            "ag export line item to the island for over a decade."
        ),
        ofac_licenses=("TSRA / CACR §515.533",),
    ),
    # ── Pharmaceutical / medical devices under GL ─────────────────────
    "PFE": CuratedExposure(
        ticker="PFE",
        exposure_level="indirect",
        summary=(
            "Pfizer ships limited categories of pharmaceuticals and vaccines "
            "to Cuba under the OFAC general license for medicine and medical "
            "devices at 31 CFR §515.559. Volume is small."
        ),
        ofac_licenses=("CACR §515.559",),
    ),
    "MRK": CuratedExposure(
        ticker="MRK",
        exposure_level="indirect",
        summary=(
            "Merck supplies certain pharmaceuticals to Cuba under the §515.559 "
            "medicine general license. Cuban biotech sector (BioCubaFarma) is "
            "a notable counterparty for joint research and licensing inquiries "
            "where authorized."
        ),
        ofac_licenses=("CACR §515.559",),
    ),
    "JNJ": CuratedExposure(
        ticker="JNJ",
        exposure_level="indirect",
        summary=(
            "Johnson & Johnson supplies authorized pharmaceuticals and medical "
            "devices to Cuba under §515.559. Has historically engaged with "
            "BioCubaFarma on selected research dialogues."
        ),
        ofac_licenses=("CACR §515.559",),
    ),
    "BAX": CuratedExposure(
        ticker="BAX",
        exposure_level="indirect",
        summary=(
            "Baxter supplies dialysis consumables and IV solutions to Cuba "
            "under the §515.559 medical device general license."
        ),
        ofac_licenses=("CACR §515.559",),
    ),
    "ABT": CuratedExposure(
        ticker="ABT",
        exposure_level="indirect",
        summary=(
            "Abbott supplies diagnostics and nutritional products to Cuba "
            "under the §515.559 medical device GL. Cuba's diagnostic-equipment "
            "supply chain depends materially on §515.559 authorizations."
        ),
        ofac_licenses=("CACR §515.559",),
    ),
    # ── Payments / remittances ─────────────────────────────────────────
    "MA": CuratedExposure(
        ticker="MA",
        exposure_level="historical",
        summary=(
            "Mastercard authorized US-issued cards for use in Cuba in 2015 "
            "under a CACR amendment, but acceptance has been intermittent and "
            "constrained by the lack of US correspondent banking with Cuban "
            "issuers (most notably FINCIMEX, which is on the Cuba Restricted "
            "List). Practical usage remains very limited."
        ),
        notes=(
            "FINCIMEX listing on the Cuba Restricted List effectively ended "
            "Western Union's regulated remittance corridor in 2020; rebuilding "
            "the corridor depends on a CRL update."
        ),
    ),
    "V": CuratedExposure(
        ticker="V",
        exposure_level="historical",
        summary=(
            "Visa, like Mastercard, authorized US card use in Cuba under "
            "post-2015 CACR amendments but acceptance is materially limited "
            "by sanctioned acquiring counterparties on the Cuba Restricted "
            "List."
        ),
    ),
    # ── Helms-Burton Title III plaintiffs (US-listed certified claims) ─
    "EXXON": CuratedExposure(
        ticker="XOM",
        exposure_level="historical",
        summary=(
            "ExxonMobil holds one of the largest US certified claims against "
            "Cuba (Standard Oil's Cuban refining and distribution assets "
            "nationalized in 1960) registered with the Foreign Claims "
            "Settlement Commission. Title III litigation activated 2019."
        ),
        notes=(
            "Certified claim ~$71M (1960 dollars) plus statutory interest. "
            "Title III suits are slow-moving and frequently negotiated."
        ),
    ),
    "XOM": CuratedExposure(
        ticker="XOM",
        exposure_level="historical",
        summary=(
            "ExxonMobil holds one of the largest US certified claims against "
            "Cuba (Standard Oil's Cuban refining and distribution assets "
            "nationalized in 1960) registered with the Foreign Claims "
            "Settlement Commission. Title III litigation activated 2019."
        ),
    ),
    # ── Frequently-asked-about names with NO meaningful exposure ──────
    "KO": CuratedExposure(
        ticker="KO",
        exposure_level="none",
        summary=(
            "Coca-Cola is one of two countries where the company does not "
            "operate (the other historically being North Korea). No Cuban "
            "subsidiary; no SDN exposure. Listed here to pre-empt the "
            "common question."
        ),
        notes="Cuba and North Korea are commonly cited as KO-not-present markets.",
    ),
    "PEP": CuratedExposure(
        ticker="PEP",
        exposure_level="none",
        summary="PepsiCo has no operating subsidiary or bottling presence in Cuba.",
    ),
    "MCD": CuratedExposure(
        ticker="MCD",
        exposure_level="none",
        summary=(
            "McDonald's does not operate in Cuba. The only McDonald's on Cuban "
            "territory is on US-controlled Naval Station Guantánamo Bay and is "
            "operated for US service members."
        ),
    ),
    "AAPL": CuratedExposure(
        ticker="AAPL",
        exposure_level="none",
        summary=(
            "Apple has no Cuban subsidiary, retail, or authorized reseller. "
            "Devices are present via grey-market import; no Cuba-specific "
            "supply-chain or sanctions exposure on the public record."
        ),
    ),
    "MSFT": CuratedExposure(
        ticker="MSFT",
        exposure_level="none",
        summary=(
            "Microsoft has no operating subsidiary in Cuba. Cloud services "
            "are gated by US export-control geofencing for Cuban end-users."
        ),
    ),
    "GOOGL": CuratedExposure(
        ticker="GOOGL",
        exposure_level="indirect",
        summary=(
            "Alphabet operates a small Google Global Cache deployment with "
            "ETECSA (announced 2019) to improve content delivery on the "
            "island, under the §515.542 telecom GL. No advertising business "
            "in Cuba."
        ),
        ofac_licenses=("CACR §515.542",),
    ),
    "META": CuratedExposure(
        ticker="META",
        exposure_level="none",
        summary=(
            "Meta has no operating presence in Cuba. WhatsApp / Facebook / "
            "Instagram are heavily used on the island via ETECSA mobile "
            "data; periodic government-imposed throttling has been documented."
        ),
    ),
    "AMZN": CuratedExposure(
        ticker="AMZN",
        exposure_level="none",
        summary=(
            "Amazon does not ship to Cuba and AWS does not serve Cuban "
            "end-customers. No retail or cloud presence."
        ),
    ),
    "WMT": CuratedExposure(
        ticker="WMT",
        exposure_level="none",
        summary="Walmart has no operating subsidiary in Cuba.",
    ),
    "CVX": CuratedExposure(
        ticker="CVX",
        exposure_level="none",
        summary=(
            "Chevron has no operating presence in Cuba. The legacy Texaco "
            "refining assets (Texas Co. de Cuba) were nationalized in 1960 "
            "and the certified FCSC claim was acquired through corporate "
            "succession but has not driven active Title III litigation."
        ),
    ),
}


def get_curated(ticker: str) -> CuratedExposure | None:
    if not ticker:
        return None
    return _CURATED.get(ticker.upper())


def all_curated_tickers() -> list[str]:
    return sorted(_CURATED.keys())


def known_subsidiary_terms(ticker: str) -> list[str]:
    """Return the list of company-specific subsidiary / brand strings to
    fuzzy-match against the OFAC SDN list, the Cuba Restricted List,
    and our text corpora."""
    entry = get_curated(ticker)
    if not entry:
        return []
    return list(entry.subsidiaries)
