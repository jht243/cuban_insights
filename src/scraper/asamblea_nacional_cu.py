"""
Scraper for the Cuban National Assembly — Asamblea Nacional del Poder
Popular (https://www.parlamentocubano.gob.cu).

Strategy
--------
The site is a Joomla install. We pull the `/noticias` listing page,
collect every `/noticias/<slug>` link (the listing renders each item
twice — once as image, once as title), dedupe, then fetch each
article's detail page to pick up:

  * headline (page <title>)
  * published date (`<time datetime="ISO">`)
  * body text (`<article>` content)
  * author (when present, used for credibility hints downstream)

Articles are filtered to `target_date` (today by default) so a daily
run only persists same-day news; a backfill run can pass a specific
target_date.

The `/labor-legislativa` page also exposes the Asamblea's catalogue of
approved laws + PDF links (e.g. "Ley 183 ‹De Reducción Excepcional...›")
but those are static / weekly-update content that doesn't fit a daily
news cadence. We skip it here and will surface it from a separate
backfill module in Phase 5.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timedelta
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.config import settings
from src.scraper.base import BaseScraper, ScrapedNews, ScrapeResult

logger = logging.getLogger(__name__)

SOURCE_ID = "asamblea_nacional_cu"

# The Asamblea publishes news on roughly a weekly cadence (legislative
# sessions, committee meetings, official declarations). Filtering to
# `published_date == target_date` would persist almost nothing on most
# days, so we look back a short window and rely on the
# UniqueConstraint(source_url) in the DB to dedupe across runs.
LOOKBACK_DAYS = 7

# News slugs come in two equivalent flavours on this Joomla site:
#   /noticias/<slug>             (SEF-rewritten URL)
#   /index.php/noticias/<slug>   (fallback URL — same content)
# We treat them as the same article and prefer the SEF form.
_NEWS_HREF_RE = re.compile(r"^/(?:index\.php/)?noticias/[^/?#]+$")


def _normalize_news_url(href: str) -> str:
    """Strip /index.php/ prefix so /noticias/foo and /index.php/noticias/foo
    dedupe to the same canonical URL."""
    if href.startswith("/index.php/"):
        href = href[len("/index.php"):]
    return href


def _parse_iso_date(value: str) -> Optional[date]:
    """Parse an ISO 8601 timestamp like '2026-04-17T12:00:00Z'."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


class AsambleaNacionalCUScraper(BaseScraper):
    """Pulls today's news items from parlamentocubano.gob.cu/noticias."""

    LISTING_URL = f"{settings.assembly_url}/noticias"

    def get_source_id(self) -> str:
        return SOURCE_ID

    def scrape(self, target_date: Optional[date] = None) -> ScrapeResult:
        start = time.time()
        target_date = target_date or date.today()
        cutoff = target_date - timedelta(days=LOOKBACK_DAYS)

        try:
            article_urls = self._collect_article_urls()
            news: list[ScrapedNews] = []

            for url in article_urls:
                try:
                    item = self._fetch_article(url, fallback_date=target_date)
                except Exception as e:
                    logger.warning(
                        "Asamblea CU: failed to fetch %s: %s", url, e,
                    )
                    continue
                if not item:
                    continue
                # Lookback window: persist anything from the last ~week.
                # The DB UniqueConstraint(source_url) dedupes repeats
                # across runs, so this is safe to call daily.
                if item.published_date < cutoff or item.published_date > target_date + timedelta(days=1):
                    logger.debug(
                        "Asamblea CU: skipping %s (date %s outside %s..%s)",
                        url, item.published_date, cutoff, target_date,
                    )
                    continue
                news.append(item)

            logger.info(
                "Asamblea CU: %d article(s) within %s..%s (out of %d on listing)",
                len(news), cutoff, target_date, len(article_urls),
            )
            return ScrapeResult(
                source=self.get_source_id(),
                success=True,
                news=news,
                duration_seconds=int(time.time() - start),
            )
        except Exception as e:
            logger.error("Asamblea CU scrape failed: %s", e, exc_info=True)
            return ScrapeResult(
                source=self.get_source_id(),
                success=False,
                error=str(e),
                duration_seconds=int(time.time() - start),
            )

    # ── Internal helpers ──────────────────────────────────────────────

    def _collect_article_urls(self) -> list[str]:
        """Return a deduped list of article URLs from the listing page."""
        resp = self._fetch(self.LISTING_URL)
        soup = BeautifulSoup(resp.text, "lxml")

        seen: set[str] = set()
        urls: list[str] = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not _NEWS_HREF_RE.match(href):
                continue
            href = _normalize_news_url(href)
            if href in seen:
                continue
            seen.add(href)
            urls.append(urljoin(settings.assembly_url, href))
        return urls

    def _fetch_article(
        self, url: str, *, fallback_date: date,
    ) -> Optional[ScrapedNews]:
        resp = self._fetch(url)
        soup = BeautifulSoup(resp.text, "lxml")

        # Strip noisy chrome.
        for tag in soup.select("script,style,header,footer,nav,.menu"):
            tag.decompose()

        # Headline: <title> minus the trailing site name (Joomla
        # convention: "Article title | Site Name").
        page_title = soup.title.get_text(strip=True) if soup.title else ""
        headline = page_title.split("|", 1)[0].strip() if "|" in page_title else page_title
        if not headline:
            h1 = soup.select_one("h1, h2.item-title, .item-page h2")
            headline = h1.get_text(strip=True) if h1 else url.rsplit("/", 1)[-1]

        # Published date — `<time datetime="ISO">` is the most reliable.
        published = fallback_date
        time_el = soup.select_one("time[datetime]")
        if time_el:
            parsed = _parse_iso_date(time_el.get("datetime", ""))
            if parsed:
                published = parsed
        else:
            # Some article pages render the date as a literal "Fecha
            # 17/04/2026" string at the top of the body — fall back to
            # that.
            body_text = soup.get_text(" ", strip=True)
            m = re.search(r"Fecha\s+(\d{2})/(\d{2})/(\d{4})", body_text)
            if m:
                try:
                    published = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                except ValueError:
                    pass

        # Body — prefer <article>, fall back to common Joomla containers.
        body_el = (
            soup.select_one("[itemprop=articleBody]")
            or soup.select_one(".com-content-article__body")
            or soup.select_one(".item-page")
            or soup.select_one("article")
        )
        body_text = None
        if body_el:
            for noise in body_el.select(
                ".article-info, .tags, .pager, .breadcrumb, .share, .social"
            ):
                noise.decompose()
            raw = body_el.get_text(separator="\n", strip=True)
            # Drop the first lines if they're just the metadata header
            # ("Fecha 17/04/2026", "Autor ...", "Fotos ...") that Joomla
            # emits above the lead paragraph.
            lines = [ln for ln in raw.split("\n") if ln.strip()]
            cleaned: list[str] = []
            for ln in lines:
                low = ln.strip().lower()
                if low.startswith(("fecha ", "autor", "fotos", "fuente", "tags:")):
                    continue
                cleaned.append(ln)
            body_text = "\n".join(cleaned).strip() or None

        return ScrapedNews(
            headline=headline,
            published_date=published,
            source_url=url,
            body_text=body_text,
        )
