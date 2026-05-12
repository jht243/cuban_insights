"""Briefing endpoints — latest, by slug, and paginated list."""

from __future__ import annotations

from flask import jsonify, request

from src.api import api_v1
from src.api.auth import require_api_key
from src.api.serializers import BriefingDetail, BriefingSummary
from src.config import settings
from src.models import BlogPost, SessionLocal, init_db


def _post_to_summary(p: BlogPost) -> dict:
    return BriefingSummary(
        slug=p.slug,
        title=p.title,
        subtitle=p.subtitle,
        summary=p.summary,
        primary_sector=p.primary_sector,
        sectors=p.sectors_json if isinstance(p.sectors_json, list) else None,
        published_date=p.published_date,
        word_count=p.word_count,
        reading_minutes=p.reading_minutes,
        url=f"{settings.site_url}/briefing/{p.slug}",
    ).model_dump(mode="json")


def _post_to_detail(p: BlogPost) -> dict:
    return BriefingDetail(
        slug=p.slug,
        title=p.title,
        subtitle=p.subtitle,
        summary=p.summary,
        primary_sector=p.primary_sector,
        sectors=p.sectors_json if isinstance(p.sectors_json, list) else None,
        published_date=p.published_date,
        word_count=p.word_count,
        reading_minutes=p.reading_minutes,
        url=f"{settings.site_url}/briefing/{p.slug}",
        body_html=p.body_html,
        keywords=p.keywords_json if isinstance(p.keywords_json, list) else None,
        canonical_source_url=p.canonical_source_url,
    ).model_dump(mode="json")


@api_v1.route("/briefings/latest")
@require_api_key
def briefings_latest():
    init_db()
    db = SessionLocal()
    try:
        post = (
            db.query(BlogPost)
            .order_by(BlogPost.published_date.desc(), BlogPost.id.desc())
            .first()
        )
        if post is None:
            return jsonify({"error": "No briefings available"}), 404
        return jsonify(_post_to_detail(post))
    finally:
        db.close()


@api_v1.route("/briefings/<slug>")
@require_api_key
def briefings_by_slug(slug: str):
    init_db()
    db = SessionLocal()
    try:
        post = db.query(BlogPost).filter(BlogPost.slug == slug).first()
        if post is None:
            return jsonify({"error": "Briefing not found"}), 404
        return jsonify(_post_to_detail(post))
    finally:
        db.close()


@api_v1.route("/briefings")
@require_api_key
def briefings_list():
    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(50, max(1, request.args.get("per_page", 20, type=int)))
    sector = request.args.get("sector", "").strip() or None

    init_db()
    db = SessionLocal()
    try:
        q = db.query(BlogPost)
        if sector:
            q = q.filter(BlogPost.primary_sector == sector)
        total = q.count()
        posts = (
            q.order_by(BlogPost.published_date.desc(), BlogPost.id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        return jsonify({
            "data": [_post_to_summary(p) for p in posts],
            "page": page,
            "per_page": per_page,
            "total": total,
            "has_more": page * per_page < total,
        })
    finally:
        db.close()
