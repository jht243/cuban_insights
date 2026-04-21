"""
Scraper for Banco Central de Cuba (BCC) official exchange rates.

The BCC publishes its daily reference rates as JSON via the public
``api.bc.gob.cu`` REST endpoint. The endpoint is undocumented but stable
(probed live during the source-research pass; see
docs/scraper_research.md). Using the API instead of scraping
www.bc.gob.cu HTML eliminates the need for headless browsers, OCR, or
proxy infrastructure.

Each currency on the BCC API has THREE rates:

- ``tasaOficial``  — the historical 1:24 official rate (legacy CADECA).
- ``tasaPublica``  — the public/CADECA rate (~5x official).
- ``tasaEspecial`` — the special/institutional rate (~20x official),
  introduced August 2022 as the de facto market-facing reference for
  state and joint-venture transactions.

We surface the USD value of each segment in the article extra_metadata
plus a normalized ``rates`` dict keyed by currency code containing all
three segments. The headline picks ``tasaEspecial`` for USD because
that's the segment most commercial counterparties actually transact at;
``tasaOficial`` is anchored at the post-2021 reform peg.

Note that the BCC rates are policy rates, NOT the parallel-market rate
that El Toque tracks. The El Toque scraper (Phase 2e) fills that gap.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import Optional

from src.scraper.base import BaseScraper, ScrapedArticle, ScrapeResult

logger = logging.getLogger(__name__)

BCC_API_BASE = "https://api.bc.gob.cu/v1/tasas-de-cambio"
ACTIVE_RATES_URL = f"{BCC_API_BASE}/activas"

# Currencies we want in the persisted record. The endpoint returns ~30
# minor currencies; we filter to the set the daily brief / FX widget
# actually display. Adding a code here automatically pulls it through.
TRACKED_CODES = ("USD", "EUR", "CAD", "GBP", "MXN", "CHF", "JPY", "CNY")

# Which segment the headline + canonical rate refers to. tasaEspecial is
# the 2022 institutional reference and the closest BCC-published rate to
# what foreign investors actually transact at.
HEADLINE_SEGMENT = "tasaEspecial"


class BCCScraper(BaseScraper):
    """
    Pulls all active BCC reference rates from the public REST API and
    emits a single ``ScrapedArticle`` per scrape with USD/EUR/etc.
    quotes for each of the three rate segments.
    """

    def get_source_id(self) -> str:
        return "bcc_rates"

    def scrape(self, target_date: Optional[date] = None) -> ScrapeResult:
        start = time.time()
        target_date = target_date or date.today()

        try:
            payload = self._fetch_active_rates()
        except Exception as exc:
            logger.error("BCC API fetch failed: %s", exc, exc_info=True)
            return ScrapeResult(
                source=self.get_source_id(),
                success=False,
                error=f"BCC API unreachable: {exc}",
                duration_seconds=int(time.time() - start),
            )

        rates_by_code = self._normalize(payload)
        if "USD" not in rates_by_code:
            return ScrapeResult(
                source=self.get_source_id(),
                success=False,
                error="BCC API returned no USD rate",
                duration_seconds=int(time.time() - start),
            )

        valuation_date = self._extract_valuation_date(payload) or target_date
        usd_special = rates_by_code["USD"].get(HEADLINE_SEGMENT)

        # extra_metadata flattens the canonical USD/EUR special rate at
        # the top level so downstream surfaces (og_image, FX widget) can
        # do a one-key lookup, while the full triple-segment table lives
        # under "rates" for the report and analyzer.
        extra: dict = {
            "valuation_date": valuation_date.isoformat(),
            "headline_segment": HEADLINE_SEGMENT,
            "rates": rates_by_code,
            "source_used": "bcc_api",
        }
        if usd_special is not None:
            extra["usd"] = usd_special  # legacy field name; segment-aware
        eur_special = rates_by_code.get("EUR", {}).get(HEADLINE_SEGMENT)
        if eur_special is not None:
            extra["eur"] = eur_special

        article = ScrapedArticle(
            headline=(
                f"BCC Reference Rate: {usd_special:.2f} CUP/USD "
                f"(tasa especial, {valuation_date.isoformat()})"
            ),
            published_date=valuation_date,
            # Make the URL unique-per-day so the dedup constraint on
            # (source, source_url) actually inserts a new row each day.
            source_url=f"{ACTIVE_RATES_URL}?date={valuation_date.isoformat()}",
            body_text=self._format_body(rates_by_code, valuation_date),
            source_name="Banco Central de Cuba",
            source_credibility="official",
            article_type="exchange_rate",
            extra_metadata=extra,
        )

        logger.info(
            "BCC rates ok: USD oficial=%s publica=%s especial=%s currencies=%d valuation=%s",
            rates_by_code["USD"].get("tasaOficial"),
            rates_by_code["USD"].get("tasaPublica"),
            usd_special,
            len(rates_by_code),
            valuation_date.isoformat(),
        )

        return ScrapeResult(
            source=self.get_source_id(),
            success=True,
            articles=[article],
            duration_seconds=int(time.time() - start),
        )

    def _fetch_active_rates(self) -> dict:
        resp = self._fetch(ACTIVE_RATES_URL)
        ctype = resp.headers.get("content-type", "")
        if "json" not in ctype:
            raise ValueError(f"BCC API returned non-JSON content-type: {ctype}")
        return resp.json()

    @staticmethod
    def _normalize(payload: dict) -> dict[str, dict]:
        """Flatten the API ``tasas`` array into ``{code: {segment: rate}}``.

        Currencies not in ``TRACKED_CODES`` are dropped to keep the
        persisted blob small. Each segment value is coerced to float and
        clamped against an obvious-noise sanity range.
        """
        out: dict[str, dict] = {}
        for row in payload.get("tasas", []) or []:
            code = (row.get("codigoMoneda") or "").upper().strip()
            if code not in TRACKED_CODES:
                continue

            segments: dict[str, float] = {}
            for seg in ("tasaOficial", "tasaPublica", "tasaEspecial"):
                raw = row.get(seg)
                try:
                    val = float(raw) if raw is not None else None
                except (TypeError, ValueError):
                    val = None
                # CUP/<currency> is currently in the 17-700 range across
                # all segments. Anything outside this is almost certainly
                # a data-entry glitch we shouldn't surface as headline.
                if val is not None and 0.001 < val < 100_000:
                    segments[seg] = round(val, 4)

            if segments:
                out[code] = {
                    "name": row.get("nombreMoneda"),
                    **segments,
                }
        return out

    @staticmethod
    def _extract_valuation_date(payload: dict) -> Optional[date]:
        """Pick the ``fechaDia`` returned by the API (UTC ISO timestamp)."""
        raw = payload.get("fechaDia") or payload.get("fechaHoy")
        if not raw:
            return None
        try:
            # API emits ``2026-04-20T00:00:00.000Z``; trim the millis +
            # Z so ``fromisoformat`` accepts it on Python 3.10.
            cleaned = raw.replace("Z", "+00:00").split(".")[0] + "+00:00"
            return datetime.fromisoformat(cleaned).date()
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _format_body(rates: dict[str, dict], valuation_date: date) -> str:
        lines = [
            f"Fecha valor: {valuation_date.isoformat()}",
            "",
            "Tasas de cambio publicadas por el Banco Central de Cuba",
            "(CUP por unidad de moneda extranjera).",
            "",
            f"{'Moneda':<8} {'Oficial':>12} {'Pública':>12} {'Especial':>12}",
        ]
        # Keep USD on top, then EUR, then alphabetical.
        ordered = ["USD", "EUR"] + sorted(c for c in rates if c not in ("USD", "EUR"))
        for code in ordered:
            seg = rates.get(code)
            if not seg:
                continue
            lines.append(
                f"{code:<8} "
                f"{seg.get('tasaOficial', 0):>12.4f} "
                f"{seg.get('tasaPublica', 0):>12.4f} "
                f"{seg.get('tasaEspecial', 0):>12.4f}"
            )
        return "\n".join(lines)
