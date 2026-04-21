"""
Curated Havana points of interest (landmarks) used as map overlays on
the safety-by-neighborhood tool. Categories are deliberately limited
to items that matter for foreign investors and business travelers:

  * hospital  — major hospitals routinely used by foreign visitors
                (Cuba operates a parallel hard-currency / "international"
                clinic system specifically for non-residents)
  * embassy   — currently-operating foreign missions in Havana
  * police    — primary PNR (Policía Nacional Revolucionaria) and
                MININT contact points
  * airport   — José Martí International (HAV / MUHA)
  * trade     — institutions a foreign investor will physically visit
                (MINCEX, ProCuba, Mariel ZEDM office, Lonja del Comercio)

Coordinates are anchored to the building or street intersection named
in the source. Each entry carries an inline citation note so a
reviewer can see where the location came from. NOT a directory — this
is a small, curated overlay sized to be useful on a map without
becoming visual noise.

If you add to this file, prefer institutions with stable, public
addresses (official ministry / embassy pages, Wikipedia, OSM via
mapcarta / wikimapia). Avoid copying coordinates from third-party
listings that don't cite a source.
"""

from __future__ import annotations


HAVANA_LANDMARKS: list[dict] = [
    # ---- Hospitals (foreign-visitor-facing "international" clinics) ----
    {
        "name": "Clínica Central Cira García",
        "category": "hospital",
        "area": "Miramar (Playa)",
        "note": (
            "Cuba's flagship international (hard-currency) clinic for "
            "foreign visitors and the diplomatic community. "
            "English-speaking staff, 24/7 emergency, and a separate "
            "consultation/inpatient track from the public Cuban "
            "system. Calle 20 e/ 41 y 43, Miramar."
        ),
        "lat": 23.1226,
        "lng": -82.4203,
    },
    {
        "name": "Hospital Hermanos Ameijeiras",
        "category": "hospital",
        "area": "Centro Habana",
        "note": (
            "Major tertiary-care hospital in central Havana — landmark "
            "Soviet-era tower on the Malecón. Used as a fallback for "
            "complex cases referred from Cira García. San Lázaro #701, "
            "esq. Belascoaín."
        ),
        "lat": 23.1414,
        "lng": -82.3722,
    },
    {
        "name": "Centro de Investigaciones Médico-Quirúrgicas (CIMEQ)",
        "category": "hospital",
        "area": "Siboney (Playa)",
        "note": (
            "High-end research hospital in west Havana, used by senior "
            "officials and high-acuity foreign-patient referrals. "
            "Calle 216 e/ 11B y 13, Reparto Siboney."
        ),
        "lat": 23.0769,
        "lng": -82.4692,
    },
    {
        "name": "Hospital Calixto García",
        "category": "hospital",
        "area": "Vedado",
        "note": (
            "Public general hospital in Vedado serving the broader "
            "city. Foreign visitors are typically routed to Cira "
            "García instead, but Calixto García is the closest A&E if "
            "you are in central Vedado. Av. Universidad y J."
        ),
        "lat": 23.1361,
        "lng": -82.3878,
    },

    # ---- Embassies (curated subset; not exhaustive) ----
    {
        "name": "Embassy of the United States",
        "category": "embassy",
        "area": "Vedado (Malecón)",
        "note": (
            "Calzada e/ L y M, Vedado. The US re-established formal "
            "diplomatic relations with Cuba in July 2015 and reopened "
            "the Embassy on the same site as the former US Interests "
            "Section. Consular services have operated at reduced "
            "capacity since the 2017 'Havana Syndrome' incidents — "
            "verify current visa-services posture before relying on "
            "in-person appointments."
        ),
        "lat": 23.1466,
        "lng": -82.3855,
    },
    {
        "name": "Embassy of the United Kingdom",
        "category": "embassy",
        "area": "Miramar (Playa)",
        "note": "Calle 34, no. 702 e/ 7ma y 17, Miramar.",
        "lat": 23.1198,
        "lng": -82.4180,
    },
    {
        "name": "Embassy of Canada",
        "category": "embassy",
        "area": "Miramar (Playa)",
        "note": (
            "Calle 30, no. 518 esq. 7ma Avenida, Miramar. Canada is "
            "Cuba's largest source of foreign tourist arrivals and a "
            "major non-US trading partner; the embassy is one of the "
            "busiest in Havana."
        ),
        "lat": 23.1233,
        "lng": -82.4322,
    },
    {
        "name": "Embassy of Spain",
        "category": "embassy",
        "area": "La Habana Vieja",
        "note": (
            "Cárcel #51 e/ Zulueta y Prado, La Habana Vieja. Spain "
            "maintains the largest non-Cuban commercial presence on "
            "the island via Meliá, Iberostar, NH, Iberia, and BBVA-"
            "linked corresponding banking."
        ),
        "lat": 23.1405,
        "lng": -82.3580,
    },
    {
        "name": "Embassy of Germany",
        "category": "embassy",
        "area": "Miramar (Playa)",
        "note": "Calle 13, no. 652 esq. B, Vedado.",
        "lat": 23.1378,
        "lng": -82.3917,
    },
    {
        "name": "Embassy of France",
        "category": "embassy",
        "area": "Vedado",
        "note": "Calle 14 no. 312 e/ 3ra y 5ta Avenidas, Miramar.",
        "lat": 23.1252,
        "lng": -82.4103,
    },
    {
        "name": "Embassy of Italy",
        "category": "embassy",
        "area": "Miramar (Playa)",
        "note": "Calle 5ta Avenida no. 402 esq. 4, Miramar.",
        "lat": 23.1306,
        "lng": -82.4058,
    },
    {
        "name": "Embassy of Mexico",
        "category": "embassy",
        "area": "Miramar (Playa)",
        "note": (
            "Calle 12 no. 518 e/ 5ta y 7ma, Miramar. Mexico is one of "
            "Cuba's most consistent diplomatic partners and a major "
            "source of medical-equipment trade."
        ),
        "lat": 23.1298,
        "lng": -82.4108,
    },
    {
        "name": "Embassy of Brazil",
        "category": "embassy",
        "area": "Miramar (Playa)",
        "note": "Calle 16 no. 503 e/ 5ta y 7ma, Miramar.",
        "lat": 23.1294,
        "lng": -82.4145,
    },
    {
        "name": "Embassy of China (P.R.C.)",
        "category": "embassy",
        "area": "Miramar (Playa)",
        "note": (
            "Calle C no. 313 e/ 13 y 15, Vedado. China is one of "
            "Cuba's largest non-tourist trading partners (telecom "
            "equipment, autos, and oil)."
        ),
        "lat": 23.1369,
        "lng": -82.3886,
    },
    {
        "name": "Embassy of the Russian Federation",
        "category": "embassy",
        "area": "Miramar (Playa)",
        "note": (
            "5ta Avenida e/ 62 y 66, Miramar. Distinctive Soviet-era "
            "concrete tower; the largest embassy compound in Havana."
        ),
        "lat": 23.1138,
        "lng": -82.4408,
    },
    {
        "name": "Embassy of the European Union",
        "category": "embassy",
        "area": "Miramar (Playa)",
        "note": (
            "Calle 76A no. 706 e/ 7ma A y 11, Miramar. The EU "
            "delegation oversees the EU-Cuba Political Dialogue and "
            "Cooperation Agreement (PDCA, in force since 2017)."
        ),
        "lat": 23.1138,
        "lng": -82.4486,
    },

    # ---- Police / public-safety ----
    {
        "name": "PNR — Estación de Cuba (Habana Vieja)",
        "category": "police",
        "area": "La Habana Vieja",
        "note": (
            "Policía Nacional Revolucionaria station at Calle Cuba esq. "
            "Chacón. Closest first-stop for foreign visitors filing a "
            "denuncia from the Old Havana tourist area."
        ),
        "lat": 23.1431,
        "lng": -82.3525,
    },
    {
        "name": "PNR — Sede Central (Aranguren)",
        "category": "police",
        "area": "Cerro",
        "note": (
            "PNR national headquarters complex on Av. de Aranguren / "
            "Calle Tulipán, Cerro. National-level coordination."
        ),
        "lat": 23.1158,
        "lng": -82.3858,
    },

    # ---- Airport ----
    {
        "name": "Aeropuerto Internacional José Martí (HAV / MUHA)",
        "category": "airport",
        "area": "Boyeros",
        "note": (
            "Cuba's primary international gateway. ~20 km south of "
            "downtown Havana. Terminal 3 (T3) handles all "
            "international flights including the US scheduled "
            "carriers (AAL, DAL, JBLU, UAL); Terminal 2 (T2) is the "
            "older US-charter terminal; Terminal 1 (T1) handles "
            "domestic routes. Pre-arrange transport via your hotel — "
            "the official taxi queue at T3 is reliable."
        ),
        "lat": 22.9892,
        "lng": -82.4091,
    },

    # ---- Trade & investment institutions ----
    {
        "name": "MINCEX (Ministerio de Comercio Exterior y Inversión Extranjera)",
        "category": "trade",
        "area": "Vedado",
        "note": (
            "The ministry that approves and registers foreign-investor "
            "operations under Law 118/2014. First and most important "
            "stop for any Empresa Mixta or association contract. "
            "Calle 1ra no. 1206 e/ 12 y 14, Plaza."
        ),
        "lat": 23.1417,
        "lng": -82.3917,
    },
    {
        "name": "Oficina de la ZEDM (Mariel Special Development Zone)",
        "category": "trade",
        "area": "Mariel (Artemisa province)",
        "note": (
            "Headquarters of the Oficina de la Zona Especial de "
            "Desarrollo Mariel — the regulator and concession-granting "
            "office for Cuba's flagship special development zone. "
            "Located inside the ZEDM perimeter, west of Havana."
        ),
        "lat": 22.9911,
        "lng": -82.7567,
    },
    {
        "name": "Lonja del Comercio (Habana Vieja)",
        "category": "trade",
        "area": "La Habana Vieja",
        "note": (
            "Restored 1909 commercial-exchange building on Plaza San "
            "Francisco de Asís, today housing many of the foreign-"
            "company representative offices accredited in Cuba "
            "(consultancies, trading houses, regional banks). "
            "Lamparilla esq. Oficios."
        ),
        "lat": 23.1399,
        "lng": -82.3491,
    },
    {
        "name": "ProCuba (Centro para la Promoción del Comercio Exterior y la Inversión Extranjera)",
        "category": "trade",
        "area": "Miramar (Playa)",
        "note": (
            "Cuba's official trade and investment promotion agency, "
            "under MINCEX. Organizes the FIHAV (Feria Internacional de "
            "La Habana) trade fair annually at Expocuba and is the "
            "first contact point for foreign investors evaluating "
            "Cuba. Calle 28 no. 504 e/ 5ta y 7ma, Miramar."
        ),
        "lat": 23.1265,
        "lng": -82.4283,
    },
]


def list_havana_landmarks() -> list[dict]:
    return HAVANA_LANDMARKS
