#!/usr/bin/env python3
"""
Smoke test for the Google Indexing API setup.

Reads the service-account JSON from one of:
  --key-file PATH                (CLI arg, highest priority)
  GOOGLE_INDEXING_SA_JSON        (env var, full JSON contents)
  GOOGLE_INDEXING_SA_FILE        (env var, path to JSON file)

Then mints an access token and POSTs a single URL_UPDATED notification
for the URL passed via --url (default: https://caracasresearch.com/).

Exit codes:
    0  success
    1  config / auth problem
    2  API call failed (prints status + body)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

try:
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request as GoogleAuthRequest
except ImportError:
    print("ERROR: google-auth not installed. Run: pip install google-auth", file=sys.stderr)
    sys.exit(1)


SCOPES = ["https://www.googleapis.com/auth/indexing"]
INDEXING_ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"


def load_credentials_dict(key_file: str | None) -> dict:
    if key_file:
        path = Path(key_file).expanduser()
        if not path.exists():
            print(f"ERROR: --key-file does not exist: {path}", file=sys.stderr)
            sys.exit(1)
        return json.loads(path.read_text())

    raw = os.environ.get("GOOGLE_INDEXING_SA_JSON")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"ERROR: GOOGLE_INDEXING_SA_JSON is not valid JSON: {exc}", file=sys.stderr)
            sys.exit(1)

    file_path = os.environ.get("GOOGLE_INDEXING_SA_FILE")
    if file_path:
        path = Path(file_path).expanduser()
        if not path.exists():
            print(f"ERROR: GOOGLE_INDEXING_SA_FILE does not exist: {path}", file=sys.stderr)
            sys.exit(1)
        return json.loads(path.read_text())

    print(
        "ERROR: no credentials provided. Pass --key-file PATH, "
        "or set GOOGLE_INDEXING_SA_JSON / GOOGLE_INDEXING_SA_FILE.",
        file=sys.stderr,
    )
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key-file", help="Path to the service-account JSON key file")
    parser.add_argument(
        "--url",
        default="https://caracasresearch.com/",
        help="URL to send a URL_UPDATED notification for",
    )
    parser.add_argument(
        "--type",
        default="URL_UPDATED",
        choices=["URL_UPDATED", "URL_DELETED"],
    )
    args = parser.parse_args()

    creds_info = load_credentials_dict(args.key_file)

    print(f"Service account: {creds_info.get('client_email')}")
    print(f"Project ID:      {creds_info.get('project_id')}")
    print(f"Target URL:      {args.url}")
    print(f"Notification:    {args.type}")
    print()

    try:
        creds = service_account.Credentials.from_service_account_info(
            creds_info, scopes=SCOPES
        )
        creds.refresh(GoogleAuthRequest())
    except Exception as exc:
        print(f"ERROR minting access token: {exc}", file=sys.stderr)
        sys.exit(1)

    print("Access token obtained, calling Indexing API...")

    try:
        resp = httpx.post(
            INDEXING_ENDPOINT,
            headers={
                "Authorization": f"Bearer {creds.token}",
                "Content-Type": "application/json",
            },
            json={"url": args.url, "type": args.type},
            timeout=15,
        )
    except Exception as exc:
        print(f"ERROR calling Indexing API: {exc}", file=sys.stderr)
        sys.exit(2)

    print(f"HTTP {resp.status_code}")
    body = resp.text
    try:
        body_json = resp.json()
        print(json.dumps(body_json, indent=2))
    except Exception:
        print(body)

    if resp.status_code == 200:
        print("\nSUCCESS — Google accepted the notification.")
        sys.exit(0)

    if resp.status_code == 403:
        print(
            "\nFAILED with 403 — most common causes:\n"
            "  1. Service account is not added as Owner of the Search Console property\n"
            "     (Editor permission is NOT enough — must be Owner).\n"
            "  2. Indexing API not enabled on the GCP project. Enable here:\n"
            "     https://console.cloud.google.com/apis/library/indexing.googleapis.com\n"
            "  3. Billing suspended on the GCP project (the Indexing API is free but\n"
            "     a billing-disabled project can still get blocked). Check at\n"
            "     https://console.cloud.google.com/billing\n"
            "  4. The URL's domain doesn't match the verified Search Console property.\n",
            file=sys.stderr,
        )

    if resp.status_code == 404:
        print(
            "\nFAILED with 404 — the Indexing API likely isn't enabled on this project.\n"
            "Enable it at: https://console.cloud.google.com/apis/library/indexing.googleapis.com",
            file=sys.stderr,
        )

    sys.exit(2)


if __name__ == "__main__":
    main()
