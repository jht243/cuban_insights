"""
Scraper for the US Federal Register API — OFAC / Cuba documents.

The Federal Register REST API is free, requires no API key, and publishes
every OFAC rule, general license, and sanctions notice as a legal requirement.
For Cuba this is the canonical source of CACR (Cuban Assets Control
Regulations, 31 CFR Part 515) amendments and general licenses.

Endpoint docs: https://www.federalregister.gov/developers/documentation/api/v1
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Optional

from src.config import settings
from src.scraper.base import BaseScraper, ScrapedArticle, ScrapeResult

logger = logging.getLogger(__name__)

FR_API_BASE = "https://www.federalregister.gov/api/v1"

CUBA_TERMS = [
    "cuba",
    "cuban",
    "CACR",
    "Helms-Burton",
    "LIBERTAD Act",
    "Havana",
]

OFAC_AGENCY_SLUG = "foreign-assets-control-office"


def _is_cuba_relevant(title: str, abstract: str) -> bool:
    """
    True iff the document is genuinely about Cuba (not just an OFAC rule
    that happens to list Cuba alongside ~20 other sanctioned jurisdictions
    in a generic compliance section).

    The Federal Register API's ``term`` parameter does full-text search,
    so e.g. a global stablecoin-issuer AML rule mentioning "Cuba, Iran,
    North Korea, ..." in its required-screening list will match. We
    keep the broad search (so we don't miss real CACR amendments) but
    require Cuba to appear in the *title or abstract* before persisting
    the doc as a Cuba briefing item.
    """
    haystack = f"{title or ''}\n{abstract or ''}".lower()
    return any(term.lower() in haystack for term in CUBA_TERMS)


class FederalRegisterScraper(BaseScraper):
    """
    Queries the Federal Register API for OFAC documents mentioning Cuba.
    Returns structured article data with direct links to PDFs and HTML.
    """

    def get_source_id(self) -> str:
        return "federal_register"

    def scrape(self, target_date: Optional[date] = None) -> ScrapeResult:
        start = time.time()
        target_date = target_date or date.today()
        lookback = target_date - timedelta(days=settings.scraper_lookback_days)

        try:
            articles = self._search_ofac_cuba(lookback, target_date)

            return ScrapeResult(
                source=self.get_source_id(),
                success=True,
                articles=articles,
                duration_seconds=int(time.time() - start),
            )

        except Exception as e:
            logger.error("Federal Register scrape failed: %s", e, exc_info=True)
            return ScrapeResult(
                source=self.get_source_id(),
                success=False,
                error=str(e),
                duration_seconds=int(time.time() - start),
            )

    def _search_ofac_cuba(
        self, date_from: date, date_to: date
    ) -> list[ScrapedArticle]:
        # The Federal Register search supports a single ``term`` query
        # parameter, so we use the broadest unambiguous keyword ("cuba")
        # and rely on OFAC agency scoping to keep recall high while
        # avoiding noise from Cuba-as-place-name in unrelated rules.
        # CUBA_TERMS is retained for any future client-side reranking.
        params = {
            "conditions[agencies][]": OFAC_AGENCY_SLUG,
            "conditions[term]": "cuba",
            "conditions[publication_date][gte]": date_from.isoformat(),
            "conditions[publication_date][lte]": date_to.isoformat(),
            "per_page": 50,
            "order": "newest",
            "fields[]": [
                "title",
                "abstract",
                "document_number",
                "publication_date",
                "type",
                "html_url",
                "pdf_url",
                "agencies",
            ],
        }

        url = f"{FR_API_BASE}/documents.json"
        resp = self._fetch_json(url, params=params)
        results = resp.get("results", [])

        articles: list[ScrapedArticle] = []
        dropped = 0
        for doc in results:
            title = doc.get("title", "")
            abstract = doc.get("abstract", "")

            if not _is_cuba_relevant(title, abstract):
                dropped += 1
                logger.debug(
                    "Federal Register: dropped non-Cuba-relevant doc %s — %r",
                    doc.get("document_number"), title[:80],
                )
                continue

            pub_date = date.fromisoformat(doc["publication_date"])
            agencies = ", ".join(
                a.get("name", "") for a in doc.get("agencies", [])
            )

            articles.append(
                ScrapedArticle(
                    headline=title,
                    published_date=pub_date,
                    source_url=doc.get("html_url", ""),
                    body_text=abstract,
                    source_name="Federal Register",
                    source_credibility="official",
                    article_type=doc.get("type", "Notice"),
                    extra_metadata={
                        "document_number": doc.get("document_number"),
                        "pdf_url": doc.get("pdf_url"),
                        "agencies": agencies,
                    },
                )
            )

        logger.info(
            "Federal Register: kept %d Cuba-relevant docs, dropped %d generic-OFAC matches (%s to %s)",
            len(articles), dropped, date_from, date_to,
        )
        return articles

    def _fetch_json(self, url: str, params: dict | None = None) -> dict:
        """GET a JSON endpoint with query params."""
        logger.info("Fetching %s", url)
        resp = self.client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()
