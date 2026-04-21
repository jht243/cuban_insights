"""
Pre-canned SEC EDGAR full-text search presets for Cuba / CACR /
Helms-Burton / Cuba Restricted List / impairment / contingent-liability
research.

These power /tools/sec-edgar-cuba-impairment-search. The tool's job is
to take a question that an analyst would otherwise spend 15 min crafting
in EDGAR's awkward Lucene-flavoured search UI and turn it into a single
click that opens a pre-built efts.sec.gov query.

Why this is its own module:
  - The presets are content. Every preset is a Cuba-research question
    phrased the way a sell-side analyst, OFAC-compliance officer, or
    Helms-Burton plaintiff's attorney would phrase it ("companies that
    disclosed Helms-Burton Title III lawsuit exposure"), and we want to
    be able to add / remove them without touching server.py.
  - The query strings need to be reviewed by anyone who knows EDGAR's
    quirks. Co-locating with `src/analysis/edgar_search.py` would
    suggest they're shared with the runtime EDGAR fetcher; they're
    not — these are deeplinks into EDGAR's user-facing UI.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urlencode


# Public-facing EDGAR full-text search base URL. The user-facing UI
# at https://efts.sec.gov/LATEST/search-index/?q=… renders results in
# the browser; we deeplink into it (the JSON API in
# `src/analysis/edgar_search.py` is a different surface used server-side
# for our own EDGAR scans).
EDGAR_SEARCH_UI = "https://efts.sec.gov/LATEST/search-index"


@dataclass(frozen=True)
class EdgarPreset:
    slug: str            # short identifier for the preset card
    title: str           # human label rendered on the card
    question: str        # the research question this answers
    query: str           # raw EDGAR search "q" string (Lucene-ish)
    forms: tuple[str, ...]  # SEC forms to constrain the search to
    lookback_days: int = 730  # default 2-year window; covers ~2 cycles of 10-K filings
    why: str = ""        # one-sentence rationale explaining the preset

    def url(self) -> str:
        """Return a deeplink to EDGAR's user-facing search UI."""
        end = date.today()
        start = end - timedelta(days=self.lookback_days)
        params = {
            "q": self.query,
            "dateRange": "custom",
            "startdt": start.isoformat(),
            "enddt": end.isoformat(),
            "forms": ",".join(self.forms),
        }
        return f"{EDGAR_SEARCH_UI}?{urlencode(params)}"


# ────────────────────────────────────────────────────────────────────
# Preset catalogue
# ────────────────────────────────────────────────────────────────────
#
# Ordering matters — the first preset is the SERP / page hero. Pick the
# one most analysts will click first (the "everything" search) and put
# it at the top.

PRESETS: tuple[EdgarPreset, ...] = (
    EdgarPreset(
        slug="any-cuba-mention",
        title="Any Cuba / CACR / Helms-Burton / ETECSA / ALIMPORT mention (10-K, 20-F, 10-Q)",
        question=(
            "Which public companies disclosed Cuba, the Cuban Assets "
            "Control Regulations, Helms-Burton, ETECSA, or ALIMPORT in "
            "their most recent annual or quarterly reports?"
        ),
        query='"Cuba" OR "Cuban Assets Control Regulations" OR "Helms-Burton" OR "Helms Burton" OR "LIBERTAD Act" OR "ETECSA" OR "ALIMPORT" OR "Havana"',
        forms=("10-K", "20-F", "10-Q"),
        why=(
            "The widest possible Cuba disclosure net. Use this as the "
            "starting point — every company that mentions Cuba in an "
            "annual or quarterly will appear here."
        ),
    ),
    EdgarPreset(
        slug="helms-burton-title-iii",
        title="Helms-Burton Title III lawsuit exposure",
        question=(
            "Which companies disclose ongoing or threatened Helms-Burton "
            "Title III lawsuits over trafficking in confiscated Cuban "
            "property?"
        ),
        # Title III became actionable on 2 May 2019 when the Trump
        # administration suspended the long-running waiver. Most
        # disclosures cite the Act, the Title, or named plaintiffs
        # (Havana Docks Corp, Exxon Mobil, etc.).
        query='("Helms-Burton" OR "Helms Burton" OR "LIBERTAD Act" OR "Title III") AND ("Cuba" OR "Cuban") AND ("lawsuit" OR "litigation" OR "claim*" OR "trafficking")',
        forms=("10-K", "20-F", "10-Q", "8-K"),
        why=(
            "Title III suits over confiscated Cuban property unfroze in "
            "May 2019 and have produced significant judgments against "
            "cruise lines, hotel chains, and online travel agencies. "
            "This preset surfaces the active defendants and any new "
            "plaintiffs."
        ),
    ),
    EdgarPreset(
        slug="cuba-impairment",
        title="Cuba operations impairment / write-down disclosures",
        question=(
            "Which companies have booked an impairment, write-down, or "
            "deconsolidation tied to their Cuban operations?"
        ),
        query='("Cuba" OR "Cuban") AND ("impairment" OR "write-down" OR "writedown" OR "deconsolidat*" OR "exit*" OR "wound down" OR "wound-down")',
        forms=("10-K", "20-F", "10-Q", "8-K"),
        why=(
            "Trump-era Cuba Restricted List additions and the 2019 Title "
            "III actionability triggered a wave of impairments and exits "
            "by cruise lines, airlines, and hotel JV partners — this "
            "surfaces those filings."
        ),
    ),
    EdgarPreset(
        slug="cacr-ofac-cuba",
        title="OFAC Cuban Assets Control Regulations compliance disclosures",
        question=(
            "Which companies disclose CACR, Cuba general licenses, or "
            "Cuba sanctions-compliance risk in their filings?"
        ),
        query='("Cuban Assets Control Regulations" OR "CACR" OR "31 CFR 515" OR "31 CFR Part 515") OR (("Cuba" OR "Cuban") AND ("OFAC" OR "general license" OR "Office of Foreign Assets Control"))',
        forms=("10-K", "20-F", "10-Q", "8-K"),
        why=(
            "Most companies that discuss the CACR in a 10-K do so "
            "because they have, or had, exposure they need to ring-fence "
            "(travel-services providers, payments networks, agricultural "
            "exporters, telecoms, pharmaceutical exporters under TSRA). "
            "Useful for the compliance-officer-as-investor."
        ),
    ),
    EdgarPreset(
        slug="cuba-restricted-list-counterparty",
        title="Cuba Restricted List / GAESA counterparty exposure",
        question=(
            "Which companies disclose GAESA, ETECSA, ALIMPORT, "
            "Cubanacán, Habaguanex, FINCIMEX, Gaviota, or other Cuba "
            "Restricted List entities as customers, suppliers, or "
            "joint-venture partners?"
        ),
        query='("GAESA" OR "ETECSA" OR "ALIMPORT" OR "Cubanacan" OR "Habaguanex" OR "FINCIMEX" OR "Gaviota" OR "Cuba Restricted List") AND ("counterparty" OR "joint venture" OR "supply agreement" OR "customer" OR "supplier")',
        forms=("10-K", "20-F", "10-Q", "8-K"),
        why=(
            "GAESA-affiliated entities and the State Department's Cuba "
            "Restricted List are the dominant compliance touchpoint for "
            "companies operating in or selling to Cuba. This is the "
            "cleanest way to enumerate active commercial relationships."
        ),
    ),
    EdgarPreset(
        slug="cuba-sst-listing",
        title="Cuba State Sponsor of Terrorism listing exposure",
        question=(
            "Which companies disclose risk from Cuba's re-designation as "
            "a State Sponsor of Terrorism (January 2021) — including ESTA, "
            "banking, or counterparty consequences?"
        ),
        query='("State Sponsor of Terrorism" OR "State Sponsors of Terrorism" OR "SST list*") AND ("Cuba" OR "Cuban")',
        forms=("10-K", "20-F", "10-Q"),
        why=(
            "Cuba's re-listing as an SST in January 2021 carries "
            "downstream effects on correspondent banking, ESTA visa-"
            "waiver eligibility for travellers who have visited Cuba, "
            "and US export controls. Disclosures cluster among financial "
            "institutions, travel platforms, and exporters."
        ),
    ),
    EdgarPreset(
        slug="cuba-tsra-agricultural",
        title="TSRA Cuba agricultural / pharmaceutical export disclosures",
        question=(
            "Which agricultural exporters, food producers, and "
            "pharmaceutical companies disclose TSRA-authorized sales to "
            "Cuba?"
        ),
        query='("Trade Sanctions Reform" OR "TSRA" OR "Trade Sanctions Reform and Export Enhancement Act") AND ("Cuba" OR "Cuban")',
        forms=("10-K", "20-F", "10-Q"),
        why=(
            "The Trade Sanctions Reform and Export Enhancement Act (2000) "
            "carved out a legal pathway for cash-only US agricultural "
            "and medical exports to Cuba — primarily routed through "
            "ALIMPORT. This surfaces the active US exporters."
        ),
    ),
    EdgarPreset(
        slug="cuba-cruise-airline-travel",
        title="Cruise lines, airlines & travel-platform Cuba disclosures",
        question=(
            "Which cruise lines, airlines, and online travel platforms "
            "disclose ongoing or historical Cuba operations, exit costs, "
            "or Helms-Burton claims?"
        ),
        query='("Cuba" OR "Cuban" OR "Havana") AND ("cruise" OR "itinerary" OR "charter flight" OR "scheduled service" OR "people-to-people" OR "Support for the Cuban People")',
        forms=("10-K", "20-F", "10-Q", "8-K"),
        why=(
            "Cruise lines (Carnival, Royal Caribbean, NCL), US carriers "
            "(JetBlue, American, Delta, Southwest, United), and the "
            "online travel agencies are the most-named defendants in "
            "Title III suits brought by the Havana Docks Corp class. "
            "This preset isolates that cohort."
        ),
    ),
    EdgarPreset(
        slug="cuba-remittance-payments",
        title="Cuba remittance & payments-corridor disclosures",
        question=(
            "Which payments networks, remitters, or fintechs disclose "
            "Cuba remittance corridor exposure (Western Union, MoneyGram, "
            "fintech alternatives)?"
        ),
        query='("Cuba" OR "Cuban") AND ("remittance*" OR "money transfer" OR "FINCIMEX" OR "Western Union" OR "MoneyGram")',
        forms=("10-K", "20-F", "10-Q", "8-K"),
        why=(
            "FINCIMEX is the GAESA-controlled gateway for incoming Cuba "
            "remittances and was added to the Cuba Restricted List in "
            "2020 — Western Union restored US-Cuba service in 2023 "
            "via a non-FINCIMEX route. This surfaces the corridor's "
            "active participants."
        ),
    ),
)


def list_presets() -> list[EdgarPreset]:
    return list(PRESETS)


def get_preset(slug: str) -> EdgarPreset | None:
    for p in PRESETS:
        if p.slug == slug:
            return p
    return None


# ────────────────────────────────────────────────────────────────────
# Curated "known disclosers" — the S&P 500 tickers most commonly named
# in Cuba-related SEC filings. Used to render a quick-link table so
# visitors can jump straight to a company's EDGAR Cuba history.
#
# Source: the curated_cuba_exposure map (which we already maintain by
# hand). This avoids hardcoding the same fact in two places.
# ────────────────────────────────────────────────────────────────────


def _build_company_edgar_url(*, cik: str | None, company_name: str) -> str:
    """Pre-canned EDGAR search for ANY Cuba mention in this company's
    recent filings."""
    end = date.today()
    start = end - timedelta(days=730)
    params = {
        "q": '"Cuba" OR "Cuban Assets Control Regulations" OR "Helms-Burton" OR "ETECSA" OR "ALIMPORT" OR "Havana"',
        "dateRange": "custom",
        "startdt": start.isoformat(),
        "enddt": end.isoformat(),
        "forms": "10-K,10-Q,8-K,20-F,6-K",
    }
    if cik:
        cik_clean = str(cik).strip().lstrip("0") or "0"
        params["ciks"] = cik_clean.zfill(10)
    else:
        params["company"] = company_name
    return f"{EDGAR_SEARCH_UI}?{urlencode(params)}"


@dataclass(frozen=True)
class CuratedDiscloser:
    ticker: str
    short_name: str
    exposure_level: str
    one_line: str
    profile_url: str  # /companies/<slug>/cuba-exposure
    edgar_search_url: str  # deeplink into EDGAR for this company


def list_curated_disclosers(*, max_n: int = 30) -> list[CuratedDiscloser]:
    """Return the curated S&P 500 companies that have any non-'none'
    exposure level, sorted by exposure-level severity then ticker."""
    try:
        from src.data.curated_cuba_exposure import _CURATED  # type: ignore
        from src.data.sp500_companies import find_company
    except Exception:
        return []

    severity = {"direct": 0, "indirect": 1, "historical": 2, "none": 9}
    rows: list[CuratedDiscloser] = []
    for ticker, entry in _CURATED.items():
        if entry.exposure_level == "none":
            continue
        company = find_company(ticker)
        if company is None:
            continue
        # Trim summary to one line for the table view; the full version
        # lives on the per-company landing page.
        first_sentence = entry.summary.split(". ")[0].rstrip(".") + "."
        rows.append(CuratedDiscloser(
            ticker=ticker,
            short_name=company.short_name,
            exposure_level=entry.exposure_level,
            one_line=first_sentence,
            profile_url=f"/companies/{company.slug}/cuba-exposure",
            edgar_search_url=_build_company_edgar_url(
                cik=company.cik, company_name=company.short_name
            ),
        ))

    rows.sort(key=lambda r: (severity.get(r.exposure_level, 9), r.ticker))
    return rows[:max_n]
