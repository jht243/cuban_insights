# Cuba data sources — scraper research

This document is the result of a one-shot research pass before Phase 2 of the
Caracas Research → Cuban Insights migration. It catalogues every candidate
data source for the rebuild, with reachability notes from live probes, the
recommended access mechanism, and the known gotchas. Update it as scrapers
land and we learn more from production.

Last refreshed: 2026-04-20.

---

## Tier 1 — Primary, must-have sources (build first)

### 1. Banco Central de Cuba — official FX rate

- **Mechanism:** **Public REST API.** Confirmed live (HTTP 200, structured JSON).
- **Endpoints:**
  - `GET https://api.bc.gob.cu/v1/tasas-de-cambio/activas` — current day, all currencies × all 3 segments.
  - `GET https://api.bc.gob.cu/v1/tasas-de-cambio/historico?fechaInicio=YYYY-MM-DD&fechaFin=YYYY-MM-DD&codigoMoneda=USD` — historical series.
- **Payload shape:** array of `{ codigoMoneda, nombreMoneda, tasaOficial, tasaPublica, tasaEspecial, fechaDia, estado, ... }`. `tasaOficial` ≈ Segment I (state companies), `tasaPublica` ≈ Segment II (special), `tasaEspecial` ≈ Segment III (population / FGNE — the one most retail-relevant).
- **Cadence to scrape:** twice daily (matches BCC's own publishing rhythm).
- **Auth / rate limit:** none documented; behaves like an unauthenticated public service.
- **Risks:** the API is undocumented in any formal sense and could disappear without notice; cache the last-good response. Tracker: confirmation that `tasaOficial` field is the right one to publish as the headline number.
- **Maps to:** `SourceType.BCC_RATES`.
- **Replaces:** `BCVRatesScraper` (Venezuela) entirely. Drop the HTML/scrape path.

### 2. El Toque — informal/parallel CUP/MLC/USD/EUR rate

- **Mechanism:** **Authenticated REST API (free beta tier).** Scraping is
  explicitly prohibited by the publisher.
- **Base URL (per their docs):** `https://tasas.eltoque.com/`. Full endpoint
  catalogue is gated behind the API key signup form at
  `https://dev.eltoque.com/eltoque-abre-acceso-a-su-api-de-las-tasas-de-cambio`.
- **Auth:** API key issued via email after submitting the form (project name +
  intended use + accept ToS). One-time approval.
- **Rate limit:** 5,000 req/month free during beta. We need ~60/month.
- **Attribution:** mandatory — must reference elTOQUE as the data source on
  every page that displays the number. Already covered by our `report.html.j2`
  footer.
- **Cadence:** twice daily. Cache aggressively.
- **Risks:** beta status means terms could change; pricing could become
  paid-tier; API key could be revoked. **Action item for the user: apply for
  the API key before this scraper is built.**
- **Maps to:** `SourceType.ELTOQUE_RATE`.
- **Replaces:** nothing — this is net-new surface area Venezuela never had an
  equivalent for.

### 3. Gaceta Oficial de la República de Cuba — official gazette

- **Mechanism:** HTML scraping. **No public API or RSS.** PDFs are
  downloadable per gazette.
- **Entry points:**
  - `https://www.gacetaoficial.gob.cu/es` — homepage shows the latest gazette
    and the unique norm identifier (`GOC-YYYY-NNN-{O|EX}NN`).
  - `https://www.gacetaoficial.gob.cu/es/servicios` — listing of recent norms
    with summaries and "Leer más" links.
  - Per-issue page pattern: `https://www.gacetaoficial.gob.cu/es/gaceta-oficial-no-{N}-{ordinaria|extraordinaria}-de-{YYYY}`.
- **Reachability:** confirmed serves **HTTP 403 to default User-Agents** (live
  probe). Send a Mozilla-style UA header and HTML loads fine. Common pattern
  for `.gob.cu` government sites.
- **Cadence:** several issues per month (Ordinaria) plus ad-hoc Extraordinaria.
- **Document type:** PDF for full text; the site also exposes a per-norm summary
  ("Resumen") in HTML that's enough for our analyzer pipeline.
- **OCR:** PDFs are typically text-layered (no Tesseract needed).
- **Risks:** the site rewrites occasionally; HTML structure has changed twice in
  the last 24 months. Keep the parser tolerant. Render IPs may eventually be
  geo-blocked from Cuba — we'll see in production.
- **Maps to:** `SourceType.GACETA_OFICIAL_CU`.
- **Replaces:** `OfficialGazetteScraper` and `TuGacetaScraper` (Venezuela).

### 4. Asamblea Nacional del Poder Popular — legislature

- **Mechanism:** HTML scraping; same UA gotcha as Gaceta (HTTP 403 to default
  curl).
- **Entry points:**
  - `https://www.parlamentocubano.gob.cu/labor-legislativa` — the most
    valuable URL: a flat list of approved laws with PDF links, each tagged with
    its Gaceta number. Mirrors what the Gaceta scraper would surface but is
    more structured (one row per law, not one row per gazette issue).
  - `https://www.parlamentocubano.gob.cu/noticias/...` — session announcements
    and convocations (e.g., "Sexto Período Ordinario de Sesiones").
  - `https://www.parlamentocubano.gob.cu/actividad` — agenda.
- **Cadence:** sessions are quarterly + extraordinary; the legislative-work
  page updates as bills clear.
- **Backup source:** `granma.cu` covers every session in detail — see Tier 2.
- **Maps to:** `SourceType.ASAMBLEA_NACIONAL_CU`.
- **Replaces:** `AssemblyScraper` (Venezuela).

### 5. OFAC — SDN list (Cuba slice)

- **Mechanism:** unchanged from the Venezuela build — same OFAC SDN feed (CSV
  + XML at `https://www.treasury.gov/ofac/downloads/`), same parser. **Only
  the program-code filter changes.**
- **Filter:** `VENEZUELA_PROGRAMS = {"VENEZUELA", "VENEZUELA-EO13884", ...}`
  → `CUBA_PROGRAMS = {"CUBA"}`. Verified live: e.g., CUBANACAN GROUP and
  CUBATABACO both list `Program: CUBA` exactly.
- **Maps to:** `SourceType.OFAC_SDN` (unchanged enum).
- **No new scraper needed**, just the filter swap in
  `src/scraper/ofac_sdn.py` and `src/data/sdn_profiles.py::PROGRAM_LABELS`.

### 6. State Department — Cuba Restricted List (CRL) **— missing from the original migration plan**

- **Mechanism:** HTML scraping of a single page, parse the entity list.
- **URL:** `https://www.state.gov/cuba-sanctions/cuba-restricted-list/`
  (also at `/division-for-counter-threat-finance-and-sanctions/cuba-restricted-list/`).
- **What it is:** entities under MINFAR / MININT / GAESA control that
  31 CFR 515.209 prohibits direct financial transactions with. Distinct from
  the OFAC SDN list — most CRL entries are NOT on the SDN.
- **Categories:** Ministries, Holding Companies, Hotels (by province), Stores,
  Defense/security service entities. ~200 entries, ~10–20 added per update.
- **Cadence:** 2–4 updates per year; each update is published via Federal
  Register Notice from State (e.g., the July 14, 2025 update added "Torre K",
  Grand Aston, Bristol Kempinski).
- **Why it matters:** companies on the CRL are the headline list our
  `/companies/<slug>/cuba-exposure` tool needs to flag. Marriott is on it
  (Four Points by Sheraton Havana via GAESA). Also the foundation of any
  Mariel ZED / Gaviota / CIMEX / Habaguanex coverage.
- **New `SourceType`:** `STATE_DEPT_CRL`.

### 7. State Department — Cuba Prohibited Accommodations List (CPAL) **— missing from the original migration plan**

- **Mechanism:** HTML scraping; structurally simpler than the CRL (just a list
  of hotel addresses).
- **URL:** `https://www.state.gov/cuba-sanctions/cuba-prohibited-accommodations-list/`.
- **What it is:** hotels in Cuba where US persons cannot lodge. Authority is
  31 CFR 515.210. Most updates also publish in the Federal Register (e.g., FR
  doc 2025-13148, 90 FR 31552).
- **Why separate from the CRL:** different legal authority (515.210 vs
  515.209); different scope (lodging vs all financial transactions); CPAL also
  covers properties that aren't necessarily GAESA-controlled.
- **New `SourceType`:** `STATE_DEPT_CPAL`.

### 8. Federal Register — CACR amendments

- **Mechanism:** unchanged from Venezuela build — same Federal Register search
  API (`https://www.federalregister.gov/api/v1/documents.json`). **Only the
  query filter changes.**
- **Filter terms:** `"Cuban Assets Control Regulations"`, `"31 CFR Part 515"`,
  `"Cuba Restricted List"`, `"Cuba Prohibited Accommodations"`,
  `"Helms-Burton"`, `"Title III"`, `"CACR"`.
- **Cadence:** historically 1–4 amendments per year, plus ~quarterly CRL/CPAL
  updates published as Public Notices.
- **Maps to:** `SourceType.FEDERAL_REGISTER` (unchanged enum).

### 9. State Department — Cuba travel advisory

- **Mechanism:** unchanged from Venezuela build (same scraper module, same
  embed format).
- **URL:** `https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories/cuba-travel-advisory.html`.
- **Cadence:** updated ~1–2x per year unless something major happens.

### 10. GDELT — global news feed (Cuba slice)

- **Mechanism:** unchanged. Same GDELT v2 doc API, same parser. Just rewrite
  the keyword query.
- **Suggested query terms:** Cuba, La Habana, Havana, Díaz-Canel,
  Helms-Burton, embargo, blockade ("bloqueo"), Mariel, GAESA, CIMEX, MINREX,
  ETECSA, BioCubaFarma, mipyme, MLC, CUP, CACR, OFAC.

---

## Tier 2 — High-signal independent press (RSS — easiest to integrate)

Every major Cuban news outlet — independent, diaspora, and state — publishes
RSS. **Use `feedparser`, not HTML scraping.** This is dramatically more
reliable than the Venezuelan press equivalents we built against.

| Outlet | RSS feed | Stance | Notes |
|---|---|---|---|
| **Granma** (en) | `https://en.granma.cu/feed` | State / Communist Party organ | Authoritative for legislative + government statements. English version is faster than scraping the Spanish site. |
| **Granma** (es) | `https://www.granma.cu/feed` | State | Use as fallback. |
| **14ymedio** | `https://www.14ymedio.com/rss` | Independent (Yoani Sánchez) | Best independent coverage of mipyme economy, FX, and shortages. |
| **CiberCuba** | `https://www.cibercuba.com/rss` (verify) | Independent / diaspora (Miami) | High volume, broad — daily FX recaps, deportations, US-Cuba bilateral. |
| **Diario de Cuba** | `https://diariodecuba.com/rss.xml` (verify) | Independent / diaspora (Madrid) | Long-form analysis, sanctions-heavy. |
| **Cubadebate** | `https://www.cubadebate.cu/feed/` | State / pro-government | The official line — useful for "what does Havana want you to think?" framing. |
| **OnCuba News** | `https://oncubanews.com/feed/` | Independent (US-based) | Bilingual, business-friendly. |
| **Havana Times** | `https://havanatimes.org/feed` | Independent (English) | English-language analysis from inside Cuba. |
| **Periódico Cubano** | `https://www.periodicocubano.com/feed/` | Independent / diaspora | Volume play. |
| **Juventud Rebelde** | `https://www.juventudrebelde.cu/get/rss/general` | State (UJC) | Lower priority. |
| **Trabajadores** | `https://www.trabajadores.cu/feed/` | State (CTC) | Lower priority. |

**Suggested approach:** one generic `RssScraper(BaseScraper)` that takes a
list of feed URLs from `settings`, persists each item with a stable hash, and
tags `SourceType.NEWSDATA` (already exists) plus a per-feed sub-tag in the raw
JSON. This is a much smaller code surface than per-outlet scrapers and trivially
extends.

---

## Tier 3 — Specialised / lower-cadence (batch as needed)

### MINREX (Ministerio de Relaciones Exteriores)

- **Domain:** `cubaminrex.cu` (note: `.cu`, **not** `.gob.cu` — common
  mistake; `MIGRATION.md` should reflect this).
- **URLs:**
  - `https://cubaminrex.cu/en/declaraciones-del-minrex` — formal MFA
    declarations (English).
  - `https://cubaminrex.cu/es/declaraciones-del-minrex` — Spanish.
  - `https://cubaminrex.cu/es/taxonomy/term/290` — full MINREX category.
- **Reachability:** HTTP 200 from default User-Agents (no UA-block — confirmed).
- **Cadence:** 1–4 declarations per month. Most are short.
- **Best mechanism:** Drupal sites typically expose `/rss.xml` — try that
  first, fall back to HTML.
- **Maps to:** `SourceType.MINREX`.

### ONEI (Oficina Nacional de Estadística e Información)

- **Domain:** `onei.gob.cu`.
- **URL:** `https://www.onei.gob.cu/publicaciones-economico` — listing of
  monthly publications: IPC (inflation), Indicadores Seleccionados del Sistema
  Empresarial y Presupuestado, PIB anual.
- **Cadence:** 4–8 publications/month, all PDF.
- **Why it matters:** ONEI's monthly IPC is the official inflation series the
  Climate Tracker's Macro Stability pillar should anchor against. **March 2026
  print: 13.42% YoY headline inflation, +2.19% MoM** — already a huge story
  vs. the Venezuelan equivalents.
- **Anuario Estadístico:** `https://www.onei.gob.cu/anuario-estadistico-de-cuba-2024`
  — annual macro book, publishes mid-year.
- **Maps to:** `SourceType.ONEI`.

### MINCEX — foreign-investment portfolio

- **Domain:** `mincex.gob.cu` (and the standalone investor portal
  `inviertaencuba.mincex.gob.cu`).
- **What:** the **annual Cartera de Oportunidades** is the canonical list of
  open foreign-investment projects. **2025–2026 edition: 426 projects, $30B
  total estimated investment, 365 of them in ZED Mariel.**
- **Mechanism:** PDF download (annual) + HTML browse on the investor portal.
  Lower cadence — quarterly check is enough.
- **Why it matters:** this is the supply side of "what foreign investment is
  Cuba *inviting*?" — direct input to the Climate Tracker's Sector Openness
  pillar and to the Mariel ZED dedicated page.
- **Maps to:** new `SourceType.MINCEX_PORTFOLIO` (or fold into ONEI tag).

### ZED Mariel

- **Domain:** `zedmariel.com`.
- **What:** the Mariel Special Development Zone publishes its own
  Portfolio of Opportunities annually (`/sites/default/files/.../Portfolio of Opportunities [YYYY-YYYY].pdf`)
  plus news. 2025-2026 PDF lists 35 sector-bucketed projects with
  contacts and capex estimates.
- **Mechanism:** PDF + HTML. Quarterly cadence.
- **Why it matters:** ZED Mariel is by far the most credible foreign-investment
  vehicle on the island. Worth its own dedicated landing page (Phase 9 in
  `MIGRATION.md`).

### EU sanctions — **nothing to scrape**

- **Cuba is NOT in the EU consolidated financial sanctions list.** Verified
  against the OpenSanctions EU FSF dataset, which lists Afghanistan, Belarus,
  Iran, North Korea, Russia, Syria, Venezuela, etc. — Cuba is absent.
- The EU lifted Common Position 96/697/CFSP in 2016 and replaced it with the
  **Political Dialogue and Cooperation Agreement (PDCA)** — a positive-engagement
  framework, not a restrictive-measures regime.
- **Action:** **drop the planned `EU_SANCTIONS` scraper from Phase 2** and
  remove the `SourceType.EU_SANCTIONS` enum value (it was added speculatively
  in Phase 1). Track PDCA-related news via the regular GDELT / RSS feeds.

### Helms-Burton Title III lawsuit tracker — **manual curation only**

- No central database. Cases live in PACER. The reliable secondary sources
  are law-firm tracking blogs:
  - Steptoe "First Tuesday Update"
  - Akerman Cuba practice updates
  - Arnold & Porter Helms-Burton advisories
  - Baker McKenzie sanctions blog
- Major active matters as of Apr 2026: *Echevarria v. Expedia* (S.D. Fla.,
  $30M jury verdict Apr 2025, post-verdict briefing); *North American Sugar v.
  Xinjiang Goldwind* ($97M cert. claim, 11th Cir. reversal Jan 2025);
  *Exxon v. CIMEX* (SCOTUS, SG views invited May 2025); *Havana Docks v.
  cruise lines* (SCOTUS oral args Feb 2026); *de Fernandez v. Seaboard*
  (11th Cir. 2025 — held Helms-Burton claims are non-inheritable).
- **Build mechanism:** curated dataclass in `src/data/`, refreshed quarterly
  by reading the law-firm trackers. **Phase 9 work, not Phase 2.**

---

## Important context for analyzer / climate-rubric prompts

These aren't scraper sources but they shape how we frame everything:

1. **State Sponsor of Terrorism status:** Cuba is on the SST list as of April
   2026. Biden certified rescission Jan 14, 2025; Trump revoked it Jan 20, 2025
   before the 45-day waiting period elapsed. SST status creates additional
   export controls, foreign-assistance bans, and secondary-sanctions risk.
   Reference in the Sanctions Trajectory rubric and the analyzer's system prompt.
2. **The embargo is codified into US law.** The Helms-Burton Act (1996)
   means only Congress can lift the embargo — not the executive branch. This
   structurally caps the upside of any "Cuba thaw" narrative and is the single
   most important framing difference vs. Venezuela coverage.
3. **Currency landscape:** there is no longer a CUC (eliminated Jan 2021 in
   Tarea Ordenamiento). Three relevant currencies: CUP (Cuban peso), MLC
   (Moneda Libremente Convertible — a USD-denominated state digital wallet),
   USD (cash). The BCC publishes three official rates (Segments I/II/III) and
   El Toque publishes the informal market rate. The spread is the story.
4. **GAESA is the corporate state.** The Grupo de Administración Empresarial
   S.A. (military holding company) controls most large Cuban tourism, retail,
   and remittance infrastructure. CRL coverage = GAESA coverage in practice.

---

## Reachability gotchas summary (live-probed 2026-04-20)

| Host | Default UA | With Mozilla UA | Notes |
|---|---|---|---|
| `api.bc.gob.cu` | ✅ 200 | ✅ 200 | Public REST API, no auth needed. |
| `gacetaoficial.gob.cu` | ❌ 403 | (not yet probed; expect 200) | Set UA header in scraper. |
| `parlamentocubano.gob.cu` | ❌ 403 | (not yet probed; expect 200) | Set UA header in scraper. |
| `cubaminrex.cu` | ✅ 200 | ✅ 200 | Note `.cu`, not `.gob.cu`. |
| `onei.gob.cu` | (not probed) | — | Expected to mirror Gaceta behaviour. |
| `en.granma.cu/feed` | ✅ 200 | ✅ 200 | RSS. |
| `eltoque.com` | (gated) | (gated) | API key required. |
| `state.gov` | ✅ 200 | ✅ 200 | No issues expected. |

**Action item:** centralise a single `CUBA_GOV_USER_AGENT` constant in
`src/scraper/_http.py` and use it from every `.gob.cu` scraper, alongside
sane retries and a 30s timeout. **Do not rely on whatever the underlying
`requests` default is.**

---

## Recommended Phase 2 build order

1. **Filter swaps (≤ 1 hour each) — highest ROI:**
   - `src/scraper/ofac_sdn.py` — `VENEZUELA_PROGRAMS` → `{"CUBA"}`.
   - `src/scraper/federal_register.py` — keyword filter.
   - `src/scraper/gdelt.py` — keyword query.
   - `src/scraper/travel_advisory.py` — URL.

2. **API-backed rewrites (~ 0.5 day each):**
   - **BCC rates** via `api.bc.gob.cu` (replaces the BCV scraper).
   - **State Dept CRL + CPAL** (single page each, simple HTML).

3. **HTML scrapers needing UA work (~ 1 day each):**
   - **Gaceta Oficial CU** (`gacetaoficial.gob.cu`).
   - **Asamblea Nacional CU** (`parlamentocubano.gob.cu`).
   - **MINREX** (`cubaminrex.cu`).
   - **ONEI publications listing** (`onei.gob.cu`).

4. **Generic RSS aggregator (~ 1 day):**
   - One scraper, configurable feed list. Wires up Granma, 14ymedio,
     CiberCuba, Diario de Cuba, OnCuba, Havana Times in one shot.

5. **El Toque (gated on user action):**
   - User must apply for the API key first. Build the scraper against the
     contract once the key arrives.

6. **Drop:** `EU_SANCTIONS` scraper plan + enum value.

7. **Defer to Phase 9:** MINCEX portfolio scraper, ZED Mariel scraper,
   Helms-Burton Title III tracker (curated, not scraped).
