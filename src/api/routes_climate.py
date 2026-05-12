"""Investment climate scorecard endpoint."""

from __future__ import annotations

from flask import jsonify

from src.api import api_v1
from src.api.auth import require_api_key
from src.api.serializers import ClimateScorecard
from src.models import ClimateSnapshot, SessionLocal, init_db


@api_v1.route("/climate")
@require_api_key
def climate_latest():
    init_db()
    db = SessionLocal()
    try:
        row = (
            db.query(ClimateSnapshot)
            .order_by(ClimateSnapshot.computed_at.desc())
            .first()
        )
        if row is None:
            return jsonify({"error": "No climate data available"}), 404

        return jsonify(ClimateScorecard(
            quarter_label=row.quarter_label,
            composite_score=row.composite_score,
            period_label=row.period_label,
            bars=row.bars_json,
            computed_at=row.computed_at,
        ).model_dump(mode="json"))
    finally:
        db.close()
