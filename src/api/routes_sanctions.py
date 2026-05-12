"""Sanctions feed endpoint — OFAC SDN and Federal Register entries."""

from __future__ import annotations

from flask import jsonify, request

from src.api import api_v1
from src.api.auth import require_api_key
from src.api.serializers import SanctionEntry
from src.models import ExternalArticleEntry, SessionLocal, SourceType, init_db


SANCTIONS_SOURCES = {SourceType.OFAC_SDN, SourceType.FEDERAL_REGISTER, SourceType.STATE_DEPT_CRL}


@api_v1.route("/sanctions/feed")
@require_api_key
def sanctions_feed():
    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(100, max(1, request.args.get("per_page", 25, type=int)))
    source_filter = request.args.get("source", "").strip() or None

    init_db()
    db = SessionLocal()
    try:
        q = db.query(ExternalArticleEntry).filter(
            ExternalArticleEntry.source.in_(SANCTIONS_SOURCES)
        )
        if source_filter:
            try:
                st = SourceType(source_filter)
                if st in SANCTIONS_SOURCES:
                    q = q.filter(ExternalArticleEntry.source == st)
            except ValueError:
                pass

        total = q.count()
        rows = (
            q.order_by(ExternalArticleEntry.published_date.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        data = []
        for r in rows:
            tier_val = r.source.value if hasattr(r.source, "value") else r.source
            data.append(SanctionEntry(
                id=r.id,
                source=tier_val,
                headline=r.headline,
                published_date=r.published_date,
                source_url=r.source_url,
                source_name=r.source_name,
                article_type=r.article_type,
                extra_metadata=r.extra_metadata,
            ).model_dump(mode="json"))

        return jsonify({
            "data": data,
            "page": page,
            "per_page": per_page,
            "total": total,
            "has_more": page * per_page < total,
        })
    finally:
        db.close()
