"""
International Trade Administration / Trade.gov scraper.

The ITA Data Services Platform is the U.S. export-facing complement to
our sanctions stack: market intelligence, trade leads, events, export
guidance, and Commercial Service contacts for U.S. companies. This
module imports Cuba-relevant public Trade.gov pages first and can later
be extended with authenticated API calls once an ITA subscription key is
available in ITA_API_KEY.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from src.config import settings
from src.scraper.base import BaseScraper, ScrapedArticle, ScrapeResult

logger = logging.getLogger(__name__)

SOURCE_ID = "ita_trade"


@dataclass(frozen=True)
class _ITAPage:
    url: str
    article_type: str
    title_hint: str


_PUBLIC_PAGES: tuple[_ITAPage, ...] = (
    _ITAPage(
        "https://www.trade.gov/trade-leads",
        "trade_lead",
        "ITA Trade Leads - Cuba",
    ),
    _ITAPage(
        "https://www.trade.gov/trade-leads-search",
        "trade_lead",
        "ITA Trade Leads Search - Cuba",
    ),
    _ITAPage(
        "https://www.trade.gov/market-intelligence-search",
        "market_intelligence",
        "ITA Market Intelligence - Cuba",
    ),
    _ITAPage(
        "https://www.trade.gov/trade-americas-contact-us",
        "contact",
        "ITA Trade Americas contacts",
    ),
    _ITAPage(
        "https://www.trade.gov/trade-americas-country-information",
        "country_guidance",
        "ITA Trade Americas country information",
    ),
    _ITAPage(
        "https://www.trade.gov/export-solutions",
        "export_guidance",
        "ITA Export Solutions",
    ),
    _ITAPage(
        "https://www.trade.gov/learn-how-export",
        "export_guidance",
        "ITA Learn How to Export",
    ),
    _ITAPage(
        "https://www.trade.gov/trade-events-search",
        "event",
        "ITA trade events search",
    ),
)

_CUBA_TERMS = (
    "cuba",
    "cuban",
    "havana",
    "caribbean",
    "trade americas",
    "sanctions",
    "export controls",
    "agriculture",
    "medical",
    "telecom",
    "telecommunications",
    "internet",
    "energy",
    "logistics",
    "construction",
    "healthcare",
)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _is_relevant(text: str) -> bool:
    haystack = (text or "").lower()
    return any(term in haystack for term in _CUBA_TERMS)


class ITATradeScraper(BaseScraper):
    """Import Cuba-relevant ITA / Trade.gov export opportunity material."""

    def get_source_id(self) -> str:
        return SOURCE_ID

    def scrape(self, target_date: Optional[date] = None) -> ScrapeResult:
        start = time.time()
        target_date = target_date or date.today()
        articles: list[ScrapedArticle] = []
        errors: list[str] = []

        for page in _PUBLIC_PAGES:
            try:
                fetched = self._scrape_public_page(page, target_date)
                articles.extend(fetched)
                logger.info("ITA [%s]: %d item(s)", page.article_type, len(fetched))
            except (httpx.HTTPError, ValueError) as exc:
                errors.append(f"{page.url}: {exc}")
                logger.warning("ITA page scrape failed for %s: %s", page.url, exc)
            except Exception as exc:
                errors.append(f"{page.url}: {exc}")
                logger.warning("ITA page scrape crashed for %s: %s", page.url, exc, exc_info=True)

        if not articles and errors:
            return ScrapeResult(
                source=self.get_source_id(),
                success=False,
                error="; ".join(errors),
                duration_seconds=int(time.time() - start),
            )

        return ScrapeResult(
            source=self.get_source_id(),
            success=True,
            articles=articles,
            error=("; ".join(errors) or None),
            duration_seconds=int(time.time() - start),
        )

    def _scrape_public_page(self, page: _ITAPage, target_date: date) -> list[ScrapedArticle]:
        resp = self._fetch(page.url)
        soup = BeautifulSoup(resp.text, "lxml")

        items = self._extract_cards(soup, page)
        if not items:
            title_node = soup.find("h1") or soup.find("title")
            title = _clean_text(title_node.get_text(" ", strip=True) if title_node else "")
            body = _clean_text(soup.get_text(" ", strip=True))
            if not _is_relevant(f"{title} {body}"):
                return []
            items.append((title or page.title_hint, page.url, body[:3500]))

        out: list[ScrapedArticle] = []
        seen: set[str] = set()
        for title, link, body in items:
            if not title or not link or link in seen:
                continue
            seen.add(link)
            out.append(ScrapedArticle(
                headline=title,
                published_date=target_date,
                source_url=link,
                body_text=body or None,
                source_name="International Trade Administration",
                source_credibility="official",
                article_type=page.article_type,
                extra_metadata={
                    "source_family": "ita_trade",
                    "page_type": page.article_type,
                    "seed_url": page.url,
                    "attribution": (
                        "This product uses the International Trade Administration's "
                        "Data API / Trade.gov content but is not endorsed or "
                        "certified by the International Trade Administration."
                    ),
                },
            ))
        return out

    def _extract_cards(self, soup: BeautifulSoup, page: _ITAPage) -> list[tuple[str, str, str]]:
        cards: list[tuple[str, str, str]] = []
        candidates = soup.select("article, .views-row, .card, .usa-card, li")
        for node in candidates:
            text = _clean_text(node.get_text(" ", strip=True))
            if len(text) < 40 or not _is_relevant(text):
                continue
            link_node = node.find("a", href=True)
            heading = node.find(["h2", "h3", "h4"]) or link_node
            title = _clean_text(heading.get_text(" ", strip=True) if heading else "")
            if not title:
                title = page.title_hint
            href = link_node["href"] if link_node else page.url
            link = urljoin(settings.ita_trade_base_url, href)
            cards.append((title, link, text[:2500]))
        return cards[:50]
