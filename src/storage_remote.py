"""
Supabase Storage helpers — used so the cron job and the web service (which
run in different Render containers) can share the generated report.html.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from src.config import settings

logger = logging.getLogger(__name__)

REPORT_OBJECT_KEY = "report.html"


def _supabase_base_url() -> Optional[str]:
    url = (settings.supabase_url or "").rstrip("/")
    return url or None


def supabase_storage_enabled() -> bool:
    """Write-side: needs both URL + service key (used by cron)."""
    return bool(_supabase_base_url() and settings.supabase_service_key)


def supabase_storage_read_enabled() -> bool:
    """Read-side: only needs URL (public bucket; used by web)."""
    return bool(_supabase_base_url())


def public_report_url() -> Optional[str]:
    base = _supabase_base_url()
    if not base:
        return None
    return f"{base}/storage/v1/object/public/{settings.supabase_report_bucket}/{REPORT_OBJECT_KEY}"


def upload_report_html(html: str) -> Optional[str]:
    """
    Upload the rendered report HTML to Supabase Storage.
    Returns the public URL on success, None if storage is not configured.
    Raises on hard failures.
    """
    if not supabase_storage_enabled():
        logger.info("Supabase Storage not configured; skipping remote upload")
        return None

    base = _supabase_base_url()
    bucket = settings.supabase_report_bucket
    upload_url = f"{base}/storage/v1/object/{bucket}/{REPORT_OBJECT_KEY}"

    headers = {
        "Authorization": f"Bearer {settings.supabase_service_key}",
        "Content-Type": "text/html; charset=utf-8",
        "x-upsert": "true",
        "cache-control": "max-age=60",
    }

    resp = httpx.post(upload_url, content=html.encode("utf-8"), headers=headers, timeout=30)
    if resp.status_code >= 400:
        logger.error("Supabase Storage upload failed %d: %s", resp.status_code, resp.text)
        resp.raise_for_status()

    public = public_report_url()
    logger.info("Uploaded report.html to Supabase Storage: %s", public)
    return public


def upload_object(
    object_key: str,
    body: bytes,
    *,
    content_type: str = "application/octet-stream",
    cache_control: str = "max-age=3600",
    bucket: Optional[str] = None,
) -> Optional[str]:
    """
    Generic Supabase Storage upload — used by the tearsheet PDF pipeline
    and any future binary asset that needs a stable public URL.

    Returns the public URL on success, None if storage is not configured.
    Raises on hard failures.
    """
    if not supabase_storage_enabled():
        logger.info("Supabase Storage not configured; skipping upload of %s", object_key)
        return None

    base = _supabase_base_url()
    target_bucket = bucket or settings.supabase_report_bucket
    upload_url = f"{base}/storage/v1/object/{target_bucket}/{object_key}"

    headers = {
        "Authorization": f"Bearer {settings.supabase_service_key}",
        "Content-Type": content_type,
        "x-upsert": "true",
        "cache-control": cache_control,
    }

    resp = httpx.post(upload_url, content=body, headers=headers, timeout=60)
    if resp.status_code >= 400:
        logger.error(
            "Supabase Storage upload failed %d for %s: %s",
            resp.status_code, object_key, resp.text[:300],
        )
        resp.raise_for_status()

    public = f"{base}/storage/v1/object/public/{target_bucket}/{object_key}"
    logger.info("Uploaded %s to Supabase Storage: %s (%d bytes)",
                object_key, public, len(body))
    return public


def public_object_url(object_key: str, bucket: Optional[str] = None) -> Optional[str]:
    """Build the public-bucket URL for an object key (does not check existence)."""
    base = _supabase_base_url()
    if not base:
        return None
    target_bucket = bucket or settings.supabase_report_bucket
    return f"{base}/storage/v1/object/public/{target_bucket}/{object_key}"


def download_object(object_key: str, bucket: Optional[str] = None) -> Optional[bytes]:
    """
    Fetch an arbitrary object from a public Supabase Storage bucket.
    Returns the raw bytes, or None if the object is missing / storage
    is not configured / the request failed.

    This is the read-side counterpart to ``upload_object`` and only
    needs ``SUPABASE_URL`` (no service key) — the bucket must be public.
    """
    url = public_object_url(object_key, bucket=bucket)
    if not url:
        return None
    try:
        resp = httpx.get(url, timeout=15)
    except httpx.HTTPError as exc:
        logger.warning("Supabase Storage GET failed for %s: %s", object_key, exc)
        return None
    if resp.status_code == 404:
        return None
    if resp.status_code >= 400:
        logger.warning(
            "Supabase Storage GET %s returned %d: %s",
            object_key, resp.status_code, resp.text[:200],
        )
        return None
    return resp.content


def list_object_keys(prefix: str, bucket: Optional[str] = None) -> list[str]:
    """
    List object keys under a folder-style prefix in Supabase Storage.

    Uses the storage list endpoint (POST .../object/list/<bucket>), which
    does require an Authorization header — we pass the service key when
    available, otherwise the anon-equivalent of the URL won't return
    results. On any failure, returns an empty list (caller should treat
    "no listing" as "nothing in storage").

    The prefix is treated as a folder path (e.g. ``state_dept_snapshots``),
    and returned keys are joined back with the prefix so callers can pass
    them straight to ``download_object``.
    """
    base = _supabase_base_url()
    if not base or not settings.supabase_service_key:
        return []
    target_bucket = bucket or settings.supabase_report_bucket
    list_url = f"{base}/storage/v1/object/list/{target_bucket}"
    headers = {
        "Authorization": f"Bearer {settings.supabase_service_key}",
        "apikey": settings.supabase_service_key,
        "Content-Type": "application/json",
    }
    folder = prefix.strip("/")
    body = {
        "prefix": folder,
        "limit": 1000,
        "offset": 0,
        "sortBy": {"column": "name", "order": "asc"},
    }
    try:
        resp = httpx.post(list_url, json=body, headers=headers, timeout=15)
    except httpx.HTTPError as exc:
        logger.warning("Supabase Storage LIST failed for %s: %s", folder, exc)
        return []
    if resp.status_code >= 400:
        logger.warning(
            "Supabase Storage LIST %s returned %d: %s",
            folder, resp.status_code, resp.text[:200],
        )
        return []
    try:
        items = resp.json()
    except ValueError:
        return []
    keys: list[str] = []
    for item in items or []:
        name = item.get("name")
        if not name:
            continue
        # The list endpoint returns names relative to the prefix, plus
        # "folder" entries with id=None. Skip the folders.
        if item.get("id") is None and not name.endswith(".json"):
            continue
        keys.append(f"{folder}/{name}" if folder else name)
    return keys


def fetch_report_html() -> Optional[str]:
    """
    Fetch the latest report.html from Supabase Storage.
    Returns the HTML string, or None if not available / not configured.
    """
    url = public_report_url()
    if not url:
        return None

    try:
        resp = httpx.get(url, timeout=15)
    except httpx.HTTPError as e:
        logger.warning("Failed to fetch report from Supabase Storage: %s", e)
        return None

    if resp.status_code == 404:
        return None
    if resp.status_code >= 400:
        logger.warning("Supabase Storage GET returned %d: %s", resp.status_code, resp.text[:200])
        return None
    return resp.text
