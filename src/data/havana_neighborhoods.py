"""
Curated Havana neighborhood safety, accommodation, and business-suitability
dataset. Scores are 1 (highest concern) to 5 (most stable for foreign
visitors and businesses), based on published State Department / FCDO
context, OSAC reporting trends, and aggregated foreign-business and
diplomatic-community feedback.

Important framing note for users coming from a Latin-American risk-map
mental model: Havana's overall violent-crime rate is low by regional
standards. Cuba's state security apparatus and tightly controlled
firearm regime keep homicide rates well below most Latin American
capitals. The dominant risk to foreign visitors and business
travelers in Havana is petty crime (pickpocketing, distraction theft,
short-change scams, jinetero / jinetera approaches in tourist zones),
not violent street crime. Power outages ("apagones"), water-supply
interruptions, and severely degraded infrastructure (potholes,
unmarked construction, sporadic gas leaks) are larger practical-safety
concerns than crime in most neighborhoods.

This is NOT a real-time crime feed — it is a one-page reference for
investors and business travelers planning a trip. Always confirm with
local security advisors and the US Embassy Havana / your home embassy
before travel. Update when on-the-ground sources signal a sustained
shift.

Coordinates are anchored to a recognisable landmark inside each
neighborhood (plaza, embassy row, hotel, or cinema) so the marker on
the safety map sits in the place a reader would expect, not on the
geometric centroid of an irregular polygon. Sources verified against
Wikipedia, OpenStreetMap (mapcarta), and Wikimapia.
"""

from __future__ import annotations


HAVANA_NEIGHBORHOODS: list[dict] = [
    {
        "name": "Miramar",
        "municipality": "Playa",
        "safety_score": 5,
        "category": "Diplomatic / business hub",
        "summary": (
            "Havana's diplomatic and modern-business district. Most "
            "non-US foreign embassies sit along 5ta Avenida (Quinta "
            "Avenida), alongside the modern hotels foreign business "
            "delegations use (Meliá Habana, Memories Miramar, Comodoro). "
            "Wide, well-lit avenues and a visible diplomatic-protection "
            "police presence make this the lowest-friction part of the "
            "city for foreign investor visits."
        ),
        "business_use": (
            "Default district for foreign-investor meetings, joint-venture "
            "negotiations with Cuban state counterparties (CIMEX, Cubanacán, "
            "Cubaníquel headquarters are nearby), and consular appointments. "
            "Most ZEDM (Mariel) commercial counterparties keep Havana "
            "representative offices in Miramar."
        ),
        "what_to_avoid": (
            "Pickpocketing risk in tourist clusters around hotels; do not "
            "exchange currency on the street."
        ),
        "lat": 23.1184,
        "lng": -82.4310,
    },
    {
        "name": "Vedado",
        "municipality": "Plaza de la Revolución",
        "safety_score": 4,
        "category": "Business / cultural / residential",
        "summary": (
            "Mid-20th-century commercial and cultural core of Havana. "
            "Concentration of legacy luxury hotels (Hotel Nacional, Habana "
            "Libre, Meliá Cohíba, Riviera), the University of Havana, and "
            "many of Cuba's most established paladares (private "
            "restaurants). Generally functional services and a steady "
            "police presence."
        ),
        "business_use": (
            "Common location for cultural attaché meetings, conference "
            "venues, and academic / biotech contacts. Convenient for "
            "ministry visits in Plaza de la Revolución."
        ),
        "what_to_avoid": (
            "Distraction theft and jinetero / jinetera approaches around "
            "the Malecón sea wall and the major hotels at night."
        ),
        "lat": 23.1391,
        "lng": -82.3845,
    },
    {
        "name": "Plaza de la Revolución",
        "municipality": "Plaza de la Revolución",
        "safety_score": 4,
        "category": "Government / ministerial",
        "summary": (
            "Administrative heart of the Cuban state. Houses the Council "
            "of State (Consejo de Estado), the Ministerio del Interior "
            "(MININT), the Ministerio de Comunicaciones, the Ministerio "
            "de Comercio Exterior y la Inversión Extranjera (MINCEX), and "
            "the iconic Memorial José Martí. Heavy uniformed and "
            "plain-clothes security presence."
        ),
        "business_use": (
            "Required visits for foreign-investment approvals (MINCEX), "
            "trade-mission meetings, and licence-related interactions. "
            "Always with local fixer or consular escort."
        ),
        "what_to_avoid": (
            "Do not photograph security personnel or ministry buildings. "
            "Demonstrations are extremely rare here but historically "
            "draw a hard security response."
        ),
        "lat": 23.1230,
        "lng": -82.3833,
    },
    {
        "name": "La Habana Vieja",
        "municipality": "La Habana Vieja",
        "safety_score": 4,
        "category": "UNESCO heritage / tourist core",
        "summary": (
            "The colonial old town, declared a UNESCO World Heritage "
            "site in 1982. The most touristed area of Cuba — restored "
            "around the four main plazas (Catedral, Vieja, San "
            "Francisco, Armas) by the Oficina del Historiador. Heavy "
            "tourist-police presence by day."
        ),
        "business_use": (
            "Where international hospitality investors do site visits; "
            "Iberostar, Meliá, Kempinski, and other foreign brands "
            "operate hotels here under Cubanacán / Habaguanex / Gran "
            "Caribe contracts."
        ),
        "what_to_avoid": (
            "Pickpocketing and short-change scams. Avoid back streets at "
            "night between Plaza Vieja and the Capitolio. Do not change "
            "money with street touts."
        ),
        "lat": 23.1399,
        "lng": -82.3540,
    },
    {
        "name": "Centro Habana",
        "municipality": "Centro Habana",
        "safety_score": 3,
        "category": "Dense urban / mixed",
        "summary": (
            "Densely populated transition zone between La Habana Vieja "
            "and Vedado. Largely residential, with severely degraded "
            "infrastructure (collapsing buildings are a real and "
            "documented hazard), and some of the city's most vibrant "
            "street life. Property risk is mostly opportunistic theft "
            "rather than violent crime."
        ),
        "business_use": (
            "Limited investor relevance directly, but transited between "
            "Vedado and Habana Vieja meetings."
        ),
        "what_to_avoid": (
            "Do not walk under balconies after heavy rain (collapse "
            "risk). Limit visible electronics. Avoid the Barrio Chino / "
            "Cuatro Caminos area at night."
        ),
        "lat": 23.1389,
        "lng": -82.3729,
    },
    {
        "name": "Habana del Este (Alamar)",
        "municipality": "Habana del Este",
        "safety_score": 3,
        "category": "Soviet-era residential",
        "summary": (
            "Large Soviet-style microdistrict housing on the east side "
            "of the bay, built largely 1971-1990. Functional but "
            "infrastructurally weak; very few foreign-investor reasons "
            "to visit beyond the beaches at Playas del Este (Santa "
            "María, Guanabo)."
        ),
        "business_use": (
            "None typical. Touristic relevance via the Playas del Este "
            "beach corridor 20 km east of the city."
        ),
        "what_to_avoid": (
            "Do not drive the Vía Blanca / Túnel de la Bahía at night "
            "without a known driver."
        ),
        "lat": 23.1607,
        "lng": -82.3018,
    },
    {
        "name": "Marianao",
        "municipality": "Marianao",
        "safety_score": 3,
        "category": "Residential / mixed-use",
        "summary": (
            "Western residential municipality, traditionally home to "
            "the working- and middle-classes. Houses the Tropicana "
            "cabaret and several hospitals. Mixed infrastructure."
        ),
        "business_use": (
            "Limited; transited en route to Mariel (ZEDM) road trips."
        ),
        "what_to_avoid": (
            "Use known transport between Marianao and downtown; not a "
            "neighborhood for casual foot-traffic exploration."
        ),
        "lat": 23.0833,
        "lng": -82.4333,
    },
    {
        "name": "Cerro",
        "municipality": "Cerro",
        "safety_score": 2,
        "category": "Dense residential / industrial",
        "summary": (
            "South-central residential and historically industrial "
            "district. Significant infrastructure decay; petty crime "
            "more frequent than the city average."
        ),
        "business_use": (
            "Limited. Some legacy state industrial sites; not typical "
            "for foreign-investor visits."
        ),
        "what_to_avoid": (
            "No casual exploration. Visits should be purpose-driven "
            "with local guidance."
        ),
        "lat": 23.1230,
        "lng": -82.3858,
    },
    {
        "name": "Diez de Octubre",
        "municipality": "Diez de Octubre",
        "safety_score": 2,
        "category": "Dense residential",
        "summary": (
            "Largest municipality in Havana by population. "
            "Predominantly residential, lower-income; degraded "
            "infrastructure and elevated petty-crime rates relative to "
            "Vedado / Miramar."
        ),
        "business_use": "None typical.",
        "what_to_avoid": (
            "Avoid as a destination for foreign visitors without a "
            "specific local contact."
        ),
        "lat": 23.0900,
        "lng": -82.3733,
    },
    {
        "name": "San Miguel del Padrón",
        "municipality": "San Miguel del Padrón",
        "safety_score": 2,
        "category": "Outer residential",
        "summary": (
            "South-eastern outer-ring residential municipality. "
            "Limited infrastructure, infrequent foreign visitor "
            "presence."
        ),
        "business_use": "None typical.",
        "what_to_avoid": "Not recommended for casual visits.",
        "lat": 23.0667,
        "lng": -82.3000,
    },
    {
        "name": "Boyeros (José Martí Airport corridor)",
        "municipality": "Boyeros",
        "safety_score": 3,
        "category": "Airport / transit",
        "summary": (
            "Southern municipality housing José Martí International "
            "Airport (HAV) and the road corridor connecting it to the "
            "city. The airport itself is well-controlled; the corridor "
            "is functional."
        ),
        "business_use": (
            "Unavoidable transit on arrival/departure. Pre-arrange a "
            "known driver via your hotel — official taxi queues at HAV "
            "are reliable but the language barrier creates friction."
        ),
        "what_to_avoid": (
            "Currency exchange touts inside the terminal — use a CADECA "
            "(state exchange house) at the airport or your hotel."
        ),
        "lat": 22.9892,
        "lng": -82.4091,
    },
    {
        "name": "Cojímar",
        "municipality": "Habana del Este",
        "safety_score": 4,
        "category": "Coastal / cultural",
        "summary": (
            "Small fishing village on the east coast; the setting that "
            "inspired Hemingway's 'The Old Man and the Sea'. Quiet, "
            "low-friction. Frequented by foreign visitors on day "
            "excursions."
        ),
        "business_use": (
            "None directly, but a recognisable cultural-tourism asset "
            "for hospitality investors evaluating east-Havana exposure."
        ),
        "what_to_avoid": "Standard coastal-area precautions only.",
        "lat": 23.1611,
        "lng": -82.3019,
    },
    {
        "name": "Mariel (ZEDM corridor)",
        "municipality": "Mariel (Artemisa province, outside Havana)",
        "safety_score": 4,
        "category": "Special Development Zone / industrial",
        "summary": (
            "Cuba's flagship Mariel Special Development Zone (Zona "
            "Especial de Desarrollo Mariel — ZEDM), 45 km west of "
            "Havana. Modern container terminal (TC Mariel) and "
            "industrial-park parcels under foreign-investor "
            "concessions. Tightly controlled, low ambient crime."
        ),
        "business_use": (
            "Primary on-island concession framework for foreign "
            "investors — site visits, terminal inspections, and parcel "
            "due diligence happen here."
        ),
        "what_to_avoid": (
            "Do not photograph the container terminal or military "
            "installations. Always coordinate visits via the ZEDM "
            "office and your appointed Cuban counterpart."
        ),
        "lat": 22.9911,
        "lng": -82.7567,
    },
]


def list_havana_neighborhoods() -> list[dict]:
    return HAVANA_NEIGHBORHOODS
