"""
OSF Preprints distribution channel.

Each daily Investor Tearsheet PDF is uploaded as a child file under a
single OSF "project" (the parent node, configured via OSF_PROJECT_NODE_ID),
then registered as a public preprint on the configured provider (default
"osf"). OSF Preprints IS indexed by Google Scholar — that's the primary
reason this channel exists alongside Internet Archive (which goes to
Google Search but not Scholar) and Zenodo (Google Search + Dataset
Search but not Scholar).

The three OSF subsystems involved are:
  - osf.io/api/v2          → JSON:API for nodes / preprints / metadata
  - files.osf.io/v1        → WaterButler binary file storage
  - osf.io/preprints/...   → public preprint pages (where Scholar crawls)

Authentication uses a Personal Access Token from
https://osf.io/settings/tokens/ with scope `osf.full_write`.

Reference:
  - https://developer.osf.io/
  - https://waterbutler.readthedocs.io/

Like all distribution modules, this one is deliberately thin — it
accepts a PDF (bytes) + a date and returns a typed result. Cooldown,
deduplication, and time-gating live in the runner.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


_OSF_API = "https://api.osf.io/v2"
_WATERBUTLER = "https://files.osf.io/v1"


@dataclass
class OSFUploadResult:
    success: bool
    file_guid: Optional[str]
    preprint_id: Optional[str]
    record_url: Optional[str]
    download_url: Optional[str]
    response_code: Optional[int]
    response_snippet: str


def is_enabled() -> bool:
    """True iff both an access token AND a parent project node are
    configured. The parent node is required because every preprint must
    point at a primary file that lives somewhere — we use one persistent
    project as the holding container for every daily file."""
    return bool(
        (settings.osf_access_token or "").strip()
        and (settings.osf_project_node_id or "").strip()
    )


def _bearer() -> dict:
    return {"Authorization": f"Bearer {settings.osf_access_token}"}


def _filename_for(d: date) -> str:
    return f"cuban-insights-tearsheet-{d.isoformat()}.pdf"


def _description(d: date) -> str:
    nice_date = d.strftime("%B %d, %Y")
    return (
        f"One-page research note for international investors covering "
        f"Cuba on {nice_date}. Includes the elTOQUE TRMI informal CUP/USD "
        f"rate vs the BCC official rate (with spread), OFAC SDN Cuba "
        f"program designations and Cuba Restricted List updates, "
        f"Helms-Burton Title III lawsuits and settlements, MIPYME policy "
        f"moves and Mariel ZED approvals, the US State Department "
        f"travel-advisory level for Cuba, and upcoming OFAC general-license "
        f"renewals plus ANPP / Council of State calendar items in the next "
        f"14 days. Sources: elTOQUE (live scrape), BCC, OFAC SDN, US State "
        f"Department, Cuban Gaceta Oficial, ANPP, Granma/Cubadebate "
        f"corpus. Full daily briefing and methodology at "
        f"https://cubaninsights.com."
    )


def upload_tearsheet(pdf_bytes: bytes, d: date) -> OSFUploadResult:
    """Upload + publish a single tearsheet PDF as an OSF preprint.

    Three-step flow:
      1. PUT  files.osf.io/v1/resources/{node}/providers/osfstorage/?name=…
              Upload the raw PDF bytes via WaterButler. Returns a payload
              with the new file's `attributes.path` and a `guid`.
      2. POST api.osf.io/v2/preprints/   Create a preprint linked to the
              target provider, the parent node, and the just-uploaded
              primary file. JSON:API requires the `data.relationships`
              shape spelled out below.
      3. POST or PATCH the preprint to set subjects + license, then flip
              `is_published` to true.

    OSF's API throttles aggressively on writes from a fresh token, so we
    use a single httpx.Client for connection reuse and let the runner
    handle retry/cooldown semantics rather than blasting from this layer.
    """
    if not is_enabled():
        return OSFUploadResult(
            success=False, file_guid=None, preprint_id=None,
            record_url=None, download_url=None,
            response_code=None, response_snippet="not configured",
        )

    node_id = settings.osf_project_node_id.strip()
    provider = (settings.osf_preprint_provider or "osf").strip()
    subject_id = (settings.osf_subject_id or "").strip()
    license_name = (settings.osf_license_name or "").strip()
    filename = _filename_for(d)

    with httpx.Client(timeout=120) as client:
        # ── Step 1: WaterButler upload ────────────────────────────────
        wb_url = (
            f"{_WATERBUTLER}/resources/{node_id}/providers/osfstorage/"
            f"?kind=file&name={filename}"
        )
        try:
            r = client.put(
                wb_url,
                headers={
                    **_bearer(),
                    "Content-Type": "application/octet-stream",
                },
                content=pdf_bytes,
            )
        except Exception as exc:
            logger.warning("osf waterbutler network error: %s", exc)
            return OSFUploadResult(
                success=False, file_guid=None, preprint_id=None,
                record_url=None, download_url=None,
                response_code=None,
                response_snippet=f"waterbutler network: {exc}"[:500],
            )

        # 409 = file already exists at that name. WaterButler doesn't
        # auto-version unless we set ?conflict=replace; for daily
        # idempotency that's exactly what we want, so retry once with
        # the replace flag.
        if r.status_code == 409:
            try:
                r = client.put(
                    wb_url + "&conflict=replace",
                    headers={
                        **_bearer(),
                        "Content-Type": "application/octet-stream",
                    },
                    content=pdf_bytes,
                )
            except Exception as exc:
                logger.warning("osf waterbutler replace network error: %s", exc)
                return OSFUploadResult(
                    success=False, file_guid=None, preprint_id=None,
                    record_url=None, download_url=None,
                    response_code=None,
                    response_snippet=f"wb replace network: {exc}"[:500],
                )

        if r.status_code >= 400:
            logger.warning("osf waterbutler %d: %s", r.status_code, r.text[:300])
            return OSFUploadResult(
                success=False, file_guid=None, preprint_id=None,
                record_url=None, download_url=None,
                response_code=r.status_code,
                response_snippet=r.text[:500],
            )

        wb_payload = r.json()
        # WaterButler returns either {"data": {...}} or the attributes
        # at root depending on version; normalise.
        attrs = (wb_payload.get("data") or {}).get("attributes") or wb_payload.get(
            "attributes"
        ) or {}
        file_guid = attrs.get("guid") or (
            (wb_payload.get("data") or {}).get("id")
        )

        if not file_guid:
            # No GUID surfaced on this WaterButler response — fall back to
            # asking the OSF API for the file by path.
            file_path = attrs.get("path") or (
                (wb_payload.get("data") or {}).get("attributes") or {}
            ).get("path")
            file_guid = _resolve_file_guid(client, node_id, file_path)

        if not file_guid:
            logger.warning(
                "osf upload succeeded but no file guid returned: %s",
                str(wb_payload)[:300],
            )
            return OSFUploadResult(
                success=False, file_guid=None, preprint_id=None,
                record_url=None, download_url=None,
                response_code=r.status_code,
                response_snippet="upload ok but no file guid",
            )

        # ── Step 2: Create preprint draft ────────────────────────────
        body: dict = {
            "data": {
                "type": "preprints",
                "attributes": {
                    "title": (
                        f"Cuban Insights — Daily Cuba Investor "
                        f"Tearsheet — {d.strftime('%B %d, %Y')}"
                    ),
                    "description": _description(d),
                    "tags": [
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
                    "original_publication_date": d.isoformat(),
                },
                "relationships": {
                    "provider": {
                        "data": {"type": "preprint_providers", "id": provider},
                    },
                    "primary_file": {
                        "data": {"type": "primary_files", "id": file_guid},
                    },
                },
            }
        }
        try:
            r = client.post(
                f"{_OSF_API}/preprints/",
                headers={
                    **_bearer(),
                    "Content-Type": "application/vnd.api+json",
                    "Accept": "application/vnd.api+json",
                },
                json=body,
            )
        except Exception as exc:
            logger.warning("osf create-preprint network error: %s", exc)
            return OSFUploadResult(
                success=False, file_guid=file_guid, preprint_id=None,
                record_url=None, download_url=None,
                response_code=None,
                response_snippet=f"create-preprint network: {exc}"[:500],
            )

        if r.status_code >= 400:
            logger.warning("osf create-preprint %d: %s", r.status_code, r.text[:300])
            return OSFUploadResult(
                success=False, file_guid=file_guid, preprint_id=None,
                record_url=None, download_url=None,
                response_code=r.status_code,
                response_snippet=r.text[:500],
            )

        preprint = (r.json().get("data") or {})
        preprint_id = preprint.get("id")
        record_url = (preprint.get("links") or {}).get("html") or (
            preprint.get("links") or {}
        ).get("self")

        if not preprint_id:
            return OSFUploadResult(
                success=False, file_guid=file_guid, preprint_id=None,
                record_url=record_url, download_url=None,
                response_code=r.status_code,
                response_snippet="preprint created but no id returned",
            )

        # ── Step 3: Subjects + license + publish ─────────────────────
        # Subjects is a doubly-nested array per OSF's JSON:API quirk:
        # `[[ {"type":"taxonomies","id":"…"} ]]` (one inner array per
        # discipline path, each inner array is a list of taxonomy nodes
        # along the path; for a single leaf node a single-element inner
        # array is fine).
        patch_attrs: dict = {"is_published": True}
        relationships: dict = {}
        if subject_id:
            patch_attrs["subjects"] = [[{"type": "taxonomies", "id": subject_id}]]
        # License relationship is set via attribute name "license_name"
        # if the provider supports it; the safest cross-provider approach
        # is to PATCH `license_name` and let the OSF API resolve to the
        # provider's license whitelist.
        if license_name:
            patch_attrs["license_record"] = {
                "year": str(d.year),
                "copyright_holders": ["Cuban Insights"],
            }

        patch_body = {
            "data": {
                "type": "preprints",
                "id": preprint_id,
                "attributes": patch_attrs,
            }
        }
        if relationships:
            patch_body["data"]["relationships"] = relationships

        try:
            r = client.patch(
                f"{_OSF_API}/preprints/{preprint_id}/",
                headers={
                    **_bearer(),
                    "Content-Type": "application/vnd.api+json",
                    "Accept": "application/vnd.api+json",
                },
                json=patch_body,
            )
        except Exception as exc:
            logger.warning("osf publish-patch network error: %s", exc)
            return OSFUploadResult(
                success=False, file_guid=file_guid, preprint_id=preprint_id,
                record_url=record_url, download_url=None,
                response_code=None,
                response_snippet=f"publish-patch network: {exc}"[:500],
            )

        if r.status_code >= 400:
            logger.warning("osf publish-patch %d: %s", r.status_code, r.text[:300])
            # Don't return error if the preprint was created — at minimum
            # the file + draft preprint exist and can be published manually.
            return OSFUploadResult(
                success=False, file_guid=file_guid, preprint_id=preprint_id,
                record_url=record_url, download_url=None,
                response_code=r.status_code,
                response_snippet=(
                    f"draft created but publish-patch failed: {r.text[:300]}"
                ),
            )

        published = (r.json().get("data") or {})
        record_url = (
            (published.get("links") or {}).get("html")
            or f"https://osf.io/preprints/{provider}/{preprint_id}"
        )
        download_url = (
            f"https://files.osf.io/v1/resources/{node_id}/providers/"
            f"osfstorage/{file_guid}?download=true"
        )

        logger.info(
            "osf preprint published: id=%s file=%s url=%s",
            preprint_id, file_guid, record_url,
        )
        return OSFUploadResult(
            success=True, file_guid=file_guid, preprint_id=preprint_id,
            record_url=record_url, download_url=download_url,
            response_code=r.status_code,
            response_snippet=f"published preprint={preprint_id}",
        )


def _resolve_file_guid(
    client: httpx.Client, node_id: str, file_path: Optional[str]
) -> Optional[str]:
    """Fallback when WaterButler doesn't return a GUID directly: list the
    parent node's osfstorage files and find the matching path.

    OSF's API requires a GUID (5-char shortlink) to attach a file as a
    preprint's `primary_file`, not the WaterButler internal path."""
    if not file_path:
        return None
    try:
        r = client.get(
            f"{_OSF_API}/nodes/{node_id}/files/osfstorage/",
            headers={**_bearer(), "Accept": "application/vnd.api+json"},
            params={"page[size]": 100, "sort": "-date_modified"},
        )
        if r.status_code >= 400:
            return None
        for f in (r.json().get("data") or []):
            attrs = f.get("attributes") or {}
            if attrs.get("path") == file_path or attrs.get("name") in file_path:
                return f.get("id") or attrs.get("guid")
    except Exception as exc:
        logger.debug("osf file-guid resolve failed: %s", exc)
    return None
