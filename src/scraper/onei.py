"""
Scraper for ONEI — Oficina Nacional de Estadística e Información
(https://www.onei.gob.cu).

ONEI is Cuba's official statistics office and the canonical source for
macroeconomic numbers (population, employment, salaries, GDP, trade,
construction, agriculture, etc.). Every release is published as a
"publicación" with a thumbnail, title, link to a detail page, and
publication date.

Strategy
--------
We pull `/publicaciones-economico` (the economics-focused publications
listing). The page is a Drupal view that renders each release as a
`.views-row` card with:

  * `.views-field-title a`        → title + relative URL
  * `time[datetime="ISO"]`        → publication date

We filter to publications whose `<time datetime>` is on or after
`(target_date - 7 days)` — ONEI typically releases between 1 and 5
publications per week and we want to catch slightly-late surfaces, but
not the entire backlog every run. Each release becomes a
`ScrapedArticle` tagged `source_name="ONEI"` so the resolver in
`pipeline._resolve_source_type` maps it to `SourceType.ONEI`.

We deliberately do NOT fetch the detail PDF for each release — many
ONEI publications are large XLSX bundles (the StatistAtlas, for
example) and we don't have a use for the raw spreadsheets in the
current pipeline. The headline + landing-page URL is enough for the
analyzer + report layer.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.config import settings
from src.scraper.base import BaseScraper, ScrapedArticle, ScrapeResult

logger = logging.getLogger(__name__)

SOURCE_ID = "onei"
SOURCE_NAME = "ONEI"

# How far back to look on each run. ONEI doesn't post-date publications,
# but releases sometimes don't appear on the listing page until a day
# or two after the printed date, so a 7-day window catches stragglers
# without re-importing the whole catalogue.
LOOKBACK_DAYS = 7


def _parse_iso_date(value: str) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


class ONEIScraper(BaseScraper):
    """Pulls latest economic publications from onei.gob.cu."""

    LISTING_URL = f"{settings.onei_url}/publicaciones-economico"

    def get_source_id(self) -> str:
        return SOURCE_ID

    def scrape(self, target_date: Optional[date] = None) -> ScrapeResult:
        start = time.time()
        target_date = target_date or date.today()
        cutoff = target_date - timedelta(days=LOOKBACK_DAYS)

        try:
            resp = self._fetch(self.LISTING_URL)
            soup = BeautifulSoup(resp.text, "lxml")
            cards = soup.select(".views-row")

            articles: list[ScrapedArticle] = []
            for card in cards:
                a = card.select_one(".views-field-title a")
                if not a or not a.get("href"):
                    continue
                title = a.get_text(strip=True)
                url = urljoin(settings.onei_url, a["href"])

                # The publicaciones-economico view occasionally renders
                # promo/banner cards that link off-domain (e.g. a
                # "Fidel Soldado de las Ideas" widget pointing at
                # fidelcastro.cu). Those aren't ONEI publications, so
                # only accept cards that resolve back to onei.gob.cu.
                if not url.startswith(settings.onei_url.rstrip("/")):
                    logger.debug("ONEI: skipping off-domain card %s", url)
                    continue

                time_el = card.select_one("time[datetime]")
                published = _parse_iso_date(
                    time_el.get("datetime", "") if time_el else ""
                ) or target_date

                if published < cutoff or published > target_date + timedelta(days=1):
                    # Past the lookback window, or implausibly future.
                    continue

                articles.append(ScrapedArticle(
                    headline=title,
                    published_date=published,
                    source_url=url,
                    body_text=None,
                    source_name=SOURCE_NAME,
                    # ONEI is the official national statistics office —
                    # treat as "official" tier, same as the BCC and
                    # Gaceta Oficial.
                    source_credibility="official",
                    article_type="release",
                    extra_metadata={"section": "economic"},
                ))

            logger.info(
                "ONEI: %d publication(s) within %s..%s (from %d listing rows)",
                len(articles), cutoff, target_date, len(cards),
            )
            return ScrapeResult(
                source=self.get_source_id(),
                success=True,
                articles=articles,
                duration_seconds=int(time.time() - start),
            )
        except Exception as e:
            logger.error("ONEI scrape failed: %s", e, exc_info=True)
            return ScrapeResult(
                source=self.get_source_id(),
                success=False,
                error=str(e),
                duration_seconds=int(time.time() - start),
            )
