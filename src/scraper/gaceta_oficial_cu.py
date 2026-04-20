"""
Scraper for the Cuban official gazette — Gaceta Oficial de la
República de Cuba (https://www.gacetaoficial.gob.cu).

Strategy
--------
The site is a Drupal install. The `/es/servicios` page is the densest
"latest published norms" surface — Drupal renders the most recent
~10 norm entries as `node-norma-juridica.node-teaser` cards, each
already containing the title, "identificador" (e.g. `GOC-2026-161-EX22`)
and a short resumen (sumario).

We grab those cards directly, then optionally drill into each norm's
detail page to pick up the "Publicado en: Gaceta Oficial No. X
[Extraordinaria] de YYYY" line which gives us the gazette ordinal +
type explicitly. The identificador also encodes the same info
(`-EX22` suffix → Extraordinaria #22; `-O09` → Ordinaria #9), so if
the detail page is unavailable we still get useful metadata.

Each scraped norm becomes a `ScrapedGazette` so it lands in
`GazetteEntry` and flows through the same OCR / analyzer / report
pipeline as the old Venezuelan TuGaceta entries. Cuba doesn't expose
PDF download links on the public website — only the in-page sumario
text — so `pdf_download_url` is left empty and the analyzer is
expected to work off `sumario_raw` directly. (For the small number of
norms we want full-text for, we'd need to subscribe to the print
edition or use the `gacetasoficiales-1990-2008` archive scraper.)
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.config import settings
from src.scraper.base import BaseScraper, ScrapedGazette, ScrapeResult

logger = logging.getLogger(__name__)

SOURCE_ID = "gaceta_oficial_cu"

# Regex: identificador like "GOC-2026-161-EX22" or "GOC-2025-410-O09".
# Group 1 = year, group 2 = type (EX|O), group 3 = gazette ordinal.
_ID_RE = re.compile(r"GOC-(\d{4})-\d+-(EX|O)(\d+)", re.IGNORECASE)

# Regex for the "Publicado en: Gaceta Oficial No. 22 Extraordinaria de
# 2026" / "No. 19 Ordinaria de 2026" line on the norm detail page.
_PUBLISHED_RE = re.compile(
    r"Gaceta Oficial No\.\s*(\d+)\s+(Extraordinaria|Ordinaria)\s+de\s+(\d{4})",
    re.IGNORECASE,
)


def _parse_identificador(identificador: str) -> tuple[Optional[str], str, Optional[int]]:
    """Return (gazette_number, gazette_type, year) parsed from the
    identificador, or (None, "ordinaria", None) if unparseable."""
    if not identificador:
        return None, "ordinaria", None
    m = _ID_RE.search(identificador)
    if not m:
        return None, "ordinaria", None
    year = int(m.group(1))
    gtype = "extraordinaria" if m.group(2).upper() == "EX" else "ordinaria"
    number = m.group(3)
    return number, gtype, year


class GacetaOficialCUScraper(BaseScraper):
    """Pulls latest norms from Gaceta Oficial de Cuba.

    `target_date` is accepted but the site doesn't expose a "by-date"
    listing — every run pulls whatever the front page surfaces. The
    pipeline's UniqueConstraint on (source, source_url) keeps us from
    re-inserting the same norm on subsequent runs.
    """

    LISTING_URL = f"{settings.gazette_official_url}/es/servicios"

    def get_source_id(self) -> str:
        return SOURCE_ID

    def scrape(self, target_date: Optional[date] = None) -> ScrapeResult:
        start = time.time()
        target_date = target_date or date.today()

        try:
            cards = self._fetch_listing()
            gazettes: list[ScrapedGazette] = []

            for card in cards:
                try:
                    g = self._parse_card(card, fallback_date=target_date)
                except Exception as e:
                    logger.warning(
                        "Gaceta CU: failed to parse card: %s", e, exc_info=True,
                    )
                    continue
                if g:
                    gazettes.append(g)

            logger.info(
                "Gaceta CU: parsed %d norm(s) from %s",
                len(gazettes), self.LISTING_URL,
            )
            return ScrapeResult(
                source=self.get_source_id(),
                success=True,
                gazettes=gazettes,
                duration_seconds=int(time.time() - start),
            )
        except Exception as e:
            logger.error("Gaceta CU scrape failed: %s", e, exc_info=True)
            return ScrapeResult(
                source=self.get_source_id(),
                success=False,
                error=str(e),
                duration_seconds=int(time.time() - start),
            )

    # ── Internal helpers ──────────────────────────────────────────────

    def _fetch_listing(self) -> list:
        """Return the list of `<div class="node-norma-juridica node-teaser">`
        cards from the /es/servicios listing."""
        resp = self._fetch(self.LISTING_URL)
        soup = BeautifulSoup(resp.text, "lxml")
        cards = soup.select("div.node-norma-juridica.node-teaser")
        if not cards:
            # Fallback: any node teaser (Drupal sometimes renders without
            # the type-specific class on certain content types).
            cards = soup.select("div.node-teaser")
        return cards

    def _parse_card(self, card, *, fallback_date: date) -> Optional[ScrapedGazette]:
        """Parse one norm-teaser card into a ScrapedGazette."""
        title_a = card.select_one("h2.title a, h1.title a, h3.title a")
        if not title_a or not title_a.get("href"):
            return None

        title = title_a.get_text(strip=True)
        href = title_a["href"]
        full_url = urljoin(settings.gazette_official_url, href)

        # Identificador (e.g. GOC-2026-161-EX22).
        ident_el = card.select_one(
            ".field-name-field-identificador-de-norma .field-item, "
            ".field-name-field-identificador-de-norma"
        )
        identificador = ident_el.get_text(strip=True) if ident_el else ""
        # Strip the inline "Identificador de norma:" label that Drupal
        # emits when both label + item are inside the same node.
        identificador = re.sub(
            r"^\s*Identificador de norma:\s*", "", identificador, flags=re.IGNORECASE,
        )

        number, gtype, year = _parse_identificador(identificador)
        # Use Jan 1 of the encoded year as a stable published_date when
        # the listing doesn't expose a per-norm date. The norm URL is
        # the dedup key, so this date is mostly cosmetic.
        published_date = (
            date(year, 1, 1) if (year and year <= fallback_date.year + 1) else fallback_date
        )

        # Resumen (the in-card sumario summary).
        body_el = card.select_one(".field-name-body .field-item")
        sumario = body_el.get_text(separator="\n", strip=True) if body_el else ""

        # Optionally drill into the detail page to pick up the canonical
        # "Publicado en Gaceta Oficial No. X [Extraordinaria]" line —
        # this is the source-of-truth for gazette number/type. We do
        # this best-effort; if the detail fetch fails we keep what we
        # parsed from the identificador.
        try:
            number_d, gtype_d = self._fetch_detail_metadata(full_url)
            if number_d:
                number = number_d
            if gtype_d:
                gtype = gtype_d
        except Exception as e:
            logger.debug(
                "Gaceta CU: detail fetch failed for %s: %s (using identificador)",
                full_url, e,
            )

        return ScrapedGazette(
            gazette_number=number,
            gazette_type=gtype,
            published_date=published_date,
            source=SOURCE_ID,
            source_url=full_url,
            title=title,
            sumario_text=sumario or None,
            pdf_download_url=None,  # Gaceta CU does not expose direct PDFs
        )

    def _fetch_detail_metadata(self, url: str) -> tuple[Optional[str], Optional[str]]:
        """Fetch a norm detail page and return (gazette_number, gazette_type)
        parsed from the 'Publicado en: Gaceta Oficial No. ...' line."""
        resp = self._fetch(url)
        soup = BeautifulSoup(resp.text, "lxml")
        text_block = soup.select_one(
            ".field-name-field-gaceta-oficial-norma"
        ) or soup
        text = text_block.get_text(" ", strip=True)
        m = _PUBLISHED_RE.search(text)
        if not m:
            return None, None
        number = m.group(1)
        gtype = "extraordinaria" if m.group(2).lower().startswith("extra") else "ordinaria"
        return number, gtype
