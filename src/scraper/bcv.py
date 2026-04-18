"""
Scraper for Venezuelan official exchange rates.

Primary source: Banco Central de Venezuela (BCV) homepage
(https://www.bcv.org.ve/), which exposes per-currency widgets with stable
DOM ids: #dolar, #euro, #yuan, #lira, #rublo. Each widget contains a single
<strong> tag with the Bs/<currency> rate, and the page header shows the
"Fecha Valor" reference date for those rates.

Fallback: ve.dolarapi.com, an open community API that mirrors the BCV
official rate and additionally surfaces the parallel-market rate. We use
the fallback when BCV is unreachable or its DOM has shifted, and we always
attempt to enrich the result with the parallel rate (the parallel premium
is one of the most-watched leading indicators for Venezuela watchers).
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from src.scraper.base import BaseScraper, ScrapedArticle, ScrapeResult

logger = logging.getLogger(__name__)

BCV_URL = "https://www.bcv.org.ve/"
DOLARAPI_OFFICIAL_URL = "https://ve.dolarapi.com/v1/dolares/oficial"
DOLARAPI_ALL_URL = "https://ve.dolarapi.com/v1/dolares"

# DOM id -> metadata key on the BCV homepage. Order matters: USD first because
# the rest of the codebase only requires "usd" to be present.
_BCV_CURRENCY_IDS = [
    ("dolar", "usd"),
    ("euro", "eur"),
    ("yuan", "cny"),
    ("lira", "try"),
    ("rublo", "rub"),
]

_SPANISH_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


class BCVScraper(BaseScraper):
    """
    Scrapes BCV official rates with a resilient fallback to ve.dolarapi.com.
    Produces a single ScrapedArticle whose extra_metadata always contains at
    least {"usd": <float>, "source_used": "bcv"|"dolarapi"} on success.
    """

    def get_source_id(self) -> str:
        return "bcv_rates"

    def scrape(self, target_date: Optional[date] = None) -> ScrapeResult:
        start = time.time()
        target_date = target_date or date.today()

        rates: Optional[dict] = None
        valuation_date: Optional[date] = None
        path_used = ""

        try:
            rates, valuation_date = self._scrape_bcv_homepage()
            if rates and "usd" in rates:
                path_used = "bcv"
        except Exception as exc:
            logger.warning("BCV homepage scrape errored: %s", exc)

        if not rates or "usd" not in rates:
            try:
                rates = self._fetch_dolarapi()
                if rates and "usd" in rates:
                    path_used = "dolarapi"
            except Exception as exc:
                logger.warning("dolarapi fallback errored: %s", exc)

        # If BCV worked, still try to enrich with the parallel rate from
        # dolarapi (it's free and Venezuela-watchers care about the spread).
        if path_used == "bcv":
            try:
                parallel = self._fetch_parallel_rate()
                if parallel:
                    rates["parallel_usd"] = parallel
                    if "usd" in rates and rates["usd"]:
                        rates["parallel_premium_pct"] = round(
                            (parallel - rates["usd"]) / rates["usd"] * 100, 2
                        )
            except Exception as exc:
                logger.debug("Parallel rate enrichment skipped: %s", exc)

        if not rates or "usd" not in rates:
            return ScrapeResult(
                source=self.get_source_id(),
                success=False,
                error="Could not retrieve BCV rates from any source",
                duration_seconds=int(time.time() - start),
            )

        rates["source_used"] = path_used
        if valuation_date:
            rates["valuation_date"] = valuation_date.isoformat()

        article = ScrapedArticle(
            headline=f"BCV Official Exchange Rate: {rates['usd']:.2f} VES/USD",
            published_date=valuation_date or target_date,
            source_url=BCV_URL,
            body_text=self._format_body(rates, valuation_date or target_date),
            source_name="Banco Central de Venezuela",
            source_credibility="official",
            article_type="exchange_rate",
            extra_metadata=rates,
        )

        logger.info(
            "BCV rates ok via=%s usd=%s eur=%s parallel=%s premium=%s%%",
            path_used,
            rates.get("usd"),
            rates.get("eur"),
            rates.get("parallel_usd"),
            rates.get("parallel_premium_pct"),
        )

        return ScrapeResult(
            source=self.get_source_id(),
            success=True,
            articles=[article],
            duration_seconds=int(time.time() - start),
        )

    # ---- BCV homepage ------------------------------------------------------

    def _scrape_bcv_homepage(self) -> tuple[Optional[dict], Optional[date]]:
        """
        Parse the BCV homepage. Each currency lives in a div with a known id
        (#dolar, #euro, ...) containing a single <strong> with the rate.
        BCV's TLS cert has been intermittently misconfigured; we tolerate
        that by retrying without verification when a cert error fires.
        """
        try:
            resp = self._fetch(BCV_URL)
        except httpx.HTTPError as exc:
            # Typical BCV failure: SSL cert chain or self-signed; retry insecure.
            logger.info("BCV fetch failed (%s); retrying without TLS verify", exc)
            try:
                with httpx.Client(
                    timeout=15,
                    follow_redirects=True,
                    verify=False,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/125.0.0.0 Safari/537.36"
                        ),
                        "Accept-Language": "es-VE,es;q=0.9,en;q=0.8",
                    },
                ) as client:
                    resp = client.get(BCV_URL)
                    resp.raise_for_status()
            except Exception as exc2:
                logger.warning("BCV homepage unreachable even without verify: %s", exc2)
                return None, None

        soup = BeautifulSoup(resp.text, "lxml")
        rates: dict = {}

        for dom_id, key in _BCV_CURRENCY_IDS:
            block = soup.find(id=dom_id)
            if not block:
                continue
            strong = block.find("strong")
            if not strong:
                continue
            value = self._parse_ve_number(strong.get_text(strip=True))
            if value is None:
                continue
            # Sanity range: VES quotes are tens to thousands; reject obvious noise.
            if not (0.01 < value < 100_000):
                continue
            rates[key] = value

        valuation_date = self._parse_fecha_valor(soup)
        return (rates if rates else None), valuation_date

    @staticmethod
    def _parse_fecha_valor(soup: BeautifulSoup) -> Optional[date]:
        """
        Extract BCV's 'Fecha Valor: <Día>, DD <Mes> YYYY' header. Returns
        None if not present or unparseable.
        """
        text = soup.get_text(" ", strip=True)
        match = re.search(
            r"Fecha\s*Valor[^A-Za-z]*"
            r"(?:Lunes|Martes|Mi[eé]rcoles|Jueves|Viernes|S[aá]bado|Domingo)"
            r"[^0-9]*(\d{1,2})\s+([A-Za-zé]+)\s+(\d{4})",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None
        day = int(match.group(1))
        month_name = match.group(2).strip().lower().replace("é", "e")
        # Spanish month names contain accents; normalise.
        month_name = month_name.replace("á", "a").replace("í", "i").replace("ó", "o").replace("ú", "u")
        month = _SPANISH_MONTHS.get(month_name)
        if not month:
            return None
        try:
            return date(int(match.group(3)), month, day)
        except ValueError:
            return None

    # ---- dolarapi fallback -------------------------------------------------

    def _fetch_dolarapi(self) -> Optional[dict]:
        """
        Pull the BCV official rate from the open ve.dolarapi.com mirror.
        The /dolares endpoint returns both oficial and paralelo in one call,
        so we use it to populate parallel_usd as well.
        """
        try:
            resp = self.client.get(DOLARAPI_ALL_URL, timeout=10)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            logger.warning("dolarapi /dolares failed: %s", exc)
            return None

        if not isinstance(payload, list):
            return None

        out: dict = {}
        for row in payload:
            if not isinstance(row, dict):
                continue
            fuente = (row.get("fuente") or "").lower()
            price = row.get("promedio") or row.get("venta") or row.get("compra")
            try:
                price = float(price) if price is not None else None
            except (TypeError, ValueError):
                price = None
            if price is None or price <= 0:
                continue
            if fuente == "oficial" and "usd" not in out:
                out["usd"] = round(price, 4)
                if row.get("fechaActualizacion"):
                    out["dolarapi_oficial_updated"] = row["fechaActualizacion"]
            elif fuente == "paralelo" and "parallel_usd" not in out:
                out["parallel_usd"] = round(price, 4)

        if "usd" in out and "parallel_usd" in out and out["usd"]:
            out["parallel_premium_pct"] = round(
                (out["parallel_usd"] - out["usd"]) / out["usd"] * 100, 2
            )
        return out or None

    def _fetch_parallel_rate(self) -> Optional[float]:
        """Fetch only the parallel-market USD price from dolarapi."""
        try:
            resp = self.client.get(
                "https://ve.dolarapi.com/v1/dolares/paralelo",
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.debug("dolarapi paralelo failed: %s", exc)
            return None
        price = data.get("promedio") or data.get("venta") or data.get("compra")
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None
        if price and price > 0:
            return round(price, 4)
        return None

    # ---- formatting --------------------------------------------------------

    @staticmethod
    def _format_body(rates: dict, valuation_date: date) -> str:
        lines = [f"Date: {valuation_date.isoformat()}"]
        for label, key in [
            ("USD (BCV official)", "usd"),
            ("EUR", "eur"),
            ("CNY", "cny"),
            ("TRY", "try"),
            ("RUB", "rub"),
        ]:
            if key in rates:
                lines.append(f"{label}: {rates[key]} VES")
        if "parallel_usd" in rates:
            lines.append(f"USD (parallel): {rates['parallel_usd']} VES")
        if "parallel_premium_pct" in rates:
            lines.append(f"Parallel premium: {rates['parallel_premium_pct']}%")
        if rates.get("source_used"):
            lines.append(f"Source: {rates['source_used']}")
        return "\n".join(lines)

    @staticmethod
    def _parse_ve_number(text: str) -> Optional[float]:
        """
        Parse Venezuelan number format. BCV emits values like '481,21770000'
        (comma decimal, no thousand separators). Some other locales would
        send '1.234,56' — handle both defensively.
        """
        if not text:
            return None
        cleaned = text.strip()
        # Strip non-numeric junk except , . - and digits
        cleaned = re.sub(r"[^0-9,.\-]", "", cleaned)
        if not cleaned:
            return None
        # If both '.' and ',' present, assume European format: '.' thousands, ',' decimal.
        if "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
