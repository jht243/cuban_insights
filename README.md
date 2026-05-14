# Cuban Insights

Daily investor briefing for Cuba. Scrapes official Cuban government sources, the OFAC SDN list, the US Federal Register (CACR notices), El Toque's parallel-rate feed, and curated international press; runs an LLM analyst pass; and publishes evergreen landing pages plus a single static daily `report.html` to a public site.

> **Status:** Cuba-native. The architecture, distribution machinery, SEO topology, and DB schema were forked from a predecessor research project; all source coverage, curated content, scrapers, prompts, and SEO surface area now point at Cuba. The `MIGRATION.md` file records what was repointed and what was retired.

> **Live site:** the Render web service serves the latest generated `report.html` from Supabase Storage.
> **Refresh schedule:** twice daily via two Render cron jobs (see §8).

---

## 1. The Big Picture (read this first)

There are **three layers** that frequently get confused — keep them straight:

| Layer | What it is | Where it lives |
|-------|------------|----------------|
| **Jinja templates** | The dynamic templates that the pipeline renders against real DB rows. The single source of truth for the live design. | `templates/*.html.j2` |
| **Generated report** | The output of `src/report_generator.py` — written to `output/report.html` and uploaded to Supabase Storage. **This is what `/` serves.** | `output/report.html` + Supabase `reports` bucket |
| **Evergreen landing pages** | Premium-LLM-generated pillar/sector/explainer pages. Stored in the `landing_pages` table; served straight out of the DB by `server.py`. | `landing_pages` rows |

If the live site looks empty, it is **almost always** because the scrapers found 0 rows for the current `report_lookback_days` window. Fix it by backfilling — see §6.

---

## 2. Data Sources (Cuba)

Every active scraper points at a Cuban source. Venezuela-related website surface area is limited to intentional static search-demand pages such as `/venezuela/transport`; legacy tool, company, and investment aliases are not kept in the app.

| Source | Type | Module | Notes |
|--------|------|--------|-------|
| **Gaceta Oficial de la República de Cuba** (`gacetaoficial.gob.cu`) | Official (govt) | `src/scraper/gaceta_oficial_cu.py` | Yearly listing pages; sumario-text only (no PDF download surface). |
| **Asamblea Nacional del Poder Popular** (`parlamentocubano.gob.cu`) + Granma legislative coverage | Official (govt) | `src/scraper/asamblea_nacional_cu.py` | Granma fills gaps in legislative coverage. |
| **Banco Central de Cuba** (`bc.gob.cu`) — official CUP/USD reference rate | Official (govt) | `src/scraper/bcc.py` | JSON API (`api.bc.gob.cu`); occasionally DNS-blocked from cloud IPs. |
| **elTOQUE TRMI** — informal CUP / MLC / USD rate (`eltoque.com`) | Tier 1 press | `src/scraper/eltoque.py` | The most-watched FX number on the island. ToS requires visible attribution. **Non-negotiable.** |
| **MINREX press releases** (`minrex.gob.cu`) | Official (govt) | `src/scraper/minrex.py` | Foreign-ministry posture. |
| **ONEI macro stats** (`onei.gob.cu`) | Official (govt) | `src/scraper/onei.py` | Annual but high-signal. |
| **OFAC SDN List** | Official (US Treasury) | `src/scraper/ofac_sdn.py` | Filtered to the `CUBA` program plus EO 13818 (Magnitsky) designations on Cuban officials. |
| **State Dept Cuba Restricted List** (CRL) | Official (US State) | `src/scraper/state_dept_crl.py` | §515.209 prohibited-counterparty list (GAESA et al.); distinct from the SDN. |
| **State Dept Cuba Prohibited Accommodations List** (CPAL) | Official (US State) | `src/scraper/state_dept_cpal.py` | §515.210 hotel-blacklist; powers the company-exposure tooling. |
| **US Federal Register** | Official (US govt) | `src/scraper/federal_register.py` | OFAC-agency scoped, `cuba` keyword filter (Helms-Burton / CACR / Cuba Restricted List notices). |
| **US State Dept Travel Advisory** | Official | `src/scraper/travel_advisory.py` | Pinned to the Cuba advisory page. |
| **Cuban press RSS** (Granma, Cubadebate, OnCuba, 14ymedio, Diario de Cuba, Havana Times) | Tier-1 / state press | `src/scraper/rss.py` | Per-outlet credibility tier preserved on `ExternalArticleEntry.source_name`. |
| **GDELT** (international press wire) | News aggregator | `src/scraper/gdelt.py` | Cuba-only query keywords; often rate-limited from Render IPs. |

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Render Cron (cij-daily-pipeline) — runs `python run_daily.py`  │
│   1. Scrape today's data from all sources (src/pipeline.py)     │
│   2. Persist to Supabase Postgres                               │
│   3. LLM analysis pass (src/analyzer.py)                        │
│      - Rule-based templating for OFAC SDN (no LLM call)         │
│      - LLM budget cap: 200 calls/run                            │
│      - Pre-filter: keyword + GDELT tone score                   │
│   4. Generate report.html (src/report_generator.py)             │
│   5. Upload report.html → Supabase Storage `reports/` bucket    │
│   6. Distribute to IndexNow / Google Indexing API / Bluesky /   │
│      Internet Archive / Zenodo / OSF (src/distribution/runner.py)│
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Render Cron (cij-weekly-climate) — Mondays 14:00 UTC           │
│   Recomputes the Investment Climate Tracker scorecard for the   │
│   current quarter; upserts climate_snapshots row.               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Render Web (cuban-insights) — gunicorn server.py               │
│   GET /                       → daily report from Supabase      │
│   GET /sanctions-tracker      → live OFAC SDN tracker (Cuba)    │
│   GET /invest-in-cuba         → pillar landing page             │
│   GET /tools/*                → free interactive tools          │
│   GET /companies/<slug>/...   → S&P 500 Cuba-exposure profiles  │
│   GET /briefing/<slug>        → individual blog post            │
│   POST /api/subscribe         → Buttondown signup               │
│   GET /health                 → status JSON                     │
└─────────────────────────────────────────────────────────────────┘
```

**Why Supabase Storage in the middle?** Render web and Render cron are *separate ephemeral services* — they don't share a filesystem. The cron writes the report; the web reads it. Supabase Storage is the bridge.

---

## 4. Local Development

```bash
# 1. Install deps
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Fill in: DATABASE_URL (Supabase pooler), OPENAI_API_KEY,
#         SUPABASE_URL, SUPABASE_SERVICE_KEY, BUTTONDOWN_API_KEY

# 3. Apply migrations
alembic upgrade head

# 4. Run the daily pipeline (today)
python run_daily.py

# 5. Backfill historical dates (see §6)
python run_backfill.py --start-date 2026-01-01

# 6. Just regenerate the report from existing DB rows
python run_daily.py --report-only

# 7. Serve locally
python server.py   # http://localhost:8080
```

The default local DB is `sqlite:///./cuban_insights.db`; override `DATABASE_URL` to point at a Supabase project for parity with Render.

---

## 5. Environment Variables

See `.env.example` for the full list. The non-obvious ones:

| Var | Purpose | Required for |
|-----|---------|--------------|
| `DATABASE_URL` | Supabase Postgres **session pooler** URL (`aws-1-us-east-1.pooler.supabase.com:5432`). The transaction pooler does not work with SQLAlchemy's connection model. | cron + web |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` / `SUPABASE_REPORT_BUCKET` | Used to read & write the report bucket. `SUPABASE_SERVICE_KEY` is **cron-only**. Bucket must be public and allow `text/html`. | cron + web |
| `SITE_URL` / `SITE_NAME` / `SITE_OWNER_ORG` | Drive every `<title>`, OG tag, JSON-LD identifier, sitemap entry, canonical link, email "from" header. Override per environment. | cron + web |
| `REPORT_LOOKBACK_DAYS` | How many days back the daily report includes. Default `120`. | cron (report gen) |
| `SCRAPER_LOOKBACK_DAYS` | How far back each scraper looks per run. | cron |
| `OPENAI_MODEL` / `OPENAI_PREMIUM_MODEL` | Daily news churn vs evergreen landing-page generation. The premium model is invoked roughly weekly. | cron |
| `LLM_CALL_BUDGET_PER_RUN` | Hard cap on LLM calls per pipeline run. | cron |
| `INDEXNOW_KEY`, `GOOGLE_INDEXING_SA_JSON`, `BLUESKY_HANDLE`/`BLUESKY_APP_PASSWORD`, `INTERNET_ARCHIVE_*`, `ZENODO_*`, `OSF_*` | Distribution channels — each is silently skipped if its credential is blank. | cron |

---

## 6. Backfilling Historical Data

When the DB is empty (e.g., after a reset), use the backfill script:

```bash
# Default: backfill all enabled sources from 2026-01-01 to today
python run_backfill.py

# Custom range
python run_backfill.py --start-date 2026-01-01 --end-date 2026-04-15

# Pick specific sources
python run_backfill.py --sources federal_register,gaceta_oficial_cu

# Skip the analyzer + report generation (just scrape)
python run_backfill.py --skip-analyze --skip-report

# After scrapers backfill, fill in long-form derivatives:
python scripts/backfill_blog_posts.py
python scripts/backfill_og_images.py
python scripts/backfill_social_hooks.py
python scripts/backfill_calendar_events.py
```

Notes:
- **Federal Register** is fetched in a single API call covering the whole range.
- **Asamblea Nacional / Gaceta Oficial / MINREX** loop one day at a time. Be patient.
- **OFAC SDN** is snapshot-diff based — backfilling only captures the *current* SDN state, not historical changes.
- The script reuses `src/pipeline.py`'s `_persist_*` functions, so duplicates are silently dropped.

---

## 7. LLM Cost Management

The OFAC SDN list contains hundreds of CUBA-program entries. Sending all of them to GPT-4o costs real money. To prevent runaway cost, `src/analyzer.py` enforces:

1. **Rule-based templating** for OFAC SDN entries — no LLM call. Fixed `relevance_score=4` so they don't clutter the main report.
2. **Pre-filter** for everything else: must contain a Cuba-relevant keyword (`RELEVANCE_KEYWORDS`) and, for GDELT, exceed `GDELT_TONE_THRESHOLD`.
3. **Hard cap** of `LLM_CALL_BUDGET_PER_RUN = 200` calls per run, prioritized by source authority and tone magnitude.
4. **Premium model isolation** — the premium model (`OPENAI_PREMIUM_MODEL`) is only invoked by `src/landing_generator.py` for evergreen pillar / sector / explainer pages, regenerated roughly weekly. Daily blog posts and the analyzer use the cheaper `OPENAI_MODEL`.

If you change these constants, expect cost to scale linearly.

---

## 8. Deployment (Render)

`render.yaml` defines three services:

- `cuban-insights` (web) — `gunicorn server:app`, health check at `/health`.
- `cij-daily-pipeline` (cron) — `python run_daily.py`, schedule `0 15,22 * * *` UTC (10:00 / 17:00 Havana standard, 11:00 / 18:00 during Cuban DST).
- `cij-weekly-climate` (cron) — `python -c 'from src.climate import run_weekly_climate_refresh; run_weekly_climate_refresh()'`, schedule `0 14 * * 1` UTC (09:00 Havana standard, Mondays).

All services share env vars including `DATABASE_URL`, `SUPABASE_*`, `OPENAI_API_KEY`, `BUTTONDOWN_API_KEY`. **`SUPABASE_SERVICE_KEY` is only needed by the cron** (web only reads the public bucket).

To trigger an out-of-cycle run: use the Render dashboard "Trigger Run" button on the cron service, or call the REST API:

```bash
curl -X POST "https://api.render.com/v1/services/$CRON_ID/jobs" \
  -H "Authorization: Bearer $RENDER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"startCommand": "python run_daily.py"}'
```

---

## 9. Common Pitfalls (lessons learned, including from the VE-era predecessor)

1. **Wrong Supabase pooler hostname.** New projects are on `aws-1-us-east-1.pooler.supabase.com`, not `aws-0-`. Symptom: `FATAL: Tenant or user not found`.
2. **SQLAlchemy enum mismatch.** Postgres enums are lowercase (`gdelt`); SQLAlchemy was sending `GDELT`. `src/models.py` patches this with `_enum_values()` — do not bypass.
3. **Bucket MIME types.** Supabase Storage rejects `text/html; charset=utf-8` by default. The `reports` bucket must explicitly allow `text/html` and `text/html; charset=utf-8`.
4. **Render health check.** Default `/` returns 503 when the report has not been generated yet, breaking deploys. `healthCheckPath` is set to `/health`.
5. **`db.rollback()` is per-transaction, not per-row.** A single duplicate insert was wiping out an entire batch. `_persist_*` functions in `src/pipeline.py` wrap each insert in `db.begin_nested()` (savepoint). Do not refactor away.
6. **OFAC SDN entries had identical `source_url`.** Scraper appends `#sdn-{uid}-{change_type}` to make them unique.
7. **Render's IPs get rate-limited or DNS-blocked by some Cuban government endpoints.** Expect to need a proxy for `bc.gob.cu` and possibly GDELT.

---

## 10. File Map

```
src/
  pipeline.py              # Orchestrates per-day scrape + persist
  analyzer.py              # LLM analysis with budget + pre-filter
  blog_generator.py        # Long-form blog post generation
  landing_generator.py     # Premium-model evergreen page generation
  report_generator.py      # DB rows → templates/report.html.j2 → output/report.html
  storage_remote.py        # Supabase Storage upload/fetch
  models.py                # SQLAlchemy models + Enum value-callable patch
  config.py                # Pydantic settings (env-driven)
  og_image.py              # 1200x630 share-card rendering
  newsletter.py            # Buttondown / SendGrid / console adapter
  page_renderer.py         # Generic page-render helper used by server.py
  scraper/                 # One module per source (see §2)
  data/                    # Curated content layer (sdn_profiles, exposure, neighborhoods, etc.)
  seo/cluster_topology.py  # Topic-cluster graph used by every cluster_nav block
  climate/                 # Investment Climate Tracker (rubric + runner + snapshots)
  analysis/                # Per-source analysis helpers (edgar_search, etc.)
  distribution/            # IndexNow, Google Indexing, Bluesky, IA, Zenodo, OSF, tearsheet
templates/                 # Jinja templates (the *real* live design)
scripts/                   # Backfill helpers + maintenance scripts
run_daily.py               # Cron entrypoint
run_backfill.py            # Backfill historical dates (see §6)
server.py                  # Flask web entrypoint
render.yaml                # Render service definitions
alembic/                   # DB migrations
MIGRATION.md               # Record of the Caracas Research → Cuban Insights repointing
```
