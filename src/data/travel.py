"""
Static curated dataset for the Cuban Insights Travel hub.

Audience: foreign business travellers, journalists, researchers, NGO and
diplomatic staff visiting Havana. Most US-based business travel to Cuba
is governed by the OFAC Cuban Assets Control Regulations (CACR) general-
license categories — this hub assumes the reader has already chosen a
qualifying category (typically "Support for the Cuban People" or
"Educational/People-to-People") and needs operational logistics.

Authoritative / source-of-truth references used to compile this dataset:
- US State Department Travel Advisory & OSAC Havana crime reports
  https://travel.state.gov/.../cuba-travel-advisory.html
  https://www.osac.gov/Country/Cuba
- UK FCDO Foreign Travel Advice for Cuba
  https://www.gov.uk/foreign-travel-advice/cuba
- Canadian Government — Cuba travel advice
  https://travel.gc.ca/destinations/cuba
- MINREX (Cancillería de Cuba) consular directory
  https://www.minrex.gob.cu/
- Embassy phone & address records published on each mission's official
  website (cross-checked against EmbassyPages and IATA timatic records).
- State Department's Cuba Restricted List (31 CFR § 515.209) — the
  blocked-properties list that determines which Havana hotels US persons
  may not stay in.
- Public listings from the major hotel groups (Meliá, Iberostar,
  Memories Resorts, NH, Kempinski) and TripAdvisor / Lonely Planet
  Havana guides.

IMPORTANT FRAMING (mirrored on the live page):
We do not personally vet hotels, drivers, casas particulares, restaurants
or assistance providers. Entries reflect operations and reputation as
known to the international business-travel and OFAC-compliance community
at time of publication. Conditions on the island change quickly —
particularly around fuel, electricity, and US-permitted transactions —
so always reconfirm a service is operating, the current pricing, the
current Cuba Restricted List status, and the current security posture
before relying on it.
"""

from __future__ import annotations


# ----------------------------------------------------------------------------
# 1) Travel advisory snapshot (also overridden live by the State Dept scraper)
# ----------------------------------------------------------------------------
TRAVEL_ADVISORY_SUMMARY = {
    "level": 2,
    "label": "Exercise Increased Caution",
    "issued": "2026 (current State Department posting)",
    "summary": (
        "The US State Department maintains Cuba at Level 2 (Exercise "
        "Increased Caution) due to anomalous health incidents reported "
        "by US government personnel (\"Havana Syndrome\"), petty crime "
        "targeting tourists, and severe shortages of food, medicine, "
        "fuel, and basic goods that have intensified during the 2024–"
        "2026 economic crisis. The defining compliance constraint for "
        "US travellers is NOT the advisory level but the Cuban Assets "
        "Control Regulations (CACR, 31 CFR Part 515): every US person "
        "must travel under one of the 12 OFAC general-license "
        "categories and avoid all transactions with entities on the "
        "State Department's Cuba Restricted List (31 CFR § 515.209). "
        "The US Embassy in Havana provides emergency consular "
        "support; routine non-immigrant visa services for Cuban "
        "nationals were partially restored in 2023."
    ),
    "primary_url": "https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories/cuba-travel-advisory.html",
}


# ----------------------------------------------------------------------------
# 1b) Embassy traveller-registration programs
# ----------------------------------------------------------------------------
# Free, government-operated traveller-registration systems. Once enrolled,
# the foreign ministry can (a) contact you in a crisis (mass evacuation,
# family emergency, hurricane), and (b) push real-time security alerts
# to your phone or email during the trip. This is the single most
# important pre-departure action after booking your flight — costs
# nothing, takes about five minutes.
EMBASSY_REGISTRATION_PROGRAMS: list[dict] = [
    {
        "country": "United States",
        "program": "STEP",
        "long_name": "Smart Traveler Enrollment Program",
        "url": "https://step.state.gov/",
        "blurb": "Run by the US State Department. Enrol your trip and your contact info; receive State Department alerts and become locatable in a crisis. Especially important for Cuba given the limited US consular footprint and hurricane-season risk.",
    },
    {
        "country": "United Kingdom",
        "program": "GOV.UK email alerts",
        "long_name": "FCDO Foreign Travel Advice subscription",
        "url": "https://www.gov.uk/foreign-travel-advice/cuba",
        "blurb": "The FCDO retired LOCATE in 2013; the modern equivalent is to subscribe to email/SMS alerts on the Cuba travel-advice page.",
    },
    {
        "country": "Canada",
        "program": "ROCA",
        "long_name": "Registration of Canadians Abroad",
        "url": "https://travel.gc.ca/travelling/registration",
        "blurb": "Free service from Global Affairs Canada. Particularly relevant given Canada's status as Cuba's largest source-tourism market — the Canadian Embassy in Havana will use this to reach you in an emergency.",
    },
    {
        "country": "Australia",
        "program": "Smartraveller",
        "long_name": "DFAT Smartraveller subscriptions",
        "url": "https://www.smartraveller.gov.au/destinations/americas/cuba",
        "blurb": "Subscribe to email/SMS updates for the Cuba advisory; DFAT will use your registered details to reach you in a consular crisis. Australia's nearest mission is in Mexico City.",
    },
    {
        "country": "Germany",
        "program": "Elefand",
        "long_name": "Elektronische Erfassung von Deutschen im Ausland",
        "url": "https://krisenvorsorgeliste.diplo.de/",
        "blurb": "Auswärtiges Amt's crisis-preparedness register for German citizens abroad.",
    },
    {
        "country": "France",
        "program": "Ariane",
        "long_name": "Fil d'Ariane",
        "url": "https://pastel.diplomatie.gouv.fr/fildariane/dyn/public/login.html",
        "blurb": "Quai d'Orsay's free traveller-registration system. Receive security alerts and be reachable by the consulate.",
    },
    {
        "country": "Italy",
        "program": "Dove Siamo Nel Mondo",
        "long_name": "Italian Foreign Ministry traveller register",
        "url": "https://www.dovesiamonelmondo.it/",
        "blurb": "Free service from the Ministero degli Affari Esteri for Italian citizens abroad.",
    },
    {
        "country": "Spain",
        "program": "Registro de Viajeros",
        "long_name": "Spanish consular traveller register",
        "url": "https://registroviajeros.exteriores.gob.es/",
        "blurb": "MAEC's free pre-travel registration for Spanish nationals. Especially important for the large Spanish-Cuban dual-national community.",
    },
    {
        "country": "Netherlands",
        "program": "BZ Information Service",
        "long_name": "Travel advice subscription + 24/7 contact centre",
        "url": "https://www.nederlandwereldwijd.nl/reisadvies/cuba",
        "blurb": "Subscribe to Cuba travel-advice updates; BZ's 24/7 contact centre (+31 247 247 247) is the Dutch consular crisis line.",
    },
    {
        "country": "Switzerland",
        "program": "Travel Admin app",
        "long_name": "EDA Travel Admin",
        "url": "https://www.eda.admin.ch/eda/en/fdfa/living-abroad/travel-advice.html",
        "blurb": "EDA's mobile app lets Swiss citizens register a trip and receive country-specific alerts.",
    },
]


# ----------------------------------------------------------------------------
# 2) Embassies & consulates in Havana
# ----------------------------------------------------------------------------
# Phone numbers are listed in international format. Cuba country code is
# +53; Havana city code is (7) for landlines; mobile prefixes start with
# +53 5xx (ETECSA's Cubacel network). Embassies are concentrated in two
# districts: most diplomatic missions sit in Miramar (Playa
# municipality) — the canonical "embassy district" — with a few historic
# missions in Vedado.
EMBASSIES: list[dict] = [
    {
        "country": "United States",
        "city": "Havana",
        "address": "Calzada entre L y M, Vedado, Habana 10400",
        "phone": "+53 7 839-4100",
        "after_hours": "+53 7 839-4100 (24h emergency line) · 1-888-407-4747 (US/Canada toll-free)",
        "email": "ACShavana@state.gov",
        "website": "https://cu.usembassy.gov/",
        "notes": (
            "Reopened in 2015, scaled back significantly after the "
            "2017 \"Havana Syndrome\" health incidents drove a near-"
            "total drawdown of US personnel. Limited routine consular "
            "services for non-immigrant visas resumed in 2023; "
            "immigrant-visa processing for Cuban nationals continues "
            "to be split between Havana and the US Embassy in "
            "Georgetown, Guyana. Provides 24/7 emergency consular "
            "services to US citizens in Cuba."
        ),
    },
    {
        "country": "United Kingdom",
        "city": "Havana",
        "address": "Calle 34, No. 702, esquina a 7ma Avenida, Miramar, Playa, Habana",
        "phone": "+53 7 214-2200",
        "after_hours": "+53 7 214-2200 (24h emergency line)",
        "email": "embajadabritanica.lahabana@fcdo.gov.uk",
        "website": "https://www.gov.uk/world/organisations/british-embassy-cuba",
        "notes": "Active mission in Miramar; full consular services for UK nationals; provides notarial services for UK investors.",
    },
    {
        "country": "Spain",
        "city": "Havana",
        "address": "Cárcel No. 51, esquina a Zulueta, Habana Vieja, Habana",
        "phone": "+53 7 866-8025",
        "after_hours": "+53 5 280-3500 (consular emergency mobile)",
        "email": "emb.lahabana@maec.es",
        "website": "https://www.exteriores.gob.es/embajadas/lahabana",
        "notes": "Largest European mission in Havana; serves the very large Spanish-Cuban dual-national community ('Ley de Memoria Democrática' descent rights). Located in Habana Vieja.",
    },
    {
        "country": "France",
        "city": "Havana",
        "address": "Calle 14, No. 312, entre 3ra y 5ta Avenida, Miramar, Playa, Habana",
        "phone": "+53 7 201-3131",
        "after_hours": "+33 1 53 59 11 00 (Quai d'Orsay 24/7 crisis centre)",
        "email": "service.consulaire.havane-amba@diplomatie.gouv.fr",
        "website": "https://cu.ambafrance.org/",
        "notes": "Active embassy with full consular section in the Miramar diplomatic corridor.",
    },
    {
        "country": "Germany",
        "city": "Havana",
        "address": "Calle 13, No. 652, esquina a Calle B, Vedado, Habana",
        "phone": "+53 7 833-2569",
        "after_hours": "+49 30 5000-2000 (Auswärtiges Amt 24/7 crisis line)",
        "email": "info@havanna.diplo.de",
        "website": "https://havanna.diplo.de/",
        "notes": "Active mission; routine services available by appointment.",
    },
    {
        "country": "Italy",
        "city": "Havana",
        "address": "5ta Avenida, No. 4006, entre 40 y 42, Miramar, Playa, Habana",
        "phone": "+53 7 204-5615",
        "after_hours": "+39 06 36225 (Unità di Crisi Roma)",
        "email": "ambasciata.havana@esteri.it",
        "website": "https://amblavana.esteri.it/",
        "notes": "Active embassy in the Miramar diplomatic corridor.",
    },
    {
        "country": "Canada",
        "city": "Havana",
        "address": "Calle 30, No. 518, esquina a 7ma Avenida, Miramar, Playa, Habana",
        "phone": "+53 7 204-2516",
        "after_hours": "+1 613 996-8885 (Ottawa Emergency Watch)",
        "email": "havan@international.gc.ca",
        "website": "https://www.international.gc.ca/country-pays/cuba/index.aspx?lang=eng",
        "notes": "Full embassy in Miramar; serves Cuba's largest source-tourism market and consular services for Canadians injured / hospitalised at the beach resorts (Varadero, Cayo Coco, Cayo Santa María).",
    },
    {
        "country": "Mexico",
        "city": "Havana",
        "address": "Calle 12, No. 518, esquina a 7ma Avenida, Miramar, Playa, Habana",
        "phone": "+53 7 204-2553",
        "after_hours": "+52 55 3686-5100 (SRE Mexico City)",
        "email": "embamexcuba@sre.gob.mx",
        "website": "https://embamex.sre.gob.mx/cuba/",
        "notes": "Active embassy; key consular point for Mexican nationals and for Mexico's role as default lateral routing hub for Cuba-related trade.",
    },
    {
        "country": "Brazil",
        "city": "Havana",
        "address": "Calle 16, No. 503, entre 5ta y 7ma Avenida, Miramar, Playa, Habana",
        "phone": "+53 7 204-2139",
        "after_hours": "+55 61 2030-1000 (Itamaraty Brasília)",
        "email": "habana@itamaraty.gov.br",
        "website": "http://habana.itamaraty.gov.br/",
        "notes": "Active full embassy; key regional partner.",
    },
    {
        "country": "Netherlands",
        "city": "Havana",
        "address": "Calle 8, No. 307, entre 3ra y 5ta Avenida, Miramar, Playa, Habana",
        "phone": "+53 7 204-2511",
        "after_hours": "+31 247 247 247 (24/7 BZ Contact Centre, Netherlands)",
        "email": "hav@minbuza.nl",
        "website": "https://www.netherlandsworldwide.nl/countries/cuba",
        "notes": "Active; also serves Dutch citizens transiting from Aruba/Curaçao/Bonaire — a common arrival vector.",
    },
    {
        "country": "Switzerland",
        "city": "Havana",
        "address": "5ta Avenida, No. 2005, entre 20 y 22, Miramar, Playa, Habana",
        "phone": "+53 7 204-2611",
        "after_hours": "+41 800 24-7 365 (Helpline EDA, Bern)",
        "email": "havanna@eda.admin.ch",
        "website": "https://www.eda.admin.ch/havanna",
        "notes": "Active embassy; from 1961 to 2015 the Swiss mission also served as the US Interests Section in Havana — a deep institutional memory of the bilateral.",
    },
]


# ----------------------------------------------------------------------------
# 3) Hotels frequently used by international business travellers
# ----------------------------------------------------------------------------
# Selection criteria: international brand or long-established Cuban
# brand operating continuously, located in safer zones (Miramar /
# Playa, Vedado, Habana Vieja core), with concierge desks that
# routinely handle airport transfers and corporate-traveller logistics.
#
# CRITICAL US-COMPLIANCE FLAG: Many of Havana's branded hotels operate
# under joint-venture agreements with Cubanacán / Gaviota / GAESA and
# appear on the State Department's Cuba Restricted List (31 CFR §
# 515.209) — which prohibits US-person transactions. We tag each hotel
# with `cuba_restricted_list` so US travellers can self-screen. This
# list changes — always cross-check with the live State Department PDF
# at https://www.state.gov/cuba-restricted-list/ before booking.
HOTELS: list[dict] = [
    {
        "name": "Meliá Habana",
        "neighborhood": "Miramar (Playa)",
        "tier": "5★ international",
        "phone": "+53 7 204-8500",
        "address": "3ra Avenida entre 76 y 80, Miramar, Playa, Habana",
        "url": "https://www.melia.com/en/hotels/cuba/havana/melia-habana/",
        "cuba_restricted_list": True,
        "why_listed": (
            "Spanish Meliá brand; default conference hotel for the foreign-investor "
            "and diplomatic circuit in Miramar. Operated under JV with Cubanacán. "
            "Listed on the Cuba Restricted List — NOT bookable by US persons."
        ),
    },
    {
        "name": "Iberostar Selection Habana Riviera",
        "neighborhood": "Vedado (Malecón)",
        "tier": "5★ international",
        "phone": "+53 7 836-4051",
        "address": "Paseo y Malecón, Vedado, Habana",
        "url": "https://www.iberostar.com/en/hotels/havana/iberostar-selection-habana-riviera/",
        "cuba_restricted_list": True,
        "why_listed": (
            "Restored Meyer Lansky-era landmark on the Malecón; Iberostar brand "
            "operated under JV with the Cuban government. Listed on the Cuba "
            "Restricted List — NOT bookable by US persons."
        ),
    },
    {
        "name": "Kempinski Hotel Manzana La Habana",
        "neighborhood": "Habana Vieja (next to the Capitolio)",
        "tier": "5★ international",
        "phone": "+53 7 869-9100",
        "address": "Calle San Rafael, entre Monserrate y Zulueta, Habana Vieja",
        "url": "https://www.kempinski.com/en/hotel-manzana-la-habana/",
        "cuba_restricted_list": True,
        "why_listed": (
            "Historic Manzana de Gómez building; first European luxury operator in "
            "Habana Vieja. Operated under contract with Gaviota. Listed on the "
            "Cuba Restricted List — NOT bookable by US persons."
        ),
    },
    {
        "name": "Hotel Nacional de Cuba",
        "neighborhood": "Vedado (Malecón)",
        "tier": "5★ historic",
        "phone": "+53 7 836-3564",
        "address": "Calle 21 y O, Vedado, Habana",
        "url": "https://www.hotelnacionaldecuba.com/",
        "cuba_restricted_list": True,
        "why_listed": (
            "Iconic 1930s landmark on the Malecón; operated by Cubanacán. Mafia-era "
            "history (Havana Conference 1946). Listed on the Cuba Restricted List "
            "— NOT bookable by US persons. Tour visits to the public areas, lobby "
            "bar and Salón de la Fama remain culturally significant."
        ),
    },
    {
        "name": "Memories Miramar Habana",
        "neighborhood": "Miramar (Playa)",
        "tier": "4★ international",
        "phone": "+53 7 204-3584",
        "address": "5ta Avenida y 72, Miramar, Playa, Habana",
        "url": "https://www.memoriesresorts.com/en/resort/memories-miramar-havana",
        "cuba_restricted_list": True,
        "why_listed": (
            "Operated by Sunwing's Memories Resorts brand under JV with Cubanacán. "
            "Convention facilities; popular with Canadian business travellers. "
            "Listed on the Cuba Restricted List — NOT bookable by US persons."
        ),
    },
    {
        "name": "Hotel NH Capri La Habana",
        "neighborhood": "Vedado",
        "tier": "4★ international",
        "phone": "+53 7 839-7200",
        "address": "Calle 21, entre N y O, Vedado, Habana",
        "url": "https://www.nh-hotels.com/hotel/nh-capri-la-habana",
        "cuba_restricted_list": True,
        "why_listed": (
            "Restored Capri (1957) under NH Hotel Group management. Listed on the "
            "Cuba Restricted List — NOT bookable by US persons."
        ),
    },
    {
        "name": "Casas Particulares (private B&Bs in Vedado / Habana Vieja / Miramar)",
        "neighborhood": "Across central Havana",
        "tier": "Private homestay",
        "phone": "Varies — book via Airbnb, Cuba Junky, or direct WhatsApp",
        "address": "Multiple",
        "url": "https://www.airbnb.com/s/Havana--Cuba/homes",
        "cuba_restricted_list": False,
        "why_listed": (
            "Casas particulares are licensed private homestays operated by Cuban "
            "MIPYMES / cuentapropistas — NOT GAESA-controlled. They are the "
            "OFAC-compliant accommodation for US travellers under the 'Support "
            "for the Cuban People' general license (31 CFR § 515.574), and "
            "supporting independent Cuban entrepreneurs is itself a justifying "
            "activity. The best Vedado / Habana Vieja / Miramar casas are "
            "operationally comparable to a small boutique hotel."
        ),
    },
    {
        "name": "Hotel Saratoga (closed since May 2022 explosion)",
        "neighborhood": "Habana Vieja",
        "tier": "Closed",
        "phone": "—",
        "address": "Paseo del Prado, esquina a Dragones, Habana Vieja",
        "url": "https://www.hotel-saratoga.com/",
        "cuba_restricted_list": True,
        "why_listed": (
            "Listed for awareness only — the Hotel Saratoga (Gaviota / Habaguanex) "
            "was destroyed by a gas explosion on 6 May 2022 and remains closed "
            "for reconstruction. Listed on the Cuba Restricted List."
        ),
    },
]


# ----------------------------------------------------------------------------
# 4) Restaurants
# ----------------------------------------------------------------------------
# Restricted to well-established places inside the safer central
# corridor (Miramar, Vedado, Habana Vieja core, Playa). We deliberately
# emphasise paladares (privately-owned restaurants licensed under
# cuentapropismo / MIPYME law) — they are independently owned, generally
# CACR-compliant for US persons under the Support for the Cuban People
# general license, and consistently of higher culinary quality than the
# state-run alternatives.
RESTAURANTS: list[dict] = [
    {
        "name": "La Guarida",
        "cuisine": "Cuban / fine-dining paladar",
        "neighborhood": "Centro Habana",
        "phone": "+53 7 866-9047",
        "url": "https://laguarida.com/",
        "notes": (
            "The most internationally-known paladar in Havana, set in a "
            "crumbling Centro Habana mansion (the Fresa y Chocolate film "
            "location). Reservations weeks ahead. Privately owned — "
            "OFAC-compliant for US persons under the Support for the "
            "Cuban People general license."
        ),
    },
    {
        "name": "El Cocinero",
        "cuisine": "Mediterranean / Cuban paladar",
        "neighborhood": "Vedado (next to Fábrica de Arte Cubano)",
        "phone": "+53 7 832-2355",
        "url": "https://elcocinerocuba.com/",
        "notes": (
            "Rooftop restaurant in a converted peanut-oil factory smokestack, "
            "co-located with FAC. Default after-hours dinner spot for the "
            "diplomatic and cultural circuit. Privately owned."
        ),
    },
    {
        "name": "La Fontana",
        "cuisine": "Cuban / steakhouse paladar",
        "neighborhood": "Miramar (Playa)",
        "phone": "+53 7 202-8337",
        "url": "https://www.facebook.com/LaFontanaHabana/",
        "notes": "Long-running Miramar paladar; a default dinner location for foreign-business meetings. Privately owned.",
    },
    {
        "name": "Doña Eutimia",
        "cuisine": "Traditional Cuban paladar",
        "neighborhood": "Habana Vieja (Catedral)",
        "phone": "+53 7 861-1332",
        "url": "https://www.facebook.com/DonaEutimia/",
        "notes": "Tucked in an alley off Plaza de la Catedral; canonical ropa vieja and lechón asado. Reservations essential. Privately owned.",
    },
    {
        "name": "Río Mar",
        "cuisine": "Seafood paladar",
        "neighborhood": "Miramar (Playa, on the river mouth)",
        "phone": "+53 7 209-4838",
        "url": "https://www.facebook.com/riomarpaladar/",
        "notes": "Riverside seafood paladar; popular with the embassy and JV-investor community. Privately owned.",
    },
    {
        "name": "San Cristóbal Paladar",
        "cuisine": "Cuban paladar",
        "neighborhood": "Centro Habana",
        "phone": "+53 7 867-9109",
        "url": "https://www.facebook.com/SanCristobalPaladar/",
        "notes": "Antique-stuffed dining rooms in a Centro Habana townhouse; hosted Barack Obama during his 2016 visit. Privately owned.",
    },
    {
        "name": "Café Laurent",
        "cuisine": "Cuban / international paladar",
        "neighborhood": "Vedado (penthouse)",
        "phone": "+53 7 832-6890",
        "url": "https://www.cafelaurent.com/",
        "notes": "Penthouse paladar with Vedado rooftop views; reliable lunch / dinner option for solo business travellers. Privately owned.",
    },
    {
        "name": "Sloppy Joe's Bar (state-run)",
        "cuisine": "American-bar / restaurant",
        "neighborhood": "Habana Vieja (Animas y Zulueta)",
        "phone": "+53 7 866-7157",
        "url": "https://www.facebook.com/SloppyJoesHavana/",
        "notes": (
            "Restored 1917 landmark bar (closed 1965, reopened 2013) operated "
            "by Habaguanex / Gaviota. Cultural-history value; US persons "
            "should note this is a state-run establishment under GAESA's "
            "tourism arm — verify current Cuba Restricted List status."
        ),
    },
]


# ----------------------------------------------------------------------------
# 5) Hospitals & medical providers commonly used by foreigners
# ----------------------------------------------------------------------------
# Cuba operates a two-tier health system. Public hospitals are for Cuban
# nationals (the medical-tourism / "salud pública" system is exceptional
# in primary care but constrained in supplies). Foreigners are routed to
# the Servicios Médicos Cubanos (SMC) network, with the Clínica Cira
# García in Miramar being the canonical hospital for diplomats and
# foreign business travellers. Travel insurance covering Cuba is
# MANDATORY under Cuban entry law — proof may be requested at
# immigration. Most US-issued policies do NOT cover Cuba; verify
# explicitly before departure.
MEDICAL_PROVIDERS: list[dict] = [
    {
        "name": "Clínica Central Cira García",
        "type": "Private hospital for foreigners (SMC network)",
        "neighborhood": "Miramar (Playa)",
        "phone": "+53 7 204-2811",
        "url": "https://www.smcsalud.cu/cira-garcia/",
        "notes": "The default hospital for diplomats, foreign investors, and tourists. Full ER, ICU, surgery, dental. International billing in convertible currency.",
    },
    {
        "name": "Hospital Hermanos Ameijeiras",
        "type": "Tertiary referral hospital (SMC for foreigners)",
        "neighborhood": "Centro Habana (Malecón)",
        "phone": "+53 7 877-6053",
        "url": "https://www.hospitalameijeiras.sld.cu/",
        "notes": "Cuba's premier tertiary-care hospital; cardiology, neurology, oncology, advanced surgery. Foreigners admitted via the international patient desk.",
    },
    {
        "name": "Clínica Internacional Camilo Cienfuegos",
        "type": "Private hospital for foreigners (SMC network)",
        "neighborhood": "Vedado",
        "phone": "+53 7 833-2811",
        "url": "https://www.smcsalud.cu/",
        "notes": "Vedado-based international clinic; convenient for visitors staying in Vedado hotels.",
    },
    {
        "name": "Asistur (Asistencia al Turista)",
        "type": "State traveller-assistance company (24/7)",
        "neighborhood": "Habana Vieja (Paseo del Prado 254)",
        "phone": "+53 7 866-4499 / +53 7 866-8527",
        "url": "https://www.asistur.cu/",
        "notes": (
            "Cuba's state-run 24/7 traveller-assistance service. Coordinates "
            "medical care, repatriation, lost documents, translation, and "
            "insurance liaison. The first call for any in-country medical or "
            "logistics emergency that doesn't require an ambulance dispatch."
        ),
    },
    {
        "name": "International SOS",
        "type": "Medical & security assistance (membership)",
        "neighborhood": "Global (regional hub: Mexico City)",
        "phone": "+1 215 942-8478 (Philadelphia 24/7 Assistance Centre)",
        "url": "https://www.internationalsos.com/",
        "notes": "Membership-based travel medical and security assistance; coordinates evacuation if required (typically to Miami, Cancún, or Mexico City).",
    },
]


# ----------------------------------------------------------------------------
# 6) Ground transport: airport transfers, drivers
# ----------------------------------------------------------------------------
# Havana's transport situation is dominated by chronic fuel shortages
# and an ageing fleet. The single most important rule is: pre-book your
# airport transfer through your hotel or casa particular host. The
# canonical airport queue at HAV Terminal 3 is reliable but the
# language barrier and currency negotiation create friction.
GROUND_TRANSPORT: list[dict] = [
    {
        "name": "Hotel concierge / casa particular host airport transfer",
        "type": "Recommended default",
        "phone": "Book via your hotel's reservation desk or your casa host's WhatsApp",
        "notes": (
            "All major hotels and most casas particulares can pre-arrange a "
            "marked vehicle for the HAV ↔ Havana transfer (~25-40 min, "
            "depending on traffic and airport gate). Quote your flight number "
            "on booking. Default cost in 2026 is roughly USD 25-40 each way "
            "for a standard sedan."
        ),
        "url": None,
    },
    {
        "name": "Cubataxi (state-run radio dispatch)",
        "type": "State taxi company",
        "phone": "+53 7 855-5555 (Havana radio dispatch)",
        "notes": (
            "Cuba's state-run radio-dispatched taxi service. Reliable and "
            "metered; price quoted in CUP or USD. Slower than a private "
            "transfer but the safer default for unannounced trips."
        ),
        "url": None,
    },
    {
        "name": "Almendrón (classic-car shared taxi)",
        "type": "Shared route taxis",
        "phone": "Hail on the street along fixed routes",
        "notes": (
            "The iconic 1950s American-car shared taxis run fixed routes "
            "along major Havana arteries (Vedado-Centro, Centro-Habana "
            "Vieja, Vedado-Miramar) at fixed peso fares (typically 50–100 "
            "CUP per leg). Useful for urban hops, NOT for the airport "
            "or for late-night use."
        ),
        "url": None,
    },
    {
        "name": "Cubacar / Havanautos / Rex (state-run car rental)",
        "type": "Self-drive rental",
        "phone": "+53 7 835-0000 (Cubacar central reservations)",
        "notes": (
            "Three state-run car-rental brands (all subsidiaries of "
            "Transtur). Inventory and pricing are constrained — book "
            "weeks ahead. Fuel-station availability is the binding "
            "constraint for road trips outside Havana; queue times of 4–8 "
            "hours have been routine since 2023. Not recommended for "
            "first-time visitors."
        ),
        "url": "https://www.cubacar-rentals.com/",
    },
    {
        "name": "Yutong tour buses (Transtur / Viazul)",
        "type": "Long-distance coach",
        "phone": "+53 7 881-1413 (Viazul reservations)",
        "notes": (
            "Viazul is the foreigner-targeted long-distance bus network "
            "covering Havana–Viñales, Havana–Trinidad, Havana–Santiago. "
            "Books out weeks ahead in high season (Dec–Mar)."
        ),
        "url": "https://www.viazul.com/",
    },
]


# ----------------------------------------------------------------------------
# 7) Corporate security advisory & assistance providers
# ----------------------------------------------------------------------------
# Cuba does not have an active corporate kidnap or active-shooter risk
# profile comparable to other Latin American capitals. The dominant
# operational risks for foreign business travellers are: anomalous
# health incidents (the unresolved "Havana Syndrome" cluster); petty
# crime in tourist zones; severe shortages of food, medicine, fuel,
# and electricity; and the always-present compliance overhead of
# operating around the embargo. The list below reflects providers that
# either operate medical and crisis assistance (the dominant need) or
# political-risk advisory services with active Cuba coverage.
SECURITY_FIRMS: list[dict] = [
    {
        "name": "International SOS",
        "type": "Medical + security assistance (membership)",
        "url": "https://www.internationalsos.com/",
        "phone": "+1 215 942-8478 (Philadelphia 24/7 Assistance Centre)",
        "notes": (
            "Combined medical and security membership service with "
            "established Cuba medical-evacuation routing (typically to "
            "Cancún, Mexico City, or Miami). The most useful single "
            "membership for any traveller without standing corporate "
            "cover."
        ),
    },
    {
        "name": "Asistur",
        "type": "Cuban state traveller-assistance (24/7)",
        "url": "https://www.asistur.cu/",
        "phone": "+53 7 866-4499 / +53 7 866-8527",
        "notes": (
            "Cuba's state-run 24/7 traveller-assistance service. The "
            "in-country first-call for medical, logistics, and document "
            "emergencies. Will coordinate hospital admission, payment "
            "translation, insurance liaison, and ground transport."
        ),
    },
    {
        "name": "Control Risks",
        "type": "Corporate political-risk advisory",
        "url": "https://www.controlrisks.com/",
        "phone": "+1 202 449-3327 (Washington DC office)",
        "notes": (
            "Global political-risk and security consultancy with active "
            "Cuba country coverage. Standard engagements include "
            "pre-travel briefings, OFAC compliance overlay, in-country "
            "fixer arrangement, and crisis support."
        ),
    },
    {
        "name": "Crisis24 (Garda World)",
        "type": "Security advisory & assistance",
        "url": "https://crisis24.garda.com/",
        "phone": "+1 877 484-1610 (24/7 Operations Center)",
        "notes": "Provides journey management and in-country security support throughout Latin America including Cuba.",
    },
    {
        "name": "OSAC (US State Department)",
        "type": "Free public-private intelligence sharing",
        "url": "https://www.osac.gov/Country/Cuba",
        "phone": "Membership via osac.gov",
        "notes": (
            "Free for any US-incorporated company. Publishes the most current "
            "Havana Crime & Safety Report and circulates same-day security "
            "alerts. Read this before any trip."
        ),
    },
]


# ----------------------------------------------------------------------------
# 8) Communications: SIM cards, eSIM, internet
# ----------------------------------------------------------------------------
# Cuba's telecoms are an ETECSA monopoly (the state operator). Foreign
# travellers face two structural realities: (1) ETECSA is on the State
# Department's Cuba Restricted List for US persons, so a US person
# buying a local SIM is a CACR compliance grey area best avoided —
# eSIMs from non-Cuban resellers are the recommended workaround;
# (2) home-internet penetration is low and Wi-Fi is a per-hour
# pre-paid product almost everywhere except modern hotels.
COMMUNICATIONS: list[dict] = [
    {
        "topic": "Local SIM cards (Cubacel / ETECSA)",
        "detail": (
            "ETECSA is the state telecom monopoly. Cubacel SIMs are sold at "
            "ETECSA offices (passport required), at HAV airport, and at "
            "some hotels. NOTE for US persons: ETECSA appears on the State "
            "Department's Cuba Restricted List, so direct purchase by US "
            "persons is a CACR compliance grey area — most US-compliant "
            "travel providers route around it via eSIM."
        ),
    },
    {
        "topic": "eSIM (recommended for short trips)",
        "detail": (
            "Airalo and Holafly both sell Cuba eSIM data plans that activate "
            "before you board. Prices are higher than a local SIM but you "
            "skip the in-country activation step entirely AND avoid the "
            "ETECSA Cuba-Restricted-List issue for US persons. Confirm "
            "your phone is carrier-unlocked and supports eSIM."
        ),
    },
    {
        "topic": "Hotel & casa particular Wi-Fi",
        "detail": (
            "Most modern Havana hotels offer Wi-Fi included or for a per-day "
            "fee. Casas particulares typically do not have in-room Wi-Fi; "
            "expect to use ETECSA's NAUTA pre-paid Wi-Fi cards (sold at "
            "ETECSA offices) at public Wi-Fi parks (the canonical example "
            "is Parque Central, Parque Fe del Valle in Centro Habana, and "
            "the Vedado Malecón hotspots)."
        ),
    },
    {
        "topic": "VPN",
        "detail": (
            "Many Western platforms (LinkedIn, US news outlets, some "
            "messaging apps) are intermittently throttled or blocked on "
            "ETECSA's network. Configure a reputable VPN (ExpressVPN, "
            "NordVPN, Mullvad, ProtonVPN) before arrival; doing it after "
            "landing is unreliable. WhatsApp and Signal generally work "
            "without a VPN."
        ),
    },
    {
        "topic": "Roaming",
        "detail": (
            "Most US carriers do not offer Cuba roaming or only at very "
            "high rates ($2-5/min calls, $0.50-2/MB data). Verizon, AT&T, "
            "and T-Mobile users should NOT assume cellular roaming will "
            "work. Plan around an eSIM or pre-paid ETECSA Wi-Fi cards."
        ),
    },
]


# ----------------------------------------------------------------------------
# 9) Money & banking on the ground
# ----------------------------------------------------------------------------
# Cuba's monetary system is currently fractured across THREE de-facto
# currencies: the official Cuban peso (CUP), the MLC (Moneda
# Libremente Convertible) cards used at certain state retail outlets,
# and US dollar / euro cash on the informal market. The official BCC
# rate (~120 CUP/USD as of 2026) and the elTOQUE informal rate
# (~340-400 CUP/USD) diverge widely and the elTOQUE rate is the one
# that actually clears in private commerce. US-issued cards do NOT
# work in Cuba — at all — under the embargo, and Cuban ATMs do not
# dispense cash to US-issued cards.
MONEY_AND_BANKING: list[dict] = [
    {
        "topic": "Cash is mandatory (especially for US travellers)",
        "detail": (
            "Bring 100% of your trip budget in cash, in advance. US-issued "
            "credit and debit cards do NOT work in Cuba under the embargo "
            "— no exceptions, no workarounds. Euro cash receives a slightly "
            "better exchange rate than USD because Cuba applies a 10% "
            "penalty on USD cash exchange. Notes must be undamaged and "
            "post-2009 series."
        ),
    },
    {
        "topic": "Cuban peso (CUP) cash",
        "detail": (
            "Carry CUP cash for street-level micro-purchases, taxi tips, "
            "and casa particular incidentals. Exchange at CADECA bureaus "
            "(state) at the official BCC rate, or via your casa host at the "
            "informal rate (typically 2-3x more favourable). DO NOT exchange "
            "back to USD on departure — it is illegal to take CUP out of Cuba."
        ),
    },
    {
        "topic": "Card payments (non-US issued cards)",
        "detail": (
            "Non-US issued Visa and Mastercard work at some hotels, "
            "international restaurants, and a few CADECAs. Acceptance is "
            "inconsistent. UK, Canadian, and EU-issued cards work better "
            "than Asian or Middle Eastern cards. American Express does not "
            "work anywhere in Cuba (US-issued by definition)."
        ),
    },
    {
        "topic": "ATMs",
        "detail": (
            "ATM withdrawals work for non-US issued Visa cards in Havana "
            "city centre but daily limits are tight (typically equivalent "
            "of USD 100-200 in CUP) and many machines run out of cash "
            "during high-tourist season. Treat ATMs as a contingency, not "
            "a planned source of funds."
        ),
    },
    {
        "topic": "MLC (Moneda Libremente Convertible)",
        "detail": (
            "Some Cuban state retail outlets (TRD Caribe, certain "
            "supermarkets, gas stations) accept ONLY pre-loaded MLC cards "
            "denominated in USD/EUR equivalents. Foreign visitors generally "
            "do not need MLC cards — ignore unless your stay involves "
            "buying groceries at a state MLC supermarket."
        ),
    },
    {
        "topic": "Informal exchange rate (elTOQUE TRMI)",
        "detail": (
            "The elTOQUE TRMI (Tasa de Referencia del Mercado Informal) is "
            "the rate that actually clears in private commerce, casas "
            "particulares, and paladares. It runs typically 2-3x the "
            "official BCC rate. Cuban Insights publishes the daily TRMI on "
            "the homepage — check before negotiating cash exchange."
        ),
        "url": "/",
    },
    {
        "topic": "Wise / Western Union / Remitly",
        "detail": (
            "Western Union restored US-Cuba remittance services in 2023 "
            "(after a Trump-era pause) and is the canonical channel for "
            "USD remittances to Cuban families — but NOT for foreign "
            "business travellers funding their own trips. Wise does not "
            "support outbound transfers to Cuba."
        ),
    },
]


# ----------------------------------------------------------------------------
# 10) Pre-departure travel checklist
# ----------------------------------------------------------------------------
PRE_TRIP_CHECKLIST: list[dict] = [
    {
        "label": "Confirm your visa / Tourist Card status",
        "detail": (
            "Most nationalities (UK, EU, Canada, Mexico) need a Cuban "
            "Tourist Card (Tarjeta del Turista) purchased through their "
            "airline or a Cuban consulate. US persons need to qualify "
            "under one of the 12 OFAC general-license categories AND buy "
            "a Tourist Card. Use our Visa Requirements tool to check the "
            "current rules for your passport."
        ),
        "url": "/tools/cuba-visa-requirements",
    },
    {
        "label": "[US persons] Document your CACR general-license category",
        "detail": (
            "Before departure, document in writing which of the 12 OFAC "
            "general-license categories under 31 CFR § 515.560–.578 your "
            "trip qualifies for (most commonly 'Support for the Cuban "
            "People' under § 515.574). Build and retain a 'full-time "
            "schedule' of qualifying activities (paladar meals, casa "
            "particular stays, MIPYME tours, cultural visits). Retain "
            "records for 5 years (the OFAC recordkeeping window)."
        ),
        "url": "/tools/ofac-cuba-sanctions-checker",
    },
    {
        "label": "Verify travel insurance covers Cuba (mandatory under Cuban law)",
        "detail": (
            "Cuban entry law requires every traveller to hold valid "
            "medical-travel insurance — proof may be requested at "
            "immigration. Many US-issued policies explicitly EXCLUDE Cuba. "
            "Confirm in writing that your policy covers (a) hospitalisation "
            "in Cuba, (b) medical evacuation to Mexico/US, and (c) "
            "trip-cancellation due to hurricane / civil unrest. Asistur "
            "(Cuba's state insurer) sells a top-up policy on arrival if "
            "your home policy doesn't qualify."
        ),
    },
    {
        "label": "Photocopy passport, Tourist Card & insurance card",
        "detail": (
            "Carry a paper photocopy + a digital copy in encrypted cloud "
            "storage. Leave a third copy with a contact at home. The PNR "
            "spot-checks documents at hotels and airport transit zones."
        ),
    },
    {
        "label": "Complete the D'Viajeros online declaration",
        "detail": (
            "Cuba requires every arriving traveller to complete the free "
            "online D'Viajeros customs and health declaration within the "
            "72 hours before arrival. The form is free at "
            "https://dviajeros.mitrans.gob.cu/ — paid 'official' versions "
            "are scams. Save the QR code to your phone and a printed copy."
        ),
        "url": "https://dviajeros.mitrans.gob.cu/",
    },
    {
        "label": "Register with your embassy",
        "detail": (
            "Free, takes 5 minutes. Once enrolled, your government can "
            "locate and contact you in a crisis (hurricane evacuations are "
            "the most common scenario). US: STEP. UK: GOV.UK email alerts. "
            "Canada: ROCA. See the full list at the top of this page."
        ),
        "url": "#register",
    },
    {
        "label": "Pre-arrange airport transfer & first night",
        "detail": (
            "Book your inbound HAV airport transfer in writing through "
            "your hotel or casa host before you board. Confirm and prepay "
            "the first night's accommodation."
        ),
    },
    {
        "label": "Bring 100% of your trip budget in cash (USD or EUR)",
        "detail": (
            "US-issued cards do NOT work in Cuba. Even non-US cards are "
            "inconsistently accepted. Bring euro cash if possible (no 10% "
            "USD penalty), in small undamaged post-2009 notes. Budget "
            "USD/EUR 100-200 per day for casa + paladar + transport."
        ),
    },
    {
        "label": "Set up an eSIM (recommended) or accept pre-paid Wi-Fi",
        "detail": (
            "Buy an Airalo or Holafly Cuba eSIM before departure and "
            "activate on landing. Avoids the ETECSA Cuba-Restricted-List "
            "issue for US persons and skips the in-country SIM activation "
            "queue. Alternative: rely on pre-paid NAUTA Wi-Fi cards at "
            "hotel lobbies and Wi-Fi parks."
        ),
    },
    {
        "label": "Install and test a VPN",
        "detail": (
            "Choose ExpressVPN, NordVPN, Mullvad or ProtonVPN. Install on "
            "phone and laptop, sign in, and confirm it works before you "
            "board — many VPN provider sites are blocked from inside Cuba."
        ),
    },
    {
        "label": "Pre-load offline maps",
        "detail": (
            "Download Havana in Google Maps for offline use, plus a backup "
            "(Maps.me or Organic Maps). Cell data is expensive and patchy."
        ),
    },
    {
        "label": "Hurricane-season awareness (June–November)",
        "detail": (
            "Atlantic hurricane season runs June–November and Cuba sits "
            "directly in the path. Build a flexible flight booking, "
            "monitor the National Hurricane Center, and have a "
            "contingency exit plan (Cancún, Nassau, Miami)."
        ),
    },
    {
        "label": "Emergency contact card",
        "detail": (
            "Print a pocket card with: hotel/casa name + phone, your "
            "embassy's after-hours line, your insurer's 24/7 number, "
            "Asistur (+53 7 866-4499), and a domestic emergency contact. "
            "In Spanish if possible."
        ),
    },
]


# ----------------------------------------------------------------------------
# 11) Personal safety checklist
# ----------------------------------------------------------------------------
SAFETY_CHECKLIST: list[dict] = [
    {
        "rule": "Stay in central Havana (Miramar / Vedado / Habana Vieja core)",
        "detail": (
            "Miramar (Playa municipality), Vedado, and the restored core "
            "of Habana Vieja are the safer business and tourism districts "
            "and host most foreign-investor meetings, embassies, "
            "international hospitals, and quality casas particulares. "
            "Avoid the outer barrios after dark — Marianao, parts of "
            "Cerro, and Diez de Octubre have higher petty-crime rates "
            "and limited street lighting during apagones (power outages)."
        ),
    },
    {
        "rule": "Petty crime, not violent crime, is the dominant risk",
        "detail": (
            "Havana has a notably lower violent-crime rate than other "
            "Latin American capitals. The dominant risks for foreign "
            "visitors are: pickpocketing on Calle Obispo and around the "
            "Plaza de Armas, distraction theft (the fake-bird-poo scam), "
            "short-change at CADECAs, jinetero / jinetera approaches in "
            "tourist zones, and snatch-and-run on cameras / phones held "
            "in hand. Stay aware, not paranoid."
        ),
    },
    {
        "rule": "Pre-book taxis through your hotel or casa host",
        "detail": (
            "State Cubataxi from a hotel rank is reliable. Almendrón "
            "shared cars on fixed routes are reliable. AVOID flagging "
            "private cars from the street, especially at night. NEVER "
            "accept a cab from someone who approaches you at HAV airport."
        ),
    },
    {
        "rule": "Apagón awareness (rolling power outages)",
        "detail": (
            "Cuba experiences daily rolling blackouts (apagones) of 4–12 "
            "hours, sometimes longer. Carry a charged power bank, a small "
            "headlamp, and a paper map. Hotels in central Havana run on "
            "generator backup but elevators and air-con may stop working "
            "outside the lobby. Refrigeration interruptions raise the "
            "risk of foodborne illness — favour cooked-to-order paladar "
            "meals over buffets during sustained outages."
        ),
    },
    {
        "rule": "Carry water and basic OTC medicine",
        "detail": (
            "Cuban pharmacies face severe shortages of basic medicines "
            "(ibuprofen, acetaminophen, antihistamines, antibiotics, "
            "ORS). Bring a 7-day kit: pain reliever, anti-diarrhoeal, "
            "ORS, antihistamine, broad-spectrum antibiotic if your "
            "doctor prescribes one, and any chronic medication in its "
            "original packaging plus the prescription. Bottled water is "
            "widely available but not always cold."
        ),
    },
    {
        "rule": "Low profile, low value",
        "detail": (
            "No visible jewellery, expensive watches, or DSLR cameras "
            "swung on a strap. Keep phones in pockets when not in use. "
            "Tourist-photographer behaviour attracts pickpocket attention "
            "in Habana Vieja and Centro Habana — not violence, just theft."
        ),
    },
    {
        "rule": "Carry cash dispersed",
        "detail": "Distribute cash across multiple pockets, the casa safe, and your bag. Never carry your entire bankroll on you.",
    },
    {
        "rule": "Comply at PNR / customs checkpoints; do not photograph officials",
        "detail": (
            "Cuban Policía Nacional Revolucionaria (PNR) and customs "
            "agents may spot-check documents. Be polite, present passport "
            "+ Tourist Card, do not photograph or film officials, and do "
            "not negotiate. Do NOT photograph government buildings (the "
            "Capitolio is fine; the Plaza de la Revolución is fine; "
            "MININT, MINFAR, port and airport infrastructure are NOT)."
        ),
    },
    {
        "rule": "Avoid demonstrations and political gatherings",
        "detail": (
            "Public protest is rare on the island but the risk profile "
            "spikes around politically sensitive dates (11 July anniversary, "
            "Communist Party congresses, election cycles). Foreign "
            "participation in any protest is a deportation risk and may "
            "trigger immigration consequences."
        ),
    },
    {
        "rule": "Two-deep comms",
        "detail": (
            "Share your daily itinerary with a trusted contact at home. "
            "Check in by message at least twice a day. If you go silent, "
            "they should know who to call (your embassy + Asistur)."
        ),
    },
    {
        "rule": "Hurricane / tropical storm awareness",
        "detail": (
            "Atlantic hurricane season runs June–November; Cuba is "
            "directly in the path. Monitor the US National Hurricane "
            "Center and Cuba's INSMET. If a storm warning is issued "
            "during your trip, follow your embassy's advice immediately "
            "— evacuation flights fill up within hours."
        ),
    },
]


# ----------------------------------------------------------------------------
# 12) Emergency numbers
# ----------------------------------------------------------------------------
EMERGENCY_NUMBERS: list[dict] = [
    {"label": "Police (PNR) — emergencies", "number": "106"},
    {"label": "Fire / Bomberos", "number": "105"},
    {"label": "Ambulance (SIUM)", "number": "104"},
    {"label": "Civil Defence (Defensa Civil) — hurricanes", "number": "108"},
    {
        "label": "Asistur — 24/7 traveller assistance",
        "number": "+53 7 866-4499 / +53 7 866-8527",
    },
    {
        "label": "Clínica Cira García (foreigners' hospital)",
        "number": "+53 7 204-2811",
    },
    {
        "label": "US citizens overseas emergency (24/7)",
        "number": "+53 7 839-4100 (US Embassy Havana) · 1-888-407-4747 (US/Canada toll-free)",
    },
    {
        "label": "UK FCDO crisis line",
        "number": "+44 20 7008-5000",
    },
    {
        "label": "Canada — Ottawa Emergency Watch",
        "number": "+1 613 996-8885",
    },
]
