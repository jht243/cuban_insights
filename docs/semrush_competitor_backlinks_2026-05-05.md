# SEMrush Competitor Backlink Outreach Pull — 2026-05-05

This is the corrected outreach-oriented SEMrush pull. The goal is not just to summarize competitor backlink profiles; it is to identify exact pages linking to better-known Cuba / Latin America policy competitors so Cuban Insights can pitch those same publishers for backlinks.

## Best Artifact

Use this first for outreach:

`storage/semrush_backlinks/cubaninsights.com_20260505T150907Z/deduped_source_url_prospects.csv`

This deduplicates by `source_url`, because we only need to contact a publisher once per linking page. It preserves all competitor context from that source page:

- competitors linked from the source page
- competitor target URLs
- anchors
- best page authority score
- nofollow/sitewide values
- count of competitor links on that exact page

Full exact backlink rows, before deduplication:

`storage/semrush_backlinks/cubaninsights.com_20260505T150907Z/combined_backlink_prospects.csv`

Columns:

- `competitor` — competitor domain receiving the backlink
- `source_domain` — domain linking to the competitor
- `source_url` — exact page where the backlink comes from
- `source_title` — title of the linking page
- `competitor_target_url` — exact competitor page being linked to
- `anchor` — linked anchor text
- `page_ascore` — SEMrush authority score for the linking page
- `first_seen` / `last_seen` — SEMrush timestamps
- `nofollow` — whether the backlink is nofollow
- `sitewide` — whether SEMrush marked it as sitewide
- `external_num` / `internal_num` — link counts on the linking page

Cuba-keyword-filtered outreach subset:

`storage/semrush_backlinks/cubaninsights.com_20260505T150907Z/deduped_cuba_source_url_prospects.csv`

Full Cuba-keyword-filtered exact rows, before deduplication:

`storage/semrush_backlinks/cubaninsights.com_20260505T150907Z/cuba_related_backlink_prospects.csv`

This local subset filters the exact backlink rows for:

`cuba`, `cuban`, `havana`, `caribbean`, `ofac`, `sanctions`, `embargo`

## Competitors Pulled

These are better-known, higher-authority competitors / adjacent publishers than the first pass:

- `cfr.org`
- `csis.org`
- `brookings.edu`
- `wilsoncenter.org`
- `wola.org`
- `as-coa.org`
- `americasquarterly.org`
- `cubastudygroup.org`

## Pull Details

- Target context: `cubaninsights.com`
- Pull timestamp: `2026-05-05T15:09:07Z`
- Backlinks pulled: 50 per competitor
- Referring domains pulled: 25 per competitor
- Exact backlink prospect rows: 400
- Deduped source-URL prospects: 219
- Cuba-related exact backlink rows: 64
- Deduped Cuba-related source-URL prospects: 61
- Unique combined referring-domain opportunities: 75
- SEMrush API unit balance before: `1,371,110`
- SEMrush API unit balance after: `1,347,110`
- Units used: `24,000`

## Top Cuba-Related Outreach Examples

Examples from `deduped_cuba_source_url_prospects.csv`:

| Competitor | Source Domain | Source URL | Competitor Target URL | Anchor | Follow |
|---|---|---|---|---|---|
| `as-coa.org` | `lapupilainsomne.wordpress.com` | `https://lapupilainsomne.wordpress.com/2018/05/23/breve-e-incompleta-cronologia-de-un-fracaso-por-iroel-sanchez/` | `http://www.as-coa.org/sites/default/files/CartaAbiertaObamaCuba.pdf` | `Carta abierta` | yes |
| `cubastudygroup.org` | `cfr.org` | `https://www.cfr.org/articles/trumps-maximum-pressure-campaign-on-cuba-explained` | `https://cubastudygroup.org/blog_posts/the-cuban-single-party-system-a-primer-on-the-pcc-in-the-exercise-of-power-in-cuba/#_ftn5` | `describes` | yes |
| `wola.org` | `commondreams.org` | `https://www.commondreams.org/` | `https://www.wola.org/analysis/understanding-failure-of-us-cuba-embargo/` | `says` | yes |
| `wilsoncenter.org` | `uz.usembassy.gov` | `https://uz.usembassy.gov/united-states-government-delivers-equipment-for-global-seismic-network-gsn-station-to-the-government-of-uzbekistan/` | `https://www.wilsoncenter.org/blog-post/cuba-and-the-oas-story-dramatic-fallout-and-reconciliation` | `Cuba had been suspended` | yes |
| `wola.org` | `commondreams.org` | `https://www.commondreams.org/tag/donald-trump` | `https://www.wola.org/analysis/understanding-failure-of-us-cuba-embargo/` | `says` | yes |

Note: `nofollow=false` in SEMrush output is represented as "Follow: yes" above. The CSV preserves the raw `nofollow` value.

## Raw Files

Folder:

`storage/semrush_backlinks/cubaninsights.com_20260505T150907Z/`

Important files:

- `combined_backlink_prospects.csv`
- `cuba_related_backlink_prospects.csv`
- `deduped_source_url_prospects.csv`
- `deduped_cuba_source_url_prospects.csv`
- `combined_refdomain_opportunities.csv`
- `<competitor>_backlinks.csv`
- `<competitor>_refdomains.csv`
- `summary.json`

## Reuse Command

```bash
python3 scripts/pull_semrush_competitor_backlinks.py \
  --target cubaninsights.com \
  --competitors cfr.org,csis.org,brookings.edu,wilsoncenter.org,wola.org,as-coa.org,americasquarterly.org,cubastudygroup.org \
  --backlinks-per-competitor 50 \
  --refdomains-per-competitor 25
```

The script reads `SEMRUSH_API_KEY` from the environment or local `.env` file.

## Notes

- A SEMrush `urlanchor` API filter for `cuba` was attempted but returned HTTP 400, so the script now writes the complete exact-link prospect file and then performs local keyword filtering into `cuba_related_backlink_prospects.csv`.
- The first pull against `oncubanews.com`, `14ymedio.com`, `diariodecuba.com`, `havanatimes.org`, and `cubadebate.cu` is still stored under `storage/semrush_backlinks/cubaninsights.com_20260505T150533Z/`, but the corrected outreach dataset is the `20260505T150907Z` folder.
