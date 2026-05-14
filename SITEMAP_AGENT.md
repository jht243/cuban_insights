# Sitemap Agent — Handoff Doc

How the sitemap system works, how to run it, and how to extend it.

## Architecture

Cuban Insights uses a **split sitemap index** (`/sitemap.xml`) pointing at
focused child sitemaps. This lets us submit only high-value buckets to Google
Search Console while the long-tail archive sits in robots discovery.

### Sitemap routes (all in `server.py`)

| Route | Source | Lines (approx) |
|-------|--------|-----------------|
| `/sitemap.xml` | Sitemap index — lists all children | ~7985 |
| `/sitemap-core.xml` | `_core_static_urls()` + `_people_sitemap_urls()` | ~8014 |
| `/sitemap-briefings-recent.xml` | `BlogPost` DB query (last 90 days) | ~8022 |
| `/sitemap-companies-priority.xml` | `list_company_index_rows()` (curated + SDN) | ~8057 |
| `/sitemap-sdn-priority.xml` | `list_profiles("entities")` | ~8083 |
| `/sitemap-cpal.xml` | `list_cpal_profiles()` | ~8109 |
| `/sitemap-crl.xml` | `list_crl_profiles()` | ~8132 |
| `/sitemap-archive.xml` | Older posts, LandingPages, sectors, non-priority companies/SDN | ~8151 |
| `/news-sitemap.xml` | Recent BlogPosts (Google News format) | ~8367 |
| `/curated-sitemap.xml` | Static XML from `seo/curated-sitemap.xml` | ~8461 |

### Hardcoded URL list

The main list of hand-curated static URLs lives in `_core_static_urls()` in
`server.py` (approx lines 7892–7965). This is what the sync script
auto-patches.

**Insertion anchor** (where new entries are spliced): the sync script appends
new hardcoded URLs immediately before the closing `]` of `_core_static_urls()`.

### Route-existence guard

DB-sourced URLs (BlogPost, LandingPage, sector slugs) are checked against
Flask's URL map via `_sitemap_route_exists()` before inclusion. This catches
orphaned DB records whose route pattern was removed. It does NOT catch
content-less wildcard matches (e.g. `/sectors/nonexistent`) — those are caught
by the nightly spot-check.

## Nightly Sync Script

**File:** `scripts/sync_sitemap.py`

### What it does

1. **Fetches** all live child sitemaps and extracts every `<loc>` path
2. **Extracts** `@app.route` declarations from `server.py`, filtering out
   parametric routes and internal/excluded paths
3. **Diffs** the two sets — routes in code but not in any sitemap are
   auto-inserted into `_core_static_urls()` with heuristic priority values
4. **Spot-checks** 25 random live sitemap URLs via HTTP GET, reporting any
   4xx/5xx as dead links
5. If entries were added, **commits and pushes** to `origin/main` (triggers
   Render auto-deploy)

### How to run

```bash
# Audit only, no file changes
python scripts/sync_sitemap.py --dry-run

# Fast offline audit (no HTTP spot-checks)
python scripts/sync_sitemap.py --dry-run --no-spot-check

# Full run: patch server.py + git push
python scripts/sync_sitemap.py
```

### When it runs

Integrated as **Phase 7** of the daily pipeline (`run_daily.py`), which runs
via the existing `cij-daily-pipeline` Render cron at 15:00 and 22:00 UTC.
No separate cron service needed — saves a Starter plan slot.

The sync respects `--dry-run` and `--report-only` flags from the pipeline.
It can also be run standalone via `python scripts/sync_sitemap.py`.

## Environment Variables

| Variable | Where to set | Purpose |
|----------|-------------|---------|
| `SITE_URL` | Render dashboard, `.env` | Canonical base URL (default: `https://cubaninsights.com`) |
| `GITHUB_TOKEN` | Render dashboard (secret) | Fine-grained PAT with Contents: Read & Write on the repo |
| `GITHUB_REPO` | Render dashboard, `.env` | `owner/repo-name` (e.g. `jonathanteplitsky/cuban-insights`) |

Create the GitHub token at **Settings → Developer settings → Fine-grained
personal access tokens**. Scope it to the single repo with only **Contents:
Read & Write**. Never commit it.

Without `GITHUB_TOKEN`, the script still audits and reports — it just can't
push fixes.

## Exclusion Rules

Defined at the top of `scripts/sync_sitemap.py`:

- **EXCLUDE_PREFIXES:** `/api/`, `/health`, `/admin`, `/webhook`, `/internal`,
  `/static/`, `/og/`, `/tearsheet/`
- **EXCLUDE_SUFFIXES:** `.txt`, `.xml`, `.pdf`, `.json`, `.png`, `.jpg`
- **EXCLUDE_EXACT:** All sitemap XML routes, `robots.txt`, `briefing/feed.xml`
- **EXCLUDE_CONTAINS:** `noindex`, `debug`, `test`

To add a new exclusion, edit the corresponding set/tuple in the script.

## Common Dead-Link Patterns

| Pattern | Guard |
|---------|-------|
| Orphaned DB record (no route) | `_sitemap_route_exists()` in server.py |
| Content-less wildcard match | Nightly spot-check (reports only) |
| Stale www/non-www GSC submission | Delete the www variant in GSC |
| Redirect alias in sitemap | Add to `EXCLUDE_EXACT` |

## Search Engine Submissions

### Google Search Console

Submitted sitemaps (via GSC dashboard or API):
- `sitemap-core.xml`
- `sitemap-briefings-recent.xml`
- `sitemap-companies-priority.xml`
- `sitemap-sdn-priority.xml`
- `sitemap-cpal.xml`
- `sitemap-crl.xml`
- `news-sitemap.xml`
- `curated-sitemap.xml`

The `sitemap-archive.xml` is intentionally NOT submitted — it's discoverable
via `robots.txt` / sitemap index but we don't want Google spending crawl budget
on it over the priority sitemaps.

### Bing Webmaster Tools

Submit the same set via the Bing dashboard or API. Delete any stale `www.`
submissions if the canonical is non-www.

## Related Scripts

- `scripts/generate_curated_sitemap.py` — regenerates `seo/curated-sitemap.xml`
- `scripts/check_links.py` — BFS link crawler (local + live)
- `scripts/indexnow_submit.py` — ping Bing/Yandex about new URLs
- `scripts/submit_priority_indexnow.py` — batch-submit priority URLs
- `src/seo/audit.py` — SEO audit run as Phase 6 of `run_daily.py`
