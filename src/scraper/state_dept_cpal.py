"""
Scraper for the U.S. State Department Cuba Prohibited Accommodations
List (CPAL).

The CPAL is a single HTML page maintained by State; it enumerates
specific properties (hotels, hostales, casas particulares marketed as
casas) at which U.S. persons are prohibited from lodging under §515.210
of the Cuban Assets Control Regulations. The list is grouped by
province, with each entry rendered as a paragraph whose leading
``<strong>`` is the property name and whose trailing text is the
address.

Two single-character markers are appended to some entries:

- ``*`` — property is marketed as a "casa" but is owned/controlled by
  the Cuban government, so it does not qualify as an independent
  ``casa particular``.
- ``^`` — property is a genuine ``casa particular`` but still meets
  CPAL inclusion criteria.

We preserve those markers in the parsed entry so the company-exposure
tooling and the LLM analyzer can treat them as classification hints.

Like the CRL scraper, this module snapshots the parsed entry set to
disk and emits one ``ScrapedArticle`` per change between runs (plus a
single baseline article on the first successful scrape).

Data source:
  https://www.state.gov/cuba-sanctions/cuba-prohibited-accommodations-list/

No API key required — public HTML page; default User-Agent works.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

from src.config import settings
from src.scraper.base import BaseScraper, ScrapedArticle, ScrapeResult

logger = logging.getLogger(__name__)

CPAL_URL = "https://www.state.gov/cuba-sanctions/cuba-prohibited-accommodations-list/"
SNAPSHOT_DIR = settings.storage_dir / "state_dept_snapshots"

_ARTICLE_SELECTOR = (
    "article.post.page, "
    "article.type-page, "
    ".entry-content, "
    "article"
)

# Lines we want to drop before we hit the per-entry list. Compared
# case-insensitively against the leading ~80 chars of each paragraph.
_PREAMBLE_PREFIXES = (
    "as of ",
    "below is the u.s. department of state",
    "* property is marketed",
    "^ property is a",
    "previous version",
    "for additional information",
)

# Cuban province names. Used both to detect province-header paragraphs
# and to validate that a stripped header is a real geography rather
# than incidental bold text.
_CUBAN_PROVINCES = {
    "Pinar del Río", "Pinar del Rio",
    "Artemisa",
    # State Dept currently uses the English exonym "Havana" as the
    # heading; we accept both that and the native Spanish forms in
    # case the page is re-localised.
    "Havana", "La Habana", "Habana",
    "Mayabeque",
    "Matanzas",
    "Cienfuegos",
    "Villa Clara",
    "Sancti Spíritus", "Sancti Spiritus",
    "Ciego de Ávila", "Ciego de Avila",
    "Camagüey", "Camaguey",
    "Las Tunas",
    "Holguín", "Holguin",
    "Granma",
    "Santiago de Cuba",
    "Guantánamo", "Guantanamo",
    "Isla de la Juventud",
}


@dataclass(frozen=True)
class CpalEntry:
    """One parsed accommodation on the CPAL."""

    province: str
    name: str
    address: str
    marker: str  # "" | "*" | "^"

    def key(self) -> str:
        # Province + name is the right diff key — addresses get edited
        # for typos but identity is name-in-province.
        return f"{self.province.lower()}::{self.name.lower()}"

    def to_dict(self) -> dict:
        return {
            "province": self.province,
            "name": self.name,
            "address": self.address,
            "marker": self.marker,
        }


class StateDeptCPALScraper(BaseScraper):
    """
    Fetch the State Dept CPAL HTML, parse hotel/casa entries grouped by
    province, snapshot the result to disk, and emit per-change articles
    diffed against the prior snapshot.
    """

    def get_source_id(self) -> str:
        return "state_dept_cpal"

    def scrape(self, target_date: Optional[date] = None) -> ScrapeResult:
        start = time.time()
        target_date = target_date or date.today()
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

        try:
            html = self._fetch(CPAL_URL).text
        except Exception as exc:
            logger.error("CPAL fetch failed: %s", exc, exc_info=True)
            return ScrapeResult(
                source=self.get_source_id(),
                success=False,
                error=f"CPAL page unreachable: {exc}",
                duration_seconds=int(time.time() - start),
            )

        soup = BeautifulSoup(html, "lxml")
        container = soup.select_one(_ARTICLE_SELECTOR) or soup.body
        if container is None:
            return ScrapeResult(
                source=self.get_source_id(),
                success=False,
                error="CPAL page had no parseable article container",
                duration_seconds=int(time.time() - start),
            )

        entries = self._parse_entries(container)
        list_effective_date = self._extract_effective_date(container)

        if not entries:
            return ScrapeResult(
                source=self.get_source_id(),
                success=False,
                error="CPAL page parsed to zero entries — selector likely drifted",
                duration_seconds=int(time.time() - start),
            )

        previous = self._load_previous_snapshot()
        current = {e.key(): e.to_dict() for e in entries}
        self._save_snapshot(current, target_date)

        articles = self._build_articles(
            previous=previous,
            current=current,
            target_date=target_date,
            list_effective_date=list_effective_date,
            is_first_run=not previous,
        )

        logger.info(
            "CPAL: %d entries across %d provinces, %d additions, %d removals (effective=%s)",
            len(entries),
            len({e.province for e in entries}),
            sum(1 for a in articles if "ADDED" in a.headline),
            sum(1 for a in articles if "REMOVED" in a.headline),
            list_effective_date,
        )

        return ScrapeResult(
            source=self.get_source_id(),
            success=True,
            articles=articles,
            duration_seconds=int(time.time() - start),
        )

    # ----- Parsing ----------------------------------------------------

    def _parse_entries(self, container) -> list[CpalEntry]:
        province = "Unknown"
        out: list[CpalEntry] = []

        # Province headers live in heading tags (currently <h5>, but we
        # accept any heading defensively in case State retypesets the
        # page); entry rows live in <p>. Walking both in document order
        # keeps the running province in sync with the entries that
        # follow it.
        for el in container.find_all(["h2", "h3", "h4", "h5", "h6", "p"]):
            text = el.get_text(" ", strip=True)
            if not text:
                continue
            if self._is_preamble(text):
                continue

            # Heading tag → candidate province header.
            if el.name != "p":
                stripped = text.rstrip(":").strip()
                if stripped in _CUBAN_PROVINCES:
                    province = stripped
                continue

            strong = el.find("strong")
            strong_text = strong.get_text(" ", strip=True) if strong else ""

            # Some older revisions of the page also place province
            # headers in <p><strong>Province:</strong></p>. Keep that
            # detection path as a fallback.
            stripped = strong_text.rstrip(":").strip()
            if (
                strong
                and strong_text == text
                and stripped in _CUBAN_PROVINCES
            ):
                province = stripped
                continue

            # An entry must start with a <strong> (the property name).
            # Without one we can't reliably split name from address;
            # skip the row rather than guess.
            if not strong or not strong_text:
                continue

            # Property name is the leading <strong>. Address is the
            # remainder of the paragraph after we strip that prefix.
            name_raw = strong_text.rstrip(",").strip()
            remainder = text[len(strong_text):].lstrip(" ,").strip()

            # Trailing single-char marker (* or ^) — pull it off the
            # address so the address field is clean.
            marker = ""
            m = re.search(r"\s+([*^])\s*$", remainder)
            if m:
                marker = m.group(1)
                remainder = remainder[: m.start()].rstrip()

            # Some rows trail with "(aka: <other name>)" inside the
            # name; keep aliases attached to the name field — they are
            # part of the property's identity.
            aka_in_name = re.search(r"\(aka:\s*([^)]+)\)", remainder)
            if aka_in_name and "(aka" not in name_raw:
                name = f"{name_raw} (aka: {aka_in_name.group(1).strip()})"
                remainder = remainder.replace(aka_in_name.group(0), "").strip(" ,.")
            else:
                name = name_raw

            out.append(
                CpalEntry(
                    province=province,
                    name=name,
                    address=remainder,
                    marker=marker,
                )
            )

        return out

    @staticmethod
    def _is_preamble(text: str) -> bool:
        head = text[:80].lower()
        return any(head.startswith(p) for p in _PREAMBLE_PREFIXES)

    @staticmethod
    def _extract_effective_date(container) -> Optional[str]:
        from datetime import datetime as _dt

        text = container.get_text(" ", strip=True)
        m = re.search(
            r"As\s+of\s+(January|February|March|April|May|June|"
            r"July|August|September|October|November|December)"
            r"\s+(\d{1,2}),?\s+(\d{4})",
            text,
            re.I,
        )
        if not m:
            return None
        try:
            parsed = _dt.strptime(
                f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y"
            )
        except ValueError:
            return None
        return parsed.date().isoformat()

    # ----- Snapshotting ------------------------------------------------

    def _load_previous_snapshot(self) -> dict[str, dict]:
        snapshots = sorted(SNAPSHOT_DIR.glob("cpal_*.json"), reverse=True)
        if not snapshots:
            return {}
        try:
            return json.loads(Path(snapshots[0]).read_text())
        except Exception as exc:
            logger.warning("Could not load previous CPAL snapshot: %s", exc)
            return {}

    def _save_snapshot(self, current: dict[str, dict], snap_date: date) -> None:
        path = SNAPSHOT_DIR / f"cpal_{snap_date.isoformat()}.json"
        path.write_text(json.dumps(current, indent=2, ensure_ascii=False))
        logger.info("Saved CPAL snapshot: %s (%d entries)", path, len(current))

    # ----- Article construction ---------------------------------------

    def _build_articles(
        self,
        *,
        previous: dict[str, dict],
        current: dict[str, dict],
        target_date: date,
        list_effective_date: Optional[str],
        is_first_run: bool,
    ) -> list[ScrapedArticle]:
        articles: list[ScrapedArticle] = []

        if is_first_run:
            articles.append(
                ScrapedArticle(
                    headline=(
                        f"Cuba Prohibited Accommodations List baseline: "
                        f"{len(current)} properties (effective "
                        f"{list_effective_date or 'unknown'})"
                    ),
                    published_date=target_date,
                    source_url=f"{CPAL_URL}#baseline-{target_date.isoformat()}",
                    body_text=self._summarize_baseline(current),
                    source_name="US State Department — Cuba Prohibited Accommodations List",
                    source_credibility="official",
                    article_type="CPAL baseline",
                    extra_metadata={
                        "entries_count": len(current),
                        "list_effective_date": list_effective_date,
                        "entries": list(current.values()),
                    },
                )
            )
            return articles

        prev_keys = set(previous.keys())
        curr_keys = set(current.keys())
        added = sorted(curr_keys - prev_keys)
        removed = sorted(prev_keys - curr_keys)

        for key in added:
            entry = current[key]
            articles.append(
                ScrapedArticle(
                    headline=(
                        f"CPAL ADDED — {entry['province']}: {entry['name']}"
                    ),
                    published_date=target_date,
                    source_url=f"{CPAL_URL}#added-{target_date.isoformat()}-{key}",
                    body_text=(
                        f"Property newly added to the U.S. State "
                        f"Department Cuba Prohibited Accommodations "
                        f"List.\n\n"
                        f"Province: {entry['province']}\n"
                        f"Name: {entry['name']}\n"
                        f"Address: {entry['address']}\n"
                        f"Marker: {entry['marker'] or '—'}\n"
                        f"List effective date: {list_effective_date or 'unknown'}"
                    ),
                    source_name="US State Department — Cuba Prohibited Accommodations List",
                    source_credibility="official",
                    article_type="CPAL addition",
                    extra_metadata={**entry, "list_effective_date": list_effective_date},
                )
            )

        for key in removed:
            entry = previous[key]
            articles.append(
                ScrapedArticle(
                    headline=(
                        f"CPAL REMOVED — {entry['province']}: {entry['name']}"
                    ),
                    published_date=target_date,
                    source_url=f"{CPAL_URL}#removed-{target_date.isoformat()}-{key}",
                    body_text=(
                        f"Property removed from the U.S. State Department "
                        f"Cuba Prohibited Accommodations List.\n\n"
                        f"Province: {entry['province']}\n"
                        f"Name: {entry['name']}\n"
                        f"Address: {entry['address']}\n"
                        f"Marker: {entry['marker'] or '—'}\n"
                        f"List effective date: {list_effective_date or 'unknown'}"
                    ),
                    source_name="US State Department — Cuba Prohibited Accommodations List",
                    source_credibility="official",
                    article_type="CPAL removal",
                    extra_metadata={**entry, "list_effective_date": list_effective_date},
                )
            )

        return articles

    @staticmethod
    def _summarize_baseline(current: dict[str, dict]) -> str:
        by_province: dict[str, list[str]] = {}
        for e in current.values():
            by_province.setdefault(e["province"], []).append(e["name"])

        lines = [
            "U.S. State Department — Cuba Prohibited Accommodations List baseline snapshot.",
            f"Total properties: {len(current)}.",
            "",
        ]
        for prov in sorted(by_province):
            names = by_province[prov]
            lines.append(f"{prov} ({len(names)}):")
            for n in sorted(names):
                lines.append(f"  - {n}")
            lines.append("")
        return "\n".join(lines).rstrip()
