"""
Cuban power-figures registry — the data layer behind /people.

Why this module exists:
  • Google Search Console traffic on sister sites shows incidental
    name-search intent landing on briefings that only mention an
    official in passing. A dedicated profile per power figure converts
    that intent: the page title and headline match the search query
    verbatim, the page answers "who is this person?" with bio + role +
    status, and a bottom rail funnels the reader into the wider Cuba
    investment / sanctions / sector coverage.
  • Slug stability matters for SEO: once a slug is published and
    indexed by Google, changing it forfeits the rank. The slug is
    permanent. Add new fields, never rename slugs.
  • Pure Python data — no external API, no LLM, no DB. Cached for the
    lifetime of the Flask worker.

Editorial freshness — bump VERIFIED_AS_OF every time the registry is
re-swept against live news so readers see a current "Verified" stamp
on every profile.

Auto-linker
  • ``link_people_in_html(html)`` inserts first-mention ``/people/<slug>``
    hyperlinks at render time so stored ``body_html`` is never mutated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Sequence

from bs4 import BeautifulSoup, NavigableString, Tag


# Bump this stamp every time the whole registry is re-verified against
# current news. Renders as "Verified {Month Year}" on every profile —
# trust signal to readers, forcing function for editorial.
VERIFIED_AS_OF: str = "2026-05-01"


# ──────────────────────────────────────────────────────────────────────
# Cohort taxonomy
# ──────────────────────────────────────────────────────────────────────

COHORTS: dict[str, dict[str, str]] = {
    "executive": {
        "label": "Executive & Council of Ministers",
        "short": "Executive",
        "description": (
            "The President of the Republic, the Prime Minister, "
            "Vice Presidents and ministers — the offices that run "
            "Cuba's day-to-day government under the 2019 Constitution."
        ),
        "url_label": "Executive & cabinet",
    },
    "pcc": {
        "label": "Communist Party of Cuba (PCC)",
        "short": "PCC",
        "description": (
            "The Politburo, Central Committee and Secretariat of the "
            "Partido Comunista de Cuba — Cuba's only legal party and, "
            "under Article 5 of the Constitution, the leading force "
            "of the state. Power flows through the PCC distinct from "
            "the cabinet."
        ),
        "url_label": "PCC leadership",
    },
    "military": {
        "label": "Military & Interior (FAR / MININT)",
        "short": "Military & MININT",
        "description": (
            "Senior leadership of the Revolutionary Armed Forces "
            "(FAR / MINFAR) and the Ministry of the Interior (MININT) "
            "— the security and intelligence apparatus that shapes "
            "every diligence question on a Cuban counterparty."
        ),
        "url_label": "Military & interior",
    },
    "judiciary": {
        "label": "Judiciary & prosecution",
        "short": "Judiciary",
        "description": (
            "The Attorney General (Fiscal General de la República), "
            "the People's Supreme Court (Tribunal Supremo Popular) "
            "and the National Electoral Council — the legal "
            "machinery of the Cuban state."
        ),
        "url_label": "Judiciary & prosecution",
    },
    "opposition": {
        "label": "Opposition, dissident & exile",
        "short": "Opposition & exile",
        "description": (
            "Cuban opposition leaders, civic-society organisers and "
            "exile figures — the voices outside the PCC. Includes "
            "those currently inside Cuba, those in the diaspora, "
            "and those moving between the two."
        ),
        "url_label": "Opposition & exile",
    },
}

COHORT_ORDER: tuple[str, ...] = (
    "executive", "pcc", "military", "judiciary", "opposition",
)


# ──────────────────────────────────────────────────────────────────────
# Status badges
# ──────────────────────────────────────────────────────────────────────
#
# The data layer carries a status code; the template maps the code to
# badge copy + colour. That separation lets editorial swap copy without
# touching the data registry.

STATUS_CODES: tuple[str, ...] = (
    "current",
    "former",
    "in_us_custody",
    "in_cuban_custody",
    "in_exile",
)


# ──────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TimelineEntry:
    year: str
    event: str


@dataclass(frozen=True)
class FAQ:
    q: str
    a: str


@dataclass(frozen=True)
class Source:
    title: str
    url: str


@dataclass(frozen=True)
class Person:
    slug: str                                  # URL-stable, never rename
    name: str                                  # canonical display name (with diacritics)
    role: str                                  # short role label
    cohorts: tuple[str, ...]                   # one or more cohort keys
    one_liner: str                             # 1-sentence "who is this" — feeds meta description
    bio: tuple[str, ...]                       # 2-4 paragraph bio
    status: str = "current"
    aliases: tuple[str, ...] = ()
    born: Optional[str] = None                 # ISO YYYY-MM-DD or "1960" if month/day unknown
    birthplace: Optional[str] = None
    nationality: str = "Cuban"
    in_office_since: Optional[str] = None
    affiliations: tuple[str, ...] = ()
    spanish_title: Optional[str] = None        # Spanish-language title if distinct
    timeline: tuple[TimelineEntry, ...] = ()
    faqs: tuple[FAQ, ...] = ()
    sources: tuple[Source, ...] = ()
    sector_path: Optional[str] = None          # e.g. "/sectors/governance"
    sanctioned: bool = False                   # does OFAC list this person under Cuba programs
    sanctioning_program: Optional[str] = None  # e.g. "EO 13818 / Global Magnitsky"
    wikidata_id: Optional[str] = None
    wikipedia_url: Optional[str] = None
    related: tuple[str, ...] = ()              # slugs of related people

    @property
    def url_path(self) -> str:
        return f"/people/{self.slug}"

    @property
    def primary_cohort(self) -> str:
        return self.cohorts[0]


# ──────────────────────────────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────────────────────────────
#
# Verification: every entry below was confirmed against live news in
# late April / early May 2026 before being committed. Bump
# VERIFIED_AS_OF whenever you re-sweep.

PEOPLE: dict[str, Person] = {}


def _add(p: Person) -> None:
    PEOPLE[p.slug] = p


_add(Person(
    slug="miguel-diaz-canel",
    name="Miguel Díaz-Canel",
    aliases=("Miguel Mario Díaz-Canel Bermúdez", "Diaz-Canel", "Díaz-Canel", "Miguel Díaz-Canel Bermúdez"),
    role="President of Cuba and First Secretary of the Communist Party",
    spanish_title="Presidente de la República de Cuba; Primer Secretario del PCC",
    cohorts=("executive", "pcc"),
    one_liner=(
        "Miguel Díaz-Canel is the President of Cuba (since 2018) and "
        "First Secretary of the Communist Party (since 2021), the "
        "first non-Castro to hold either office."
    ),
    bio=(
        "Miguel Mario Díaz-Canel Bermúdez has served as President of "
        "the Republic of Cuba since 19 April 2018, succeeding Raúl "
        "Castro after a decade of grooming through provincial Party "
        "posts and the Council of Ministers. He was elected First "
        "Secretary of the Partido Comunista de Cuba (PCC) at the 8th "
        "Party Congress in April 2021, formally consolidating the two "
        "most powerful offices in Cuba in a single individual for the "
        "first time since Raúl Castro stepped down.",
        "Trained as an electronics engineer, Díaz-Canel rose through "
        "PCC structures in Villa Clara and Holguín provinces before "
        "joining the Politburo in 2003. As President he has presided "
        "over the 2019 constitutional reform, the January 2021 Tarea "
        "Ordenamiento monetary unification, the July 2021 protests, "
        "and a sustained economic crisis defined by chronic blackouts "
        "(the apagones), inflation, food shortages and emigration.",
        "For investors and compliance teams, Díaz-Canel sits at the "
        "apex of every counterparty chain into the Cuban state. He "
        "was designated by the U.S. Treasury under Executive Order "
        "13818 (Global Magnitsky) in July 2022 for human-rights "
        "abuses connected to the suppression of the July 2021 "
        "protests. The designation remains active in 2026.",
    ),
    born="1960-04-20",
    birthplace="Placetas, Villa Clara, Cuba",
    in_office_since="2018-04-19",
    affiliations=(
        "Communist Party of Cuba (PCC) — First Secretary",
        "Council of State — President",
        "Politburo of the PCC",
    ),
    timeline=(
        TimelineEntry("1982", "Graduates as electronics engineer, Universidad Central de Las Villas."),
        TimelineEntry("2003", "Joins the Politburo of the PCC."),
        TimelineEntry("2013", "Appointed First Vice President of the Council of State by Raúl Castro."),
        TimelineEntry("2018", "Elected President of the Council of State and Council of Ministers."),
        TimelineEntry("2019", "Becomes President of the Republic under the new 2019 Constitution."),
        TimelineEntry("2021", "Elected First Secretary of the PCC at the 8th Congress (April)."),
        TimelineEntry("2021", "Major nationwide protests on 11 July; security forces detain hundreds."),
        TimelineEntry("2022", "Designated by U.S. Treasury under EO 13818 (Global Magnitsky)."),
        TimelineEntry("2023", "Re-elected by the National Assembly to a second presidential term."),
    ),
    faqs=(
        FAQ(
            q="Who is Miguel Díaz-Canel?",
            a=(
                "Miguel Díaz-Canel is the President of Cuba and First Secretary of the "
                "Cuban Communist Party (PCC). He took office as President in April 2018 "
                "and added the PCC First Secretary role in April 2021, becoming the "
                "first non-Castro to hold either position."
            ),
        ),
        FAQ(
            q="Is Miguel Díaz-Canel sanctioned by the United States?",
            a=(
                "Yes. The U.S. Department of the Treasury's Office of Foreign Assets "
                "Control (OFAC) designated Díaz-Canel under Executive Order 13818 "
                "(Global Magnitsky) in July 2022, for human-rights abuses connected to "
                "the violent suppression of the 11 July 2021 protests. The designation "
                "remains active. Any U.S. person dealing with him is generally "
                "prohibited under the Cuban Assets Control Regulations (CACR, 31 CFR "
                "Part 515) and the OFAC SDN regime."
            ),
        ),
        FAQ(
            q="Is the President of Cuba the same as the First Secretary of the PCC?",
            a=(
                "Since April 2021 they are held by the same person — Miguel Díaz-Canel "
                "— but they are distinct offices. The President of the Republic is the "
                "head of state defined by the 2019 Constitution. The First Secretary "
                "of the PCC leads the Communist Party, which under Article 5 of the "
                "Constitution is the 'leading force of the society and the state.' "
                "In Cuban practice the PCC role is the more powerful of the two."
            ),
        ),
    ),
    sources=(
        Source("Wikipedia — Miguel Díaz-Canel", "https://en.wikipedia.org/wiki/Miguel_D%C3%ADaz-Canel"),
        Source("OFAC press release — EO 13818 designation (July 2022)", "https://home.treasury.gov/news/press-releases/jy0875"),
        Source("Granma (PCC official organ)", "https://en.granma.cu/"),
    ),
    sector_path="/sectors/governance",
    sanctioned=True,
    sanctioning_program="EO 13818 (Global Magnitsky)",
    wikidata_id="Q1058356",
    wikipedia_url="https://en.wikipedia.org/wiki/Miguel_D%C3%ADaz-Canel",
    related=("manuel-marrero-cruz", "bruno-rodriguez-parrilla", "alvaro-lopez-miera", "esteban-lazo-hernandez"),
))


_add(Person(
    slug="manuel-marrero-cruz",
    name="Manuel Marrero Cruz",
    aliases=("Manuel Marrero", "Marrero Cruz", "Marrero"),
    role="Prime Minister of Cuba",
    spanish_title="Primer Ministro de la República de Cuba",
    cohorts=("executive", "pcc"),
    one_liner=(
        "Manuel Marrero Cruz has served as Cuba's Prime Minister "
        "since December 2019 — the first to hold the post since it "
        "was abolished in 1976."
    ),
    bio=(
        "Manuel Marrero Cruz became Cuba's first Prime Minister in "
        "more than four decades on 21 December 2019, when the new "
        "2019 Constitution restored the office that Fidel Castro had "
        "abolished in 1976. He had previously served for 15 years as "
        "Minister of Tourism, where he ran Gaviota — the tourism arm "
        "of the military-controlled GAESA holding — and presided over "
        "the boom-and-bust of Cuba's hotel sector.",
        "As Prime Minister, Marrero chairs the Council of Ministers "
        "and is the day-to-day operational head of government beneath "
        "President Díaz-Canel. He has been the public face of the "
        "post-Tarea-Ordenamiento economic agenda — the partial "
        "dollarisation of the economy, the legalisation of MIPYME "
        "private enterprises in 2021, and the ongoing struggle to "
        "stabilise the electricity grid against chronic apagones.",
        "Marrero is also a member of the PCC Politburo. In early "
        "2026 he announced a decentralisation of MIPYME licensing to "
        "the municipal level and renewed the call for a 'different "
        "way' of confronting the crisis, language that drew "
        "scepticism from independent Cuban observers.",
    ),
    born="1963-07-11",
    birthplace="Holguín, Cuba",
    in_office_since="2019-12-21",
    affiliations=(
        "Council of Ministers — President / Prime Minister",
        "Politburo of the PCC",
    ),
    timeline=(
        TimelineEntry("1986", "Graduates as architect, Universidad de Camagüey."),
        TimelineEntry("2004", "Appointed Minister of Tourism — runs the office for 15 years."),
        TimelineEntry("2019", "Appointed Prime Minister of Cuba (December) — first since 1976."),
        TimelineEntry("2021", "Elected to the PCC Politburo at the 8th Congress."),
        TimelineEntry("2026", "Announces municipal-level MIPYME licensing decentralisation (March)."),
    ),
    faqs=(
        FAQ(
            q="Who is Manuel Marrero Cruz?",
            a=(
                "Manuel Marrero Cruz is the Prime Minister of Cuba, in office since "
                "21 December 2019. Before that he served 15 years as Minister of "
                "Tourism, running the Gaviota state hotel group. He also sits on the "
                "Politburo of the Communist Party of Cuba."
            ),
        ),
        FAQ(
            q="What is the role of Cuba's Prime Minister?",
            a=(
                "The Prime Minister chairs the Council of Ministers and is the "
                "operational head of the executive branch under Cuba's 2019 "
                "Constitution. The President of the Republic remains head of state; "
                "the Prime Minister handles the cabinet, ministries and economic "
                "programme. The post had been abolished in 1976 by Fidel Castro and "
                "restored under the 2019 Constitution."
            ),
        ),
    ),
    sources=(
        Source("Wikipedia — Manuel Marrero Cruz", "https://en.wikipedia.org/wiki/Manuel_Marrero_Cruz"),
        Source("Granma — Council of Ministers", "https://en.granma.cu/cuba"),
    ),
    sector_path="/sectors/tourism",
    wikidata_id="Q79358625",
    wikipedia_url="https://en.wikipedia.org/wiki/Manuel_Marrero_Cruz",
    related=("miguel-diaz-canel", "salvador-valdes-mesa", "roberto-morales-ojeda"),
))


_add(Person(
    slug="bruno-rodriguez-parrilla",
    name="Bruno Rodríguez Parrilla",
    aliases=("Bruno Rodriguez", "Bruno Rodríguez", "Rodríguez Parrilla"),
    role="Minister of Foreign Affairs of Cuba (MINREX)",
    spanish_title="Ministro de Relaciones Exteriores de Cuba",
    cohorts=("executive", "pcc"),
    one_liner=(
        "Bruno Rodríguez Parrilla has served as Cuba's Foreign "
        "Minister since 2009 — the longest-serving member of the "
        "current cabinet and Havana's lead voice at the UN."
    ),
    bio=(
        "Bruno Rodríguez Parrilla has led the Cuban Ministry of "
        "Foreign Affairs (MINREX) since 2009, making him by some "
        "distance the longest-serving member of Cuba's current "
        "cabinet. He is best known internationally as the architect "
        "of the annual UN General Assembly resolution condemning the "
        "U.S. embargo, which he has personally introduced almost "
        "every year for more than a decade.",
        "A former president of the Federation of University Students "
        "(FEU), Rodríguez Parrilla rose through the Communist Youth "
        "and the diplomatic service before becoming Vice Minister of "
        "Foreign Affairs in 1995 and then Minister fourteen years "
        "later. He sits on the Politburo of the PCC.",
        "In 2026, Rodríguez Parrilla has been Cuba's primary "
        "international interlocutor through a year of tightened U.S. "
        "policy — meeting with Putin in Moscow, with Spanish Foreign "
        "Minister José Manuel Albares in Madrid, and with Chinese "
        "officials in Beijing. He has been the regime's public face "
        "in pushing back against the second-Trump-administration's "
        "renewed maximum-pressure posture on Cuba.",
    ),
    born="1958-01-23",
    birthplace="Havana, Cuba",
    in_office_since="2009-03-02",
    affiliations=(
        "Ministry of Foreign Affairs (MINREX)",
        "Politburo of the PCC",
        "Council of State",
    ),
    timeline=(
        TimelineEntry("1980s", "Serves as president of the Federation of University Students (FEU)."),
        TimelineEntry("1995", "Appointed Vice Minister of Foreign Affairs."),
        TimelineEntry("2009", "Becomes Minister of Foreign Affairs (March)."),
        TimelineEntry("2021", "Re-elected to the PCC Politburo at the 8th Congress."),
        TimelineEntry("2026", "Tours Moscow, Madrid and Beijing seeking support amid U.S. pressure."),
    ),
    faqs=(
        FAQ(
            q="Who is Bruno Rodríguez Parrilla?",
            a=(
                "Bruno Rodríguez Parrilla is the Minister of Foreign Affairs of Cuba, "
                "head of MINREX, in office since March 2009. He is the longest-serving "
                "minister in Cuba's current cabinet and a member of the Politburo of "
                "the Cuban Communist Party."
            ),
        ),
        FAQ(
            q="What is MINREX?",
            a=(
                "MINREX is the Ministerio de Relaciones Exteriores — the Cuban "
                "foreign ministry, the equivalent of the U.S. State Department. It "
                "runs the Cuban diplomatic service, embassies, consulates and the "
                "annual UN campaign against the U.S. embargo."
            ),
        ),
    ),
    sources=(
        Source("Wikipedia — Bruno Rodríguez Parrilla", "https://en.wikipedia.org/wiki/Bruno_Rodr%C3%ADguez_Parrilla"),
        Source("MINREX (official site)", "https://cubaminrex.cu/en"),
    ),
    sector_path="/sectors/diplomatic",
    wikidata_id="Q1014127",
    wikipedia_url="https://en.wikipedia.org/wiki/Bruno_Rodr%C3%ADguez_Parrilla",
    related=("miguel-diaz-canel", "manuel-marrero-cruz"),
))


_add(Person(
    slug="salvador-valdes-mesa",
    name="Salvador Valdés Mesa",
    aliases=("Salvador Antonio Valdés Mesa",),
    role="Vice President of Cuba",
    spanish_title="Vicepresidente de la República de Cuba",
    cohorts=("executive", "pcc"),
    one_liner=(
        "Salvador Valdés Mesa has been Vice President of Cuba since "
        "2018 and is one of the most senior Afro-Cuban figures in "
        "the Communist Party leadership."
    ),
    bio=(
        "Salvador Antonio Valdés Mesa has served as Vice President "
        "of the Republic of Cuba since 2018, having previously been "
        "First Vice President of the Council of State under Raúl "
        "Castro. He is one of the most senior Black Cubans in the "
        "PCC leadership in a country where Afro-Cubans have "
        "historically been under-represented at the apex of party "
        "structures.",
        "Valdés Mesa rose through the trade-union movement, serving "
        "as general secretary of the Central de Trabajadores de Cuba "
        "(CTC), the official trade union federation, from 2006 to "
        "2013. He was Minister of Labour and Social Security from "
        "1995 to 1999. He sits on the Politburo of the PCC.",
        "As Vice President his portfolio focuses on agriculture and "
        "labour matters; he is a frequent presence at official "
        "events and the Council of Ministers Executive Committee.",
    ),
    born="1945-08-13",
    birthplace="Camagüey, Cuba",
    in_office_since="2018-04-19",
    affiliations=(
        "Council of State",
        "Politburo of the PCC",
        "Central de Trabajadores de Cuba (CTC) — former general secretary",
    ),
    timeline=(
        TimelineEntry("1995", "Appointed Minister of Labour and Social Security."),
        TimelineEntry("2006", "Becomes general secretary of the CTC trade union federation."),
        TimelineEntry("2013", "Elected First Vice President of the Council of State."),
        TimelineEntry("2018", "Becomes Vice President of the Republic of Cuba."),
        TimelineEntry("2021", "Re-elected to the Politburo at the 8th PCC Congress."),
    ),
    faqs=(
        FAQ(
            q="Who is Salvador Valdés Mesa?",
            a=(
                "Salvador Valdés Mesa is the Vice President of Cuba, in office since "
                "April 2018. He is a Politburo member of the Communist Party of Cuba "
                "and a former general secretary of the CTC trade union federation."
            ),
        ),
    ),
    sources=(
        Source("Wikipedia — Salvador Valdés Mesa", "https://en.wikipedia.org/wiki/Salvador_Vald%C3%A9s_Mesa"),
    ),
    sector_path="/sectors/governance",
    wikipedia_url="https://en.wikipedia.org/wiki/Salvador_Vald%C3%A9s_Mesa",
    related=("miguel-diaz-canel", "manuel-marrero-cruz"),
))


_add(Person(
    slug="esteban-lazo-hernandez",
    name="Esteban Lazo Hernández",
    aliases=("Esteban Lazo", "Lazo Hernández", "Lazo Hernandez"),
    role="President of the National Assembly of People's Power",
    spanish_title="Presidente de la Asamblea Nacional del Poder Popular",
    cohorts=("pcc", "executive"),
    one_liner=(
        "Esteban Lazo Hernández is the President of Cuba's National "
        "Assembly (ANPP) and one of the longest-serving members of "
        "the PCC Politburo."
    ),
    bio=(
        "Esteban Lazo Hernández has presided over Cuba's National "
        "Assembly of People's Power (Asamblea Nacional del Poder "
        "Popular, ANPP) since 2013. As Assembly president he also "
        "chairs the Council of State, the standing body that "
        "exercises legislative authority between Assembly sessions "
        "under the 2019 Constitution.",
        "Lazo joined the PCC Politburo in 1991 and is one of its "
        "longest-tenured members. He is, with Salvador Valdés Mesa, "
        "one of the senior Afro-Cuban figures in the Cuban "
        "leadership. Earlier in his career he served as Vice "
        "President of the Council of State and as a provincial "
        "First Secretary of the PCC in Santiago de Cuba.",
        "His role at the head of the ANPP makes him the formal "
        "presiding officer over the legislative ratification of "
        "every law and major appointment in Cuba — including, in "
        "2018 and 2023, the election of Miguel Díaz-Canel to the "
        "presidency.",
    ),
    born="1944-02-26",
    birthplace="Jovellanos, Matanzas, Cuba",
    in_office_since="2013-02-24",
    affiliations=(
        "National Assembly of People's Power (ANPP) — President",
        "Council of State",
        "Politburo of the PCC",
    ),
    timeline=(
        TimelineEntry("1991", "Joins the Politburo of the PCC."),
        TimelineEntry("2013", "Elected President of the National Assembly."),
        TimelineEntry("2018", "Presides over the ANPP session electing Díaz-Canel as President."),
        TimelineEntry("2021", "Re-elected to the Politburo at the 8th PCC Congress."),
        TimelineEntry("2023", "Re-elected President of the National Assembly for a fresh term."),
    ),
    faqs=(
        FAQ(
            q="Who is Esteban Lazo?",
            a=(
                "Esteban Lazo Hernández is the President of Cuba's National Assembly "
                "of People's Power (ANPP), the parliament. He has held the post since "
                "February 2013 and is one of the longest-serving members of the "
                "Communist Party Politburo."
            ),
        ),
        FAQ(
            q="What is the ANPP?",
            a=(
                "The Asamblea Nacional del Poder Popular (ANPP) is Cuba's unicameral "
                "parliament. It elects the President of the Republic, the Prime "
                "Minister, the Council of State and the Council of Ministers, and "
                "ratifies legislation. It meets in plenary sessions twice a year; "
                "between sessions, the Council of State exercises legislative power."
            ),
        ),
    ),
    sources=(
        Source("Wikipedia — Esteban Lazo Hernández", "https://en.wikipedia.org/wiki/Esteban_Lazo_Hern%C3%A1ndez"),
        Source("Parlamento Cubano (official)", "https://www.parlamentocubano.gob.cu/"),
    ),
    sector_path="/sectors/governance",
    wikipedia_url="https://en.wikipedia.org/wiki/Esteban_Lazo_Hern%C3%A1ndez",
    related=("miguel-diaz-canel", "roberto-morales-ojeda"),
))


_add(Person(
    slug="roberto-morales-ojeda",
    name="Roberto Morales Ojeda",
    aliases=("Roberto Morales", "Morales Ojeda"),
    role="Member of the PCC Politburo and Secretariat (cadres)",
    spanish_title="Miembro del Buró Político y Secretariado del PCC",
    cohorts=("pcc",),
    one_liner=(
        "Roberto Morales Ojeda is a Politburo and Secretariat member "
        "of the Cuban Communist Party, with the cadres portfolio "
        "that decides senior Party appointments."
    ),
    bio=(
        "Roberto Tomás Morales Ojeda is a member of both the "
        "Politburo and the Secretariat of the Communist Party of "
        "Cuba. Within the Secretariat his portfolio covers the "
        "internal life of the Party and cadres policy — meaning he "
        "is the senior figure responsible for the selection and "
        "rotation of PCC officials at provincial and national level. "
        "In a one-party state, that brief is one of the most "
        "operationally consequential roles in the country.",
        "Morales was Minister of Public Health from 2010 to 2018, "
        "presiding over the international expansion of Cuba's "
        "medical-mission programme — one of the regime's largest "
        "sources of hard currency. He served as Deputy Prime "
        "Minister from 2018 to 2019 before joining the Secretariat.",
        "He is widely seen as one of the rising figures who could "
        "feature in succession discussions at the 9th PCC Congress, "
        "currently scheduled for April 2026.",
    ),
    born="1967-10-04",
    birthplace="Cienfuegos, Cuba",
    affiliations=(
        "Politburo of the PCC",
        "Secretariat of the PCC — cadres portfolio",
    ),
    timeline=(
        TimelineEntry("2010", "Appointed Minister of Public Health."),
        TimelineEntry("2018", "Becomes Deputy Prime Minister."),
        TimelineEntry("2019", "Joins the Secretariat of the PCC, leaves the cabinet."),
        TimelineEntry("2021", "Re-elected to the Politburo at the 8th Congress."),
    ),
    faqs=(
        FAQ(
            q="Who is Roberto Morales Ojeda?",
            a=(
                "Roberto Morales Ojeda is a member of the Politburo and Secretariat "
                "of the Communist Party of Cuba. He holds the cadres portfolio in "
                "the Secretariat — the brief responsible for senior Party "
                "appointments. He was previously Minister of Public Health "
                "(2010-2018) and a Deputy Prime Minister (2018-2019)."
            ),
        ),
    ),
    sources=(
        Source("PCC official biography", "https://www.pcc.cu/"),
        Source("Wikipedia — Roberto Morales Ojeda", "https://en.wikipedia.org/wiki/Roberto_Morales_Ojeda"),
    ),
    sector_path="/sectors/governance",
    wikipedia_url="https://en.wikipedia.org/wiki/Roberto_Morales_Ojeda",
    related=("miguel-diaz-canel", "esteban-lazo-hernandez"),
))


_add(Person(
    slug="alvaro-lopez-miera",
    name="Álvaro López Miera",
    aliases=("Alvaro Lopez Miera", "Álvaro López-Miera", "López Miera", "Lopez Miera", "Alvaro López Miera"),
    role="Minister of the Revolutionary Armed Forces (FAR)",
    spanish_title="Ministro de las Fuerzas Armadas Revolucionarias (FAR)",
    cohorts=("military", "pcc"),
    one_liner=(
        "Corps General Álvaro López Miera has led Cuba's armed "
        "forces (MINFAR) since April 2021 — and is sanctioned by "
        "OFAC for human-rights abuses tied to the July 2021 protests."
    ),
    bio=(
        "Corps General Álvaro López Miera became Minister of the "
        "Revolutionary Armed Forces (Ministro de las FAR / MINFAR) "
        "on 15 April 2021, succeeding the late General Leopoldo Cintra "
        "Frías. He had previously served as Chief of the General "
        "Staff of the FAR, the institution's senior operational role.",
        "López Miera fought in the Angolan Civil War (Operación "
        "Carlota) and rose steadily through MINFAR command "
        "structures over four decades. He is a member of the PCC "
        "Politburo and of the Council of State. As Minister he "
        "oversees both the conventional armed forces and, "
        "indirectly, the GAESA business holding — Cuba's largest "
        "economic conglomerate.",
        "On 22 July 2021, the U.S. Treasury designated López Miera "
        "and the Cuban National Special Brigade ('Boinas Negras') "
        "under Executive Order 13818 (Global Magnitsky) for serious "
        "human-rights abuses connected to the violent suppression of "
        "the 11 July 2021 protests. The designation remains active "
        "in 2026.",
    ),
    born="1943-12-03",
    birthplace="Havana, Cuba",
    in_office_since="2021-04-15",
    affiliations=(
        "Ministry of the Revolutionary Armed Forces (MINFAR)",
        "Politburo of the PCC",
        "Council of State",
        "Cuban Revolutionary Armed Forces (FAR) — Corps General",
    ),
    timeline=(
        TimelineEntry("1975", "Deployed to Angola — Operación Carlota."),
        TimelineEntry("1998", "Becomes Vice Minister of FAR."),
        TimelineEntry("2011", "Appointed Chief of the General Staff of the FAR."),
        TimelineEntry("2021", "Appointed Minister of FAR (15 April), succeeding Cintra Frías."),
        TimelineEntry("2021", "Designated by OFAC under EO 13818 (Global Magnitsky), 22 July."),
    ),
    faqs=(
        FAQ(
            q="Who is Álvaro López Miera?",
            a=(
                "Álvaro López Miera is the Minister of the Revolutionary Armed Forces "
                "(MINFAR / FAR) of Cuba, in office since 15 April 2021. He holds the "
                "rank of Corps General and is a member of the Politburo of the "
                "Communist Party of Cuba."
            ),
        ),
        FAQ(
            q="Is Álvaro López Miera sanctioned by OFAC?",
            a=(
                "Yes. The U.S. Treasury Office of Foreign Assets Control designated "
                "López Miera under Executive Order 13818 (Global Magnitsky) on 22 July "
                "2021, citing human-rights abuses linked to the suppression of the 11 "
                "July 2021 protests. He remains on the OFAC SDN list. Any U.S. person "
                "dealing with him is generally prohibited under the Cuban Assets "
                "Control Regulations."
            ),
        ),
        FAQ(
            q="What is MINFAR?",
            a=(
                "MINFAR is the Ministerio de las Fuerzas Armadas Revolucionarias — "
                "the Cuban Ministry of the Revolutionary Armed Forces, equivalent to "
                "a Ministry of Defense. It runs the army, navy, air force, and "
                "indirectly controls GAESA, the military-owned conglomerate that "
                "dominates Cuba's tourism, retail, real estate and finance sectors."
            ),
        ),
    ),
    sources=(
        Source("Wikipedia — Álvaro López Miera", "https://en.wikipedia.org/wiki/%C3%81lvaro_L%C3%B3pez_Miera"),
        Source("OFAC press release — July 2021 designations", "https://home.treasury.gov/news/press-releases/jy0288"),
    ),
    sector_path="/sectors/governance",
    sanctioned=True,
    sanctioning_program="EO 13818 (Global Magnitsky)",
    wikipedia_url="https://en.wikipedia.org/wiki/%C3%81lvaro_L%C3%B3pez_Miera",
    related=("lazaro-alvarez-casas", "miguel-diaz-canel"),
))


_add(Person(
    slug="lazaro-alvarez-casas",
    name="Lázaro Alberto Álvarez Casas",
    aliases=("Lazaro Alvarez Casas", "Lázaro Álvarez Casas"),
    role="Minister of the Interior of Cuba (MININT)",
    spanish_title="Ministro del Interior de la República de Cuba",
    cohorts=("military",),
    one_liner=(
        "Army Corps General Lázaro Alberto Álvarez Casas has led "
        "Cuba's Ministry of the Interior (MININT) since November "
        "2020 — and is sanctioned by OFAC under Global Magnitsky."
    ),
    bio=(
        "Lázaro Alberto Álvarez Casas was appointed Minister of the "
        "Interior of Cuba on 24 November 2020 by President Miguel "
        "Díaz-Canel, succeeding Vice Admiral Julio César Gandarilla "
        "Bermejo, who died in office. He was promoted to the rank of "
        "Army Corps General (General de Cuerpo de Ejército) in June "
        "2025.",
        "A law graduate, Álvarez Casas spent most of his career in "
        "Military Counterintelligence before taking over the "
        "Internal Counterintelligence Directorate of MININT in 2015 "
        "and serving as a Vice Minister prior to his promotion to "
        "Minister.",
        "MININT is the parent ministry of the Cuban national police, "
        "the political police (Departamento de Seguridad del Estado, "
        "DSE), the Border Guard Troops, and the prisons system — "
        "every branch of Cuban internal security excluding the FAR "
        "itself. The U.S. Treasury designated MININT and Álvarez "
        "Casas personally under Executive Order 13818 (Global "
        "Magnitsky) on 19 January 2021 for serious human-rights "
        "abuses against protesters and dissidents. The designation "
        "remains active.",
    ),
    in_office_since="2020-11-24",
    affiliations=(
        "Ministry of the Interior (MININT)",
        "Politburo of the PCC",
    ),
    timeline=(
        TimelineEntry("2015", "Becomes head of the Internal Counterintelligence Directorate of MININT."),
        TimelineEntry("2020", "Appointed Minister of the Interior (24 November)."),
        TimelineEntry("2021", "Designated by OFAC under EO 13818 (Global Magnitsky), 19 January."),
        TimelineEntry("2025", "Promoted to General de Cuerpo de Ejército (Army Corps General)."),
    ),
    faqs=(
        FAQ(
            q="Who is Lázaro Álvarez Casas?",
            a=(
                "Lázaro Alberto Álvarez Casas is the Minister of the Interior of Cuba, "
                "head of MININT, in office since 24 November 2020. He holds the rank "
                "of Army Corps General (promoted June 2025) and is a Politburo member."
            ),
        ),
        FAQ(
            q="Is Álvarez Casas sanctioned by the United States?",
            a=(
                "Yes. The U.S. Treasury OFAC designated Álvarez Casas and the "
                "Ministry of the Interior under Executive Order 13818 (Global "
                "Magnitsky) on 19 January 2021 for serious human-rights abuses. "
                "The designation remains active. U.S. persons are generally prohibited "
                "from dealing with him."
            ),
        ),
        FAQ(
            q="What is MININT?",
            a=(
                "MININT is the Ministerio del Interior de Cuba — the Ministry of the "
                "Interior. It oversees the Cuban national police, the State Security "
                "political police (DSE), the Border Guard Troops and the prison "
                "system. Distinct from MINFAR (the armed forces ministry), MININT "
                "handles internal security and intelligence."
            ),
        ),
    ),
    sources=(
        Source("Wikipedia — Lázaro Álvarez Casas (es)", "https://es.wikipedia.org/wiki/L%C3%A1zaro_Alberto_%C3%81lvarez_Casas"),
        Source("OFAC press release — January 2021 MININT designation", "https://home.treasury.gov/news/press-releases/sm1237"),
        Source("Granma — appointment notice (24 Nov 2020)", "https://www.granma.cu/cuba/2020-11-24/promueven-al-cargo-de-ministro-del-interior-al-general-de-brigada-lazaro-alberto-alvarez-casas-24-11-2020-19-11-10"),
    ),
    sector_path="/sectors/governance",
    sanctioned=True,
    sanctioning_program="EO 13818 (Global Magnitsky)",
    related=("alvaro-lopez-miera", "miguel-diaz-canel"),
))


_add(Person(
    slug="yamila-pena-ojeda",
    name="Yamila Peña Ojeda",
    aliases=("Yamila Pena Ojeda",),
    role="Attorney General of Cuba (Fiscal General de la República)",
    spanish_title="Fiscal General de la República de Cuba",
    cohorts=("judiciary",),
    one_liner=(
        "Yamila Peña Ojeda has been Cuba's Attorney General — Fiscal "
        "General de la República — since 2018, the chief criminal "
        "prosecutor of the Cuban state."
    ),
    bio=(
        "Yamila Peña Ojeda was appointed Fiscal General de la "
        "República de Cuba (Attorney General) by the Council of "
        "State on 14 July 2018. The Fiscalía General de la República "
        "is the national criminal-prosecution authority — the office "
        "that brings charges in Cuban courts and oversees lower "
        "Fiscalía offices at the provincial and municipal level.",
        "Peña Ojeda is a specialist in Criminal Law and National "
        "Security and has completed training at the Academy of the "
        "General Prosecutor's Office of the Russian Federation. In "
        "September 2024 she signed a 2025-2026 cooperation programme "
        "with the General Prosecutor's Office of Belarus.",
        "Note on translation: Cuba's Fiscal General is properly "
        "translated as 'Attorney General' in U.S. usage — the office "
        "responsible for criminal prosecution. It is distinct from "
        "Cuba's Procurador General, a different office. Compliance "
        "and diligence searches commonly mistranslate the two.",
    ),
    in_office_since="2018-07-14",
    affiliations=(
        "Fiscalía General de la República de Cuba",
        "Communist Party of Cuba (PCC)",
    ),
    timeline=(
        TimelineEntry("2018", "Appointed Attorney General by the Council of State (14 July)."),
        TimelineEntry("2024", "Signs prosecutor-cooperation agreement with Belarus."),
    ),
    faqs=(
        FAQ(
            q="Who is Yamila Peña Ojeda?",
            a=(
                "Yamila Peña Ojeda is the Attorney General of Cuba — Fiscal General "
                "de la República — in office since July 2018. She heads the Fiscalía "
                "General, the national criminal-prosecution authority."
            ),
        ),
        FAQ(
            q="Is Cuba's Fiscal General the same as a U.S. Attorney General?",
            a=(
                "Yes — Cuba's Fiscal General de la República is the closest analogue "
                "to the U.S. Attorney General: the chief national prosecutor with "
                "authority over criminal cases. Cuba's Procurador General is a "
                "separate office handling state representation in civil litigation. "
                "The two should not be conflated."
            ),
        ),
    ),
    sources=(
        Source("Fiscalía General de la República (official)", "https://www.fgr.gob.cu/directivos/yamila-pena-ojeda"),
        Source("PCC biography", "https://www.pcc.cu/yamila-pena-ojeda"),
    ),
    sector_path="/sectors/legal",
    related=("miguel-diaz-canel", "esteban-lazo-hernandez"),
))


_add(Person(
    slug="jose-daniel-ferrer",
    name="José Daniel Ferrer",
    aliases=("Jose Daniel Ferrer", "José Daniel Ferrer García"),
    role="National Coordinator of UNPACU (Patriotic Union of Cuba)",
    spanish_title="Coordinador Nacional de la Unión Patriótica de Cuba (UNPACU)",
    cohorts=("opposition",),
    status="in_exile",
    one_liner=(
        "José Daniel Ferrer is one of Cuba's best-known opposition "
        "leaders — head of UNPACU and, since October 2025, in exile "
        "in Miami after years of imprisonment."
    ),
    bio=(
        "José Daniel Ferrer García is the founder and National "
        "Coordinator of the Unión Patriótica de Cuba (UNPACU), the "
        "country's largest dissident organisation. A former member "
        "of the 75 prisoners detained in the 2003 'Black Spring' "
        "crackdown, Ferrer has spent more years in Cuban prisons "
        "than free in the last two decades.",
        "Ferrer was released, re-arrested, jailed in 2021 in the "
        "wake of the 11 July protests, and held until October 2025, "
        "when the Cuban government negotiated his exile to the "
        "United States. He arrived in Miami on 13 October 2025 with "
        "his family, ending one of the longest-running political "
        "imprisonments in contemporary Cuba.",
        "From exile, Ferrer has continued to lead UNPACU "
        "operationally and remains one of the most public voices in "
        "the diaspora opposition — appearing in U.S. and Spanish "
        "media, meeting with U.S. policymakers, and publicly "
        "supporting the second Trump administration's tightened "
        "pressure posture on Havana through 2026.",
    ),
    born="1970-07-29",
    birthplace="Santiago de Cuba, Cuba",
    nationality="Cuban (in exile, United States)",
    affiliations=(
        "Unión Patriótica de Cuba (UNPACU) — National Coordinator",
    ),
    timeline=(
        TimelineEntry("2003", "Arrested in the 'Black Spring' crackdown — sentenced to 25 years."),
        TimelineEntry("2011", "Conditionally released after Catholic Church-mediated process."),
        TimelineEntry("2011", "Founds UNPACU."),
        TimelineEntry("2019", "Re-arrested; held in increasingly harsh conditions."),
        TimelineEntry("2021", "Re-arrested in connection with the 11 July nationwide protests."),
        TimelineEntry("2025", "Released into exile; arrives in Miami with family on 13 October."),
        TimelineEntry("2026", "Continues to lead UNPACU from Miami; publicly engages with US policy on Cuba."),
    ),
    faqs=(
        FAQ(
            q="Who is José Daniel Ferrer?",
            a=(
                "José Daniel Ferrer is the founder and National Coordinator of UNPACU "
                "(the Patriotic Union of Cuba), Cuba's largest dissident organisation. "
                "He is one of the country's best-known opposition leaders, having "
                "spent much of the past two decades in Cuban prisons before being "
                "exiled to the United States in October 2025."
            ),
        ),
        FAQ(
            q="Where is José Daniel Ferrer now?",
            a=(
                "Since 13 October 2025, Ferrer has been in Miami, Florida, after the "
                "Cuban government negotiated his release into exile with his family. "
                "He continues to lead UNPACU remotely and is active in U.S. and "
                "diaspora media."
            ),
        ),
        FAQ(
            q="Is José Daniel Ferrer sanctioned by anyone?",
            a=(
                "No. Ferrer is a dissident, not a state actor. He is not on the OFAC "
                "SDN list or any other sanctions list. He has been the recipient of "
                "international human-rights recognition."
            ),
        ),
    ),
    sources=(
        Source("Wikipedia — José Daniel Ferrer", "https://en.wikipedia.org/wiki/Jos%C3%A9_Daniel_Ferrer"),
        Source("UNPACU (official)", "https://www.unpacu.org/"),
    ),
    related=("berta-soler",),
))


_add(Person(
    slug="berta-soler",
    name="Berta Soler",
    aliases=("Berta Soler Fernández",),
    role="Leader of the Damas de Blanco (Ladies in White)",
    spanish_title="Líder de las Damas de Blanco",
    cohorts=("opposition",),
    one_liner=(
        "Berta Soler leads the Damas de Blanco — Cuba's most "
        "internationally recognised women's dissident movement, "
        "winner of the Sakharov Prize and a target of continual "
        "regime harassment."
    ),
    bio=(
        "Berta Soler Fernández is the leader of the Damas de Blanco "
        "(Ladies in White), the Cuban women's dissident movement "
        "founded in 2003 by the wives, mothers and daughters of the "
        "75 men jailed in the 'Black Spring'. The movement is best "
        "known for its weekly Sunday march to and from Mass at the "
        "Iglesia de Santa Rita in the Miramar neighbourhood of "
        "Havana, dressed in white and carrying a single gladiolus.",
        "Soler took over leadership of the movement in 2011 "
        "following the death of founder Laura Pollán. The Damas de "
        "Blanco received the European Parliament's Sakharov Prize "
        "for Freedom of Thought in 2005, and Soler herself has been "
        "awarded the Lech Wałęsa Solidarity Prize.",
        "Soler is subject to continual regime harassment — police "
        "cordons around her home, short-term arbitrary detentions, "
        "and the prevention of attendance at Sunday Mass. On 1 "
        "January 2026 she was arrested while heading to the "
        "Cathedral of Havana for the New Year's Mass for Peace and "
        "released without charge four hours later. In April 2026 "
        "she publicly denounced an intensification of repression "
        "against the movement.",
    ),
    born="1963-08-07",
    birthplace="Matanzas, Cuba",
    affiliations=(
        "Damas de Blanco — Leader",
    ),
    timeline=(
        TimelineEntry("2003", "Damas de Blanco movement founded after the 'Black Spring' arrests."),
        TimelineEntry("2005", "Damas de Blanco awarded the Sakharov Prize."),
        TimelineEntry("2011", "Soler takes over leadership of the movement after Laura Pollán's death."),
        TimelineEntry("2026", "Arrested on 1 January while heading to the Cathedral of Havana."),
        TimelineEntry("2026", "Denounces intensified regime repression in March-April."),
    ),
    faqs=(
        FAQ(
            q="Who is Berta Soler?",
            a=(
                "Berta Soler is the leader of the Damas de Blanco (Ladies in White), "
                "the Cuban women's dissident movement. She has led the movement since "
                "2011 and remains in Cuba despite continual regime harassment."
            ),
        ),
        FAQ(
            q="What are the Damas de Blanco?",
            a=(
                "The Damas de Blanco — Ladies in White — are a Cuban women's "
                "dissident movement founded in 2003 by the female relatives of "
                "political prisoners jailed in the 'Black Spring'. They march each "
                "Sunday to and from Mass dressed in white, carrying a single "
                "gladiolus, calling for the release of political prisoners. The "
                "movement received the Sakharov Prize from the European Parliament "
                "in 2005."
            ),
        ),
    ),
    sources=(
        Source("Wikipedia — Berta Soler (es)", "https://es.wikipedia.org/wiki/Berta_Soler"),
    ),
    related=("jose-daniel-ferrer",),
))


# ── Additional figures (auto-linker coverage) ────────────────────────

_add(Person(
    slug="raul-castro",
    name="Raúl Castro",
    aliases=("Raul Castro", "Castro", "Castro Ruz", "Raúl Castro Ruz"),
    role="Former First Secretary of the Communist Party of Cuba",
    spanish_title="Primer Secretario del PCC (2011–2021); Presidente (2008–2018)",
    cohorts=("pcc", "executive"),
    one_liner=(
        "Raúl Castro led Cuba as President (2008-2018) and PCC First "
        "Secretary (2011-2021), succeeding his brother Fidel and "
        "overseeing the Obama-era thaw and economic reforms."
    ),
    bio=(
        "Raúl Modesto Castro Ruz served as President of Cuba from "
        "2008 to 2018 and as First Secretary of the Communist Party "
        "from 2011 to 2021. He succeeded his brother Fidel Castro "
        "in both roles. Under his leadership Cuba opened diplomatic "
        "relations with the United States (2014-2015), expanded "
        "private-sector activity, and drafted the 2019 Constitution.",
        "Although formally retired from all state and party offices, "
        "Castro remains the single most powerful figure in Cuban "
        "politics through informal influence over the FAR and PCC "
        "old guard. He is sanctioned by the United States.",
    ),
    born="1931-06-03",
    birthplace="Birán, Holguín, Cuba",
    status="former",
    affiliations=(
        "Communist Party of Cuba (PCC) — former First Secretary",
        "Revolutionary Armed Forces (FAR) — former Minister",
    ),
    sector_path="/sectors/governance",
    sanctioned=True,
    sanctioning_program="EO 13818 (Global Magnitsky)",
    wikipedia_url="https://en.wikipedia.org/wiki/Ra%C3%BAl_Castro",
    related=("miguel-diaz-canel", "fidel-castro"),
))


_add(Person(
    slug="fidel-castro",
    name="Fidel Castro",
    aliases=("Fidel Castro Ruz", "Fidel"),
    role="Former Prime Minister and President of Cuba (deceased)",
    spanish_title="Primer Ministro (1959–1976); Presidente (1976–2008)",
    cohorts=("pcc", "executive"),
    status="former",
    one_liner=(
        "Fidel Castro led Cuba from the 1959 Revolution until 2008, "
        "shaping the country's one-party socialist system, its "
        "alliance with the Soviet Union, and its confrontation with "
        "the United States."
    ),
    bio=(
        "Fidel Alejandro Castro Ruz (1926-2016) led Cuba for nearly "
        "five decades — as Prime Minister (1959-1976) and then as "
        "President of the Council of State (1976-2008). He founded "
        "the revolutionary movement that overthrew the Batista "
        "dictatorship, aligned Cuba with the Soviet Union, survived "
        "the Bay of Pigs invasion and the Cuban Missile Crisis, and "
        "built the one-party socialist state that persists today.",
        "Castro stepped down from formal power in 2006-2008 due to "
        "ill health, handing the presidency and eventually the PCC "
        "leadership to his brother Raúl. He died on 25 November 2016.",
    ),
    born="1926-08-13",
    birthplace="Birán, Holguín, Cuba",
    sector_path="/sectors/governance",
    wikipedia_url="https://en.wikipedia.org/wiki/Fidel_Castro",
    related=("raul-castro", "miguel-diaz-canel"),
))


_add(Person(
    slug="alejandro-gil-fernandez",
    name="Alejandro Gil Fernández",
    aliases=("Alejandro Gil", "Gil Fernández"),
    role="Former Minister of Economy and Planning",
    spanish_title="Exministro de Economía y Planificación",
    cohorts=("executive",),
    status="former",
    one_liner=(
        "Alejandro Gil Fernández served as Cuba's Minister of "
        "Economy and Planning and was removed from office amid "
        "corruption allegations."
    ),
    bio=(
        "Alejandro Gil Fernández served as Cuba's Minister of "
        "Economy and Planning from 2018 until his removal in 2024. "
        "He was the architect of the Tarea Ordenamiento monetary "
        "reform and the peso devaluation. His dismissal was "
        "accompanied by corruption allegations — a rare public "
        "acknowledgment of senior-level graft by the Cuban "
        "government.",
    ),
    sector_path="/sectors/governance",
    related=("miguel-diaz-canel", "manuel-marrero-cruz"),
))


_add(Person(
    slug="ricardo-cabrisas-ruiz",
    name="Ricardo Cabrisas Ruiz",
    aliases=("Cabrisas", "Ricardo Cabrisas"),
    role="Deputy Prime Minister and Chief Debt Negotiator",
    spanish_title="Viceprimer Ministro",
    cohorts=("executive",),
    one_liner=(
        "Ricardo Cabrisas Ruiz is Cuba's chief external-debt "
        "negotiator and a Deputy Prime Minister with a decades-long "
        "portfolio over the island's foreign financial obligations."
    ),
    bio=(
        "Ricardo Cabrisas Ruiz has served as Deputy Prime Minister "
        "and as Cuba's lead negotiator on sovereign-debt "
        "restructuring with the Paris Club and bilateral creditors. "
        "He is one of the longest-serving economic officials in "
        "the Cuban government.",
    ),
    sector_path="/sectors/governance",
    related=("miguel-diaz-canel", "manuel-marrero-cruz"),
))


_add(Person(
    slug="rogelio-polanco-fuentes",
    name="Rogelio Polanco Fuentes",
    aliases=("Polanco Fuentes", "Rogelio Polanco"),
    role="Ideology Secretary, Communist Party of Cuba",
    spanish_title="Jefe del Departamento Ideológico del PCC",
    cohorts=("pcc",),
    one_liner=(
        "Rogelio Polanco Fuentes heads the ideology department of "
        "the Cuban Communist Party, overseeing state media, "
        "propaganda, and ideological training."
    ),
    bio=(
        "Rogelio Polanco Fuentes is a member of the PCC Secretariat "
        "responsible for the Party's ideology portfolio — state "
        "media, propaganda, political education, and the ideological "
        "formation of cadres. He is a former Cuban ambassador in "
        "Caracas.",
    ),
    sector_path="/sectors/governance",
    related=("miguel-diaz-canel", "roberto-morales-ojeda"),
))


_add(Person(
    slug="joaquin-alonso-vazquez",
    name="Joaquín Alonso Vázquez",
    aliases=("Joaquín Alonso", "Alonso Vázquez", "Joaquin Alonso"),
    role="President, Banco Central de Cuba",
    spanish_title="Presidente del Banco Central de Cuba",
    cohorts=("executive",),
    one_liner=(
        "Joaquín Alonso Vázquez leads the Central Bank of Cuba, "
        "the institution responsible for monetary policy, exchange "
        "rates, and banking regulation on the island."
    ),
    bio=(
        "Joaquín Alonso Vázquez serves as President of the Banco "
        "Central de Cuba (BCC), the country's central bank and "
        "monetary authority. He oversees monetary policy, foreign "
        "exchange controls, and the banking system amid Cuba's "
        "severe dual-currency and inflation crisis.",
    ),
    sector_path="/sectors/governance",
    related=("miguel-diaz-canel", "alejandro-gil-fernandez"),
))


_add(Person(
    slug="ana-teresa-igarza",
    name="Ana Teresa Igarza",
    aliases=("Igarza",),
    role="Director General, Mariel Special Development Zone (ZEDM)",
    spanish_title="Directora General de la Zona Especial de Desarrollo Mariel",
    cohorts=("executive",),
    one_liner=(
        "Ana Teresa Igarza leads the Mariel Special Development "
        "Zone (ZEDM), Cuba's flagship foreign-investment enclave "
        "west of Havana."
    ),
    bio=(
        "Ana Teresa Igarza has served as Director General of the "
        "Zona Especial de Desarrollo Mariel (ZEDM) — Cuba's "
        "flagship special economic zone. The ZEDM offers foreign "
        "investors tax incentives, streamlined customs, and a "
        "dedicated port and logistics corridor. Igarza is the "
        "public face of Cuba's pitch to foreign capital.",
    ),
    sector_path="/sectors/mariel-zedm",
    related=("miguel-diaz-canel", "manuel-marrero-cruz"),
))


_add(Person(
    slug="luis-alberto-rodriguez-lopez-calleja",
    name="Luis Alberto Rodríguez López-Calleja",
    aliases=(
        "López-Calleja",
        "Lopez-Calleja",
        "Rodríguez López-Calleja",
        "Luis Alberto Rodríguez",
    ),
    role="Former Head of GAESA (deceased)",
    spanish_title="Director del Grupo de Administración Empresarial S.A. (GAESA)",
    cohorts=("military",),
    status="former",
    one_liner=(
        "Luis Alberto Rodríguez López-Calleja ran GAESA, Cuba's "
        "military-owned business conglomerate, until his death in "
        "2022. He was Raúl Castro's son-in-law and one of the most "
        "powerful economic figures in Cuba."
    ),
    bio=(
        "Brigadier General Luis Alberto Rodríguez López-Calleja "
        "headed GAESA (Grupo de Administración Empresarial S.A.), "
        "the military-owned conglomerate that controls much of "
        "Cuba's tourism, retail, real-estate, and financial "
        "infrastructure. He was the son-in-law of Raúl Castro. "
        "He died on 1 July 2022.",
    ),
    sector_path="/sectors/governance",
    sanctioned=True,
    sanctioning_program="EO 13818 (Global Magnitsky)",
    wikipedia_url="https://en.wikipedia.org/wiki/Luis_Alberto_Rodr%C3%ADguez_L%C3%B3pez-Calleja",
    related=("raul-castro", "alvaro-lopez-miera"),
))


# ──────────────────────────────────────────────────────────────────────
# Public helpers
# ──────────────────────────────────────────────────────────────────────

def get_person(slug: str) -> Optional[Person]:
    return PEOPLE.get(slug)


def all_people() -> list[Person]:
    """Return every registered person, sorted by display name."""
    return sorted(PEOPLE.values(), key=lambda p: _surname_key(p.name))


def _surname_key(name: str) -> str:
    parts = name.strip().split()
    if not parts:
        return name.lower()
    return (parts[-1] + " " + " ".join(parts[:-1])).lower()


def people_in_cohort(cohort: str) -> list[Person]:
    """Return every person tagged with the given cohort, sorted by surname."""
    return [p for p in all_people() if cohort in p.cohorts]


def cohort_siblings(person: Person, *, limit: int = 6) -> list[Person]:
    """Return up to `limit` other people in the same primary cohort."""
    out: list[Person] = []
    for p in people_in_cohort(person.primary_cohort):
        if p.slug == person.slug:
            continue
        out.append(p)
        if len(out) >= limit:
            break
    return out


def related_people(person: Person) -> list[Person]:
    """Resolve a person's `related` slugs into Person objects."""
    out: list[Person] = []
    for slug in person.related:
        rp = PEOPLE.get(slug)
        if rp is not None:
            out.append(rp)
    return out


def cohort_label(cohort: str) -> str:
    return COHORTS.get(cohort, {}).get("label", cohort.title())


def cohort_short(cohort: str) -> str:
    return COHORTS.get(cohort, {}).get("short", cohort.title())


def cohort_url(cohort: str) -> str:
    return f"/people/by-role/{cohort}"


# ──────────────────────────────────────────────────────────────────────
# Status badge mapping (used by templates)
# ──────────────────────────────────────────────────────────────────────
#
# Editorial copy lives here, not in the data, so badge wording can
# change without re-touching every Person entry.

STATUS_BADGES: dict[str, dict[str, str]] = {
    "current":          {"text": "",                    "color": ""},
    "former":           {"text": "FORMER OFFICEHOLDER", "color": "#6c757d"},
    "in_us_custody":    {"text": "IN U.S. CUSTODY",     "color": "#cc0000"},
    "in_cuban_custody": {"text": "DETAINED IN CUBA",    "color": "#cc0000"},
    "in_exile":         {"text": "IN EXILE",            "color": "#b8860b"},
}


def status_badge(status: str) -> dict[str, str]:
    return STATUS_BADGES.get(status, STATUS_BADGES["current"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Auto-linker — render-time first-mention linking to /people/<slug>
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_SKIP_ANCESTORS = frozenset(
    {"a", "code", "pre", "h1", "h2", "h3", "h4", "h5", "h6", "script", "style", "title"}
)

_PatternEntry = tuple[re.Pattern[str], str]  # (compiled regex, slug)
_compiled_patterns: list[_PatternEntry] | None = None


def _build_patterns() -> list[_PatternEntry]:
    """Build sorted (longest-label-first) regex patterns for all people."""
    entries: list[tuple[str, str]] = []  # (label, slug)
    for slug, person in PEOPLE.items():
        entries.append((person.name, slug))
        for alias in person.aliases:
            entries.append((alias, slug))

    entries.sort(key=lambda t: len(t[0]), reverse=True)

    patterns: list[_PatternEntry] = []
    for label, slug in entries:
        pat = re.compile(
            r"(?<!\w)" + re.escape(label) + r"(?!\w)",
            re.UNICODE,
        )
        patterns.append((pat, slug))
    return patterns


def _get_patterns() -> list[_PatternEntry]:
    global _compiled_patterns
    if _compiled_patterns is None:
        _compiled_patterns = _build_patterns()
    return _compiled_patterns


def _ancestor_in_skip_set(node: NavigableString) -> bool:
    """Return True if any ancestor tag is in the skip set."""
    parent = node.parent
    while parent is not None:
        if isinstance(parent, Tag) and parent.name in _SKIP_ANCESTORS:
            return True
        parent = parent.parent
    return False


def link_people_in_html(html: str) -> str:
    """Insert first-mention ``/people/<slug>`` links into an HTML fragment.

    Pure function — the input string is never mutated; a new string is
    returned.  Calling this on already-linked HTML is a no-op (names
    inside ``<a>`` tags are skipped).
    """
    if not html:
        return html

    patterns = _get_patterns()
    if not patterns:
        return html

    soup = BeautifulSoup(html, "html.parser")

    text_nodes = [
        node
        for node in list(soup.descendants)
        if isinstance(node, NavigableString)
        and str(node).strip()
    ]

    linked_slugs: set[str] = set()

    for node in text_nodes:
        if _ancestor_in_skip_set(node):
            continue

        text = str(node)
        matches: list[tuple[int, int, str, str]] = []  # (start, end, slug, matched_text)

        for pat, slug in patterns:
            if slug in linked_slugs:
                continue
            m = pat.search(text)
            if m:
                matches.append((m.start(), m.end(), slug, m.group()))

        if not matches:
            continue

        matches.sort(key=lambda t: t[0])

        filtered: list[tuple[int, int, str, str]] = []
        for match in matches:
            if filtered and match[0] < filtered[-1][1]:
                continue
            filtered.append(match)

        fragments: list[NavigableString | Tag] = []
        cursor = 0
        for start, end, slug, matched in filtered:
            if start > cursor:
                fragments.append(NavigableString(text[cursor:start]))

            link = soup.new_tag(
                "a",
                href=f"/people/{slug}",
                target="_blank",
                rel="noopener",
            )
            link.string = matched
            fragments.append(link)
            linked_slugs.add(slug)
            cursor = end

        if cursor < len(text):
            fragments.append(NavigableString(text[cursor:]))

        if fragments:
            node.replace_with(*fragments)

    return str(soup)
