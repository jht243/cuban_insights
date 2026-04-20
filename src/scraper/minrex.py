"""
Scraper for MINREX — Ministerio de Relaciones Exteriores de la
República de Cuba (https://www.cubaminrex.cu).

Why this is defensive
---------------------
At time of writing the `cubaminrex.cu` domain does not resolve from
several US/EU residential ISPs (DNS poisoning + Cuban network
restrictions are both known to interfere). The scraper therefore:

  * Catches `httpx.ConnectError` / DNS failures and returns
    `success=False` with the error rather than crashing the whole
    pipeline.
  * Tries the RSS feed first (`/rss.xml`) — cheap to parse, gives us a
    structured `<item>` per declaration with title, link, date, and
    description.
  * Falls back to scraping the declaraciones HTML listing if RSS is
    empty/unavailable.

When the site IS reachable the scraper produces `ScrapedArticle`s
tagged `source_name="MINREX"` → `SourceType.MINREX`. These feed into
the same external-articles pipeline as Federal Register / GDELT / etc.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from src.config import settings
from src.scraper.base import BaseScraper, ScrapedArticle, ScrapeResult

logger = logging.getLogger(__name__)

SOURCE_ID = "minrex"
SOURCE_NAME = "MINREX"

# Same logic as the ONEI scraper: look back a week so a daily run catches
# any items that were posted late or whose timestamp is off by a day.
LOOKBACK_DAYS = 7


def _parse_dt_struct(struct_time) -> Optional[date]:
    """Convert a `feedparser` struct_time tuple into a `date`."""
    if not struct_time:
        return None
    try:
        return date(struct_time.tm_year, struct_time.tm_mon, struct_time.tm_mday)
    except (AttributeError, ValueError):
        return None


class MinrexScraper(BaseScraper):
    """Pulls latest declarations / press releases from cubaminrex.cu.

    Returns success=False (instead of raising) if the site is
    unreachable, so a transient DNS / network failure doesn't poison
    the whole daily run.
    """

    RSS_URL = f"{settings.minrex_url}/rss.xml"
    HTML_URL = f"{settings.minrex_url}/es/declaraciones-del-minrex"

    def get_source_id(self) -> str:
        return SOURCE_ID

    def scrape(self, target_date: Optional[date] = None) -> ScrapeResult:
        start = time.time()
        target_date = target_date or date.today()
        cutoff = target_date - timedelta(days=LOOKBACK_DAYS)

        # RSS first — cheaper and more structured.
        try:
            articles = self._scrape_rss(cutoff, target_date)
            if articles:
                logger.info("MINREX (RSS): %d item(s)", len(articles))
                return ScrapeResult(
                    source=self.get_source_id(),
                    success=True,
                    articles=articles,
                    duration_seconds=int(time.time() - start),
                )
        except (httpx.ConnectError, httpx.HTTPError) as e:
            # Network / DNS failure — record and continue to HTML
            # fallback. We only short-circuit the whole scraper if BOTH
            # surfaces fail.
            logger.warning("MINREX RSS unreachable: %s", e)
        except Exception as e:
            logger.warning("MINREX RSS parse failed: %s", e, exc_info=True)

        # HTML fallback.
        try:
            articles = self._scrape_html(cutoff, target_date)
            logger.info("MINREX (HTML): %d item(s)", len(articles))
            return ScrapeResult(
                source=self.get_source_id(),
                success=True,
                articles=articles,
                duration_seconds=int(time.time() - start),
            )
        except (httpx.ConnectError, httpx.HTTPError) as e:
            logger.warning("MINREX HTML unreachable: %s", e)
            return ScrapeResult(
                source=self.get_source_id(),
                success=False,
                error=f"unreachable: {e}",
                duration_seconds=int(time.time() - start),
            )
        except Exception as e:
            logger.error("MINREX scrape failed: %s", e, exc_info=True)
            return ScrapeResult(
                source=self.get_source_id(),
                success=False,
                error=str(e),
                duration_seconds=int(time.time() - start),
            )

    # ── Internal helpers ──────────────────────────────────────────────

    def _scrape_rss(self, cutoff: date, target_date: date) -> list[ScrapedArticle]:
        """Try the RSS feed. Returns [] if the feed is reachable but
        doesn't include any items in the lookback window. Raises on
        network errors (caller catches)."""
        # Lazy-import feedparser so the rest of the pipeline doesn't
        # die if it's not installed (it's a hard dep for the RSS
        # aggregator scraper too — see scraper/rss.py).
        try:
            import feedparser  # type: ignore
        except ImportError:
            logger.warning("feedparser not installed; skipping MINREX RSS")
            return []

        resp = self._fetch(self.RSS_URL)
        feed = feedparser.parse(resp.content)
        articles: list[ScrapedArticle] = []
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
            summary = (entry.get("summary") or entry.get("description") or "").strip()
            # Strip embedded HTML from summary if present.
            if summary and "<" in summary:
                summary = BeautifulSoup(summary, "lxml").get_text(" ", strip=True)
            articles.append(ScrapedArticle(
                headline=title,
                published_date=published,
                source_url=link,
                body_text=summary or None,
                source_name=SOURCE_NAME,
                source_credibility="official",
                article_type="press_release",
                extra_metadata={"feed": "rss"},
            ))
        return articles

    def _scrape_html(self, cutoff: date, target_date: date) -> list[ScrapedArticle]:
        """HTML fallback: parse the declaraciones listing page."""
        resp = self._fetch(self.HTML_URL)
        soup = BeautifulSoup(resp.text, "lxml")

        articles: list[ScrapedArticle] = []
        # The exact selectors here are a best-effort guess — the live
        # site couldn't be probed from the build environment. We look
        # for any anchor inside an article/teaser/views-row that has a
        # nearby <time> or "DD/MM/YYYY" string, which covers Drupal
        # (most likely) and Joomla (less likely) layouts.
        candidates = (
            soup.select(".views-row")
            or soup.select("article.node")
            or soup.select(".node-teaser")
            or soup.select(".item")
        )
        for card in candidates:
            a = card.find("a", href=True)
            if not a:
                continue
            title = a.get_text(strip=True)
            href = a["href"]
            if not title or len(title) < 8:
                continue
            url = urljoin(settings.minrex_url, href)

            published = target_date
            time_el = card.find("time")
            if time_el and time_el.get("datetime"):
                try:
                    published = datetime.fromisoformat(
                        time_el["datetime"].replace("Z", "+00:00")
                    ).date()
                except ValueError:
                    pass
            if published < cutoff or published > target_date + timedelta(days=1):
                continue

            articles.append(ScrapedArticle(
                headline=title,
                published_date=published,
                source_url=url,
                body_text=None,
                source_name=SOURCE_NAME,
                source_credibility="official",
                article_type="press_release",
                extra_metadata={"feed": "html"},
            ))
        return articles
