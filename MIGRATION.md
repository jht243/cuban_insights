# Caracas Research → Cuban Insights migration tracker

This file is the single source of truth for which parts of the codebase have been repointed at Cuba and which are still in their Venezuela-era state. The architecture, DB schema, deployment, distribution channels, and SEO machinery all stay; the source coverage, curated content, copy, and route paths are being rewritten.

Update this file whenever you complete a phase. Numbering follows the original migration spec.

---

## Phase 1 — Foundation (DONE)

Pure mechanical refactor. Doesn't touch scraper logic or curated content. Result: the site identifies as Cuban Insights everywhere brand strings are read from `settings`, but the data layer / route paths / curated content are still Venezuela-shaped.

- [x] `src/config.py` — `site_name`, `site_owner_org`, `site_url`, `database_url`, `newsletter_from_email`, source URLs (gazette / assembly / TSJ / El Toque / BCC) all repointed at Cuba defaults.
- [x] `src/models.py` — `SourceType` enum extended with `GACETA_OFICIAL_CU`, `ASAMBLEA_NACIONAL_CU`, `BCC_RATES`, `ELTOQUE_RATE`, `MINREX`, `ONEI`. Venezuela-era values retained until the corresponding scrapers are retired (see Phase 2). _(Phase 1 originally added a speculative `EU_SANCTIONS` value; removed in Phase 2 after research confirmed Cuba is not on the EU consolidated sanctions list.)_
- [x] `render.yaml` — web service renamed `cuban-insights`, crons renamed `cij-daily-pipeline` and `cij-weekly-climate`, `NEWSLETTER_FROM_EMAIL` updated.
- [x] `.env.example` — newsletter email + premium-model comment + Search Console comment + Bluesky handle example all repointed; new `SITE_URL`/`SITE_NAME`/`SITE_OWNER_ORG`/`SITE_LOCALE` block added.
- [x] `templates/_brand_logo.svg` — Cuban-flag-derived (3 blue / 2 white stripes + red triangle hoist + lone star).
- [x] `templates/_base.html.j2` — visible brand text, footer copy, JS title default, "By Cuban Insights" CSS comment.
- [x] `templates/report.html.j2` — meta defaults, OG/Twitter copy, body brand strings, footer copyright + disclaimer (now references BCC, El Toque, ONEI, CACR, Helms-Burton).
- [x] Deleted `report.html` (root VE demo fixture) and `output/report.html` (stale VE-generated report — will regenerate on first pipeline run).
- [x] `README.md` — rewritten around Cuban Insights identity, preserving architecture / ops / pitfalls sections that still apply.

**What's intentionally still Venezuela-shaped after Phase 1:**

- Scraper modules (`src/scraper/*.py`) still implement Venezuelan endpoint logic.
- Curated data (`src/data/*.py`) still describes Venezuelan profiles, neighborhoods, landmarks, exposures.
- Route paths (`/invest-in-venezuela`, `/sanctions-tracker`, `/tools/bolivar-usd-exchange-rate`, etc.) still use Venezuela slugs.
- `src/seo/cluster_topology.py` anchor strings still reference Venezuela / Caracas / PDVSA / BCV.
- `src/analyzer.py` `RELEVANCE_KEYWORDS` and `SYSTEM_PROMPT` still target Venezuelan content.
- `src/blog_generator.py` and `src/landing_generator.py` system prompts still target Venezuela.
- `src/climate/rubric.py` thresholds + evidence selection still tuned for Venezuela.
- All hardcoded copy in templates other than `_base.html.j2` and `report.html.j2`.
- `src/distribution/runner.py::_STATIC_URLS_TO_PING_DAILY` still lists VE slugs.
- `server.py::sitemap_xml` static URLs and route paths.

These are addressed in Phases 2–7 below. **The site will read coherently as "Cuban Insights branding wrapped around Venezuelan content" until Phase 4 lands.** That's expected and acceptable as a checkpoint.

---

## Phase 2 — Scrapers (IN PROGRESS — 2a + 2b + 2c + 2d DONE)

Plan revised after the dedicated source-research pass — see `docs/scraper_research.md` for the full source-by-source dossier (endpoints, reachability probes, gotchas, rate limits). Build order below reflects that research; it differs in several places from the original migration spec.

### Build order (easy → hard, by ROI)

#### 2a. Filter-only swaps (DONE)

These reuse the existing scraper modules wholesale; only the keyword/program/URL filter changes.

- [x] **OFAC SDN** (`src/scraper/ofac_sdn.py`) — `VENEZUELA_PROGRAMS` → `CUBA_PROGRAMS = {"CUBA"}` with semicolon-tokenised matching to avoid "CUBAN…" substring false positives. Snapshot path namespaced from `sdn_ve_*.json` → `sdn_cu_*.json` (first run will treat all entries as additions, which is the desired behaviour for the Cuba reset).
- [x] **Federal Register** (`src/scraper/federal_register.py`) — `VENEZUELA_TERMS` → `CUBA_TERMS = ["cuba", "cuban", "CACR", "Helms-Burton", "LIBERTAD Act", "Havana"]`. The `conditions[term]` query stays a single keyword (`"cuba"`) — the FR API supports only one search term and OFAC-agency scoping keeps recall high. `CUBA_TERMS` is retained as a constant for future client-side reranking.
- [x] **GDELT** (`src/scraper/gdelt.py`) — EN/ES queries swapped to Cuba terms (sanctions / investment / remittances / tourism / economy ⇆ sanciones / inversión / remesas / turismo / economía). `state_media` credibility set replaced with Cuban state outlets (Granma, Cubadebate, Juventud Rebelde, Trabajadores, AIN, Prensa Latina, ICRT, Radio Rebelde, plus Telesur).
- [x] **State Dept travel advisory** (`src/scraper/travel_advisory.py`) — `ADVISORY_URL` repointed at the Cuba page, headline string rewritten. HTML structure / level-parser / level-label table all unchanged (State Dept uses a single template across countries).

#### 2b. API-backed rewrites (DONE)

- [x] **BCC rates** (`src/scraper/bcc.py`, new) — consumes `GET https://api.bc.gob.cu/v1/tasas-de-cambio/activas`. Live-verified: returns ~30 currencies × 3 segments (`tasaOficial`, `tasaPublica`, `tasaEspecial`) in a single JSON call. Headline rate uses `tasaEspecial` (the post-2022 institutional reference, e.g. ~488 CUP/USD); all three segments + USD/EUR/CAD/GBP/MXN/CHF/JPY/CNY are persisted in `extra_metadata.rates`. The valuation date is parsed from the API's `fechaDia` field. No HTML scraping, no proxy, no headless browser. `BCVScraper` was removed from `src/pipeline.py::scrapers`; `src/scraper/bcv.py` left in place as dead code (still imported by the deferred `/tools/bolivar-usd-exchange-rate` route — both go in Phase 5). Maps to `SourceType.BCC_RATES`.
- [x] **State Dept Cuba Restricted List** (`src/scraper/state_dept_crl.py`, new) — fetch + parse + snapshot + diff. The `<article>` body is walked in document order, paragraphs that are JUST a `<strong>` heading set the running section ("Ministries", "Holding Companies", "Hotels in La Habana Province", "Additional Subentities of CIMEX", etc.), and entry paragraphs become `CrlEntry(section, name)` tuples. The `As of <date>` preamble is captured as `list_effective_date`. Snapshots stored as `storage/state_dept_snapshots/crl_<isodate>.json`; on first run we emit one baseline article, on subsequent runs only diff articles (`CRL ADDED — …`, `CRL REMOVED — …`). Live-verified against the current page: **247 entities across 4+ sections, effective date 2025-07-14**. Maps to `SourceType.STATE_DEPT_CRL`.
- [x] **State Dept Cuba Prohibited Accommodations List** (`src/scraper/state_dept_cpal.py`, new) — same fetch+snapshot+diff pattern as the CRL. Province headers live in `<h5>` (not `<p>`) so the parser walks both heading + paragraph tags in document order, syncing the running province before reading entries. Each entry's `<strong>` carries the property name and the trailing text carries the address; the `*` and `^` casa-marketing markers are extracted into a separate `marker` field. `(aka: …)` aliases are folded into the name. Live-verified: **431 properties across all 16 Cuban provinces, 51 ✱-flagged casas + 1 ^-flagged casa, 0 unclassified entries, effective date 2025-07-14**. Maps to `SourceType.STATE_DEPT_CPAL`.

Both new `SourceType` enum values added to `src/models.py` (no DB migration helper yet — the project is fresh on Render so `create_all` covers it; if/when a Postgres ALTER TYPE migration is needed we'll add an `_ensure_enum_values()` helper alongside `_ensure_columns()`).

Read-side `SourceType.BCV_RATES` query references swapped to `SourceType.BCC_RATES` in `src/og_image.py`, `src/climate/evidence.py`, `src/report_generator.py` (one query + one display-label entry; the legacy `BCV_RATES` label kept in the `_SOURCE_LABEL` map until Phase 4). The `/tools/bolivar-usd-exchange-rate` route in `server.py` intentionally still queries `BCV_RATES` because that whole tool is Venezuela-shaped and gets renamed/rewritten in Phase 5.

#### 2c. `.gob.cu` HTML scrapers (DONE)

The original plan assumed a **HTTP 403 to default UAs** gotcha across `.gob.cu` sites. Live-probing during the build pass found the situation is more nuanced — `gacetaoficial.gob.cu`, `parlamentocubano.gob.cu`, and `onei.gob.cu` all responded 200 to a vanilla `httpx`/`curl` UA from US residential IPs, while `cubaminrex.cu` (note: not `.gob.cu`) doesn't resolve in DNS at all from several US ISPs. We shipped the `CUBA_GOV_USER_AGENT` constant anyway because the behaviour is known to drift by edge node + time of day, and using it costs nothing.

- [x] **`src/scraper/_http.py`** — new module exporting `CUBA_GOV_USER_AGENT` (Chrome 125 desktop) + `CUBA_GOV_HEADERS` (UA + `Accept-Language: es-CU,es;q=0.9,en;q=0.6`) + `cuba_gov_client()` factory for one-off probes outside the `BaseScraper` retry loop. The base `BaseScraper.__init__` was updated in the same pass to use the same `es-CU`-first Accept-Language (was leftover `es-VE` from the Venezuela codebase).
- [x] **Gaceta Oficial CU** (`src/scraper/gaceta_oficial_cu.py`, new) — Drupal site. Strategy: scrape `/es/servicios`, the densest "latest published norms" surface. Each `.node-norma-juridica.node-teaser` card already contains title + identificador (e.g. `GOC-2026-161-EX22`) + resumen text. The identificador encodes year + gazette type + ordinal (`-EX22` → Extraordinaria #22). For each card we then fetch the norm detail page best-effort to pick up the canonical "Publicado en: Gaceta Oficial No. X [Extraordinaria] de YYYY" line — this is the source of truth for gazette number/type. Live-verified: **10 norms parsed cleanly, with sumario + gazette ordinal + type all populated**. `pdf_download_url` is left empty (the public site doesn't expose PDF links — the analyzer works off `sumario_raw`). Maps to `SourceType.GACETA_OFICIAL_CU`. Old `src/scraper/gazette.py` is left on disk because `run_backfill.py` still imports it; both go in the Phase 5 cleanup.
- [x] **Asamblea Nacional CU** (`src/scraper/asamblea_nacional_cu.py`, new) — Joomla site. Strategy: pull `/noticias`, dedupe `/noticias/<slug>` and `/index.php/noticias/<slug>` anchors (the listing renders each item twice), then fetch each article page for headline / `<time datetime>` / body. Filtered to a 7-day lookback (the Asamblea publishes ~weekly, not daily; a today-only filter would persist 0 items most days). The `/labor-legislativa` page has the catalogue of approved laws with PDF links — that's static / weekly-refresh content and gets surfaced from a separate backfill module in Phase 5 instead. Live-verified: **3 news items in the current 7-day window** (Girón declaration, Díaz-Canel speech, Programa Económico). Maps to `SourceType.ASAMBLEA_NACIONAL_CU`. Old `src/scraper/assembly.py` left on disk for `run_backfill.py`.
- [x] **MINREX** (`src/scraper/minrex.py`, new) — `cubaminrex.cu` (corrected from the `minrex.gob.cu` placeholder Phase 1 used). Defensive shape: tries `/rss.xml` first (uses `feedparser` if available), falls back to HTML at `/es/declaraciones-del-minrex`, and returns `success=False` with a logged warning instead of crashing if both surfaces fail. The site **doesn't resolve in DNS from at least some US residential ISPs** (smoke-tested; this looks like the same DNS interference pattern that affects `granma.cu`); the scraper is built to fail gracefully so a transient network problem can't poison the daily run. Maps to `SourceType.MINREX`. Will need a re-verification pass once the production server (Render box) confirms it can resolve the domain.
- [x] **ONEI** (`src/scraper/onei.py`, new) — Drupal site, `/publicaciones-economico` endpoint. Each `.views-row` card has a clean `.views-field-title a` + `time[datetime]` pair. 7-day lookback window. Off-domain promo banners (e.g. a sticky "Fidel Soldado de las Ideas" widget linking to `fidelcastro.cu`) are filtered out. Live-verified: **2 fresh publications today** ("Salario Medio en Cifras. Cuba 2025", "Indicadores Seleccionados del sistema empresarial y presupuestado Febrero 2026") plus the off-domain card correctly dropped. Maps to `SourceType.ONEI`.

The `minrex_url` and `onei_url` settings were added to `src/config.py` as part of this batch.

#### 2d. RSS aggregator for the press feed (DONE)

Built a single generic `PressRssScraper(BaseScraper)` in `src/scraper/rss.py` with a hardcoded outlet whitelist + per-outlet credibility tier. Lazy-imports `feedparser` (added to `requirements.txt`). Each item becomes a `ScrapedArticle` tagged `source_name="<outlet>"`; per-outlet attribution is preserved in `source_name` while every outlet folds into a single new `SourceType.PRESS_RSS` enum value (avoids enum-bloat — `pipeline._resolve_source_type` maps each known outlet name to `PRESS_RSS`).

Per-feed network failures are isolated: a transient DNS/timeout on one outlet logs a warning and continues; the run only reports `success=False` if every outlet fails.

Live-verified results:

| Outlet | Feed URL | Tier | Items in 2-day window |
|---|---|---|---|
| Granma | `https://www.granma.cu/feed` | official (state) | 33 |
| Cubadebate | `http://www.cubadebate.cu/feed/` | official (state) | 10 |
| 14ymedio | `https://www.14ymedio.com/rss/` | tier1 (in-island independent) | 25 |
| OnCuba | `https://oncubanews.com/feed/` | tier1 (diaspora balanced) | 27 |
| Diario de Cuba | `https://diariodecuba.com/rss.xml` | tier2 (diaspora opposition) | 10 |
| Havana Times | `https://havanatimes.org/feed/` | tier2 (independent expat) | 7 |

Total: **112 items per run across 6 outlets**.

CiberCuba (the 7th outlet the user picked) is intentionally **omitted from the whitelist** — the site is a pure AMP WordPress build and `/feed`, `?feed=rss2`, `/atom.xml`, etc. all return AMP HTML rather than RSS XML. Adding it would require a sitemap-driven HTML scraper, which is a separate module. Tracking this as a Phase 9 item if/when we want CiberCuba's volume.

`SourceType.PRESS_RSS` was added to `src/models.py` as part of this batch.

#### Pipeline wiring (2c+2d)

`src/pipeline.py` now lists the Cuba-era scrapers in the daily `scrapers` list:

```
GacetaOficialCUScraper   AsambleaNacionalCUScraper   MinrexScraper   ONEIScraper
PressRssScraper          FederalRegisterScraper      OFACSdnScraper  TravelAdvisoryScraper
StateDeptCRLScraper      StateDeptCPALScraper        BCCScraper      GDELTScraper
```

The Venezuela-era `TuGacetaScraper`, `OfficialGazetteScraper`, `AssemblyNewsScraper`, and `BCVScraper` are no longer imported by the pipeline. The legacy modules remain on disk because `run_backfill.py` still imports the gazette + assembly scrapers and `server.py`'s `/tools/bolivar-usd-exchange-rate` route still imports `BCVScraper`; both consumers get rewritten in Phase 5.

#### 2e. Gated on external action — El Toque (BLOCKED ON USER)

- [ ] **Action item for the user, not a code task:** apply for the El Toque API key via the form embedded in `https://dev.eltoque.com/eltoque-abre-acceso-a-su-api-de-las-tasas-de-cambio`. Step-by-step walkthrough with paste-ready Spanish answers and field-by-field cheat-sheet lives in `docs/eltoque_api_application.md`. Free beta tier, 5,000 req/month (we need ~60). API key arrives by email after manual review (1–4 week turnaround historically). Scraping `eltoque.com` directly is explicitly prohibited by the publisher.
- [ ] Once the key is in `.env` as `ELTOQUE_API_KEY` (and on Render as a service env var), build `src/scraper/eltoque.py` against `https://tasas.eltoque.com/`. Maps to `SourceType.ELTOQUE_RATE`. Mandatory attribution to elTOQUE on any page that displays the number (already covered by `report.html.j2` footer; FX tool page gets the visible credit + outbound link in Phase 5).

### Plan changes vs. the original Phase 2 spec

- **Drop EU sanctions scraper.** Cuba is not in the EU consolidated financial sanctions list — verified against OpenSanctions FSF data. The EU lifted Common Position 96/697/CFSP in 2016 and replaced it with the PDCA (positive engagement, not restrictive measures). `SourceType.EU_SANCTIONS` removed from `src/models.py` in batch 2a (was added speculatively in Phase 1).
- **Add State Dept CRL + CPAL scrapers.** These are Cuba-specific lists distinct from OFAC SDN — most CRL entries are NOT on the SDN. Without these, our `/companies/<slug>/cuba-exposure` and `/sanctions-tracker` surfaces would miss Marriott / Iberostar / Kempinski / GAESA exposure entirely.
- **BCC plan changed from HTML scrape (with proxy worry) to public REST API.** The published, undocumented-but-stable `api.bc.gob.cu` endpoint removes any need for headless browsers, OCR, or proxy work for FX. This is the single biggest plan upgrade from the research pass.
- **Defer to Phase 9** (curated, not scraped): MINCEX foreign-investment portfolio (annual PDF), ZED Mariel project portfolio (annual PDF), Helms-Burton Title III lawsuit tracker (no central database; built from law-firm advisories).

### Cleanup once each Cuba scraper is shipping data

After each Cuba scraper produces its first successful run, retire the corresponding Venezuela-era `SourceType` value from `src/models.py` (keep enum order; mark removal in this file's "Things to delete" section).

---

## Phase 3 — LLM keyword filters & prompts (TODO)

- `src/analyzer.py::RELEVANCE_KEYWORDS` — replace Spanish list with Cuba terms (mipyme, Mariel ZED, MLC, CUP, tarea ordenamiento, cuentapropista, remesa, bloqueo, embargo, Helms-Burton, Título III, LIBERTAD Act, OFAC, CACR, cooperativa, dolarización parcial). Keep English sanctions/OFAC terms.
- `src/analyzer.py::SYSTEM_PROMPT` — Venezuela → Cuba; replace audience line with "navigating Cuba's reform cycle and the US embargo regime". Keep JSON schema unchanged.
- Sectors list — replace/add: tourism, remittances, telecom (ETECSA), biotech (BioCubaFarma), nickel/mining, agriculture, mipymes, energy, real_estate, sanctions, governance, diplomatic. Update `SECTOR_OPTIONS` in `src/report_generator.py` to match.
- `src/blog_generator.py` and `src/landing_generator.py`: same Venezuela → Cuba retargeting in `SYSTEM_PROMPT` and `USER_PROMPT_TEMPLATE`. Keep the social-hook voice rules verbatim.

---

## Phase 4 — Curated data layer (TODO — biggest manual lift)

These are pure rewrites. Keep file structure and dataclass shapes; replace content. Budget roughly a day per file.

- [ ] `src/data/sdn_profiles.py` — update `PROGRAM_LABELS` and `PROGRAM_EXEC_ORDERS` to Cuba programs. Re-do sector classification heuristics for Cuban roles (FAR, MININT, GAESA officers vs FANB/SEBIN).
- [ ] Rename `curated_venezuela_exposure.py` → `curated_cuba_exposure.py`. Rewrite from scratch. Starter S&P 500 / large-cap exposures: MAR (Marriott — Four Points by Sheraton Havana, OFAC license), MSC (cruises, post-2019 wind-down), VZ (Verizon roaming), WU (Western Union — restored 2023 remittance corridor), AAL/JBLU/DAL (authorized US-Cuba flights), MGM (none — confirmed), HLT/IHG (no current presence).
- [ ] `src/data/company_exposure.py` — engine stays; point at the new curated file and rewrite the fuzzy-match seed terms (drop PDVSA/CITGO; add GAESA / CIMEX / ETECSA / Mariel ZED / Habanos).
- [ ] `src/data/edgar_search_presets.py` — rewrite all 7 query strings. Add Helms-Burton + Title III queries (Cuba-unique).
- [ ] `src/data/ofac_general_licenses.py` — replace all 10 entries with current CACR general licenses: §515.530 (family remittances), §515.534 (telecom), §515.542 (mail/parcel), §515.560 (12 authorized travel categories), §515.572 (travel-related transactions), §515.582 (independent Cuban entrepreneurs / mipymes — the most important commercial GL), §515.584 (banking) + recent specific licenses.
- [ ] Rename `caracas_neighborhoods.py` → `havana_neighborhoods.py`. Rewrite for Vedado, Miramar, Habana Vieja, Centro Habana, Playa, Plaza, Cerro, 10 de Octubre, Marianao, Habana del Este, Cojímar. Score for safety + business use + casa-particular density.
- [ ] Rename `caracas_landmarks.py` → `havana_landmarks.py`. Embassies, hospitals (Cira García is the foreigner hospital), Mariel ZED gate.
- [ ] `src/data/travel.py` — wholesale rewrite. Embassy list (much wider than Caracas — most western embassies operate in Havana). Hotels: state chains (Gran Caribe, Cubanacán, Habaguanex) + foreign-managed (Iberostar, Meliá, Kempinski, Four Points by Sheraton). **Critical Cuba-specific section: payment infrastructure.** US-issued cards do NOT work; Visa/MC from non-US banks usually do; cash USD/EUR exchange at CADECA; MLC stores. Add a "what to bring" subsection (toiletries, OTC meds — perennial shortages).
- [ ] `src/data/visa_requirements.py` — Cuba's regime is fundamentally different. Most travelers buy a *tarjeta turística* from the airline. **US travelers must self-certify under one of the 12 OFAC-authorized travel categories.** This is its own UI flow — surface the 12 categories prominently.
- [ ] `src/data/sp500_companies.py` — no change.

---

## Phase 5 — Routes (TODO — coordinated commit)

Path renames must land alongside Phase 6 (cluster topology) and the corresponding template updates so internal links don't 404. Do NOT split.

| Old path | New path |
|----------|----------|
| `/invest-in-venezuela` | `/invest-in-cuba` |
| `/sanctions-tracker` | _(unchanged path; Cuba data)_ |
| `/tools/bolivar-usd-exchange-rate` | `/tools/cup-mlc-usd-exchange-rate` |
| `/tools/ofac-venezuela-sanctions-checker` | `/tools/ofac-cuba-sanctions-checker` |
| `/tools/ofac-venezuela-general-licenses` | `/tools/ofac-cuba-general-licenses` |
| `/tools/public-company-venezuela-exposure-check` | `/tools/public-company-cuba-exposure-check` |
| `/tools/sec-edgar-venezuela-impairment-search` | `/tools/sec-edgar-cuba-helms-burton-search` |
| `/tools/venezuela-investment-roi-calculator` | `/tools/cuba-investment-roi-calculator` |
| `/tools/venezuela-visa-requirements` | `/tools/cuba-visa-and-travel-categories` |
| `/tools/caracas-safety-by-neighborhood` | `/tools/havana-safety-by-neighborhood` |
| `/companies/<slug>/venezuela-exposure` | `/companies/<slug>/cuba-exposure` |

**New Cuba-specific route:** `/tools/ofac-12-travel-categories` — interactive picker for the OFAC self-certification decision tree. No Venezuela equivalent.

Also update:
- `src/distribution/runner.py::_STATIC_URLS_TO_PING_DAILY`
- `server.py::sitemap_xml` static URL list
- All hardcoded `href="..."` strings in templates

---

## Phase 6 — SEO topology (TODO — paired with Phase 5)

`src/seo/cluster_topology.py` rewrites:

- 4-cluster mesh structure stays.
- **Sanctions cluster** — pillar `/sanctions-tracker`. Add a Helms-Burton Title III explainer (no Venezuela analog).
- **Investment cluster** — pillar `/invest-in-cuba`. Sectors: tourism, nickel-mining, biotech, telecom, agriculture, mipymes, energy, real-estate, remittances, **mariel-zed** (mandatory dedicated page).
- **Travel cluster** — pillar `/travel`. Add `/tools/ofac-12-travel-categories`.
- **FX cluster** — pillar `/tools/cup-mlc-usd-exchange-rate`. Members: CUP/CUC unification ("Tarea Ordenamiento", Jan 2021), MLC explainer, what the BCC actually does.
- Update `_PROGRAM_TO_SECTOR_SLUG` for CACR program codes.
- Update `_ANCHOR` for every renamed path.

---

## Phase 7 — Investment Climate Tracker rubrics (TODO)

Keep the 6-pillar structure and rubric machinery in `src/climate/rubric.py`. Retune:

- **Sanctions Trajectory** — anchor against the embargo's structural permanence (Helms-Burton codified into US law — only Congress can lift). CACR amendments and Title III suspensions matter more than net SDN movement. Lower the ceiling — even a "good" Cuba quarter caps lower than a "good" Venezuela quarter could.
- **Macro Stability** — track CUP-MLC-USD divergence, remittance volume, electricity blackout frequency. ONEI annual; El Toque daily.
- **Rule of Law** — weight against the 2022 penal code changes and the foreign-investment law (Ley 118 / successors).
- **Sector Openness** — gated by the foreign-investment portfolio published annually by MINCEX. Add as evidence source.
- **FX Access** — central to Cuba's investment story. Score the spread between official CUP/USD and El Toque's parallel rate.
- **Diplomatic Posture** — US-Cuba bilateral state, EU PDCA state, Latin American postures.
- Update `src/climate/subtitles.py` deterministic-text functions accordingly.

---

## Phase 8 — Backfill + content generation (TODO — runs after Phases 2–7)

```bash
python run_backfill.py --start-date 2026-01-01
python scripts/backfill_blog_posts.py
python scripts/backfill_og_images.py
python scripts/backfill_social_hooks.py
python scripts/backfill_calendar_events.py
python scripts/generate_landing_pages.py   # premium model
```

Then turn on distribution channels one at a time, watching `distribution_logs`.

---

## Phase 9 — Cuba-specific net-new surfaces (TODO — after baseline Cuba parity is reached)

These are content surfaces that exist because of Cuba's idiosyncrasies, not Venezuela renames:

- **Helms-Burton Title III tracker** — list of active Title III lawsuits, defendants, claimed properties.
- **OFAC 12 travel categories tool** — interactive self-certification picker (above).
- **Mariel ZED dedicated page** — the only credible foreign-investment vehicle on the island.
- **Mipyme tracker** — Cuba authorized private SMEs in Sept 2021; ~10,000+ now exist. Directory + sector breakdown is a long-tail SEO goldmine.
- **Remittance corridor explainer** — Western Union + alternatives + the role of MLC stores.
- **Biotech sector page** — BioCubaFarma's portfolio.
- **Electricity grid status tracker** — daily blackout intensity has been a top-of-mind story since 2024.

---

## Things to delete after migration is content-complete

- Venezuela-era `SourceType` enum values (`GACETA_OFICIAL`, `TU_GACETA`, `ASAMBLEA_NACIONAL`, `TSJ`, `BCV_RATES`).
- Original Venezuela scraper modules once their Cuban replacements ship.
- Any Venezuela snapshot files in `storage/` (will rebuild on first scrape; OFAC snapshot dir is empty as of Phase 1).

## Things explicitly NOT to change

- `src/models.py` schema (just extend the enum).
- `src/pipeline.py` orchestration shape.
- `src/distribution/*` channel modules (just confirm Bluesky/IndexNow/Google credentials are new).
- `src/og_image.py` rendering pipeline.
- `src/storage_remote.py` Supabase bridge.
- `templates/_base.html.j2` design system (other than brand strings — done in Phase 1).
- The savepoint pattern in `_persist_*` functions.
- The `_enum_values()` SQLAlchemy patch.
- The 3-tier LLM cost discipline (daily / long-form / premium) and budget caps.
- ~~`requirements.txt`.~~ (Phase 2d added `feedparser>=6.0`.)
- Render service shape (1 web + 2 cron).
- Sitemap / news-sitemap / robots.txt logic.
