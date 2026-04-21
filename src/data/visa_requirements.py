"""
Static curated dataset of Cuba visa and entry requirements by passport
nationality, plus current US travel-advisory level.

Authoritative sources (verify before publishing changes):
  https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories/cuba-travel-advisory.html
  https://travel.state.gov/content/travel/en/international-travel/International-Travel-Country-Information-Pages/Cuba.html
  https://www.gov.uk/foreign-travel-advice/cuba
  https://travel.gc.ca/destinations/cuba
  https://www.eeas.europa.eu/cuba_en
  https://www.minrex.gob.cu/

Cuba-specific entry concepts to keep straight:
  • "Tourist Card" (Tarjeta del Turista, formerly the visa-equivalent
    yellow/green card) is what most leisure travellers buy through
    their airline or a Cuban consulate. It is a single-entry, 30-day
    permit (90 days for Canadians) that can be extended once on-island.
  • US travellers do NOT get a Tourist Card; they need to qualify under
    one of OFAC's 12 authorized travel categories under the CACR
    (31 CFR § 515.560–.578) — "Support for the Cuban People" being by
    far the most common — and book through a US-based travel provider
    that polices that compliance. There is no "tourism" category for
    US persons.
  • "Travel" to Cuba by US persons remains general-license-authorised
    only inside those 12 categories. The narrative that "Americans can
    visit Cuba freely" is wrong. The narrative that "Americans cannot
    visit Cuba at all" is also wrong. The truth is in the categorical
    framework.
  • The US "Cuba Restricted List" (State Department, 31 CFR § 515.209)
    blocks transactions with named GAESA-affiliated hotels, marinas,
    rum/cigar/tobacco entities, etc. — a separate compliance layer on
    top of the general-license categories.
  • Cuba added a mandatory online entry form (the D'Viajeros customs +
    health declaration) in 2022. Every traveller — US or otherwise —
    must complete it within the 72 hours before arrival. The form is
    free; "official" paid versions are scams.

NOTE: The US row's `advisory_level` and `advisory_summary` are also
overridden at request time by the latest TravelAdvisoryScraper row in
the database (see server.tool_visa_requirements). Keep this dict as
the static fallback in case the scraper hasn't run yet or returns
no result.

Update whenever you confirm a policy change. The tool's UI always
links the user back to the relevant embassy / state-department page.
"""

from __future__ import annotations


# As of the most recent State Department review the US Department of
# State maintains Cuba at Level 2 ("Exercise Increased Caution"),
# citing the unexplained health incidents reported by US government
# personnel in 2017–2024 ("Havana Syndrome"), petty crime against
# tourists, and limited consular services for US citizens. This is the
# static baseline; the live page also reads from the
# TravelAdvisoryScraper output and will reflect any further changes
# automatically.
#
# The defining compliance fact for US persons is NOT the State
# Department advisory — it's the OFAC Cuban Assets Control Regulations
# (CACR) general-license categories. Any US person travelling for any
# reason must self-attest on departure (and retain records for 5 years)
# that their travel falls into one of the 12 authorised categories.
VISA_REQUIREMENTS: list[dict] = [
    {
        "country": "United States",
        "code": "US",
        # We mark "visa_required: True" for US travellers because the
        # plain-English answer is that you cannot just buy a tourist card
        # and go. The compliance answer is that you need to qualify under
        # one of the OFAC general-license categories (the most common
        # being "Support for the Cuban People" under 31 CFR § 515.574),
        # plus pay USD ~100 for a Cuba-issued Tourist Card via the
        # airline / charter at check-in.
        "visa_required": True,
        "visa_type": (
            "OFAC general-license travel category required (one of 12 "
            "categories under the CACR — typically 'Support for the "
            "Cuban People' or 'Educational/People-to-People'). "
            "PLUS a USD ~100 Cuban Tourist Card purchased through your "
            "airline at the US gate or at a Cuban consulate."
        ),
        "visa_validity": (
            "Tourist Card: 30 days, single-entry, extendable once "
            "on-island for an additional 30 days at a Cuban "
            "immigration office."
        ),
        "tourist_stay": "Up to 30 days per entry (extendable to 60).",
        # The US Embassy in Havana is the canonical reference for US
        # citizens travelling to Cuba — it tracks both the State
        # Department advisory and the OFAC general-license framework.
        "embassy_url": "https://travel.state.gov/content/travel/en/international-travel/International-Travel-Country-Information-Pages/Cuba.html",
        "advisory_level": 2,
        "advisory_summary": (
            "Exercise Increased Caution — anomalous health incidents "
            "(\"Havana Syndrome\"), petty crime, and shortages of food, "
            "medicine, fuel, and basic goods. Limited consular services "
            "for US citizens. The CACR remains the dominant compliance "
            "constraint, not the advisory level."
        ),
        "advisory_url": "https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories/cuba-travel-advisory.html",
        "investor_note": (
            "US persons (citizens, green-card holders, US-organised "
            "entities) must travel under one of the 12 OFAC "
            "general-license categories and must avoid all transactions "
            "with entities on the State Department's Cuba Restricted "
            "List (31 CFR § 515.209) — that includes a long list of "
            "GAESA-owned hotels (Meliá, Iberostar properties under "
            "Gaviota title, NH Capri, etc.), marinas, and rum/cigar "
            "houses. Maintain a written 'full-time schedule' record of "
            "Cuban-people-supporting activities and retain it for 5 "
            "years (the OFAC recordkeeping window). Cuba's classification "
            "as a State Sponsor of Terrorism (re-listed January 2021) "
            "also forecloses the ESTA visa-waiver route for any "
            "non-citizen who has visited Cuba on or after January 12, "
            "2021 — they need a full B1/B2 US visa, not ESTA."
        ),
    },
    {
        "country": "United Kingdom",
        "code": "GB",
        "visa_required": True,
        "visa_type": "Tourist Card (Tarjeta del Turista) — purchased at Cuban consulate, online via Cuba Visa Services, or at the airline check-in counter",
        "visa_validity": "30 days, single-entry, extendable once on-island for an additional 30 days",
        "tourist_stay": "Up to 30 days (extendable to 60)",
        "embassy_url": "https://www.gov.uk/foreign-travel-advice/cuba/entry-requirements",
        "advisory_level": 2,
        "advisory_summary": (
            "FCDO advises against all but essential travel to specific "
            "areas during peak hurricane season and warns of severe "
            "shortages of medicines, fuel, and basic supplies. "
            "Otherwise general travel is permitted with caution."
        ),
        "advisory_url": "https://www.gov.uk/foreign-travel-advice/cuba",
        "investor_note": (
            "British citizens need a Tourist Card and comprehensive "
            "travel insurance (mandatory under Cuban law — proof may be "
            "asked at immigration). The UK does not enforce the US "
            "embargo; UK companies operate freely under EU/UK blocking "
            "regulations against Helms-Burton extraterritoriality. "
            "The British Embassy in Havana provides full consular "
            "services, including notarial services for UK investors."
        ),
    },
    {
        "country": "Canada",
        "code": "CA",
        "visa_required": True,
        "visa_type": (
            "Tourist Card (Tarjeta del Turista) — usually included in "
            "the air-ticket price by Canadian carriers (Air Canada, "
            "Sunwing, Air Transat, WestJet)."
        ),
        # Canadians get the longest standard tourist stay of any
        # nationality — a legacy of Cuba's heavy reliance on Canadian
        # winter tourism through Varadero and Cayo Coco.
        "visa_validity": "90 days, single-entry, extendable on-island for an additional 90 days",
        "tourist_stay": "Up to 90 days (extendable to 180)",
        "embassy_url": "https://travel.gc.ca/destinations/cuba",
        "advisory_level": 2,
        "advisory_summary": (
            "Exercise a high degree of caution — shortages of food, "
            "medicine, electricity, and fuel; deteriorating "
            "infrastructure; petty crime targeting tourists in Old "
            "Havana and Vedado."
        ),
        "advisory_url": "https://travel.gc.ca/destinations/cuba",
        "investor_note": (
            "Canada is Cuba's largest single-source tourism market and "
            "Sherritt International is the largest publicly-traded "
            "foreign investor on the island (Moa nickel/cobalt joint "
            "venture). Canadian citizens enter under the most generous "
            "Tourist Card terms (90+90 days), and the Canadian Embassy "
            "in Havana provides full consular and trade-promotion "
            "services. Helms-Burton Title III lawsuits remain a residual "
            "exposure for any Canadian entity holding Cuban assets that "
            "were originally expropriated from US persons."
        ),
    },
    {
        "country": "Mexico",
        "code": "MX",
        "visa_required": True,
        "visa_type": "Tourist Card (Tarjeta del Turista) — sold by airlines (Aeroméxico, Viva Aerobús) and Cuban consulates",
        "visa_validity": "30 days, single-entry, extendable",
        "tourist_stay": "Up to 30 days (extendable to 60)",
        "embassy_url": "https://embamex.sre.gob.mx/cuba/",
        "advisory_level": 1,
        "advisory_summary": "Mexican government maintains active diplomatic and consular relations with Cuba, with no significant travel restrictions for Mexican citizens.",
        "advisory_url": "https://embamex.sre.gob.mx/cuba/",
        "investor_note": (
            "Mexico hosts the largest concentration of Cuban-American "
            "and Cuban-diaspora business intermediation outside Florida, "
            "and Mexican companies (CEMEX historically, Grupo BMV, "
            "tourism conglomerates) have long-running joint ventures "
            "with Cuban state entities. Mérida and Cancún are the "
            "default lateral routing points for US-origin shipments to "
            "Cuba that need to avoid the embargo's direct-shipment "
            "prohibition."
        ),
    },
    {
        "country": "Spain",
        "code": "ES",
        "visa_required": True,
        "visa_type": "Tourist Card (Tarjeta del Turista) — purchased at Cuban consulate or via airline (Iberia, Air Europa)",
        "visa_validity": "30 days, single-entry, extendable",
        "tourist_stay": "Up to 30 days (extendable to 60)",
        "embassy_url": "https://www.exteriores.gob.es/embajadas/lahabana",
        "advisory_level": 2,
        "advisory_summary": "Spanish foreign ministry advises caution due to shortages and infrastructure issues; full diplomatic relations maintained.",
        "advisory_url": "https://www.exteriores.gob.es/embajadas/lahabana",
        "investor_note": (
            "Spain is Cuba's third-largest trading partner and the "
            "single largest source of European foreign direct "
            "investment. Spanish hotel groups — Meliá, Iberostar, "
            "Barceló, NH — operate the bulk of Cuba's branded "
            "tourism inventory under joint-venture agreements with "
            "Cubanacán and Gaviota. The Spanish Embassy in Havana is "
            "the largest European mission and a key consular point "
            "for Cuban-Spanish dual nationals (a sizeable cohort under "
            "Spain's 'Ley de Memoria Democrática' descent rights)."
        ),
    },
    {
        "country": "European Union (Schengen)",
        "code": "EU",
        "visa_required": True,
        "visa_type": "Tourist Card (Tarjeta del Turista) — purchased at Cuban consulate or via airline",
        "visa_validity": "30 days, single-entry, extendable",
        "tourist_stay": "Up to 30 days (extendable to 60)",
        "embassy_url": "https://www.eeas.europa.eu/cuba_en",
        "advisory_level": 2,
        "advisory_summary": "EU member states broadly advise caution due to shortages of food, medicine, and fuel; the EU-Cuba Political Dialogue and Cooperation Agreement (PDCA) remains in force.",
        "advisory_url": "https://www.eeas.europa.eu/cuba_en",
        "investor_note": (
            "EU citizens travel under standard Tourist Card terms. The "
            "EU does not enforce the US embargo and the EU Blocking "
            "Statute (Council Regulation 2271/96) explicitly protects "
            "EU companies from Helms-Burton Title III claims. France, "
            "Italy, and the Netherlands maintain active investment "
            "promotion offices in Havana. Cuba's EU-funded "
            "agriculture and renewable-energy projects are concentrated "
            "in Pinar del Río, Matanzas, and Holguín."
        ),
    },
    {
        "country": "China",
        "code": "CN",
        "visa_required": True,
        "visa_type": "Tourist Card (Tarjeta del Turista) or Business visa for commercial activity",
        "visa_validity": "30-90 days depending on visa class",
        "tourist_stay": "Per visa terms",
        "embassy_url": "http://cu.china-embassy.gov.cn/",
        "advisory_level": 1,
        "advisory_summary": "Chinese government maintains full strategic and economic relations as part of Cuba's Belt and Road Initiative participation.",
        "advisory_url": "http://cu.china-embassy.gov.cn/",
        "investor_note": (
            "China is Cuba's second-largest trading partner after "
            "Venezuela and the largest creditor on the island. Chinese "
            "infrastructure investment is concentrated in "
            "telecommunications (Huawei is ETECSA's primary network "
            "vendor), the Mariel ZED port and logistics zone, and "
            "renewable energy. State-to-state arrangements smooth FX "
            "repatriation friction for Chinese SOEs that would be "
            "unworkable for Western investors operating under the "
            "embargo."
        ),
    },
    {
        "country": "Russia",
        "code": "RU",
        "visa_required": False,
        "visa_type": "Visa-free for stays of up to 90 days (since 2024 bilateral agreement)",
        "visa_validity": "Tourist entry stamp issued at port of entry",
        "tourist_stay": "Up to 90 days",
        "embassy_url": "https://cuba.mid.ru/",
        "advisory_level": 1,
        "advisory_summary": "Russian government maintains a strategic relationship with Havana, including resumed direct flights to Varadero and Havana.",
        "advisory_url": "https://cuba.mid.ru/",
        "investor_note": (
            "Russia is a strategic but secondary economic partner — "
            "active in oil supply (since 2023, partially replacing "
            "lapsed Venezuelan crude shipments), sovereign-debt "
            "rescheduling, and military-technical cooperation. "
            "Secondary-sanctions risk for any non-Russian co-investor "
            "is acute given OFAC's expanded Russia-program "
            "enforcement since 2022."
        ),
    },
    {
        "country": "United Arab Emirates",
        "code": "AE",
        "visa_required": True,
        "visa_type": "Tourist Card or Business visa via Cuban consulate",
        "visa_validity": "30 days, extendable",
        "tourist_stay": "Up to 30 days (extendable to 60)",
        "embassy_url": "https://www.mofa.gov.ae/en/missions/uae-missions-abroad",
        "advisory_level": 1,
        "advisory_summary": "UAE government maintains diplomatic and trade relations.",
        "advisory_url": "https://www.mofa.gov.ae/en/missions/uae-missions-abroad",
        "investor_note": (
            "Dubai has emerged as a meaningful intermediation hub for "
            "Cuba-related trade structuring, particularly for "
            "remittance corridors and dual-currency settlements that "
            "would face correspondent-banking friction in USD or EUR. "
            "DP World operates the Mariel container terminal under a "
            "long-term concession with the Cuban government."
        ),
    },
    {
        "country": "Other (please confirm with embassy)",
        "code": "OTHER",
        "visa_required": True,
        "visa_type": "Most nationalities require a Tourist Card; some (Russia, Antigua, Saint Kitts) are visa-free",
        "visa_validity": "Confirm with the nearest Cuban embassy or consulate",
        "tourist_stay": "Varies",
        "embassy_url": "https://www.minrex.gob.cu/",
        "advisory_level": None,
        "advisory_summary": "Check your home country's foreign affairs ministry for the current advisory level.",
        "advisory_url": "https://www.minrex.gob.cu/",
        "investor_note": (
            "Always confirm visa status, validity, and the current "
            "published advisory level with both the Cuban diplomatic "
            "mission in your country and your home country's foreign "
            "affairs ministry before booking travel. All travellers — "
            "every nationality — must also complete the free online "
            "D'Viajeros customs and health declaration within the 72 "
            "hours before arrival in Cuba."
        ),
    },
]


def list_visa_requirements() -> list[dict]:
    return VISA_REQUIREMENTS
