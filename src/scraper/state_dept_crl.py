"""
Scraper for the U.S. State Department Cuba Restricted List (CRL).

The CRL is a single HTML page maintained by State's Division for
Counter Threat Finance and Sanctions. It enumerates entities and
subentities that U.S. persons are prohibited from transacting directly
with under §515.209 of the Cuban Assets Control Regulations.

The page is updated only a few times a year, but each update materially
changes our company-exposure surfaces (e.g. new GAESA-affiliated hotels
appearing on the list immediately disqualifies any U.S. operator from
managing them). The scraper therefore snapshots the parsed entity set
to disk and emits one ``ScrapedArticle`` per change (addition / removal)
so the daily brief can surface diffs.

Most CRL entries are NOT on OFAC's SDN list — the two regimes complement
each other but are managed by different agencies. Any analysis that only
looks at SDN will miss the bulk of the Cuba exposure picture.

Data source:
  https://www.state.gov/cuba-sanctions/cuba-restricted-list/

No API key required — public HTML page. State serves the page to
default User-Agents (no UA-blocking gotcha here, unlike .gob.cu sites).
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

CRL_URL = "https://www.state.gov/cuba-sanctions/cuba-restricted-list/"
SNAPSHOT_DIR = settings.storage_dir / "state_dept_snapshots"

# The page wraps real content in this <article> class set; we drill into
# it instead of the whole document so the sidebar nav doesn't pollute
# the entity walk.
_ARTICLE_SELECTOR = (
    "article.post.page, "
    "article.type-page, "
    ".entry-content, "
    "article"
)

# Paragraphs starting with these tokens are page boilerplate, not
# entries. Matched against the leading 80 chars, case-insensitive.
_PREAMBLE_PREFIXES = (
    "list of restricted entities",
    "as of ",
    "below is the u.s. department of state",
    "***",
    "the cuba restricted list",
    "for additional information",
    "contact: ",
    "previous version",
    "u.s. persons",
)


@dataclass(frozen=True)
class CrlEntry:
    """One parsed entity on the CRL, scoped to its section heading."""

    section: str
    name: str

    def key(self) -> str:
        """Stable identity for diffing across runs."""
        return f"{self.section.lower()}::{self.name.lower()}"

    def to_dict(self) -> dict:
        return {"section": self.section, "name": self.name}


class StateDeptCRLScraper(BaseScraper):
    """
    Fetch the State Dept CRL HTML, parse its entity list grouped by
    section heading, snapshot the result to disk, and emit per-change
    articles diffed against the prior snapshot.
    """

    def get_source_id(self) -> str:
        return "state_dept_crl"

    def scrape(self, target_date: Optional[date] = None) -> ScrapeResult:
        start = time.time()
        target_date = target_date or date.today()
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

        try:
            html = self._fetch(CRL_URL).text
        except Exception as exc:
            logger.error("CRL fetch failed: %s", exc, exc_info=True)
            return ScrapeResult(
                source=self.get_source_id(),
                success=False,
                error=f"CRL page unreachable: {exc}",
                duration_seconds=int(time.time() - start),
            )

        soup = BeautifulSoup(html, "lxml")
        container = soup.select_one(_ARTICLE_SELECTOR) or soup.body
        if container is None:
            return ScrapeResult(
                source=self.get_source_id(),
                success=False,
                error="CRL page had no parseable article container",
                duration_seconds=int(time.time() - start),
            )

        entries = list(self._parse_entries(container))
        list_effective_date = self._extract_effective_date(container)

        if not entries:
            return ScrapeResult(
                source=self.get_source_id(),
                success=False,
                error="CRL page parsed to zero entries — selector likely drifted",
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
            "CRL: %d entries, %d additions, %d removals (effective=%s)",
            len(entries),
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

    def _parse_entries(self, container) -> list[CrlEntry]:
        """Walk the article in document order, tracking the current
        section heading and emitting a ``CrlEntry`` for every paragraph
        that looks like an entity row.

        Paragraphs that contain ONLY a ``<strong>`` whose text matches a
        plausible section heading (e.g. "Ministries", "Holding
        Companies", "Hotels in La Habana Province") set the running
        section. Other paragraphs become entries under that section.
        """
        section = "Unclassified"
        out: list[CrlEntry] = []

        for p in container.find_all("p"):
            text = p.get_text(" ", strip=True)
            if not text:
                continue
            if self._is_preamble(text):
                continue

            # Pull only the text that comes from a leading <strong>; if
            # the paragraph IS just that <strong>, treat it as a
            # section header. Otherwise the strong is decorative
            # (entity name within the entry) and we keep the full text.
            strong = p.find("strong")
            strong_text = strong.get_text(" ", strip=True) if strong else ""
            is_section_header = bool(
                strong
                and strong_text
                and strong_text == text
                and self._looks_like_section(strong_text)
            )

            if is_section_header:
                section = strong_text.rstrip(":").strip()
                continue

            # Drop any "Effective <date>" tail the State Dept appends to
            # newly-added entries — keep it stripped from the canonical
            # name so a renamed effective date doesn't churn our diff.
            name = re.sub(r"\s+Effective\s+[A-Z][a-z]+\s+\d{1,2},?\s+\d{4}\.?$", "", text).strip()
            name = name.rstrip(".").strip()
            if not name:
                continue

            out.append(CrlEntry(section=section, name=name))

        return out

    @staticmethod
    def _is_preamble(text: str) -> bool:
        head = text[:80].lower()
        return any(head.startswith(p) for p in _PREAMBLE_PREFIXES)

    @staticmethod
    def _looks_like_section(text: str) -> bool:
        """Heading tests: short, no comma, no dash separator. Real
        entity rows are longer and almost always contain ``—`` or ``,``
        (address, acronym expansion, etc.)."""
        if len(text) > 80:
            return False
        if "," in text or "—" in text or " - " in text:
            return False
        # "***" decorations and effective-date stamps are not sections.
        if text.startswith("***") or text.lower().startswith("effective "):
            return False
        return True

    @staticmethod
    def _extract_effective_date(container) -> Optional[str]:
        """Pull the ``As of <Month Day, Year>`` line from the preamble.

        Returned as ISO ``YYYY-MM-DD`` so it lives happily in JSONB.
        """
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
        snapshots = sorted(SNAPSHOT_DIR.glob("crl_*.json"), reverse=True)
        if not snapshots:
            return {}
        try:
            return json.loads(Path(snapshots[0]).read_text())
        except Exception as exc:
            logger.warning("Could not load previous CRL snapshot: %s", exc)
            return {}

    def _save_snapshot(self, current: dict[str, dict], snap_date: date) -> None:
        path = SNAPSHOT_DIR / f"crl_{snap_date.isoformat()}.json"
        path.write_text(json.dumps(current, indent=2, ensure_ascii=False))
        logger.info("Saved CRL snapshot: %s (%d entries)", path, len(current))

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
            # Emit one baseline article so the daily brief reflects the
            # current CRL state, then start diffing from the next run.
            articles.append(
                ScrapedArticle(
                    headline=(
                        f"Cuba Restricted List baseline: {len(current)} "
                        f"entities (effective {list_effective_date or 'unknown'})"
                    ),
                    published_date=target_date,
                    source_url=f"{CRL_URL}#baseline-{target_date.isoformat()}",
                    body_text=self._summarize_baseline(current),
                    source_name="US State Department — Cuba Restricted List",
                    source_credibility="official",
                    article_type="CRL baseline",
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
                        f"CRL ADDED — {entry['section']}: {entry['name']}"
                    ),
                    published_date=target_date,
                    source_url=f"{CRL_URL}#added-{target_date.isoformat()}-{key}",
                    body_text=(
                        f"Entity newly added to the U.S. State Department "
                        f"Cuba Restricted List.\n\n"
                        f"Section: {entry['section']}\n"
                        f"Name: {entry['name']}\n"
                        f"List effective date: {list_effective_date or 'unknown'}"
                    ),
                    source_name="US State Department — Cuba Restricted List",
                    source_credibility="official",
                    article_type="CRL addition",
                    extra_metadata={**entry, "list_effective_date": list_effective_date},
                )
            )

        for key in removed:
            entry = previous[key]
            articles.append(
                ScrapedArticle(
                    headline=(
                        f"CRL REMOVED — {entry['section']}: {entry['name']}"
                    ),
                    published_date=target_date,
                    source_url=f"{CRL_URL}#removed-{target_date.isoformat()}-{key}",
                    body_text=(
                        f"Entity removed from the U.S. State Department "
                        f"Cuba Restricted List.\n\n"
                        f"Section: {entry['section']}\n"
                        f"Name: {entry['name']}\n"
                        f"List effective date: {list_effective_date or 'unknown'}"
                    ),
                    source_name="US State Department — Cuba Restricted List",
                    source_credibility="official",
                    article_type="CRL removal",
                    extra_metadata={**entry, "list_effective_date": list_effective_date},
                )
            )

        return articles

    @staticmethod
    def _summarize_baseline(current: dict[str, dict]) -> str:
        # Group entries by section for a readable baseline body.
        by_section: dict[str, list[str]] = {}
        for e in current.values():
            by_section.setdefault(e["section"], []).append(e["name"])

        lines = [
            "U.S. State Department — Cuba Restricted List baseline snapshot.",
            f"Total entities: {len(current)}.",
            "",
        ]
        for section, names in sorted(by_section.items()):
            lines.append(f"{section} ({len(names)}):")
            for n in sorted(names):
                lines.append(f"  - {n}")
            lines.append("")
        return "\n".join(lines).rstrip()
