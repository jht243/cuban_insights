"""
Shared HTTP helpers for Cuban government sources.

Why this module exists
----------------------
Several of Cuba's official sites — `gacetaoficial.gob.cu`,
`parlamentocubano.gob.cu`, `cubaminrex.cu`, `onei.gob.cu`, etc. — sit
behind front-ends that intermittently return 403/empty responses to
"non-browser" User-Agents (`python-requests/...`, `httpx/...`, default
`curl`). Sometimes they tolerate a default UA, sometimes not; behaviour
varies by edge node and time of day. To remove that variable from the
pipeline entirely, every Cuba-government scraper should send a
plausible desktop-Chrome UA and a Spanish `Accept-Language` so we look
like an ordinary visitor from a Cuban or Latin-American IP.

The base `BaseScraper.__init__` already sets a reasonable Mozilla UA
on `self.client`, so for those scrapers `self._fetch(url)` is enough.
This module exists for the cases where a scraper needs to do a
one-shot request *outside* the `BaseScraper` retry loop (e.g. a
non-retried HEAD probe, a feedparser preflight, or a smoke-test
script). Using the constants from here keeps the UA + language headers
identical everywhere so we don't accidentally drift between modules.

Do NOT change the UA string casually: some `.gob.cu` edge nodes
fingerprint exactly on the Chrome major version, so picking an
implausible one (e.g. "Chrome/9.0") may itself trigger a block.
"""
from __future__ import annotations

import httpx

CUBA_GOV_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

CUBA_GOV_HEADERS: dict[str, str] = {
    "User-Agent": CUBA_GOV_USER_AGENT,
    # Cuban sites prefer Spanish; a few CU edge nodes treat non-CU
    # Spanish locales as suspicious. "es-CU" first, generic Spanish
    # second, English last.
    "Accept-Language": "es-CU,es;q=0.9,en;q=0.6",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
}


def cuba_gov_client(timeout: float = 25.0) -> httpx.Client:
    """Return an `httpx.Client` preconfigured for `.gob.cu` sources.

    Caller is responsible for closing the client (or using it as a
    context manager). Most scrapers do not need this — they should use
    `self.client` from `BaseScraper`. This helper is for one-off probes
    (smoke tests, manual backfills, feedparser preflight, etc.).
    """
    return httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers=CUBA_GOV_HEADERS,
    )
