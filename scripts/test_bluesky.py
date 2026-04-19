"""
Manual Bluesky smoke test. Run from a Render shell or locally with the
BLUESKY_HANDLE / BLUESKY_APP_PASSWORD env vars set.

Posts a single test message that is clearly marked as a smoke test so
it can be deleted from the Bluesky profile after verification.

Usage:
    BLUESKY_HANDLE=foo.bsky.social BLUESKY_APP_PASSWORD='xxxx-xxxx-xxxx-xxxx' \
        python scripts/test_bluesky.py
"""

from __future__ import annotations

import sys
from datetime import datetime

from src.distribution import bluesky


def main() -> int:
    if not bluesky.is_enabled():
        print("ERROR: Bluesky not configured. Set BLUESKY_HANDLE and BLUESKY_APP_PASSWORD.")
        return 1

    client = bluesky.get_client()
    if client is None:
        print("ERROR: Failed to construct Bluesky client.")
        return 1

    test_url = "https://caracasresearch.com/"
    text = (
        f"Smoke test from caracasresearch.com pipeline @ "
        f"{datetime.utcnow().isoformat()}Z. "
        f"Will be deleted after verification.\n\n{test_url}"
    )

    print(f"Posting as @{client.handle} ...")
    result = client.post(text=text, link_url=test_url)

    if result.success:
        print(f"OK posted: {result.post_url}")
        print(f"   uri:    {result.post_uri}")
        return 0

    print(f"FAILED status={result.status_code}")
    print(f"   body: {result.response_snippet}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
