"""
Zenodo distribution channel.

Each daily Investor Tearsheet PDF is deposited as a public Zenodo record
and assigned a permanent DOI (e.g. 10.5281/zenodo.123456). Zenodo records
are indexed by Google Search, Google Dataset Search, and OpenAIRE — over
time this builds a permanent, DOI-citable corpus of dated research notes
that all link back to cubaninsights.com.

Note on Google Scholar: as of 2026, Zenodo is *not* indexed by Google
Scholar (per Zenodo's own FAQ; their generic-repository policy + URL
structure conflicts with Scholar's heuristics). We get around that with
the parallel OSF Preprints channel which IS indexed by Scholar.

Authentication uses a Personal Access Token from
https://zenodo.org/account/settings/applications/tokens/new/
with scopes `deposit:write` + `deposit:actions`. Leave the token blank
and the channel is silently skipped (consistent with every other
distribution channel).

Reference: https://developers.zenodo.org/

This module is intentionally thin: it accepts a PDF (bytes) + a date,
constructs Zenodo-compliant metadata, executes the 4-step deposit flow,
returns a result record. Deduplication and cooldown logic live in the
runner.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


_PROD_API = "https://zenodo.org/api"
_SANDBOX_API = "https://sandbox.zenodo.org/api"

# Zenodo upload_type vocabulary; "publication" + publication_type
# "report" is the closest match for an investor research note.
_UPLOAD_TYPE = "publication"
_PUBLICATION_TYPE = "report"


@dataclass
class ZenodoUploadResult:
    success: bool
    deposition_id: Optional[int]
    doi: Optional[str]
    record_url: Optional[str]
    download_url: Optional[str]
    response_code: Optional[int]
    response_snippet: str


def is_enabled() -> bool:
    """True iff a Zenodo access token is configured."""
    return bool((settings.zenodo_access_token or "").strip())


def _api_base() -> str:
    return _SANDBOX_API if settings.zenodo_use_sandbox else _PROD_API


def _auth_headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.zenodo_access_token}",
        "Content-Type": "application/json",
    }


def _build_metadata(d: date) -> dict:
    """Zenodo deposition metadata.

    Required fields per the deposit schema: title, upload_type,
    description, creators. Everything else (keywords, communities,
    license, publication_date) is optional but improves discoverability
    and citation hygiene."""
    nice_date = d.strftime("%B %d, %Y")
    meta: dict = {
        "title": f"Cuban Insights — Daily Cuba Investor Tearsheet — {nice_date}",
        "upload_type": _UPLOAD_TYPE,
        "publication_type": _PUBLICATION_TYPE,
        "publication_date": d.isoformat(),
        "description": (
            f"<p>One-page research note for international investors covering "
            f"Cuba on {nice_date}.</p>"
            f"<p>Includes: the elTOQUE TRMI informal CUP/USD rate vs the "
            f"BCC official rate (with spread), OFAC SDN Cuba program "
            f"designations and Cuba Restricted List updates, Helms-Burton "
            f"Title III lawsuits and settlements, MIPYME policy moves and "
            f"Mariel ZED approvals, the US State Department travel-advisory "
            f"level for Cuba, and upcoming OFAC general-license renewals "
            f"plus ANPP / Council of State calendar items in the next 14 "
            f"days.</p>"
            f"<p><b>Sources:</b> elTOQUE (live scrape), BCC, OFAC SDN, "
            f"US State Department, Cuban Gaceta Oficial, ANPP, "
            f"Granma/Cubadebate corpus. Full daily briefing and methodology "
            f"at <a href=\"https://cubaninsights.com\">cubaninsights.com</a>.</p>"
        ),
        "creators": [
            {"name": "Cuban Insights", "affiliation": "Cuban Insights"},
        ],
        "keywords": [
            "Cuba",
            "investment",
            "sanctions",
            "OFAC",
            "CACR",
            "Helms-Burton",
            "Mariel ZED",
            "MIPYMES",
            "tearsheet",
            "elTOQUE TRMI",
            "BCC",
        ],
        "subjects": [
            {"term": "Economics and Business", "scheme": "FOS"},
            {"term": "Political Sciences", "scheme": "FOS"},
        ],
        "language": "eng",
        "access_right": "open",
        "license": "cc-by-4.0",
        "notes": (
            "Daily auto-generated research note. For methodology, "
            "historical archive, and live data, see "
            "https://cubaninsights.com."
        ),
    }
    community = (settings.zenodo_community or "").strip()
    if community:
        meta["communities"] = [{"identifier": community}]
    return meta


def upload_tearsheet(pdf_bytes: bytes, d: date) -> ZenodoUploadResult:
    """Upload a single tearsheet PDF to Zenodo as a published deposition.

    The Zenodo deposit flow is 4 steps:
      1. POST  /deposit/depositions          → empty draft, returns id + bucket
      2. PUT   <bucket>/<filename>           → stream PDF bytes
      3. PUT   /deposit/depositions/{id}     → set metadata
      4. POST  /deposit/depositions/{id}/actions/publish → publish (assigns DOI)

    Failure at any step is non-fatal — we attempt to discard the draft
    so we don't leave orphan drafts cluttering the account.
    """
    if not is_enabled():
        return ZenodoUploadResult(
            success=False, deposition_id=None,
            doi=None, record_url=None, download_url=None,
            response_code=None, response_snippet="not configured",
        )

    base = _api_base()
    filename = f"cuban-insights-tearsheet-{d.isoformat()}.pdf"
    deposition_id: Optional[int] = None

    with httpx.Client(timeout=60) as client:
        # Step 1: create empty draft.
        try:
            r = client.post(
                f"{base}/deposit/depositions",
                headers=_auth_headers(),
                json={},
            )
        except Exception as exc:
            logger.warning("zenodo create-draft network error: %s", exc)
            return ZenodoUploadResult(
                success=False, deposition_id=None,
                doi=None, record_url=None, download_url=None,
                response_code=None,
                response_snippet=f"create-draft network: {exc}"[:500],
            )

        if r.status_code >= 400:
            logger.warning("zenodo create-draft %d: %s", r.status_code, r.text[:300])
            return ZenodoUploadResult(
                success=False, deposition_id=None,
                doi=None, record_url=None, download_url=None,
                response_code=r.status_code,
                response_snippet=r.text[:500],
            )

        draft = r.json()
        deposition_id = int(draft["id"])
        bucket_url = draft["links"]["bucket"]
        record_url = draft["links"].get("html")

        # Step 2: stream the PDF into the deposition's bucket. The bucket
        # endpoint needs the raw bytes as the request body — NOT a multipart
        # form like the older /files endpoint.
        try:
            r = client.put(
                f"{bucket_url}/{filename}",
                headers={
                    "Authorization": f"Bearer {settings.zenodo_access_token}",
                    "Content-Type": "application/octet-stream",
                },
                content=pdf_bytes,
            )
        except Exception as exc:
            _discard_draft(client, base, deposition_id)
            logger.warning("zenodo upload-bytes network error: %s", exc)
            return ZenodoUploadResult(
                success=False, deposition_id=deposition_id,
                doi=None, record_url=record_url, download_url=None,
                response_code=None,
                response_snippet=f"upload-bytes network: {exc}"[:500],
            )

        if r.status_code >= 400:
            _discard_draft(client, base, deposition_id)
            logger.warning(
                "zenodo upload-bytes %d for deposition %d: %s",
                r.status_code, deposition_id, r.text[:300],
            )
            return ZenodoUploadResult(
                success=False, deposition_id=deposition_id,
                doi=None, record_url=record_url, download_url=None,
                response_code=r.status_code,
                response_snippet=r.text[:500],
            )

        # Step 3: attach metadata.
        meta = _build_metadata(d)
        try:
            r = client.put(
                f"{base}/deposit/depositions/{deposition_id}",
                headers=_auth_headers(),
                json={"metadata": meta},
            )
        except Exception as exc:
            _discard_draft(client, base, deposition_id)
            logger.warning("zenodo set-metadata network error: %s", exc)
            return ZenodoUploadResult(
                success=False, deposition_id=deposition_id,
                doi=None, record_url=record_url, download_url=None,
                response_code=None,
                response_snippet=f"set-metadata network: {exc}"[:500],
            )

        if r.status_code >= 400:
            _discard_draft(client, base, deposition_id)
            logger.warning(
                "zenodo set-metadata %d for %d: %s",
                r.status_code, deposition_id, r.text[:300],
            )
            return ZenodoUploadResult(
                success=False, deposition_id=deposition_id,
                doi=None, record_url=record_url, download_url=None,
                response_code=r.status_code,
                response_snippet=r.text[:500],
            )

        # Step 4: publish. After this the record is public and gets its
        # DOI minted; further edits require creating a new version.
        try:
            r = client.post(
                f"{base}/deposit/depositions/{deposition_id}/actions/publish",
                headers=_auth_headers(),
            )
        except Exception as exc:
            # Don't discard here — the metadata + file are uploaded; user
            # can manually publish from the Zenodo UI if the network blip
            # was just at publish time.
            logger.warning("zenodo publish network error: %s", exc)
            return ZenodoUploadResult(
                success=False, deposition_id=deposition_id,
                doi=None, record_url=record_url, download_url=None,
                response_code=None,
                response_snippet=f"publish network: {exc}"[:500],
            )

        if r.status_code >= 400:
            logger.warning(
                "zenodo publish %d for %d: %s",
                r.status_code, deposition_id, r.text[:300],
            )
            return ZenodoUploadResult(
                success=False, deposition_id=deposition_id,
                doi=None, record_url=record_url, download_url=None,
                response_code=r.status_code,
                response_snippet=r.text[:500],
            )

        published = r.json()
        doi = published.get("doi") or (published.get("metadata") or {}).get("doi")
        record_url = (
            (published.get("links") or {}).get("record_html")
            or (published.get("links") or {}).get("html")
            or record_url
        )
        download_url = None
        files = published.get("files") or []
        if files:
            download_url = (files[0].get("links") or {}).get("self") or (
                files[0].get("links") or {}
            ).get("download")

        logger.info(
            "zenodo published: deposition=%s doi=%s url=%s",
            deposition_id, doi, record_url,
        )
        return ZenodoUploadResult(
            success=True, deposition_id=deposition_id,
            doi=doi, record_url=record_url, download_url=download_url,
            response_code=r.status_code,
            response_snippet=f"published doi={doi}",
        )


def _discard_draft(client: httpx.Client, base: str, deposition_id: int) -> None:
    """Best-effort cleanup of an unfinished draft so failed runs don't
    leave orphan drafts in the Zenodo account."""
    try:
        client.delete(
            f"{base}/deposit/depositions/{deposition_id}",
            headers=_auth_headers(),
        )
    except Exception as exc:
        logger.debug("zenodo discard-draft cleanup failed (non-fatal): %s", exc)
