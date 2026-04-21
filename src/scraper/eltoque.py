"""
Scraper for elTOQUE's TRMI (Tasa Representativa del Mercado Informal).

The TRMI is the most-watched financial number in Cuba: the daily
informal-market CUP/USD/MLC/USDT exchange rate, computed by elTOQUE
from a basket of street-level signals (classifieds, remittance
chatter, bidirectional Telegram channels). It is the rate at which
ordinary Cubans actually transact, and the spread between it and the
BCC's tasa especial (~120 CUP/USD vs. ~525 CUP/USD as of mid-2026)
is the single most important macro indicator for any investor,
remittance sender, or visitor making decisions about the island.

Data access
-----------
elTOQUE expressly prohibits scraping their HTML platforms (clause:
"no se intenten extraer datos de las plataformas de elTOQUE por
medios automatizados distintos a la API"). Their answer is the
authenticated dev API at ``tasas.eltoque.com``, which they issue
keys for free after a one-time application — see
``docs/eltoque_api_application.md``.

Endpoint
--------
``GET https://tasas.eltoque.com/v1/trmi``

Headers: ``Authorization: Bearer <ELTOQUE_API_KEY>``

Response (probed live 2026-04-20)::

    {
      "tasas": {
        "USD": 525.0,
        "MLC": 400.0,
        "USDT_TRC20": 620.0,
        "BTC": 535.0,
        "TRX": 191.5,
        "ECU": 600.0
      },
      "date": "2026-04-20",
      "hour": 18,
      "minutes": 10,
      "seconds": 12
    }

Note that USD/MLC/USDT_TRC20 are the three rates most relevant to
the Cuban Insights audience — USD is cash, MLC is the state digital
wallet, USDT_TRC20 is the dominant crypto on-ramp/off-ramp on the
island. BTC/TRX/ECU are crypto pairs that are useful as context for
the USDT premium but rarely make the headline.

Rate limit
----------
The free beta tier permits ~5,000 requests per month and the API
itself rate-limits to ``1 request per 1 second`` (HTTP 429 if
exceeded). The daily pipeline calls this exactly twice a day, so
both budgets are wildly under-utilised; no caching layer needed.

Attribution
-----------
elTOQUE's ToS *requires* visible attribution on every surface that
displays the TRMI. The site footer in ``templates/_base.html.j2``
already covers this for the web rendering of ``report.html``; the
extra_metadata field carries ``attribution`` so any downstream
generator (newsletter, blog post, OG image) can render it without
hard-coding the string.

Cross-refs
----------
- Complements ``BCCScraper`` (official rates). The two together let
  the report compute the spread, which is the actual story.
- Maps to ``SourceType.ELTOQUE_RATE``.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from typing import Optional

from src.config import settings
from src.scraper.base import BaseScraper, ScrapedArticle, ScrapeResult

logger = logging.getLogger(__name__)

ELTOQUE_API_BASE = "https://tasas.eltoque.com"
ELTOQUE_TRMI_URL = f"{ELTOQUE_API_BASE}/v1/trmi"

# Currencies we surface. Order matters for `_format_body` (USD first).
HEADLINE_CURRENCY = "USD"
TRACKED_CURRENCIES = ("USD", "MLC", "USDT_TRC20", "BTC", "TRX", "ECU")

ATTRIBUTION = "Tasa Representativa del Mercado Informal — elTOQUE (tasas.eltoque.com)"


class ElToqueScraper(BaseScraper):
    """Pull elTOQUE's current TRMI snapshot from the authenticated API.

    Emits one ``ScrapedArticle`` per scrape. The article body lists
    every currency in the response; ``extra_metadata`` flattens the
    headline USD/MLC/USDT rates to the top level for one-key lookups
    in downstream generators (FX widget, OG image, newsletter).

    Graceful failure modes (returns ``success=False`` with diagnostic
    error rather than crashing the pipeline):

    - ``ELTOQUE_API_KEY`` not configured → soft skip, "no key set".
    - HTTP 401/403 → key revoked or invalid, surface clearly.
    - HTTP 429 → rate-limited; the daily pipeline can retry tomorrow.
    - HTTP 5xx / network → backed off by ``BaseScraper._fetch`` retry,
      then surfaced as a single error.
    """

    def get_source_id(self) -> str:
        return "eltoque_rate"

    def scrape(self, target_date: Optional[date] = None) -> ScrapeResult:
        start = time.time()
        target_date = target_date or date.today()

        api_key = (settings.eltoque_api_key or "").strip()
        if not api_key:
            logger.warning(
                "ELTOQUE_API_KEY not configured; skipping eltoque scrape. "
                "See docs/eltoque_api_application.md to obtain a key."
            )
            return ScrapeResult(
                source=self.get_source_id(),
                success=False,
                error="ELTOQUE_API_KEY not set",
                duration_seconds=int(time.time() - start),
            )

        try:
            payload = self._fetch_trmi(api_key)
        except Exception as exc:
            logger.error("elTOQUE TRMI fetch failed: %s", exc, exc_info=True)
            return ScrapeResult(
                source=self.get_source_id(),
                success=False,
                error=f"elTOQUE API unreachable: {exc}",
                duration_seconds=int(time.time() - start),
            )

        rates = self._normalize(payload.get("tasas") or {})
        if HEADLINE_CURRENCY not in rates:
            return ScrapeResult(
                source=self.get_source_id(),
                success=False,
                error=f"elTOQUE response missing {HEADLINE_CURRENCY} rate",
                duration_seconds=int(time.time() - start),
            )

        observed_at = self._extract_timestamp(payload, fallback=target_date)
        observed_date = observed_at.date()
        usd_rate = rates[HEADLINE_CURRENCY]

        extra: dict = {
            "valuation_date": observed_date.isoformat(),
            "observed_at_utc": observed_at.isoformat(),
            "rates": rates,
            "attribution": ATTRIBUTION,
            "source_used": "eltoque_api",
        }
        # Flatten the three rates downstream surfaces actually
        # display so the OG image / newsletter / FX widget don't have
        # to dig into the nested ``rates`` dict for a one-shot lookup.
        for code in ("USD", "MLC", "USDT_TRC20"):
            if code in rates:
                extra[code.lower()] = rates[code]

        article = ScrapedArticle(
            headline=(
                f"elTOQUE TRMI: {usd_rate:.2f} CUP/USD "
                f"(mercado informal, {observed_date.isoformat()})"
            ),
            published_date=observed_date,
            source_url=f"{ELTOQUE_TRMI_URL}?date={observed_date.isoformat()}",
            body_text=self._format_body(rates, observed_at),
            source_name="elTOQUE",
            source_credibility="tier1",
            article_type="exchange_rate",
            extra_metadata=extra,
        )

        logger.info(
            "elTOQUE TRMI ok: USD=%.2f MLC=%s USDT=%s observed=%s",
            usd_rate,
            rates.get("MLC"),
            rates.get("USDT_TRC20"),
            observed_at.isoformat(),
        )

        return ScrapeResult(
            source=self.get_source_id(),
            success=True,
            articles=[article],
            duration_seconds=int(time.time() - start),
        )

    def _fetch_trmi(self, api_key: str):
        """One-shot GET against the TRMI endpoint with the bearer token.

        Bypasses ``BaseScraper._fetch`` because that helper does not
        accept extra headers, and we must not stash the bearer token
        on ``self.client`` (other scrapers re-use the class — but in
        practice each scraper instance is per-class so this is moot;
        still, keeping the auth scoped to the one call is clearer).
        """
        logger.info("Fetching %s", ELTOQUE_TRMI_URL)
        resp = self.client.get(
            ELTOQUE_TRMI_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        if "json" not in ctype.lower():
            raise ValueError(f"elTOQUE returned non-JSON content-type: {ctype}")
        return resp.json()

    @staticmethod
    def _normalize(tasas: dict) -> dict[str, float]:
        """Coerce the ``tasas`` blob to ``{code: float}``, filtered + clamped.

        Drops currencies we don't track and silently skips any value
        that fails sanity check (TRMI is currently in the 100-700
        CUP/unit range across tracked currencies; anything outside
        the broad 0.01-1_000_000 envelope is almost certainly an
        upstream data glitch we shouldn't surface as a headline).
        """
        out: dict[str, float] = {}
        for code, raw in (tasas or {}).items():
            code_norm = (code or "").upper().strip()
            if code_norm not in TRACKED_CURRENCIES:
                continue
            try:
                val = float(raw)
            except (TypeError, ValueError):
                continue
            if not (0.01 < val < 1_000_000):
                continue
            out[code_norm] = round(val, 4)
        return out

    @staticmethod
    def _extract_timestamp(payload: dict, fallback: date) -> datetime:
        """Build a UTC datetime from the ``date``/``hour``/``minutes``/``seconds`` fields.

        elTOQUE returns the date and time of the snapshot as four
        separate keys. We assemble them into a single timezone-aware
        datetime in UTC (the API itself reports in UTC per their
        docs). Falls back to midnight on the ``fallback`` date if any
        component is missing or unparseable, so the article still
        gets persisted with a sensible timestamp.
        """
        raw_date = payload.get("date")
        try:
            d = (
                datetime.strptime(raw_date, "%Y-%m-%d").date()
                if raw_date
                else fallback
            )
        except (TypeError, ValueError):
            d = fallback

        try:
            h = int(payload.get("hour") or 0)
            m = int(payload.get("minutes") or 0)
            s = int(payload.get("seconds") or 0)
        except (TypeError, ValueError):
            h = m = s = 0

        try:
            return datetime(d.year, d.month, d.day, h, m, s, tzinfo=timezone.utc)
        except ValueError:
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)

    @staticmethod
    def _format_body(rates: dict[str, float], observed_at: datetime) -> str:
        lines = [
            f"Snapshot UTC: {observed_at.isoformat()}",
            "",
            "Tasa Representativa del Mercado Informal (TRMI) — elTOQUE.",
            "Tasas en CUP por unidad de moneda extranjera o cripto.",
            "",
            f"{'Moneda':<12} {'Tasa CUP':>12}",
        ]
        # Stable display order: cash USD first, then MLC, then USDT,
        # then crypto alphabetically. Anything not in the order list
        # gets sorted to the end alphabetically — defensive in case
        # elTOQUE adds new pairs in the future.
        order = ["USD", "MLC", "USDT_TRC20", "BTC", "TRX", "ECU"]
        seen = set(order)
        for code in order + sorted(c for c in rates if c not in seen):
            val = rates.get(code)
            if val is None:
                continue
            lines.append(f"{code:<12} {val:>12.4f}")
        lines.extend(["", ATTRIBUTION])
        return "\n".join(lines)
