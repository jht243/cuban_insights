"""
Generic RSS aggregator for Cuban press outlets.

This scraper consumes a small whitelist of outlet RSS feeds and emits
each item as a `ScrapedArticle`. It exists so the analyzer + report
pipeline gets daily editorial coverage from the major Cuba-focused
news outlets without us building a bespoke HTML scraper for each one.

Outlet selection (Phase 2d)
---------------------------
The user picked these seven outlets in Phase 2 planning:

  Granma          — official Communist Party paper (state)
  Cubadebate      — state-aligned digital outlet (state)
  14ymedio        — in-island independent / Yoani Sánchez (tier1)
  Diario de Cuba  — Madrid-based diaspora opposition (tier2)
  OnCuba          — Miami-based diaspora, broadly balanced (tier1)
  Havana Times    — expat/independent commentary (tier2)
  CiberCuba       — Spain-based diaspora populist (no public RSS)

CiberCuba does not expose an RSS feed (it's an AMP-only WordPress
build, and `/feed` returns AMP HTML rather than RSS XML). It's
intentionally omitted from `_OUTLETS` below; if we ever want it we'll
need a sitemap-driven HTML scraper as a separate module.

Note about Granma: from some networks (including the build environment
used during smoke-testing of this module) `granma.cu` does not resolve
in DNS — Cuban government domains intermittently fail to resolve from
US/EU residential ISPs. The scraper handles per-feed network failures
gracefully (logs + continues), so a transient Granma DNS issue won't
abort the whole RSS run.

Credibility tiers
-----------------
We tag each outlet with a `source_credibility` so the downstream
analyzer can weight or distinguish them:

  * official  — state-controlled (Granma, Cubadebate)
  * tier1     — in-island or balanced independent (14ymedio, OnCuba)
  * tier2     — diaspora opposition (Diario de Cuba, Havana Times)

These map onto the same `CredibilityTier` enum used elsewhere in the
codebase via `pipeline._persist_articles`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from src.scraper.base import BaseScraper, ScrapedArticle, ScrapeResult

logger = logging.getLogger(__name__)

SOURCE_ID = "press_rss"

# How far back to import on each run. Daily cron runs twice a day so a
# 2-day window catches anything that landed late or got reposted with a
# minor edit, without re-importing the entire monthly archive.
LOOKBACK_DAYS = 2


@dataclass(frozen=True)
class _Outlet:
    name: str        # used as ScrapedArticle.source_name
    feed_url: str    # primary RSS URL
    credibility: str # "official" | "tier1" | "tier2"


# Outlet whitelist. Order is cosmetic; failures on any one outlet are
# isolated so the order doesn't affect coverage.
_OUTLETS: tuple[_Outlet, ...] = (
    _Outlet("Granma",         "https://www.granma.cu/feed",      "official"),
    _Outlet("Cubadebate",     "http://www.cubadebate.cu/feed/",  "official"),
    _Outlet("14ymedio",       "https://www.14ymedio.com/rss/",   "tier1"),
    _Outlet("OnCuba",         "https://oncubanews.com/feed/",    "tier1"),
    _Outlet("Diario de Cuba", "https://diariodecuba.com/rss.xml", "tier2"),
    _Outlet("Havana Times",   "https://havanatimes.org/feed/",   "tier2"),
)


def _parse_dt_struct(struct_time) -> Optional[date]:
    if not struct_time:
        return None
    try:
        return date(struct_time.tm_year, struct_time.tm_mon, struct_time.tm_mday)
    except (AttributeError, ValueError):
        return None


def _strip_html(value: str) -> str:
    """Many RSS items embed HTML in the description/summary. Strip it
    so the analyzer + report layer get clean plain text."""
    if not value:
        return ""
    if "<" not in value:
        return value.strip()
    return BeautifulSoup(value, "lxml").get_text(" ", strip=True)


class PressRssScraper(BaseScraper):
    """Aggregates RSS feeds from major Cuban press outlets.

    Network errors on individual feeds are caught and logged; the
    scraper only reports `success=False` if every single feed fails,
    which is essentially "the internet is down" rather than "this
    source is broken".
    """

    def get_source_id(self) -> str:
        return SOURCE_ID

    def scrape(self, target_date: Optional[date] = None) -> ScrapeResult:
        start = time.time()
        target_date = target_date or date.today()
        cutoff = target_date - timedelta(days=LOOKBACK_DAYS)

        # Lazy-import feedparser so the rest of the pipeline keeps
        # working if the dependency is somehow missing.
        try:
            import feedparser  # type: ignore
        except ImportError:
            logger.error(
                "feedparser is not installed — install with `pip install "
                "feedparser` or add it to requirements.txt"
            )
            return ScrapeResult(
                source=self.get_source_id(),
                success=False,
                error="feedparser dependency missing",
                duration_seconds=int(time.time() - start),
            )

        articles: list[ScrapedArticle] = []
        successes = 0
        per_outlet_errors: list[str] = []

        for outlet in _OUTLETS:
            try:
                fetched = self._fetch_outlet(
                    feedparser, outlet, cutoff=cutoff, target_date=target_date,
                )
                articles.extend(fetched)
                successes += 1
                logger.info(
                    "RSS [%s]: %d new item(s)", outlet.name, len(fetched),
                )
            except (httpx.ConnectError, httpx.HTTPError) as e:
                # Network errors are common and NON-fatal for a single
                # outlet — log and move on.
                per_outlet_errors.append(f"{outlet.name}: {e}")
                logger.warning("RSS [%s] unreachable: %s", outlet.name, e)
            except Exception as e:
                per_outlet_errors.append(f"{outlet.name}: {e}")
                logger.warning(
                    "RSS [%s] failed: %s", outlet.name, e, exc_info=True,
                )

        # Treat the run as a failure only if no outlet returned anything
        # AND no outlet succeeded — otherwise it's a partial success
        # which is the normal steady state given Granma's DNS issues.
        if successes == 0:
            return ScrapeResult(
                source=self.get_source_id(),
                success=False,
                error="all RSS outlets failed: " + "; ".join(per_outlet_errors),
                duration_seconds=int(time.time() - start),
            )

        return ScrapeResult(
            source=self.get_source_id(),
            success=True,
            articles=articles,
            error=("; ".join(per_outlet_errors) or None),
            duration_seconds=int(time.time() - start),
        )

    # ── Internal helpers ──────────────────────────────────────────────

    def _fetch_outlet(
        self,
        feedparser_mod,
        outlet: _Outlet,
        *,
        cutoff: date,
        target_date: date,
    ) -> list[ScrapedArticle]:
        # Use BaseScraper._fetch so we get retry + Mozilla UA.
        resp = self._fetch(outlet.feed_url)
        feed = feedparser_mod.parse(resp.content)

        out: list[ScrapedArticle] = []
        for entry in feed.entries:
            published = (
                _parse_dt_struct(getattr(entry, "published_parsed", None))
                or _parse_dt_struct(getattr(entry, "updated_parsed", None))
                or target_date
            )
            if published < cutoff or published > target_date + timedelta(days=1):
                continue

            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue

            summary = _strip_html(
                entry.get("summary") or entry.get("description") or ""
            )
            # Some feeds return the entire article body in `content` —
            # prefer that over the (often truncated) summary when
            # available.
            content_blocks = entry.get("content") or []
            if content_blocks:
                full = _strip_html(content_blocks[0].get("value", ""))
                if full and len(full) > len(summary):
                    summary = full

            out.append(ScrapedArticle(
                headline=title,
                published_date=published,
                source_url=link,
                body_text=summary or None,
                source_name=outlet.name,
                source_credibility=outlet.credibility,
                article_type="news",
                extra_metadata={
                    "feed_url": outlet.feed_url,
                    "outlet": outlet.name,
                },
            ))
        return out
