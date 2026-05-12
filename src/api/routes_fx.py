"""FX rate endpoints — latest informal CUP rates and historical series."""

from __future__ import annotations

from flask import jsonify, request

from src.api import api_v1
from src.api.auth import require_api_key
from src.api.serializers import FXRate, FXRateHistoryPoint
from src.models import ExternalArticleEntry, SessionLocal, SourceType, init_db


@api_v1.route("/fx/rates")
@require_api_key
def fx_latest():
    init_db()
    db = SessionLocal()
    try:
        row = (
            db.query(ExternalArticleEntry)
            .filter(ExternalArticleEntry.source == SourceType.ELTOQUE_RATE)
            .order_by(ExternalArticleEntry.published_date.desc())
            .first()
        )
        if row is None:
            return jsonify({"error": "No FX rate data available"}), 404

        meta = row.extra_metadata or {}
        return jsonify(FXRate(
            usd_cup=meta.get("usd"),
            eur_cup=meta.get("eur"),
            mlc_cup=meta.get("mlc"),
            usdt_cup=meta.get("usdt_trc20"),
            date=str(row.published_date) if row.published_date else None,
            attribution=meta.get(
                "attribution",
                "Tasa Representativa del Mercado Informal — elTOQUE (tasas.eltoque.com)",
            ),
        ).model_dump(mode="json"))
    finally:
        db.close()


@api_v1.route("/fx/rates/history")
@require_api_key
def fx_history():
    limit = min(365, max(1, request.args.get("limit", 30, type=int)))

    init_db()
    db = SessionLocal()
    try:
        rows = (
            db.query(ExternalArticleEntry)
            .filter(ExternalArticleEntry.source == SourceType.ELTOQUE_RATE)
            .order_by(ExternalArticleEntry.published_date.desc())
            .limit(limit)
            .all()
        )
        points = []
        for r in rows:
            meta = r.extra_metadata or {}
            points.append(FXRateHistoryPoint(
                date=str(r.published_date),
                usd_cup=meta.get("usd"),
                mlc_cup=meta.get("mlc"),
                usdt_cup=meta.get("usdt_trc20"),
            ).model_dump(mode="json"))
        return jsonify({"data": points, "count": len(points)})
    finally:
        db.close()
