"""
Static catalogue of currently-relevant OFAC general licenses (GLs)
authorising specific transactions involving Cuba. This is the seed data
for the /tools/ofac-cuba-general-licenses lookup tool.

Update whenever OFAC publishes a new GL or amends an existing one.

Authoritative source for everything below:
  https://ofac.treasury.gov/recent-actions
  https://ofac.treasury.gov/sanctions-programs-and-country-information/cuba-sanctions
  31 CFR Part 515 (Cuban Assets Control Regulations) — the underlying
    regulatory framework
  31 CFR § 515.560–.578 — the 12 CACR general-license categories for
    travel
  https://www.state.gov/cuba-restricted-list/ — the State Department's
    parallel Cuba Restricted List of blocked entities

Cuba-specific framing:
  Unlike the Venezuela sanctions program (which is mostly built on
  Executive Orders + numbered specific licenses), the Cuba sanctions
  program is primarily REGULATORY. The CACR itself contains broad
  blanket "general licenses" embedded as named sections (515.530 etc.)
  rather than the standalone GL-NN-numbered documents OFAC issues for
  newer programs. We list both: the CACR-section-style GLs that
  authorise broad activity (the 12 travel categories, agricultural
  exports under TSRA, telecom, support for the Cuban people) AND the
  occasional standalone numbered GLs OFAC has issued for narrower
  Cuba-specific contingencies.

The site UI must always link readers back to the OFAC primary text;
this list is a navigation aid, not a legal substitute.
"""

from __future__ import annotations


GENERAL_LICENSES: list[dict] = [
    # ─────────────────────────────────────────────────────────────────
    # The 12 CACR travel general licenses — the most-used authorisations
    # in the entire Cuba sanctions program. Every US person travelling
    # to Cuba must self-attest to one of these categories.
    # ─────────────────────────────────────────────────────────────────
    {
        "number": "31 CFR § 515.560",
        "title": "General travel framework for the 12 authorised categories",
        "summary": (
            "The umbrella regulation defining the 12 categories of "
            "authorised travel-related transactions to Cuba by US "
            "persons. Tourism is NOT one of the categories — every "
            "trip must qualify under one of the named categories below."
        ),
        "expires": "Permanent regulation (subject to Treasury amendment)",
        "scope": ["travel", "framework"],
        "ofac_url": "https://www.ecfr.gov/current/title-31/subtitle-B/chapter-V/part-515/subpart-E/section-515.560",
        "context": "Read this section first before reading any of the 12 individual categories — it defines key terms (full-time schedule, recordkeeping, related transactions) that apply across all of them.",
    },
    {
        "number": "31 CFR § 515.564",
        "title": "Professional research and professional meetings in Cuba",
        "summary": "Authorises travel for professional research in any field and attendance at professional meetings — provided the research is not for personal recreation and the schedule is full-time.",
        "expires": "Permanent regulation",
        "scope": ["travel", "research", "professional"],
        "ofac_url": "https://www.ecfr.gov/current/title-31/subtitle-B/chapter-V/part-515/subpart-E/section-515.564",
        "context": "Used by academics, journalists travelling for non-news-gathering research, and professionals attending Cuban government or industry conferences (e.g. ZEDM-related, biotech, agriculture).",
    },
    {
        "number": "31 CFR § 515.565",
        "title": "Educational activities and people-to-people exchanges",
        "summary": (
            "Authorises educational travel sponsored by US academic "
            "institutions and (under certain conditions) "
            "people-to-people educational exchanges. Trump-era "
            "amendments (2019) ended individual people-to-people travel "
            "and now require all such travel to be under the auspices "
            "of a US sponsor organisation."
        ),
        "expires": "Permanent regulation (with 2019 amendments)",
        "scope": ["travel", "education", "people-to-people"],
        "ofac_url": "https://www.ecfr.gov/current/title-31/subtitle-B/chapter-V/part-515/subpart-E/section-515.565",
        "context": "Used by US universities running study-abroad and faculty-led courses in Cuba; also the legal home for licensed group educational tour operators.",
    },
    {
        "number": "31 CFR § 515.574",
        "title": "Support for the Cuban People",
        "summary": (
            "Authorises travel-related transactions and other "
            "transactions intended to provide support to the Cuban "
            "people. The traveller must engage in a full-time schedule "
            "of activities that enhance contact with the Cuban people, "
            "support civil society, or promote independent activity — "
            "and must avoid transactions with prohibited entities on "
            "the Cuba Restricted List."
        ),
        "expires": "Permanent regulation",
        "scope": ["travel", "individual", "casa-particular", "paladar"],
        "ofac_url": "https://www.ecfr.gov/current/title-31/subtitle-B/chapter-V/part-515/subpart-E/section-515.574",
        "context": (
            "By far the most common category for individual US "
            "travellers post-2017 (the only individual self-organised "
            "category that survived the Trump-era restrictions). "
            "Staying in casas particulares and eating at paladares is "
            "the canonical compliance pattern. Retain a written "
            "full-time schedule for 5 years."
        ),
    },
    {
        "number": "31 CFR § 515.563",
        "title": "Family visits to close relatives in Cuba",
        "summary": "Authorises Cuban-American and US-permanent-resident travel to visit close relatives in Cuba.",
        "expires": "Permanent regulation",
        "scope": ["travel", "family"],
        "ofac_url": "https://www.ecfr.gov/current/title-31/subtitle-B/chapter-V/part-515/subpart-E/section-515.563",
        "context": "The Cuban-American family-visit category. Frequency restrictions tightened under the Trump administration and partially relaxed under Biden (May 2022); current rules are the post-2022 framework.",
    },
    {
        "number": "31 CFR § 515.575",
        "title": "Humanitarian projects",
        "summary": "Authorises travel and related transactions for designated humanitarian projects (medical, disaster relief, etc.).",
        "expires": "Permanent regulation",
        "scope": ["travel", "humanitarian"],
        "ofac_url": "https://www.ecfr.gov/current/title-31/subtitle-B/chapter-V/part-515/subpart-E/section-515.575",
        "context": "Used by NGOs, faith-based humanitarian groups, and US medical-relief organisations.",
    },
    {
        "number": "31 CFR § 515.566",
        "title": "Religious activities in Cuba",
        "summary": "Authorises travel and related transactions for religious activities by religious organisations.",
        "expires": "Permanent regulation",
        "scope": ["travel", "religious"],
        "ofac_url": "https://www.ecfr.gov/current/title-31/subtitle-B/chapter-V/part-515/subpart-E/section-515.566",
        "context": "Used by US churches, synagogues, and faith-based delegations — historically a major travel channel.",
    },
    {
        "number": "31 CFR § 515.567",
        "title": "Public performances, clinics, workshops, athletic and other competitions, and exhibitions",
        "summary": "Authorises travel for participation in public performances, athletic competitions, clinics, workshops, and exhibitions.",
        "expires": "Permanent regulation",
        "scope": ["travel", "cultural", "athletic"],
        "ofac_url": "https://www.ecfr.gov/current/title-31/subtitle-B/chapter-V/part-515/subpart-E/section-515.567",
        "context": "Used by US sports federations, music ensembles, and exhibitors at Cuban trade fairs (FIHAV).",
    },
    {
        "number": "31 CFR § 515.561",
        "title": "Journalistic activity",
        "summary": "Authorises travel for full-time journalists employed by news-gathering organisations.",
        "expires": "Permanent regulation",
        "scope": ["travel", "journalism", "media"],
        "ofac_url": "https://www.ecfr.gov/current/title-31/subtitle-B/chapter-V/part-515/subpart-E/section-515.561",
        "context": "Used by US news organisations covering Cuban politics, economy, and culture. Cuba's MINREX-issued journalist visa is a separate Cuban-side requirement.",
    },
    {
        "number": "31 CFR § 515.562",
        "title": "Official business of the US government, foreign governments, and intergovernmental organisations",
        "summary": "Authorises travel by US government employees on official business and by representatives of intergovernmental organisations.",
        "expires": "Permanent regulation",
        "scope": ["travel", "government", "diplomatic"],
        "ofac_url": "https://www.ecfr.gov/current/title-31/subtitle-B/chapter-V/part-515/subpart-E/section-515.562",
        "context": "The US Embassy Havana, USDA, and other US-government missions operate under this authority.",
    },
    {
        "number": "31 CFR § 515.572",
        "title": "Authorised export transactions",
        "summary": "Authorises travel-related transactions necessary to support authorised exports — covering the agricultural-export industry under TSRA and certain humanitarian exports.",
        "expires": "Permanent regulation",
        "scope": ["travel", "exports", "TSRA"],
        "ofac_url": "https://www.ecfr.gov/current/title-31/subtitle-B/chapter-V/part-515/subpart-E/section-515.572",
        "context": "Used by US agricultural exporters (chicken, soy, corn, dairy via ALIMPORT) and pharmaceutical exporters travelling to negotiate or service contracts.",
    },
    {
        "number": "31 CFR § 515.576",
        "title": "Activities of private foundations or research or educational institutes",
        "summary": "Authorises travel and related transactions for the activities of private foundations or research/educational institutes that have an established interest in international relations.",
        "expires": "Permanent regulation",
        "scope": ["travel", "foundations", "research"],
        "ofac_url": "https://www.ecfr.gov/current/title-31/subtitle-B/chapter-V/part-515/subpart-E/section-515.576",
        "context": "Used by US foundations (Ford, Open Society, Brookings) and policy think-tanks running Cuba-focused programs.",
    },
    # ─────────────────────────────────────────────────────────────────
    # Non-travel CACR general licenses — the substantive sectoral
    # authorisations under which most US-Cuba commercial activity
    # actually happens.
    # ─────────────────────────────────────────────────────────────────
    {
        "number": "31 CFR § 515.578",
        "title": "Telecommunications and internet-based services",
        "summary": (
            "Authorises a broad range of telecommunications and "
            "internet-based services to support the free flow of "
            "information into, out of, and within Cuba — including "
            "internet connectivity infrastructure, internet-based "
            "platforms, and remittance-related telecoms."
        ),
        "expires": "Permanent regulation (Obama-era 2015 amendment, expanded subsequent years)",
        "scope": ["telecoms", "internet", "platforms"],
        "ofac_url": "https://www.ecfr.gov/current/title-31/subtitle-B/chapter-V/part-515/subpart-E/section-515.578",
        "context": "The compliance home for Google, AirBnb, Stripe, and other US tech platforms operating Cuba-related services. Note: ETECSA's status on the Cuba Restricted List complicates direct telecom infrastructure investment.",
    },
    {
        "number": "31 CFR § 515.582",
        "title": "Authorised exports of certain goods (independent Cuban entrepreneurs)",
        "summary": "Authorises exports of certain goods from the US to independent Cuban entrepreneurs (cuentapropistas, MIPYMES) for use in their independent economic activity, provided the goods are not destined for state-sector use.",
        "expires": "Permanent regulation (Obama-era expansion, narrowed under Trump, partially restored under Biden)",
        "scope": ["exports", "MIPYMES", "private-sector"],
        "ofac_url": "https://www.ecfr.gov/current/title-31/subtitle-B/chapter-V/part-515/subpart-E/section-515.582",
        "context": "The legal channel for US suppliers selling tools, vehicles, computers, restaurant equipment, and other inputs to Cuba's MIPYME sector. Aligns with the CACR's policy direction to support the independent (non-state) economy.",
    },
    {
        "number": "TSRA / 31 CFR § 515.533",
        "title": "Authorised agricultural and medical exports under TSRA",
        "summary": (
            "Authorises commercial sales of US agricultural commodities, "
            "medicine, and medical devices to Cuba on a cash-in-advance "
            "or third-country financing basis, under the Trade Sanctions "
            "Reform and Export Enhancement Act of 2000."
        ),
        "expires": "Permanent statutory framework",
        "scope": ["exports", "agriculture", "TSRA", "medical"],
        "ofac_url": "https://ofac.treasury.gov/sanctions-programs-and-country-information/cuba-sanctions",
        "context": "The single largest channel of legal US-Cuba commerce — chicken, soy, corn, and other ag exports routed through ALIMPORT under TSRA cash terms. The cash-in-advance restriction is the binding commercial constraint.",
    },
    {
        "number": "31 CFR § 515.570",
        "title": "Remittances to nationals of Cuba",
        "summary": "Authorises remittances from the US to Cuban nationals subject to per-quarter and per-recipient limits — relaxed by the Biden administration in May 2022.",
        "expires": "Permanent regulation (with 2022 Biden-era expansion)",
        "scope": ["remittances", "family", "humanitarian"],
        "ofac_url": "https://www.ecfr.gov/current/title-31/subtitle-B/chapter-V/part-515/subpart-E/section-515.570",
        "context": (
            "FINCIMEX (the GAESA-controlled Cuban remittance gateway) "
            "is on the Cuba Restricted List, which forced Western Union "
            "to suspend US-Cuba remittances in 2020 and reroute through "
            "non-FINCIMEX channels in 2023. Compliance teams must check "
            "the receiving-bank chain."
        ),
    },
    {
        "number": "31 CFR § 515.571",
        "title": "Certain remittances by persons subject to US jurisdiction",
        "summary": "Authorises additional categories of remittances (donative, humanitarian, support for the Cuban people, support for MIPYMES, emigration-related).",
        "expires": "Permanent regulation",
        "scope": ["remittances", "humanitarian", "MIPYMES"],
        "ofac_url": "https://www.ecfr.gov/current/title-31/subtitle-B/chapter-V/part-515/subpart-E/section-515.571",
        "context": "The CACR section under which donor-style remittances to Cuban civil society and MIPYMES are authorised. Distinct from the family-remittance limit framework in § 515.570.",
    },
    # ─────────────────────────────────────────────────────────────────
    # OFAC standalone numbered GLs and FAQs that have arisen for
    # specific Cuba-related contingencies. These are the "newer style"
    # standalone documents OFAC publishes alongside Recent Actions.
    # ─────────────────────────────────────────────────────────────────
    {
        "number": "Cuba GL 1",
        "title": "Authorising Certain Transactions Related to a Vessel Owned by a Blocked Cuban Entity",
        "summary": "Periodically issued narrow GLs authorising specific wind-down or maintenance transactions involving Cuban-owned blocked vessels (oil tankers servicing the Venezuela-Cuba corridor, GAESA-owned commercial assets).",
        "expires": "Time-limited (typically 30-90 days from issuance)",
        "scope": ["maritime", "wind-down", "vessels"],
        "ofac_url": "https://ofac.treasury.gov/recent-actions",
        "context": "Compliance teams should diary any narrow Cuba GL expiration date as a hard cut-off for blocked-counterparty exposure on a named vessel.",
    },
    {
        "number": "OFAC FAQ — Cuba Restricted List interaction",
        "title": "Interaction between CACR general licenses and the State Department's Cuba Restricted List",
        "summary": (
            "OFAC FAQs clarify that even where a CACR section authorises "
            "a category of activity (e.g. travel under § 515.574), the "
            "transaction must still avoid all named entities on the "
            "State Department's Cuba Restricted List — including most "
            "GAESA-owned hotels, marinas, rum/cigar houses, and FINCIMEX."
        ),
        "expires": "Ongoing guidance — list updated periodically",
        "scope": ["compliance", "GAESA", "Cuba-Restricted-List"],
        "ofac_url": "https://www.state.gov/cuba-restricted-list/",
        "context": "The single most-asked compliance question on the Cuba program. Even a § 515.574 'Support for the Cuban People' traveller cannot stay at a Cuba-Restricted-List-named hotel.",
    },
]


def list_general_licenses() -> list[dict]:
    return GENERAL_LICENSES
