"""
Page renderer for the secondary site pages — blog posts, blog index,
pillar / sector / sanctions / sources / tools — all of which share a
slim Jinja2 base layout (templates/_base.html.j2) and need their own
SEO + JSON-LD blocks.

Kept separate from src/report_generator.py because the home report is
written to disk + Supabase Storage on a cron schedule, while these
pages are server-rendered on every request from live DB rows.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.config import settings


logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml", "j2"]),
)


def _link_people_filter(html: str) -> str:
    if not html:
        return html
    from src.data.people import link_people_in_html
    return link_people_in_html(html)


_env.filters["link_people"] = _link_people_filter

_BARE_IMG_RE = re.compile(r"<img(?![^>]*\bloading\s*=)", re.IGNORECASE)


def _lazy_images_filter(html: str) -> str:
    if not html:
        return html
    return _BARE_IMG_RE.sub('<img loading="lazy"', html)


_env.filters["lazy_images"] = _lazy_images_filter


def _base_url() -> str:
    return settings.site_url.rstrip("/")


def _iso(d: date | datetime | None) -> str:
    if d is None:
        return ""
    if isinstance(d, datetime):
        return d.replace(tzinfo=timezone.utc).isoformat()
    return datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc).isoformat()


_BRIEFING_SEO_OVERRIDES = {
    "cuba-implements-new-customs-decrees-affecting-import-export-procedures": {
        "title": "Cuba Customs Decrees 2026: Import and Export Rule Changes",
        "description": (
            "What Cuba's 2026 customs decrees mean for import and export "
            "procedures, documentation, compliance risk, logistics, and "
            "foreign companies moving goods through Cuban ports."
        ),
        "keywords": [
            "Cuba customs decrees 2026",
            "Cuba import export procedures",
            "Cuba customs rules",
            "Cuba trade compliance",
            "Cuba import regulations",
        ],
    },
    "us-cuba-diplomatic-talks-amid-rising-geopolitical-tensions": {
        "title": "U.S.-Cuba Talks 2026: Sanctions, Investment & Policy Risk",
        "description": (
            "How the latest U.S.-Cuba diplomatic talks reshape sanctions "
            "exposure, OFAC compliance risk, and foreign-investment outlook "
            "— key takeaways for businesses, travelers, and policy watchers."
        ),
        "keywords": [
            "US Cuba diplomatic meeting 2026",
            "US Cuba diplomatic talks",
            "US Cuba sanctions impact",
            "Cuba diplomacy 2026",
            "US Cuba relations",
            "Cuba investment risk",
            "OFAC Cuba compliance",
        ],
    },
    "cuba-develops-technology-to-refine-its-own-crude-oil": {
        "title": "Cuba Crude Oil Refining 2026: Investment & Sanctions Outlook",
        "description": (
            "Cuba is developing domestic crude-oil refining capacity — what "
            "it means for energy investors, sanctions compliance, and foreign "
            "companies eyeing Cuba's petroleum sector."
        ),
        "keywords": [
            "Cuba crude oil refining",
            "Cuba oil investment 2026",
            "Cuba petroleum sanctions",
            "Cuba energy sector",
            "Cuba oil refining technology",
            "Cuba foreign investment oil",
        ],
    },
}


def _briefing_seo_override(slug: str | None) -> dict | None:
    """Return a targeted search-facing override for known GSC opportunities."""
    slug = slug or ""
    for prefix, override in _BRIEFING_SEO_OVERRIDES.items():
        if slug.startswith(prefix):
            return override
    return None


def _briefing_display_title(post) -> str:
    override = _briefing_seo_override(getattr(post, "slug", ""))
    return (override.get("title") if override else None) or getattr(post, "title", "") or ""


def render_blog_post(post, *, related: list | None = None) -> str:
    """Render a single BlogPost row to HTML with full NewsArticle JSON-LD.

    Uses NewsArticle (not BlogPosting) so briefings are eligible for the
    Google News Top Stories carousel. NewsArticle is a strict subtype of
    Article that Google specifically scans for time-sensitive news content.
    """
    base = _base_url()
    canonical = f"{base}/briefing/{post.slug}"
    # Prefer the per-briefing OG card (rendered at creation time and
    # served from /og/briefing/<slug>.png). Fall back to the generic
    # site-wide tile for any briefing that hasn't been rendered yet.
    has_og_bytes = bool(getattr(post, "og_image_bytes", None))
    og_image = (
        f"{base}/og/briefing/{post.slug}.png"
        if has_og_bytes
        else f"{base}/static/og-image.png?v=3"
    )

    override = _briefing_seo_override(post.slug)

    keywords = post.keywords_json or []
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]
    if override and override.get("keywords"):
        keyword_seen = {str(k).lower() for k in keywords}
        for keyword in override["keywords"]:
            if keyword.lower() not in keyword_seen:
                keywords.append(keyword)
                keyword_seen.add(keyword.lower())

    seo_title = _briefing_display_title(post)
    seo_description = (override.get("description") if override else None) or post.summary or post.subtitle or ""

    seo = {
        "title": seo_title[:110],
        "description": seo_description[:300],
        "keywords": ", ".join(keywords) if keywords else "",
        "news_keywords": ", ".join(keywords[:10]) if keywords else "",
        "canonical": canonical,
        "site_name": settings.site_name,
        "site_url": base,
        "locale": settings.site_locale,
        "og_image": og_image,
        "og_type": "article",
        "published_iso": _iso(post.published_date),
        "modified_iso": _iso(post.updated_at or post.created_at or post.published_date),
        "section": (post.primary_sector or "Cuba investment").replace("_", " ").title(),
        "article_tags": keywords[:10],
    }

    breadcrumbs = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
            {"@type": "ListItem", "position": 2, "name": "Analysis", "item": f"{base}/briefing"},
            {"@type": "ListItem", "position": 3, "name": post.title, "item": canonical},
        ],
    }

    news_article = {
        "@type": "NewsArticle",
        "@id": f"{canonical}#article",
        "url": canonical,
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical, "name": seo_title},
        "headline": seo_title[:110],
        "description": seo_description[:300],
        "image": [og_image],
        "datePublished": _iso(post.published_date),
        "dateModified": _iso(post.updated_at or post.created_at or post.published_date),
        "wordCount": post.word_count or 0,
        "author": {"@type": "Organization", "name": settings.site_name, "url": f"{base}/"},
        "publisher": {
            "@type": "Organization",
            "name": settings.site_name,
            "url": f"{base}/",
            "logo": {"@type": "ImageObject", "url": og_image, "width": 1200, "height": 630},
        },
        "keywords": keywords,
        "articleSection": seo["section"],
        "inLanguage": "en-US",
        "isAccessibleForFree": True,
    }
    if post.canonical_source_url:
        news_article["citation"] = post.canonical_source_url

    jsonld = json.dumps(
        {"@context": "https://schema.org", "@graph": [breadcrumbs, news_article]},
        ensure_ascii=False,
    )

    takeaways: list[str] = []
    post_display_title = seo_title
    related_display = [
        {
            "post": r,
            "display_title": _briefing_display_title(r),
        }
        for r in (related or [])
    ]

    template = _env.get_template("blog_post.html.j2")
    return template.render(
        post=post,
        post_display_title=post_display_title,
        related=related_display,
        takeaways=takeaways,
        seo=seo,
        jsonld=jsonld,
        current_year=date.today().year,
    )


def render_blog_index(posts: Iterable) -> str:
    base = _base_url()
    canonical = f"{base}/briefing"

    posts_list = list(posts)
    post_cards = [
        {
            "post": p,
            "display_title": _briefing_display_title(p),
        }
        for p in posts_list
    ]

    seo = {
        "title": "Cuba investment, embargo & sanctions analysis — long-form briefings",
        "description": (
            "Long-form analysis of the US embargo (CACR), OFAC general licenses, "
            "Cuban Asamblea Nacional legislation, Gaceta Oficial decrees, "
            "Mariel ZEDM deal flow, and sector capital. Published twice daily."
        ),
        "keywords": "invest in Cuba, OFAC Cuba analysis, Cuba embargo, Helms-Burton, Mariel ZEDM, Havana investment briefing, Cuban sectors",
        "canonical": canonical,
        "site_name": settings.site_name,
        "site_url": base,
        "locale": settings.site_locale,
        "og_image": f"{base}/static/og-image.png?v=3",
        "og_type": "website",
        "published_iso": _iso(datetime.utcnow()),
        "modified_iso": _iso(datetime.utcnow()),
    }

    item_list = {
        "@type": "ItemList",
        "name": "Cuba investment briefings",
        "itemListOrder": "https://schema.org/ItemListOrderDescending",
        "numberOfItems": len(posts_list),
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": idx,
                "name": _briefing_display_title(p),
                "url": f"{base}/briefing/{p.slug}",
            }
            for idx, p in enumerate(posts_list[:50], start=1)
        ],
    }
    breadcrumbs = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
            {"@type": "ListItem", "position": 2, "name": "Analysis", "item": canonical},
        ],
    }
    jsonld = json.dumps(
        {"@context": "https://schema.org", "@graph": [breadcrumbs, item_list]},
        ensure_ascii=False,
    )

    template = _env.get_template("blog_index.html.j2")
    return template.render(
        posts=post_cards,
        seo=seo,
        jsonld=jsonld,
        current_year=date.today().year,
    )


def _sdn_actors_for_sector(sector_slug: str, *, limit: int = 10) -> list:
    """Best-effort list of OFAC SDN profiles relevant to a sector page.

    We use the program-to-sector mapping from cluster_topology to flip
    the relationship: for any sector that is the canonical sector for
    one or more OFAC programs, return the SDN profiles designated under
    those programs (capped at `limit`, prioritising individuals).

    Returns an empty list for sectors with no program mapping (e.g.
    /sectors/agriculture isn't bound to a Cuba-program EO), in
    which case the template skips the section. This means we only
    surface the cross-cluster section when it carries real signal.
    """
    from src.data.sdn_profiles import list_all_profiles
    from src.seo.cluster_topology import program_to_sector_links

    target_path = f"/sectors/{sector_slug}"
    relevant_programs = {
        prog for prog, link in program_to_sector_links().items()
        if link.path == target_path
    }
    if not relevant_programs:
        return []

    # Sort by bucket priority (individuals first — they're the searchable
    # name queries from GSC), then alphabetically.
    bucket_order = {"individuals": 0, "entities": 1, "vessels": 2, "aircraft": 3}
    candidates = [
        p for p in list_all_profiles()
        if (p.program or "").upper() in relevant_programs
    ]
    candidates.sort(key=lambda p: (bucket_order.get(p.bucket, 9), p.raw_name.upper()))
    return candidates[:limit]


def render_landing_page(page, *, recent_briefings: list | None = None) -> str:
    """Render a LandingPage row (pillar / sector / explainer) to HTML."""
    base = _base_url()
    canonical = f"{base}{page.canonical_path}"
    og_image = f"{base}/static/og-image.png?v=3"

    keywords = page.keywords_json or []
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]

    seo = {
        "title": (page.title or "")[:110],
        "description": (page.summary or page.subtitle or "")[:300],
        "keywords": ", ".join(keywords) if keywords else "",
        "canonical": canonical,
        "site_name": settings.site_name,
        "site_url": base,
        "locale": settings.site_locale,
        "og_image": og_image,
        "og_type": "article",
        "published_iso": _iso(page.created_at or page.last_generated_at),
        "modified_iso": _iso(page.last_generated_at or page.updated_at),
        "section": page.page_type.title(),
        "article_tags": keywords[:10],
    }

    schema_type = "WebPage"
    if page.page_type == "sector":
        schema_type = "CollectionPage"
    elif page.page_type == "pillar":
        schema_type = "Article"
    elif page.page_type == "explainer":
        schema_type = "Article"

    breadcrumbs_items = [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{base}/"},
    ]
    if page.page_type == "sector":
        breadcrumbs_items.append(
            {"@type": "ListItem", "position": 2, "name": "Invest in Cuba", "item": f"{base}/invest-in-cuba"}
        )
        breadcrumbs_items.append(
            {"@type": "ListItem", "position": 3, "name": page.title, "item": canonical}
        )
    else:
        breadcrumbs_items.append(
            {"@type": "ListItem", "position": 2, "name": page.title, "item": canonical}
        )

    breadcrumbs = {"@type": "BreadcrumbList", "itemListElement": breadcrumbs_items}

    main_obj = {
        "@type": schema_type,
        "@id": f"{canonical}#main",
        "url": canonical,
        "name": page.title,
        "headline": (page.title or "")[:110],
        "description": (page.summary or "")[:300],
        "image": [og_image],
        "inLanguage": "en-US",
        "datePublished": _iso(page.created_at or page.last_generated_at),
        "dateModified": _iso(page.last_generated_at or page.updated_at),
        "wordCount": page.word_count or 0,
        "author": {"@type": "Organization", "name": settings.site_name, "url": f"{base}/"},
        "publisher": {
            "@type": "Organization",
            "name": settings.site_name,
            "url": f"{base}/",
            "logo": {"@type": "ImageObject", "url": og_image, "width": 1200, "height": 630},
        },
        "keywords": keywords,
        "isAccessibleForFree": True,
    }

    jsonld = json.dumps(
        {"@context": "https://schema.org", "@graph": [breadcrumbs, main_obj]},
        ensure_ascii=False,
    )

    from src.seo.cluster_topology import build_cluster_ctx
    cluster_ctx = build_cluster_ctx(page.canonical_path)

    # For sector landing pages, surface a "Sanctioned actors in this
    # sector" section pulling profiles from the new SDN cluster. This
    # is the cross-cluster bridge from /sectors/<slug> back into the
    # sanctions cluster — the second half of the reciprocal link the
    # SDN profile pages already make to /sectors/<slug>.
    sector_sdn_actors: list = []
    if page.page_type == "sector":
        sector_slug = page.canonical_path.rsplit("/", 1)[-1]
        sector_sdn_actors = _sdn_actors_for_sector(sector_slug)

    template = _env.get_template("landing.html.j2")
    return template.render(
        page=page,
        recent_briefings=recent_briefings or [],
        sector_sdn_actors=sector_sdn_actors,
        cluster_ctx=cluster_ctx,
        seo=seo,
        jsonld=jsonld,
        current_year=date.today().year,
    )


def render_blog_feed_xml(posts: Iterable) -> str:
    """Atom 1.0 feed for the /briefing/feed.xml route."""
    from xml.sax.saxutils import escape as _x

    base = _base_url()
    posts_list = list(posts)
    updated_iso = _iso(posts_list[0].updated_at or posts_list[0].created_at) if posts_list else _iso(datetime.utcnow())

    parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    parts.append('<feed xmlns="http://www.w3.org/2005/Atom">')
    parts.append(f"<title>{_x(settings.site_name)} — Cuba investment analysis</title>")
    parts.append(f'<link href="{base}/briefing/feed.xml" rel="self" type="application/atom+xml"/>')
    parts.append(f'<link href="{base}/briefing" rel="alternate" type="text/html"/>')
    parts.append(f"<id>{base}/briefing</id>")
    parts.append(f"<updated>{updated_iso}</updated>")
    parts.append(
        "<subtitle>OFAC sanctions, US embargo (CACR), Cuban Asamblea Nacional "
        "legislation, Mariel ZEDM deal flow, and sector capital — "
        "twice-daily Cuba investment briefings.</subtitle>"
    )
    parts.append(
        "<author><name>{name}</name><uri>{base}/</uri></author>".format(
            name=_x(settings.site_name), base=base
        )
    )

    for p in posts_list[:50]:
        url = f"{base}/briefing/{p.slug}"
        parts.append("<entry>")
        parts.append(f"<title>{_x(_briefing_display_title(p))}</title>")
        parts.append(f'<link href="{url}"/>')
        parts.append(f"<id>{url}</id>")
        parts.append(f"<published>{_iso(p.published_date)}</published>")
        parts.append(f"<updated>{_iso(p.updated_at or p.created_at or p.published_date)}</updated>")
        if p.summary:
            parts.append(f"<summary>{_x(p.summary)}</summary>")
        if p.body_html:
            parts.append(
                f'<content type="html"><![CDATA[{p.body_html}]]></content>'
            )
        parts.append("</entry>")
    parts.append("</feed>")
    return "".join(parts)
