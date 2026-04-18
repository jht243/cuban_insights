"""
Outbound distribution layer.

Each submodule wraps one external channel (Google Indexing API, Bluesky,
Mastodon, Telegram, LinkedIn, Threads, Medium...) and exposes a single
function the runner can call with a list of URLs / a BlogPost. Every
attempt is recorded in the `distribution_logs` table for idempotency
and operational visibility.

The runner (src.distribution.runner) is invoked from run_daily.py as
Phase 5 after the report has been generated.
"""
