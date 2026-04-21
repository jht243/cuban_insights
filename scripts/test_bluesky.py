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

    test_url = "https://cubaninsights.com/"
    text = (
        f"Smoke test from cubaninsights.com pipeline @ "
        f"{datetime.utcnow().isoformat()}Z. Will be deleted after verification."
    )

    print(f"Posting as @{client.handle} ...")
    thumb = client.upload_image_from_url("https://cubaninsights.com/static/og-image.png?v=3")
    link_card = bluesky.LinkCard(
        uri=test_url,
        title="Cuban Insights",
        description="Daily Cuba investment, sanctions, and policy research.",
        thumb_blob=thumb,
    )
    result = client.post(text=text, link_card=link_card)

    if result.success:
        print(f"OK posted: {result.post_url}")
        print(f"   uri:    {result.post_uri}")
        return 0

    print(f"FAILED status={result.status_code}")
    print(f"   body: {result.response_snippet}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
