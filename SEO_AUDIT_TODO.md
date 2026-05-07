# SEO Audit Tool — Status & TODO

## What's done

### Core audit engine (`src/seo/audit.py`)
- **Meta tag checks** — validates `<title>` length (20–70 chars), `<meta description>` length (50–160 chars), canonical URL, og:title, og:image, robots directive
- **Heading checks** — single H1 per page, no skipped heading levels (H1→H3 without H2)
- **Structured data** — verifies JSON-LD blocks exist and extracts `@type` values
- **Content depth** — flags pages under 100 words as thin content
- **Cluster coverage** — cross-references every page registered in `src/seo/cluster_topology.py` against the crawl; flags members not reached or missing the cluster nav block
- **Sitemap alignment** — cross-references `seo/curated-sitemap.xml` against the crawl; flags pages in the sitemap that weren't reachable
- **Internal link analysis** — counts inbound internal links to hub pages; flags hubs with < 2 inbound links
- **Crawl engine** — BFS crawl via Flask test_client (zero network, zero external deps), follows internal links transitively, caps at configurable max pages

### CLI (`scripts/seo_audit.py`)
- `python scripts/seo_audit.py` — human-readable Rich table + findings
- `python scripts/seo_audit.py --json` — machine-readable JSON output
- `python scripts/seo_audit.py --verbose` — includes info-level findings
- `python scripts/seo_audit.py --fail-on-error` — exits 1 if errors found (CI gate)
- `python scripts/seo_audit.py --max-pages N` — limit crawl depth
- `python scripts/seo_audit.py --no-follow` — seed pages only, no link following

### Daily pipeline integration (`run_daily.py`)
- Phase 6: SEO audit runs on every daily cron invocation (after distribution)
- Phase 6b: auto-fix engine runs immediately after audit, fixing clearly wrong issues
- Non-fatal — audit and fix failures never block content publication
- Summary logged to pipeline results (pages crawled, error/warning counts, fixes applied)

### Auto-fix engine (`src/seo/content_fixer.py`)
- **Title/description clamping** — Jinja filters (`seo_title`, `seo_desc`) in `_base.html.j2` clamp titles to 70 chars and descriptions to 160 chars at render time (word-boundary aware, ellipsis appended)
- **Missing canonical fallback** — `_base.html.j2` falls back to `request.url` when canonical is empty
- **Missing H1 fix** — for LandingPage-backed pages, web-searches the topic for current data, generates an H1 + opening paragraph via premium LLM, prepends to body_html
- **Thin content fix** — for LandingPage-backed pages under 200 words, web-searches for current information, expands body to 400-600 words via premium LLM
- Budget-capped at 5 fixes per run (~$0.20-0.40/day max)
- Only operates on LandingPage rows (sectors, explainers, pillar pages) — tool/hub pages excluded

### Pre-existing SEO infrastructure
- **Topic clusters** (`src/seo/cluster_topology.py`) — 6 clusters (sanctions, investment, export, travel, people, fx) with pillar pages, canonical anchor text, related tools graph
- **Curated sitemap** (`scripts/generate_curated_sitemap.py` → `seo/curated-sitemap.xml`) — top ~100 URLs for initial search engine submission
- **Priority indexing** (`seo/priority-indexing.txt`) — top 20 URLs for manual "Request Indexing"
- **IndexNow** (`src/distribution/indexnow.py`, `scripts/indexnow_submit.py`) — batch URL submission to Bing/Yandex/Seznam/Naver/Mojeek
- **Google Indexing API** (`src/distribution/google_indexing.py`) — URL_UPDATED pings for new content
- **Broken link checker** (`scripts/check_links.py`) — BFS crawl + optional live HEAD checks on external links
- **Companion links** (`templates/_companion_links.html.j2`) — cross-hub internal links on `/tools`, `/sanctions-tracker`, `/companies`
- **Cluster nav** (`templates/_cluster_nav.html.j2`) — per-page topic cluster navigation
- **Related tools** — per-tool "Other tools" strip with curated 3-tool recommendations
- **OG images** (`src/og_image.py`, `scripts/backfill_og_images.py`) — per-page 1200×630 PNGs
- **Dynamic sitemaps** (`server.py`) — `/sitemap.xml` and `/news-sitemap.xml` served live

---

## What's left (TODO)

### Scheduling (main gap)
- [x] ~~**Configurable schedule**~~ — now runs daily (every cron invocation), no day-of-week gate.
- [ ] **Standalone cron mode** — add a `--schedule` flag to `scripts/seo_audit.py` that uses APScheduler (already in requirements) to run the audit on a cron expression, independent of the daily pipeline. Useful for dedicated SEO-monitoring deployments.
- [ ] **Audit result persistence** — store each audit run in a new `SeoAuditLog` model (timestamp, pages_crawled, error_count, warning_count, findings_json) so trends can be tracked over time and regressions caught.
- [ ] **Trend dashboard** — expose `/admin/seo-audit` (or a CLI `--history` flag) showing audit score over time — are errors going up or down week-over-week?

### Depth improvements
- [ ] **Canonical URL validation** — check that the canonical URL matches the actual request path (catch self-referencing canonical mismatches)
- [ ] **Duplicate title/description detection** — flag pages that share identical titles or meta descriptions
- [ ] **Image alt text audit** — check that `<img>` tags have non-empty `alt` attributes
- [ ] **Hreflang validation** — verify hreflang tags are well-formed (relevant if/when the site adds Spanish content)
- [ ] **robots.txt cross-check** — verify none of the pages in the sitemap are disallowed by robots.txt
- [ ] **Page speed proxy** — measure HTML payload size, count render-blocking resources (not a real Lighthouse score, but a directional signal)
- [ ] **Anchor text drift** — compare actual anchor text used in internal links against the canonical anchors in `cluster_topology.py`; flag significant deviations

### External integrations
- [ ] **GSC MCP integration** — after crawl, optionally query the GSC MCP (`user-gsc`) for indexing status of pages with errors, and surface "indexed with errors" or "not indexed" alongside audit findings
- [ ] **Bing Webmaster MCP** — similar integration with `user-bing-webmaster` for Bing coverage gaps
- [ ] **Slack/email alerting** — post audit summary to a Slack webhook or send via Resend when errors exceed a threshold

---

## Key files

| File | What it does |
|------|-------------|
| `src/seo/__init__.py` | Package marker |
| `src/seo/audit.py` | Core audit engine (crawl, parse, check, report) |
| `src/seo/cluster_topology.py` | Topic cluster definitions, canonical anchors, related tools |
| `scripts/seo_audit.py` | CLI entry point for the audit |
| `scripts/check_links.py` | Standalone broken link checker (separate from audit) |
| `scripts/generate_curated_sitemap.py` | Generates `seo/curated-sitemap.xml` and `seo/priority-indexing.txt` |
| `scripts/indexnow_submit.py` | Batch IndexNow submission |
| `seo/curated-sitemap.xml` | Hand-curated 100-URL sitemap |
| `seo/priority-indexing.txt` | Top 20 URLs for manual indexing |
| `src/seo/content_fixer.py` | Auto-fix engine (web search + LLM for missing H1 / thin content) |
| `run_daily.py` | Daily pipeline — Phase 6 runs the SEO audit, Phase 6b auto-fixes |
| `src/distribution/runner.py` | Phase 5 — Google Indexing + IndexNow + Bluesky + IA + Zenodo + OSF |

---

## How to test

```bash
# Quick smoke test (5 pages, no link following)
python scripts/seo_audit.py --max-pages 5 --no-follow

# Full audit (follows links, ~200 pages, ~40s)
python scripts/seo_audit.py

# JSON output for CI/scripting
python scripts/seo_audit.py --json | python -m json.tool

# CI gate — fails if any errors
python scripts/seo_audit.py --fail-on-error

# Verbose — shows info-level findings (thin content, sitemap gaps)
python scripts/seo_audit.py --verbose

# Broken link checker (separate tool, overlapping purpose)
python scripts/check_links.py
python scripts/check_links.py --live  # also HEAD-checks external URLs
```
