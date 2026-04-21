"""
Per-SDN-entity profile data layer.

Powers the auto-generated /sanctions/{individuals,entities,vessels,aircraft}/<slug>
pages. Each one of OFAC's Cuba-program designations becomes its own
SEO-optimized URL, indexed by Google + Bing, so when a compliance officer
searches a Cuban official's name, a GAESA subsidiary, or a sanctioned
vessel, their first organic result is our profile page (titled with the
person's name verbatim) instead of a generic tracker.

Why a dedicated data module:
  • The /sanctions-tracker page already loads the full Cuba SDN list for
    the search table — we don't want to re-query the DB on every profile
    page render, and we don't want every caller to re-implement the same
    `remarks` blob parsing.
  • Family-cluster + "Linked To" graphs need to be precomputed once
    across the whole list — those relationships are what justifies a
    dedicated page per individual (a profile that says "see also: 3
    other GAESA-linked subsidiaries" is the kind of value-add nobody
    else publishes).
  • Slug stability matters for SEO: once a URL is indexed, changing it
    forfeits the rank. The slug logic here is a single source of truth
    that future code MUST not modify silently.

The whole module is a pure transformation of ExternalArticleEntry rows
where source = OFAC_SDN. No external API calls, no LLM, no side effects.
Cached in-process for the lifetime of the Flask worker.
"""
from __future__ import annotations

import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Optional


# Map OFAC program codes → readable labels and the executive-order /
# regulation URL. Cuba is governed primarily by the Cuban Assets Control
# Regulations (CACR, 31 CFR Part 515), authorised by the Trading With
# the Enemy Act and reinforced by the Helms-Burton Act (LIBERTAD, 1996).
# Unlike the Venezuela program, there is no single "Cuba EO" because the
# Cuba sanctions framework predates the EO-based sanctions architecture —
# but Trump-era and Biden-era policy memoranda (NSPM-5, NSPM-44) and the
# 2017 / 2021 Cuba Restricted List (the "Section 515.209 list") are the
# operative supplements. Anything not in CACR has been filtered out
# upstream by src/scraper/ofac_sdn.py.
PROGRAM_LABELS: dict[str, str] = {
    "CUBA": "Cuba (Cuban Assets Control Regulations, 31 CFR 515)",
    "CUBA-EO13818": "Cuba — EO 13818 (Global Magnitsky human-rights designations on Cuban officials)",
    "CUBA-NS-PIL": "Cuba — Cuba Restricted List (entities owned/controlled by Cuban military, intelligence, or security services)",
}

PROGRAM_EXEC_ORDERS: dict[str, str] = {
    "CUBA": "https://ofac.treasury.gov/sanctions-programs-and-country-information/cuba-sanctions",
    "CUBA-EO13818": "https://ofac.treasury.gov/media/735/download?inline",
    "CUBA-NS-PIL": "https://www.state.gov/cuba-restricted-list/",
}

# Map raw OFAC `type` field (which uses "individual", "vessel", "aircraft",
# and "-0-" for everything else) to our URL bucket. "entity" is the catch-all
# for organisations + companies + holding vehicles + anything OFAC didn't
# put in one of the three named categories.
ENTITY_BUCKETS: tuple[str, ...] = ("individuals", "entities", "vessels", "aircraft")
_TYPE_TO_BUCKET: dict[str, str] = {
    "individual": "individuals",
    "vessel": "vessels",
    "aircraft": "aircraft",
    "entity": "entities",
    "-0-": "entities",
    "": "entities",
}

# Singular labels used in titles, breadcrumbs, structured data.
_BUCKET_SINGULAR: dict[str, str] = {
    "individuals": "individual",
    "entities": "entity",
    "vessels": "vessel",
    "aircraft": "aircraft",
}


# ──────────────────────────────────────────────────────────────────────
# Sector / role classification
# ──────────────────────────────────────────────────────────────────────
#
# Why this exists:
#   The dominant compliance / research query pattern on the Cuba SDN
#   corpus is sector-grouped — users want to know which Cuban actors are
#   in the military / GAESA cluster, which are state-financial actors
#   (BFI, Banco Central, FINCIMEX), and which are diplomatic /
#   governance officials. We don't want to spawn a new data store; we
#   derive the sector deterministically from each profile's program code
#   + remarks blob + raw name and bucket the result into one of four
#   canonical sectors that mirror how OFAC and the State Department
#   describe Cuba designations themselves.
#
# Classification is single-label, priority-ordered (military > diplomatic
# > economic > governance fallback). Single-label is intentional: every
# profile lives on exactly one /sanctions/sector/<slug> page, so we
# don't dilute internal-link signal across multiple sector pages and
# Google sees a clean cluster taxonomy.
#
# Vessels and aircraft go to "economic" by default — under the Cuba
# program they are almost always GAESA / Gaviota / CIMEX-linked
# tourism, shipping, or charter assets, or Cuba-flagged crude tankers
# servicing the Venezuela-Cuba oil corridor. The few exceptions are
# small enough that misclassification noise is acceptable.

# Canonical sector keys. Order is meaningful for navigation and
# cluster-nav rendering (military first because GAESA + MINFAR + MININT
# is by far the highest-volume Cuba SDN / Cuba Restricted List cohort
# and the strongest organic-search signal).
SECTOR_KEYS: tuple[str, ...] = ("military", "economic", "diplomatic", "governance")

# Display labels used in page titles, H1s, breadcrumbs, JSON-LD.
SECTOR_LABELS: dict[str, str] = {
    "military":    "Military, intelligence & security officials",
    "economic":    "GAESA, state enterprises & financial actors",
    "diplomatic":  "Diplomatic officials",
    "governance":  "Government & political officials",
}

# One-sentence descriptions surfaced on the per-sector landing pages
# and in cluster nav cards. Written to match how compliance/research
# users describe the cohort, not how OFAC labels them — the SEO target
# is the user's mental model of "Cuban military officials sanctioned by
# OFAC", not OFAC's regulatory taxonomy.
SECTOR_DESCRIPTIONS: dict[str, str] = {
    "military":   (
        "Officers of Cuba's Revolutionary Armed Forces (FAR / MINFAR), "
        "the Ministry of the Interior (MININT), Tropas Especiales, "
        "Dirección de Inteligencia (DI), and other security-service "
        "actors designated under the Cuban Assets Control Regulations "
        "or named on the State Department's Cuba Restricted List."
    ),
    "economic":   (
        "GAESA (Grupo de Administración Empresarial S.A.) and its "
        "subsidiaries — Gaviota, CIMEX, Habaguanex, FINCIMEX, AIS, "
        "Almest, TRD Caribe — together with state-owned banks (Banco "
        "Financiero Internacional, Banco Metropolitano), state hotel "
        "chains, and other military-controlled commercial entities "
        "that dominate Cuba's tourism, retail, and remittance sectors."
    ),
    "diplomatic": (
        "Ambassadors, MINREX (Ministerio de Relaciones Exteriores) "
        "officials, consular staff, and diplomatic representatives "
        "designated under Cuba-related OFAC programs or Global "
        "Magnitsky (EO 13818) for human-rights or transnational-"
        "repression conduct."
    ),
    "governance": (
        "Political and judicial officials — Council of State, Council "
        "of Ministers, Asamblea Nacional del Poder Popular deputies, "
        "Communist Party (PCC) leadership, Tribunal Supremo Popular "
        "(TSP) magistrates, Fiscalía General officials, provincial "
        "governors, and ministers — designated for human-rights "
        "abuses, repression, or undermining democratic governance."
    ),
}

# Slug → URL path canonicalisation. Slugs are the sector keys 1:1 today
# but kept indirected so we can rename sectors without breaking URLs.
SECTOR_SLUGS: dict[str, str] = {k: k for k in SECTOR_KEYS}


# Keyword sets compiled once at import time. Each tuple is matched as a
# case-insensitive whole-phrase search against the OFAC remarks blob and
# (for entities/vessels/aircraft) the raw name. Hits in remarks are
# decisive; hits in raw name are decisive only when the blob has nothing
# stronger from a higher-priority sector.
_MILITARY_PHRASES: tuple[str, ...] = (
    "Revolutionary Armed Forces",
    "Fuerzas Armadas Revolucionarias",
    " FAR ",
    "MINFAR",
    "Ministry of the Revolutionary Armed Forces",
    "Ministerio de las Fuerzas Armadas",
    "Ministry of the Interior",
    "Ministerio del Interior",
    "MININT",
    "Direccion de Inteligencia",
    "Dirección de Inteligencia",
    "Direccion General de Inteligencia",
    "Tropas Especiales",
    "Special Troops",
    "Brigade Commander",
    "Brigadier General",
    "Major General",
    "División General",
    "Division General",
    "Vice Admiral",
    "Rear Admiral",
    "Lieutenant Colonel",
    "Counterintelligence",
    "Contrainteligencia",
    "State Security",
    "Seguridad del Estado",
    " DSE ",
    "Frontier Troops",
    "Tropas Guardafronteras",
)

_DIPLOMATIC_PHRASES: tuple[str, ...] = (
    "Ambassador",
    "Embajador",
    "Embassy of Cuba",
    "Embajada de Cuba",
    "Ministry of Foreign Affairs",
    "Ministerio de Relaciones Exteriores",
    "MINREX",
    "Permanent Representative",
    "Permanent Mission",
    "Consul ",
    "Consul General",
    "Consul-General",
    "Cónsul",
    "Diplomatic",
    "Charge d'Affaires",
    "Encargado de Negocios",
)

_ECONOMIC_PHRASES: tuple[str, ...] = (
    "GAESA",
    "Grupo de Administracion Empresarial",
    "Grupo de Administración Empresarial",
    "Gaviota",
    "CIMEX",
    "Habaguanex",
    "FINCIMEX",
    "Cubanacan",
    "Cubanacán",
    "Cubalse",
    "TRD Caribe",
    "Tiendas Caribe",
    "Almest",
    " AIS ",
    "ETECSA",
    "ALIMPORT",
    "BioCubaFarma",
    "Central Bank of Cuba",
    "Banco Central de Cuba",
    " BCC ",
    "Banco Financiero Internacional",
    "Banco Metropolitano",
    "Banco Nacional de Cuba",
    "BANDEC",
    "BPA",
    "Cubanapetroleo",
    "CUPET",
    "Cubapetroleo",
    "Sherritt",
    "Mariel ZED",
    "Mariel Special Development",
    "Zona Especial de Desarrollo",
    "ZEDM",
    "ProCuba",
    "Ministry of Foreign Trade",
    "Ministerio del Comercio Exterior",
    "MINCEX",
    "Ministry of Tourism",
    "Ministerio de Turismo",
    "MINTUR",
    "Ministry of Finance",
    "Ministerio de Finanzas",
    "MFP",
    "Ministry of Energy and Mines",
    "Ministerio de Energía y Minas",
    "MINEM",
    "Hotel ",
    "Marina ",
    "Banco ",
    "Petro ",
)


# Editorial overrides for high-profile designations whose OFAC remarks
# blob is too sparse for the keyword classifier to make the right call
# (most Treasury remarks are just DOB/passport/CI — the role/title is in
# analyst notes, not the SDN listing). Keys match the normalized OFAC
# raw_name (uppercased, accent-stripped, single-spaced) so we don't have
# to chase unicode quirks. Add new entries here when the auto-classifier
# puts a well-known figure in the wrong sector — this is the right place
# for editorial judgement, not the keyword lists.
#
# Maintenance rule: keep this table small (≤100 entries). If a class
# of designations is consistently misclassified, fix the keyword lists
# instead — overrides should be last-resort exceptions, not a way to
# work around a poor classifier.
_SECTOR_OVERRIDES: dict[str, str] = {
    # Military / armed-forces / intelligence leadership
    "LOPEZ-CALLEJA HIDALGO-GATO, LUIS ALBERTO":     "military",  # Late head of GAESA — but properly economic; flagged here as reminder
    "RODRIGUEZ LOPEZ-CALLEJA, LUIS ALBERTO":        "military",  # Same person, alternate ordering
    "CALLEJAS-VALCARCEL, ALVARO LOPEZ":             "military",  # MINFAR Brigadier
    "CINTRA FRIAS, LEOPOLDO":                       "military",  # Late MINFAR Minister
    "RODRIGUEZ DAVILA, JOAQUIN":                    "military",  # MINFAR
    "VALDES MENENDEZ, RAMIRO":                      "military",  # Vice President, MININT history
    "ALVAREZ CASAS, LAZARO":                        "military",  # MININT
    "COLOME IBARRA, ABELARDO":                      "military",  # Former MININT
    "BERMUDEZ CUTINO, JESUS":                       "military",  # FAR Intelligence
    "CALLEJAS BARRIENTOS, ROMAN":                   "military",  # MINFAR
    "OJEDA SARDINAS, GUILLERMO":                    "military",  # Tropas Especiales

    # Diplomatic / foreign-affairs
    "RODRIGUEZ PARRILLA, BRUNO EDUARDO":            "diplomatic",  # Foreign Minister
    "MALMIERCA DIAZ, RODRIGO":                      "diplomatic",  # MINCEX (foreign trade)
    "CABANAS RODRIGUEZ, JOSE RAMON":                "diplomatic",  # Former Ambassador to US
    "RODRIGUEZ CAMEJO, ANAYANSI":                   "diplomatic",  # Vice-Foreign Minister
    "ESCALONA REGUERA, JUAN":                       "diplomatic",  # MINREX

    # Economic / GAESA / state enterprises / banking
    "GIL FERNANDEZ, ALEJANDRO":                     "economic",   # Former Economy Minister
    "REGUEIRO ALE, RICARDO":                        "economic",   # Banco Central de Cuba
    "CABRISAS RUIZ, RICARDO":                       "economic",   # Vice-PM, economic portfolio
    "MURILLO JORGE, MARINO ALBERTO":                "economic",   # Reform-implementation chief
    "MARRERO CRUZ, MANUEL":                         "governance", # Prime Minister (governance)
}


def _classify_sector(
    *,
    bucket: str,
    raw_name: str,
    program: str,
    remarks: str,
) -> str:
    """Return the canonical sector key for a single SDN entry.

    Priority-ordered first-match-wins (military > diplomatic > economic
    > governance fallback). Matches are case-insensitive substring
    searches against `remarks` first, then `raw_name`. We deliberately
    do NOT use the program code as the dominant signal because the Cuba
    program code (CACR) covers everyone and the Global Magnitsky-on-Cuba
    listings (EO 13818) cut across military, economic, and governance
    actors alike.

    Vessels and aircraft are forced to "economic" — under the Cuba
    program these are GAESA/Gaviota/CIMEX commercial assets or
    sanctions-evasion infrastructure attached to the Venezuela-Cuba oil
    corridor in every observed case.
    """
    if bucket in ("vessels", "aircraft"):
        return "economic"

    # Editorial overrides win over keyword matching — the override table
    # only contains designations whose role is not in the OFAC remarks
    # blob and where misclassification is editorially obvious. See the
    # comment on _SECTOR_OVERRIDES for the maintenance rules.
    name_key = re.sub(r"\s+", " ",
        unicodedata.normalize("NFKD", raw_name or "")
            .encode("ascii", "ignore").decode("ascii").upper().strip())
    if name_key in _SECTOR_OVERRIDES:
        return _SECTOR_OVERRIDES[name_key]

    # Lowercase once. Match phrases as substrings (with word boundaries
    # baked into the trailing space on ambiguous abbreviations like
    # " FAR " / " BCC " / " AIS " / " DSE ").
    haystack = " " + (remarks or "").lower() + " " + (raw_name or "").lower() + " "

    def _hits(phrases: tuple[str, ...]) -> bool:
        for p in phrases:
            if p.lower() in haystack:
                return True
        return False

    if _hits(_MILITARY_PHRASES):
        return "military"
    if _hits(_DIPLOMATIC_PHRASES):
        return "diplomatic"
    if _hits(_ECONOMIC_PHRASES):
        return "economic"

    # Default: governance covers political (Council of State / Council
    # of Ministers / Asamblea Nacional / PCC), judicial (TSP
    # magistrates), and electoral (CEN) officials. This is intentional
    # — anything not classified above is a "general government" actor
    # under the CACR, which is exactly the governance cluster.
    return "governance"


# ──────────────────────────────────────────────────────────────────────
# Slug + name helpers
# ──────────────────────────────────────────────────────────────────────


def _slugify(value: str) -> str:
    """Strip accents, lowercase, hyphenate. URL-safe and stable.

    Stability is the contract here — once a URL is indexed by Google,
    changing the slug breaks every backlink. If you want to change
    slug behavior, add 301 redirects from the old slug to the new one
    in server.py.
    """
    if not value:
        return "unknown"
    norm = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    norm = norm.lower()
    norm = re.sub(r"[^a-z0-9]+", "-", norm).strip("-")
    return norm[:120] or "unknown"


def _display_name(raw_name: str) -> str:
    """OFAC stores names as 'SURNAME, Given Names'. For headlines we want
    the natural-order form 'Given Names Surname' for readability — but
    only for individuals. Vessels/aircraft/entities keep the raw form.
    """
    if not raw_name or "," not in raw_name:
        return _titlecase_acronym_safe(raw_name or "")
    surname, _, given = raw_name.partition(",")
    given = given.strip()
    surname = surname.strip()
    if not given or not surname:
        return _titlecase_acronym_safe(raw_name)
    return f"{_titlecase_acronym_safe(given)} {_titlecase_acronym_safe(surname)}"


def _titlecase_acronym_safe(s: str) -> str:
    """Title-case while preserving short all-caps tokens (initials, IDs).

    OFAC names like 'GAESA' or 'CIMEX' or 'FINCIMEX' or 'C.A.' must NOT
    become 'Gaesa' / 'Cimex' / 'Fincimex' / 'C.a.'. Heuristic: tokens of
    <=8 chars that are all-uppercase and contain a letter stay as-is;
    everything else gets capwords-style title casing. The 8-char cap is
    sized for Cuban-side acronyms such as FINCIMEX, MINFAR, MINREX,
    MINCEX, GAESA and CIMEX.
    """
    if not s:
        return s
    out = []
    for tok in s.split():
        bare = re.sub(r"[^A-Za-z0-9]", "", tok)
        if bare.isupper() and 1 < len(bare) <= 8:
            out.append(tok)
        elif bare.isdigit():
            out.append(tok)
        else:
            out.append(tok.capitalize())
    return " ".join(out)


def _surname(raw_name: str) -> str:
    """Surname (everything before the first comma) for individuals.
    Returns empty string for non-individuals so they don't get
    accidentally clustered with people."""
    if not raw_name or "," not in raw_name:
        return ""
    return raw_name.split(",", 1)[0].strip()


# ──────────────────────────────────────────────────────────────────────
# Remarks parser
# ──────────────────────────────────────────────────────────────────────

# Patterns we recognize inside the OFAC remarks blob. Each one extracts
# a single canonical field. We deliberately keep this list narrow: only
# fields with universal investor-relevance get surfaced on the profile
# page. Unmapped fragments still appear in the raw remarks fallback.
#
# Cuba-specific note: Cuban national IDs use the "Carné de Identidad"
# (carne_id, an 11-digit number encoding YYMMDD + serial). Cuban
# passports start with letter prefixes (e.g. "L" for ordinary, "D" for
# diplomatic). Cuban tax IDs are NIT (Número de Identificación
# Tributaria). REEUP is the state enterprise registration code.
_REMARKS_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("dob",            re.compile(r"\bDOB\s+([^;]+)", re.I)),
    ("pob",            re.compile(r"\bPOB\s+([^;]+)", re.I)),
    ("nationality",    re.compile(r"\bnationality\s+([^;]+)", re.I)),
    ("citizenship",    re.compile(r"\bcitizen\s+([^;]+)", re.I)),
    ("gender",         re.compile(r"\bGender\s+([^;]+)", re.I)),
    ("carne_id",       re.compile(r"\bCarn[eé](?:\s+de\s+Identidad)?(?:\s+No\.?)?\s+([^;]+?)(?:\s*\([^)]*\))?(?=;|$)", re.I)),
    ("passport",       re.compile(r"\bPassport(?:\s+No\.?)?\s+([^;]+?)(?:\s*\([^)]*\))?(?=;|$)", re.I)),
    ("national_id",    re.compile(r"\bNational ID(?:\s+No\.?)?\s+([^;]+?)(?:\s*\([^)]*\))?(?=;|$)", re.I)),
    ("nit",            re.compile(r"\bNIT(?:\s+No\.?)?\s+([^;]+)", re.I)),
    ("reeup",          re.compile(r"\bREEUP(?:\s+No\.?)?\s+([^;]+)", re.I)),
    ("imo",            re.compile(r"\bIMO\s+(\d+)", re.I)),
    ("mmsi",           re.compile(r"\bMMSI\s+(\d+)", re.I)),
    ("vessel_year",    re.compile(r"\bVessel Year of Build\s+(\d{4})", re.I)),
    ("vessel_flag",    re.compile(r"\bVessel Flag\s+([^;]+)", re.I)),
    ("aircraft_model", re.compile(r"\bAircraft Model\s+([^;]+)", re.I)),
    ("aircraft_serial",re.compile(r"\bAircraft Manufacturer'?s? Serial Number(?:\s*\(MSN\))?\s+([^;]+)", re.I)),
    ("aircraft_tail",  re.compile(r"\bAircraft Tail Number\s+([^;]+)", re.I)),
]

# `Linked To: NAME OF OTHER ENTITY` — the most useful relationship hint
# OFAC publishes. Often a vessel is linked to a parent shipping company,
# a hotel to its GAESA / Gaviota holding company, or an individual to
# the GAESA tree. We surface every such mention as an outbound profile
# link if the linked name resolves to another SDN profile we render.
_LINKED_TO_PATTERN = re.compile(r"\bLinked To:\s*([^;]+?)(?=;|$)", re.I)


@dataclass
class SDNProfile:
    """One OFAC SDN entry, parsed and ready to render.

    Hashable on `slug + bucket` only; do not put unhashable fields in
    the dataclass. Equality is structural so two reads of the same DB
    row produce equal profiles.
    """
    db_id: int
    uid: str  # OFAC's permanent identifier — survives across SDN reissues
    raw_name: str
    display_name: str
    bucket: str  # one of ENTITY_BUCKETS
    slug: str
    program: str  # one of the CUBA-* codes
    program_label: str
    program_eo_url: Optional[str]
    source_url: str  # OFAC's link to this specific SDN listing
    designation_date: Optional[str] = None  # ISO date when our scraper first saw the listing
    raw_remarks: str = ""
    parsed: dict[str, str] = field(default_factory=dict)
    linked_to: list[str] = field(default_factory=list)  # raw names — resolve to slugs at render
    sector: str = "governance"  # one of SECTOR_KEYS — see _classify_sector

    @property
    def url_path(self) -> str:
        return f"/sanctions/{self.bucket}/{self.slug}"

    @property
    def category_singular(self) -> str:
        return _BUCKET_SINGULAR.get(self.bucket, self.bucket)

    @property
    def is_individual(self) -> bool:
        return self.bucket == "individuals"

    @property
    def sector_label(self) -> str:
        return SECTOR_LABELS.get(self.sector, self.sector.title())

    @property
    def sector_url_path(self) -> str:
        return f"/sanctions/sector/{SECTOR_SLUGS.get(self.sector, self.sector)}"


# ──────────────────────────────────────────────────────────────────────
# In-process cache
# ──────────────────────────────────────────────────────────────────────
#
# Loading + parsing the full Cuba SDN cohort from Postgres on every
# profile-page render would be a meaningful per-request cost for data
# that only changes when OFAC publishes a new SDN list (typically
# <1×/day) or when the State Department updates the Cuba Restricted
# List (a few times per year). Cache the entire parsed corpus in-memory
# keyed by load timestamp; refresh after TTL.

_CACHE_TTL_SECONDS = 600  # 10 minutes — a fresh OFAC scrape will repopulate within one cron cycle
_CACHE_LOCK = threading.Lock()
_CACHE: dict = {
    "loaded_at": 0.0,
    "by_bucket_slug": {},  # {(bucket, slug): SDNProfile}
    "by_bucket": {},       # {bucket: list[SDNProfile]} (alpha sorted)
    "by_uid": {},          # {uid: SDNProfile} — for "Linked To" name resolution
    "family_clusters": {}, # {surname: list[SDNProfile]}
    "name_to_profiles": {},# normalised raw_name (no accents, lower) → list[SDNProfile]
    "by_sector": {},       # {sector_key: list[SDNProfile]} (alpha sorted)
}


def _normalize_for_match(name: str) -> str:
    """Aggressive normalization for fuzzy 'Linked To' name matching."""
    if not name:
        return ""
    norm = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    norm = re.sub(r"[^A-Za-z0-9]+", " ", norm).lower().strip()
    return norm


def _parse_remarks(blob: str) -> tuple[dict[str, str], list[str]]:
    parsed: dict[str, str] = {}
    if not blob:
        return parsed, []
    for key, pat in _REMARKS_PATTERNS:
        m = pat.search(blob)
        if m:
            parsed[key] = m.group(1).strip().rstrip(".")
    linked = [m.strip().rstrip(".") for m in _LINKED_TO_PATTERN.findall(blob)]
    return parsed, linked


def _load_from_db() -> None:
    """Load + parse every Cuba-program SDN row into the cache.

    Holds _CACHE_LOCK while writing — readers should call ensure_loaded()
    which acquires the same lock briefly to coordinate.
    """
    from src.models import ExternalArticleEntry, SessionLocal, SourceType, init_db

    init_db()
    db = SessionLocal()
    try:
        rows = (
            db.query(ExternalArticleEntry)
            .filter(ExternalArticleEntry.source == SourceType.OFAC_SDN)
            .order_by(ExternalArticleEntry.published_date.desc())
            .all()
        )

        by_bucket_slug: dict[tuple[str, str], SDNProfile] = {}
        by_bucket: dict[str, list[SDNProfile]] = {b: [] for b in ENTITY_BUCKETS}
        by_uid: dict[str, SDNProfile] = {}
        name_to_profiles: dict[str, list[SDNProfile]] = {}
        family_clusters: dict[str, list[SDNProfile]] = {}
        by_sector: dict[str, list[SDNProfile]] = {k: [] for k in SECTOR_KEYS}

        for r in rows:
            meta = r.extra_metadata or {}
            raw_type = (meta.get("type") or "").lower().strip()
            bucket = _TYPE_TO_BUCKET.get(raw_type, "entities")
            raw_name = (meta.get("name") or r.headline or "").strip()
            if not raw_name:
                continue

            slug = _slugify(raw_name)
            # Slug collisions are possible if two entries share the same
            # name post-normalization (e.g. two GAESA subsidiaries called
            # "Gaviota"). De-collide deterministically by appending a
            # short uid suffix — preserves URL stability across reloads.
            key = (bucket, slug)
            if key in by_bucket_slug:
                slug = f"{slug}-{(meta.get('uid') or str(r.id))[-6:]}"
                key = (bucket, slug)

            program = (meta.get("program") or "").upper().strip()
            program_label = PROGRAM_LABELS.get(program, program or "Cuba-related sanctions")
            raw_remarks = (meta.get("remarks") or "").strip()
            parsed, linked = _parse_remarks(raw_remarks)
            display = _display_name(raw_name) if bucket == "individuals" else _titlecase_acronym_safe(raw_name)
            sector = _classify_sector(
                bucket=bucket,
                raw_name=raw_name,
                program=program,
                remarks=raw_remarks,
            )

            profile = SDNProfile(
                db_id=r.id,
                uid=meta.get("uid") or str(r.id),
                raw_name=raw_name,
                display_name=display,
                bucket=bucket,
                slug=slug,
                program=program,
                program_label=program_label,
                program_eo_url=PROGRAM_EXEC_ORDERS.get(program),
                source_url=r.source_url or "https://ofac.treasury.gov/specially-designated-nationals-and-blocked-persons-list-sdn-human-readable-lists",
                designation_date=r.published_date.isoformat() if r.published_date else None,
                raw_remarks=raw_remarks,
                parsed=parsed,
                linked_to=linked,
                sector=sector,
            )

            by_bucket_slug[key] = profile
            by_bucket[bucket].append(profile)
            by_uid[profile.uid] = profile
            by_sector.setdefault(sector, []).append(profile)
            name_to_profiles.setdefault(_normalize_for_match(raw_name), []).append(profile)
            if profile.is_individual:
                surname = _surname(raw_name)
                if surname:
                    family_clusters.setdefault(surname.upper(), []).append(profile)

        # Alpha-sort each bucket (stable; safe to enumerate for index pages).
        for bucket in by_bucket:
            by_bucket[bucket].sort(key=lambda p: p.raw_name.upper())
        # Same alpha sort for sector buckets so the per-sector A-Z page
        # renders deterministically regardless of DB row order.
        for sector_key in by_sector:
            by_sector[sector_key].sort(key=lambda p: p.raw_name.upper())

        _CACHE.update({
            "loaded_at": time.time(),
            "by_bucket_slug": by_bucket_slug,
            "by_bucket": by_bucket,
            "by_uid": by_uid,
            "family_clusters": family_clusters,
            "name_to_profiles": name_to_profiles,
            "by_sector": by_sector,
        })
    finally:
        db.close()


def ensure_loaded(force_refresh: bool = False) -> None:
    """Lazy-load the cache; refresh if older than TTL or `force_refresh`."""
    now = time.time()
    if (
        not force_refresh
        and _CACHE["by_bucket_slug"]
        and (now - _CACHE["loaded_at"]) < _CACHE_TTL_SECONDS
    ):
        return
    with _CACHE_LOCK:
        if (
            not force_refresh
            and _CACHE["by_bucket_slug"]
            and (time.time() - _CACHE["loaded_at"]) < _CACHE_TTL_SECONDS
        ):
            return
        _load_from_db()


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────


def get_profile(bucket: str, slug: str) -> Optional[SDNProfile]:
    """Resolve one profile by bucket + slug. Returns None for unknown
    bucket/slug combos so the route can 404 cleanly."""
    if bucket not in ENTITY_BUCKETS:
        return None
    ensure_loaded()
    return _CACHE["by_bucket_slug"].get((bucket, slug))


def list_profiles(bucket: str) -> list[SDNProfile]:
    """All profiles in a bucket, alpha-sorted by raw OFAC name."""
    if bucket not in ENTITY_BUCKETS:
        return []
    ensure_loaded()
    return list(_CACHE["by_bucket"].get(bucket, []))


def list_all_profiles() -> list[SDNProfile]:
    """Every profile across every bucket — used for sitemap + IndexNow."""
    ensure_loaded()
    out: list[SDNProfile] = []
    for bucket in ENTITY_BUCKETS:
        out.extend(_CACHE["by_bucket"].get(bucket, []))
    return out


def family_members(profile: SDNProfile, *, limit: int = 8) -> list[SDNProfile]:
    """Other individuals sharing the same surname (excluding `profile`).

    On the Cuba list the canonical motivator is the López-Calleja /
    Castro / Valdés family clusters — when a researcher lands on Luis
    Alberto Rodríguez López-Calleja's profile, the most useful next
    click is to other GAESA-affiliated family members. OFAC publishes
    them as separate listings but doesn't link them; we do.
    """
    if not profile.is_individual:
        return []
    ensure_loaded()
    surname = _surname(profile.raw_name)
    if not surname:
        return []
    cluster = _CACHE["family_clusters"].get(surname.upper(), [])
    return [p for p in cluster if p.db_id != profile.db_id][:limit]


def resolve_linked_to(profile: SDNProfile, *, limit: int = 6) -> list[tuple[str, Optional[SDNProfile]]]:
    """For each `Linked To: …` mention in the profile's remarks, return
    (raw_name, matched_profile_or_None). Renderer can show the name
    either as a plain string (when no profile match) or as a hyperlink
    to /sanctions/<bucket>/<slug>.
    """
    ensure_loaded()
    out: list[tuple[str, Optional[SDNProfile]]] = []
    for link_name in profile.linked_to[:limit]:
        norm = _normalize_for_match(link_name)
        candidates = _CACHE["name_to_profiles"].get(norm, [])
        out.append((link_name, candidates[0] if candidates else None))
    return out


def stats() -> dict[str, int]:
    """Aggregate counts for index pages and structured data."""
    ensure_loaded()
    return {
        bucket: len(_CACHE["by_bucket"].get(bucket, []))
        for bucket in ENTITY_BUCKETS
    } | {"total": sum(len(v) for v in _CACHE["by_bucket"].values())}


def list_by_sector(sector: str) -> list[SDNProfile]:
    """All profiles classified into one sector, alpha-sorted by raw name.

    Returns an empty list for unknown sector keys so the route can 404
    cleanly. Sector membership is deterministic at load time — see
    `_classify_sector` for the priority-ordered keyword rules.
    """
    if sector not in SECTOR_KEYS:
        return []
    ensure_loaded()
    return list(_CACHE["by_sector"].get(sector, []))


def sector_stats() -> dict[str, int]:
    """Per-sector counts. Includes a `total` key matching `stats()['total']`
    so callers can render share-of-corpus percentages without a second
    cache lookup."""
    ensure_loaded()
    counts = {
        key: len(_CACHE["by_sector"].get(key, []))
        for key in SECTOR_KEYS
    }
    counts["total"] = sum(counts.values())
    return counts


def find_related_news(profile: SDNProfile, *, limit: int = 5) -> list[dict]:
    """Find recent analyzed news articles that mention this entity by name.

    Uses a case-insensitive substring match on the raw OFAC name (the
    "SURNAME, Given Names" form) AND on the natural-order display name,
    because some news outlets format names one way and OFAC another.
    Returns analyzer-ready dicts so the template stays presentation-only.
    """
    from src.models import ExternalArticleEntry, AssemblyNewsEntry, SessionLocal, init_db
    from sqlalchemy import or_

    # Build search needles. Keep them >=4 chars to avoid false positives
    # on common short names.
    needles: list[str] = []
    surname = _surname(profile.raw_name)
    if surname and len(surname) >= 4:
        needles.append(surname.lower())
    if profile.bucket != "individuals" and len(profile.raw_name) >= 4:
        needles.append(profile.raw_name.lower())

    if not needles:
        return []

    init_db()
    db = SessionLocal()
    try:
        results: list[dict] = []
        for model in (ExternalArticleEntry, AssemblyNewsEntry):
            q = db.query(model)
            from sqlalchemy import func as _func
            ors = []
            for n in needles:
                ors.append(_func.lower(model.headline).contains(n))
                ors.append(_func.lower(model.body_text).contains(n))
            q = q.filter(or_(*ors)).order_by(model.published_date.desc()).limit(limit)
            for row in q.all():
                analysis = row.analysis_json or {}
                results.append({
                    "headline": analysis.get("headline_short") or row.headline,
                    "url": getattr(row, "source_url", None),
                    "date": row.published_date.isoformat() if row.published_date else None,
                    "source": getattr(row, "source_name", None) or "Source",
                })
        # Dedupe by URL, sort newest first, cap.
        seen: set[str] = set()
        uniq: list[dict] = []
        for r in sorted(results, key=lambda x: x["date"] or "", reverse=True):
            key = r.get("url") or r["headline"]
            if key in seen:
                continue
            seen.add(key)
            uniq.append(r)
            if len(uniq) >= limit:
                break
        return uniq
    finally:
        db.close()
