"""
Investment Climate Tracker scoring framework.

This package replaces the historical hardcoded `_build_climate()` literal
in `src/report_generator.py` with a deterministic, weekly-refreshed
scorecard derived from data the daily pipeline already collects.

Architecture
------------
evidence.py   Pulls raw inputs out of the DB into an Evidence dataclass.
              Pure read; no scoring decisions.
rubric.py     Per-pillar scoring functions. Pure: (Evidence) -> (score,
              color, signals). All thresholds documented in one place.
snapshot.py   Quarter math + ClimateSnapshot upsert/read. Provides the
              prior-quarter baseline that produces real QoQ deltas.
subtitles.py  Deterministic templated "why" sentences from the same
              evidence, so the bar subtitles auto-refresh too.
runner.py     Orchestration entry point: run_weekly_climate_refresh().

The report generator's _build_climate() reads the latest snapshot and
falls back to a static literal if no snapshot exists yet (cold start).
"""

from src.climate.runner import run_weekly_climate_refresh

__all__ = ["run_weekly_climate_refresh"]
