# SEO Audit Tool — Continuation Notes

> **For the next AI session**: when told to "continue the SEO tool", start here.

## What's done

**`scripts/seo_audit.py`** — a complete SEO audit + auto-fix script. It:

- Queries all `BlogPost` and `LandingPage` rows from the database
- Runs 10 audit checks per entity:
  1. Title length (warn >60, error >110, auto-truncate)
  2. Meta description (missing, too short <50, too long >300, auto-truncate)
  3. Keywords (missing → backfill from `primary_sector`)
  4. Slug hygiene (lowercase, no double-hyphens, auto-normalize)
  5. JSON-LD data quality (HTML in titles, unescaped quotes)
  6. OG image coverage (blog posts missing `og_image_bytes`)
  7. Date completeness (`published_date` required)
  8. Body content (empty/orphan pages, very short content)
  9. Duplicate slugs (belt-and-suspenders on UNIQUE constraint)
  10. Social hook presence (needed for Bluesky distribution)
- Auto-fixes: title truncation, description truncation, slug normalization, keyword backfill, whitespace stripping
- Outputs: text summary (default) or `--json` machine-readable report
- Saves JSON reports to `seo/audit-reports/seo-audit-YYYY-MM-DD.json`
- `--commit` flag: git add + commit + push the report
- `--dry-run` flag: audit only, no DB writes

## What's left to do

### 1. Schedule daily execution (highest priority)
The script needs to run daily. Options:
- **Claude `/schedule`** — create a scheduled remote agent (was blocked by auth issue)
- **Render cron** — add to the existing pipeline alongside the daily report/blog generation
- **System crontab** — `0 6 * * * cd /path/to/repo && python3 scripts/seo_audit.py --commit`

### 2. Live-site HTML validation (medium priority)
Currently the script audits DB fields only. A next-level check would:
- Fetch rendered pages via the Flask test client (like `scripts/check_links.py` does)
- Parse actual `<meta>` tags and `<script type="application/ld+json">` from the HTML
- Validate JSON-LD against schema.org specs
- Check that OG image URLs actually return 200
- Verify canonical URLs resolve correctly

### 3. SERP preview simulation (nice to have)
- Render Google SERP snippets for each page (title + description + URL)
- Flag truncation visually
- Could output an HTML report

### 4. Alerting (nice to have)
- Send a summary to Slack/email when errors are found
- Could use the existing `DistributionLog` pattern

## Key files to understand

| File | What it does |
|------|-------------|
| `scripts/seo_audit.py` | The audit script (this is the main deliverable) |
| `src/models.py` | `BlogPost`, `LandingPage`, `SessionLocal`, `init_db` |
| `src/page_renderer.py` | Builds SEO dicts and JSON-LD for each page type |
| `src/config.py` | `settings.site_url`, `settings.site_name`, etc. |
| `templates/_base.html.j2` | Shared `<head>` with all meta/OG/JSON-LD tags |
| `scripts/check_links.py` | Existing link checker (uses Flask test client — good pattern for live validation) |
| `scripts/generate_curated_sitemap.py` | Hand-curated sitemap generator |

## How to test

```bash
# Dry run (no DB changes)
python3 scripts/seo_audit.py --dry-run

# Full run with fixes
python3 scripts/seo_audit.py

# Full run + commit report to git
python3 scripts/seo_audit.py --commit

# JSON output (for piping to other tools)
python3 scripts/seo_audit.py --dry-run --json
```

Note: local SQLite DB is empty — real data is on Render (Postgres). Set `DATABASE_URL` env var to point at the production DB for meaningful results.
