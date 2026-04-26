"""
Cuban Insights report generator: reads analyzed entries from the
database and renders the Jinja2 template into a static report.html
file. The output is the daily investor briefing published at
cubaninsights.com.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup, escape as html_escape

from src.config import settings
from src.models import (
    SessionLocal,
    ExternalArticleEntry,
    AssemblyNewsEntry,
    GazetteStatus,
    SourceType,
    init_db,
)

logger = logging.getLogger(__name__)


# Matches **bold** but not stray single asterisks. Non-greedy, no
# crossing newlines.
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)


def _render_takeaway(raw: str) -> Markup:
    """
    Convert the LLM-produced takeaway into safe HTML.

    The prompt asks the model to wrap the most important sentence in
    <strong> tags, but the model often reverts to markdown-style
    **bold**. Both are normalized to <strong>...</strong> here so the
    Jinja template can render them as actual bold text.

    Everything else is HTML-escaped, so this is safe even if the model
    returns unexpected characters.
    """
    if not raw:
        return Markup("")
    escaped = str(html_escape(raw))
    escaped = escaped.replace("&lt;strong&gt;", "<strong>").replace(
        "&lt;/strong&gt;", "</strong>"
    )
    escaped = _MD_BOLD_RE.sub(r"<strong>\1</strong>", escaped)
    return Markup(escaped)


SECTOR_OPTIONS = [
    {"value": "realestate", "label": "Real Estate"},
    {"value": "security", "label": "Safety & Security"},
    {"value": "economic", "label": "Economic Policy"},
    {"value": "fiscal", "label": "Tax & Fiscal"},
    {"value": "sanctions", "label": "Sanctions"},
    {"value": "diplomatic", "label": "US Relations"},
    {"value": "governance", "label": "Governance"},
    {"value": "legal", "label": "Legal & Rights"},
    {"value": "mining", "label": "Mining"},
    {"value": "energy", "label": "Energy & Oil"},
    {"value": "banking", "label": "Banking & Finance"},
]

STATUS_CSS_MAP = {
    "passed": "passed",
    "in_effect": "passed",
    "in_progress": "progress",
    "announced": "announced",
    "monitoring": "monitoring",
}

TRUST_CSS_MAP = {
    "official": ("trust-official", "Official"),
    "tier1": ("trust-tier1", "Verified Source"),
    "state": ("trust-state", "State Media"),
    "tier2": ("trust-tier2", "News Source"),
}

SOURCE_DISPLAY_MAP = {
    SourceType.FEDERAL_REGISTER: "Federal Register",
    SourceType.OFAC_SDN: "OFAC SDN List",
    SourceType.GDELT: None,
    SourceType.BCC_RATES: "BCC",
    SourceType.ELTOQUE_RATE: "elTOQUE TRMI",
    SourceType.TRAVEL_ADVISORY: "State Dept",
    SourceType.STATE_DEPT_CRL: "State Dept (Cuba Restricted List)",
    SourceType.STATE_DEPT_CPAL: "State Dept (Cuba Prohibited Accommodations)",
    SourceType.ASAMBLEA_NACIONAL_CU: "Asamblea Nacional del Poder Popular",
    SourceType.GACETA_OFICIAL_CU: "Gaceta Oficial de la República de Cuba",
    SourceType.MINREX: "MINREX",
    SourceType.ONEI: "ONEI",
    SourceType.PRESS_RSS: "Cuban Press",
    SourceType.ITA_TRADE: "International Trade Administration",
    SourceType.BCV_RATES: "BCC",
}


def generate_report(output_path: Path | None = None) -> Path:
    """
    Query the database for analyzed entries and render the report.
    Returns the path to the generated HTML file.
    """
    output_path = output_path or settings.output_dir / "report.html"
    init_db()
    db = SessionLocal()

    try:
        cutoff = date.today() - timedelta(days=settings.report_lookback_days)

        ext_articles = (
            db.query(ExternalArticleEntry)
            .filter(ExternalArticleEntry.status == GazetteStatus.ANALYZED)
            .filter(ExternalArticleEntry.published_date >= cutoff)
            .order_by(ExternalArticleEntry.published_date.desc())
            .all()
        )

        assembly_news = (
            db.query(AssemblyNewsEntry)
            .filter(AssemblyNewsEntry.status == GazetteStatus.ANALYZED)
            .filter(AssemblyNewsEntry.published_date >= cutoff)
            .order_by(AssemblyNewsEntry.published_date.desc())
            .all()
        )

        entries = _build_entries(ext_articles, assembly_news)
        _attach_blog_links(db, entries)
        ticker_items = _build_ticker(db)
        news_items = _build_news_sidebar(entries)
        calendar_events = _build_calendar(ext_articles, assembly_news)
        climate = _build_climate()
        generated_dt = datetime.utcnow()
        seo = _build_seo(entries, generated_dt)
        jsonld = _build_jsonld(entries, seo, generated_dt)

        template_dir = Path(__file__).parent.parent / "templates"
        env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=False,
        )
        template = env.get_template("report.html.j2")

        html = template.render(
            entries=entries,
            ticker_items=ticker_items,
            news_items=news_items,
            calendar_events=calendar_events,
            climate=climate,
            all_sectors=SECTOR_OPTIONS,
            current_year=date.today().year,
            generated_at=generated_dt.strftime("%Y-%m-%d %H:%M UTC"),
            tearsheet_date_label=(
                f"{generated_dt.month}/{generated_dt.day}/{generated_dt.year % 100:02d}"
            ),
            seo=seo,
            jsonld=jsonld,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
        logger.info("Report generated: %s (%d entries)", output_path, len(entries))

        try:
            from src.storage_remote import upload_report_html, supabase_storage_enabled
            if supabase_storage_enabled():
                upload_report_html(html)
        except Exception as e:
            logger.error("Failed to upload report to Supabase Storage: %s", e)

        return output_path

    finally:
        db.close()


def _build_entries(ext_articles, assembly_news) -> list[dict]:
    """Convert DB entries into template-ready dicts, filtered by relevance."""
    entries = []
    min_score = settings.analysis_min_relevance

    all_items = []
    for a in ext_articles:
        all_items.append(("external", a))
    for n in assembly_news:
        all_items.append(("assembly", n))

    for item_type, item in all_items:
        analysis = item.analysis_json or {}
        relevance = analysis.get("relevance_score", 0)
        if relevance < min_score:
            continue
        # Federal Register matches use a broad full-text "cuba" query
        # against OFAC docs and can pick up rules where Cuba is just
        # one of ~20 sanctioned jurisdictions in a generic compliance
        # screening list. We already drop those at scrape time when
        # the title/abstract have no Cuba terms, but as a safety net
        # we also require Federal Register entries to clear a higher
        # relevance bar before they make the daily briefing.
        source = getattr(item, "source", None)
        source_value = getattr(source, "value", source)
        if source_value == "federal_register" and relevance < 7:
            continue

        sectors = analysis.get("sectors", [])
        sentiment = analysis.get("sentiment", "mixed")
        status = analysis.get("status", "monitoring")
        status_label = analysis.get("status_label", status.replace("_", " ").title())
        category_label = analysis.get("category_label", "General")
        headline = analysis.get("headline_short", item.headline[:80])
        takeaway_raw = analysis.get("takeaway", "")
        takeaway = _render_takeaway(takeaway_raw)
        is_breaking = analysis.get("is_breaking", False)
        source_trust = analysis.get("source_trust", "tier2")

        status_key = status.lower().replace(" ", "_").replace("—", "").replace("-", "_").strip()
        for k in STATUS_CSS_MAP:
            if k in status_key:
                status_key = k
                break
        status_css = STATUS_CSS_MAP.get(status_key, "monitoring")

        trust_css, trust_label_default = TRUST_CSS_MAP.get(source_trust, ("trust-tier2", "News Source"))

        if item_type == "external":
            source_display = item.source_name or "Source"
            if item.source == SourceType.FEDERAL_REGISTER:
                source_display = "Federal Register"
                trust_label_default = "Official — Federal Register"
            elif item.source == SourceType.TRAVEL_ADVISORY:
                source_display = "State Dept"
                trust_label_default = "Official — US State Department"
            elif item.source == SourceType.GDELT:
                domain = (item.extra_metadata or {}).get("domain", "")
                source_display = domain or item.source_name or "International Press"
                trust_label_default = f"Via GDELT — {source_display}"
        else:
            source_display = "Asamblea Nacional del Poder Popular"
            trust_label_default = "State Media"

        is_new = (date.today() - item.published_date).days <= 3

        safe_id = re.sub(r"[^a-z0-9]", "-", headline.lower())[:40].strip("-")
        slug_base = re.sub(r"[^a-z0-9]+", "-", headline.lower()).strip("-")[:80] or "briefing"
        slug = f"{slug_base}-{item.published_date.strftime('%Y%m%d')}-{item.id}"

        published_iso = datetime.combine(
            item.published_date, datetime.min.time(), tzinfo=timezone.utc
        ).isoformat()

        entries.append({
            "id": safe_id,
            "slug": slug,
            "db_id": item.id,
            "item_type": item_type,
            "headline": item.headline,
            "headline_short": headline,
            "date_display": item.published_date.strftime("%B %d, %Y"),
            "published_date": item.published_date,
            "published_iso": published_iso,
            "modified_iso": published_iso,
            "source_url": item.source_url,
            "source_display": source_display,
            "sectors": sectors,
            "sectors_str": " ".join(sectors),
            "sentiment": sentiment,
            "status_class": status_css,
            "status_label": status_label,
            "category_label": category_label,
            "takeaway": takeaway,
            "takeaway_plain": takeaway_raw.replace("**", "").replace("<strong>", "").replace("</strong>", ""),
            "is_new": is_new,
            "is_breaking": is_breaking,
            "trust_class": trust_css,
            "trust_label": trust_label_default,
            "body_text": item.body_text if item.body_text and len(item.body_text) > 100 else None,
            "relevance": relevance,
        })

    entries.sort(key=lambda e: e["published_date"], reverse=True)
    entries = _deduplicate_entries(entries)
    return entries


# Words that don't help disambiguate topics (Spanish + English).
_TOPIC_STOPWORDS = frozenset({
    # English
    "the", "and", "for", "with", "from", "that", "this", "into", "over",
    "have", "has", "are", "was", "were", "will", "new", "more", "than",
    "but", "not", "may", "can", "now", "all", "how", "why", "when",
    "what", "which", "who", "you", "your", "his", "her", "its", "their",
    "cuba", "cuban", "cuba's", "law", "laws", "bill",
    # Spanish
    "para", "con", "por", "del", "los", "las", "una", "uno", "que",
    "como", "esta", "este", "esto", "esos", "esas", "muy", "ser",
    "cubano", "cubana", "cubanos", "cubanas",
    "nacional", "nacionales", "asamblea", "diputado", "diputada",
    "diputados", "diputadas", "presidente", "presidenta",
    "comision", "comision", "permanente",
})

# Investor-relevant topic clusters. Any entry whose normalized text
# contains one of these keywords is tagged with the topic. Entries that
# share a topic AND fall within DEDUP_WINDOW_DAYS of each other are
# collapsed to a single entry (the highest-relevance one). This is the
# big hammer that catches "12 different ANPP deputies each made a
# statement about the Foreign Investment Law this week" -> one entry.
# Order matters: the first tag whose keyword appears in the entry text
# wins. Put NARROW, SPECIFIC topics first; broad ones last. This prevents
# e.g. "foreign_investment" body text from getting mis-tagged as
# "mipymes_decree" just because the article mentions MIPYMES in passing.
_TOPIC_TAGS: list[tuple[str, tuple[str, ...]]] = [
    # Specific named Cuban laws (highest priority)
    ("foreign_investment_law", ("ley de inversion extranjera", "ley 118", "foreign investment law", "ley no. 118")),
    ("mipymes_decree", ("decreto-ley 46", "decreto ley 46", "decreto ley de las mipymes", "mipymes decree", "decreto ley sobre las mipymes")),
    ("price_control_resolution", ("resolucion sobre precios", "topes de precios", "price control resolution", "precios maximos")),
    ("tarea_ordenamiento", ("tarea ordenamiento", "monetary unification", "ordenamiento monetario", "unificacion monetaria")),
    ("mariel_zed_regulations", ("zona especial de desarrollo mariel", "mariel special development zone", "zed mariel", "decreto-ley zed")),
    ("constitution_2019", ("constitucion de 2019", "2019 constitution", "constitutional reform 2019", "reforma constitucional")),
    # Specific OFAC/sanctions actions on Cuba
    ("ofac_general_license", (
        "general license 1",
        "general license 5",
        "general license b",
        "general license n",
        "general license under cacr",
        "licencia general bajo cacr",
        "cacr general license",
    )),
    ("cuba_restricted_list", ("cuba restricted list", "lista restringida de cuba", "section 515.209", "§515.209")),
    ("cpal_update", ("cuba prohibited accommodations list", "lista de alojamientos prohibidos", "cpal update", "section 515.210")),
    ("ofac_designations", ("notice of ofac sanctions actions", "ofac sdn list update", "ofac sanctions actions", "magnitsky designations")),
    ("helms_burton_title_iii", ("helms-burton title iii", "title iii lawsuit", "libertad act title iii", "trafficking in confiscated property")),
    ("travel_advisory", ("travel advisory", "do not travel advisory", "reconsider travel", "advisory level")),
    # Recurring Cuban anti-embargo mobilizations (one campaign, many
    # headlines). MUST come BEFORE ofac_sanctions_relief because state
    # press routinely couples protest framing with calls to lift the
    # embargo, which would otherwise split one event into two buckets.
    ("anti_embargo_protest", (
        # English framings used by Granma / Cubadebate translations.
        "march against the blockade",
        "march against the embargo",
        "anti-embargo march",
        "anti-blockade march",
        "national mobilization against the blockade",
        "national mobilization against the embargo",
        # Spanish: state media rotates marcha / movilizacion / tribuna
        # antiimperialista / acto. Catch the canonical phrasings.
        "marcha contra el bloqueo",
        "movilizacion contra el bloqueo",
        "tribuna antiimperialista",
        "acto contra el bloqueo",
        "marcha del pueblo combatiente",
        "abajo el bloqueo",
        "cuba vs bloqueo",
        "no al bloqueo",
        "un solo pueblo contra el bloqueo",
    )),
    # UN General Assembly anti-embargo vote — recurring annual story.
    ("un_anti_embargo_vote", (
        "un general assembly resolution against the embargo",
        "un vote against the cuba embargo",
        "resolucion de la onu contra el bloqueo",
        "votacion en la onu contra el bloqueo",
        "asamblea general de la onu contra el bloqueo",
    )),
    # Generic embargo-easing commentary (no specific protest framing).
    # Sits AFTER anti_embargo_protest so protest pieces win the tag.
    ("ofac_sanctions_relief", (
        "lift the embargo",
        "easing of the embargo",
        "embargo easing",
        "ease the embargo",
        "lift sanctions on cuba",
        "us eases cuba sanctions",
        "levantamiento del bloqueo",
        "flexibilizacion del bloqueo",
    )),
    # Diplomatic ties (specific bilaterals)
    ("eu_pdca", ("acuerdo de dialogo politico y cooperacion", "eu-cuba pdca", "political dialogue and cooperation agreement", "ue-cuba pdca")),
    ("us_relations_specific", ("us senate resolution on cuba", "us state department releases on cuba", "us-cuba bilateral", "havana-washington bilateral")),
    # Sector-broad (lowest priority — only catch if nothing more specific matched)
    ("foreign_investment_general", ("inversion extranjera directa", "foreign direct investment")),
    ("private_sector_reform", ("reforma del sector privado", "private sector reform", "mipymes y cuentapropistas")),
    ("tourism_recovery", ("recuperacion del turismo", "tourism recovery", "llegadas de turistas", "tourist arrivals")),
    ("biotech_sector", ("biocubafarma", "cuban biotech", "cuban vaccines", "abdala", "soberana")),
    ("nickel_sector", ("moa nickel", "sherritt joint venture", "cubaniquel", "nickel and cobalt")),
    ("telecom_etecsa", ("etecsa", "cuban telecom", "section 515.578", "§515.578 telecom carve-out")),
    ("remittances_corridor", ("western union cuba", "fincimex", "mlc remittances", "envio de remesas a cuba")),
    ("real_estate_reform", ("reforma del sector inmobiliario", "real estate sector reform", "leyes inmobiliarias", "mercado inmobiliario en cuba")),
]


def _normalize(text: str) -> str:
    """Strip accents + lowercase. 'Petróleo' -> 'petroleo'."""
    import unicodedata
    return (
        unicodedata.normalize("NFKD", text or "")
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )


def _topic_signature(text: str) -> set[str]:
    """Significant-word set for Jaccard similarity comparison."""
    norm = _normalize(text)
    tokens = re.findall(r"[a-zA-Z]+", norm)
    return {t for t in tokens if len(t) > 3 and t not in _TOPIC_STOPWORDS}


def _topic_tag(text: str) -> str | None:
    """Return the first topic tag whose keyword appears in text, else None."""
    norm = _normalize(text)
    for tag, kws in _TOPIC_TAGS:
        for kw in kws:
            if kw in norm:
                return tag
    return None


def _entry_text(entry: dict) -> str:
    return " ".join(filter(None, [
        entry.get("headline_short"),
        entry.get("headline"),
        entry.get("body_text") or "",
    ]))


DEDUP_WINDOW_DAYS = 7
JACCARD_THRESHOLD = 0.35
# Even when two entries share a topic tag and fall inside the dedup
# window, they must also have at least this much *content* overlap to
# be merged. This protects against the "two genuinely different
# private-sector reforms were announced in the same week" case — both
# would tag as private_sector_reform, but their headlines/bodies would
# have low word overlap (e.g. "MIPYMES Tax Window Extended" vs "New
# cuentapropistas licensing bands"), so they stay as separate entries.
#
# This Jaccard floor is *only* applied to non-exclusive topic tags
# (see _EXCLUSIVE_TOPIC_TAGS below). For named single-instrument tags
# like foreign_investment_law (= Ley 118), sharing the tag + date
# window is sufficient to merge — those tags inherently refer to one
# specific legal instrument, so 5 articles tagged foreign_investment_law
# in the same week are all about the same law.
TOPIC_MERGE_MIN_JACCARD = 0.25

# Topic tags that refer to a single, uniquely-named instrument or
# event. Articles sharing one of these tags within DEDUP_WINDOW_DAYS
# always describe the same underlying story (e.g. "Ley 118" / the
# Foreign Investment Law only exists once; the Cuba Restricted List
# is one document; an annual UN anti-embargo vote is one event;
# a single travel-advisory revision only exists once), so we collapse
# them without requiring extra word-overlap evidence.
#
# Add a tag here only when you're confident the tag's keyword set
# uniquely identifies one instrument. Broad tags like
# "foreign_investment_general" must NOT be exclusive — those legitimately
# cover multiple distinct deals.
_EXCLUSIVE_TOPIC_TAGS = frozenset({
    "foreign_investment_law",
    "mipymes_decree",
    "tarea_ordenamiento",
    "mariel_zed_regulations",
    "constitution_2019",
    "cuba_restricted_list",
    "cpal_update",
    "helms_burton_title_iii",
    "travel_advisory",
    "anti_embargo_protest",
    "un_anti_embargo_vote",
})

# Calendar-specific dedup threshold. Lower than the news Jaccard floor
# because the calendar surface is small (≤8 items) and tolerates more
# aggressive merging — a duplicate slot is much more visible there
# than buried in a 27-item news feed.
CALENDAR_JACCARD_THRESHOLD = 0.30


def _deduplicate_entries(entries: list[dict]) -> list[dict]:
    """Collapse near-duplicate entries.

    Two passes:
      1. **Topic-window pass**: entries with the same topic tag within
         DEDUP_WINDOW_DAYS collapse to the highest-relevance one. This
         catches the "12 ANPP deputies separately commented on the
         Foreign Investment Law this week" case.
      2. **Jaccard fallback**: catches near-duplicates that didn't
         match a topic tag, using shared significant-word ratio.

    Within each merge, we keep the entry with the highest LLM
    relevance score (tiebreak: newer date).
    """
    if not entries:
        return entries

    original_count = len(entries)

    # --- Pass 1: topic + time-window clustering ---
    survivors: list[dict] = []
    by_tag: dict[str, list[dict]] = {}
    for e in entries:
        tag = _topic_tag(_entry_text(e))
        if tag is None:
            survivors.append(e)
            continue
        by_tag.setdefault(tag, []).append(e)

    for tag, group in by_tag.items():
        # Sort newest first, then iterate building "clusters" of entries
        # that satisfy:
        #   - within DEDUP_WINDOW_DAYS of an existing cluster member
        #   - AND (only for non-exclusive tags) shared significant-word
        #     Jaccard >= TOPIC_MERGE_MIN_JACCARD with an existing
        #     cluster member.
        # Exclusive tags refer to a single named instrument, so the
        # date-window check alone is enough — see _EXCLUSIVE_TOPIC_TAGS.
        is_exclusive = tag in _EXCLUSIVE_TOPIC_TAGS
        group.sort(key=lambda e: e["published_date"], reverse=True)
        sigs = {id(e): _topic_signature(_entry_text(e)) for e in group}
        clusters: list[list[dict]] = []
        for e in group:
            placed = False
            sig = sigs[id(e)]
            for cluster in clusters:
                date_ok = any(
                    abs((e["published_date"] - x["published_date"]).days) <= DEDUP_WINDOW_DAYS
                    for x in cluster
                )
                if not date_ok:
                    continue
                if is_exclusive:
                    cluster.append(e)
                    placed = True
                    break
                content_ok = False
                for x in cluster:
                    x_sig = sigs[id(x)]
                    union = sig | x_sig
                    if not union:
                        continue
                    if len(sig & x_sig) / len(union) >= TOPIC_MERGE_MIN_JACCARD:
                        content_ok = True
                        break
                if not content_ok:
                    continue
                cluster.append(e)
                placed = True
                break
            if not placed:
                clusters.append([e])

        for cluster in clusters:
            cluster.sort(
                key=lambda e: (e["relevance"], e["published_date"]),
                reverse=True,
            )
            keeper = cluster[0]
            survivors.append(keeper)
            if len(cluster) > 1:
                dropped_titles = ", ".join(
                    f"'{e['headline_short'][:40]}'" for e in cluster[1:]
                )
                rule = "exclusive" if is_exclusive else f"jacc>={TOPIC_MERGE_MIN_JACCARD:.2f}"
                logger.info(
                    "Dedup [%s win=%dd, %s]: kept '%s' (rel=%s, %s); dropped %d: %s",
                    tag,
                    DEDUP_WINDOW_DAYS,
                    rule,
                    keeper["headline_short"][:60],
                    keeper["relevance"],
                    keeper["published_date"],
                    len(cluster) - 1,
                    dropped_titles,
                )

    # --- Pass 2: Jaccard for everything that survived (no tag match) ---
    survivors.sort(key=lambda e: e["published_date"], reverse=True)
    enriched = [(e, _topic_signature(_entry_text(e))) for e in survivors]
    final: list[tuple[dict, set[str]]] = []
    for entry, sig in enriched:
        if not sig:
            final.append((entry, sig))
            continue
        merged = False
        for i, (kept_entry, kept_sig) in enumerate(final):
            if not kept_sig:
                continue
            jaccard = len(sig & kept_sig) / len(sig | kept_sig)
            if jaccard < JACCARD_THRESHOLD:
                continue
            challenger = (entry["relevance"], entry["published_date"])
            kept = (kept_entry["relevance"], kept_entry["published_date"])
            if challenger > kept:
                final[i] = (entry, sig)
            merged = True
            break
        if not merged:
            final.append((entry, sig))

    deduped = [e for e, _ in final]
    deduped.sort(key=lambda e: e["published_date"], reverse=True)
    if len(deduped) < original_count:
        logger.info("Dedup total: %d -> %d entries", original_count, len(deduped))
    return deduped


# How far back the "This Week's News" sidebar reaches. Match the
# label on the panel — we tell readers it's the past week, so the
# data must actually be from the past week. If a slow news week
# leaves us with <2 items inside the window, _build_news_sidebar
# transparently extends to 14d so the panel never renders nearly
# empty next to a populated calendar.
NEWS_SIDEBAR_PRIMARY_DAYS = 7
NEWS_SIDEBAR_FALLBACK_DAYS = 14
NEWS_SIDEBAR_MIN_ITEMS_BEFORE_FALLBACK = 2


def _build_news_sidebar(entries: list[dict]) -> list[dict]:
    """Top items for the This Week's News sidebar.

    Filters to the last 7 days (Option B from the duplicate-fix
    discussion — keep the heading honest). Falls back to a 14-day
    window only if fewer than NEWS_SIDEBAR_MIN_ITEMS_BEFORE_FALLBACK
    items survive the 7-day filter, so a quiet news week doesn't
    leave the panel looking broken next to a fully-populated calendar.
    Within the chosen window, ranks by (is_breaking, relevance) and
    caps at 8.
    """
    today = date.today()

    def _within(days: int) -> list[dict]:
        cutoff = today - timedelta(days=days)
        return [e for e in entries if e["published_date"] >= cutoff]

    pool = _within(NEWS_SIDEBAR_PRIMARY_DAYS)
    if len(pool) < NEWS_SIDEBAR_MIN_ITEMS_BEFORE_FALLBACK:
        widened = _within(NEWS_SIDEBAR_FALLBACK_DAYS)
        logger.info(
            "News sidebar: only %d item(s) in last %dd, widening to %dd (%d items)",
            len(pool), NEWS_SIDEBAR_PRIMARY_DAYS,
            NEWS_SIDEBAR_FALLBACK_DAYS, len(widened),
        )
        pool = widened

    top = sorted(
        pool,
        key=lambda e: (e.get("is_breaking", False), e["relevance"]),
        reverse=True,
    )
    sidebar = []
    for e in top[:8]:
        plain = e.get("takeaway_plain") or re.sub(r"<[^>]+>", "", str(e["takeaway"]))
        summary_short = plain[:120].rsplit(" ", 1)[0] + "..." if len(plain) > 120 else plain
        sidebar.append({
            "id": e["id"],
            "headline_short": e["headline_short"],
            "summary_short": summary_short,
            "sentiment": e["sentiment"],
        })
    return sidebar


def _build_ticker(db) -> list[dict]:
    """Build ticker bar items from latest DB data."""
    items = []

    bcc = (
        db.query(ExternalArticleEntry)
        .filter(ExternalArticleEntry.source == SourceType.BCC_RATES)
        .order_by(ExternalArticleEntry.published_date.desc())
        .first()
    )
    if bcc and bcc.extra_metadata:
        usd_rate = bcc.extra_metadata.get("usd")
        if usd_rate:
            source_used = bcc.extra_metadata.get("source_used") or "BCC"
            source_label = "BCC (live)" if source_used == "bcc" else f"BCC via {source_used}"
            items.append({
                "label": "BCC Official",
                "value": f"{float(usd_rate):.2f}",
                "unit": "CUP/$",
                "change": None,
                "change_dir": "up",
                "value_color": None,
                "source": source_label,
            })

    eltoque = (
        db.query(ExternalArticleEntry)
        .filter(ExternalArticleEntry.source == SourceType.ELTOQUE_RATE)
        .order_by(ExternalArticleEntry.published_date.desc())
        .first()
    )
    if eltoque and eltoque.extra_metadata:
        usd_informal = eltoque.extra_metadata.get("usd")
        premium = eltoque.extra_metadata.get("informal_premium_pct")
        change = f"+{premium:.1f}% vs BCC" if premium is not None else None
        if usd_informal:
            items.append({
                "label": "elTOQUE TRMI",
                "value": f"{float(usd_informal):.2f}",
                "unit": "CUP/$",
                "change": change,
                "change_dir": "up",
                "value_color": "#fbbf24",
                "source": "elTOQUE (informal)",
            })
        mlc_rate = eltoque.extra_metadata.get("mlc")
        if mlc_rate:
            items.append({
                "label": "MLC Rate",
                "value": f"{float(mlc_rate):.2f}",
                "unit": "CUP/MLC",
                "change": None,
                "change_dir": "up",
                "value_color": "#a78bfa",
                "source": "elTOQUE (informal)",
            })

    advisory = (
        db.query(ExternalArticleEntry)
        .filter(ExternalArticleEntry.source == SourceType.TRAVEL_ADVISORY)
        .order_by(ExternalArticleEntry.published_date.desc())
        .first()
    )
    if advisory and advisory.extra_metadata:
        level = advisory.extra_metadata.get("level")
        if level:
            color = "#4ade80" if level <= 2 else "#fbbf24" if level == 3 else "#f87171"
            items.append({
                "label": "Travel Advisory",
                "value": f"Level {level}",
                "unit": None,
                "change": None,
                "change_dir": "up" if level < 4 else "down",
                "value_color": color,
                "source": "State Dept",
            })

    if not items or len(items) < 2:
        items.extend([
            {"label": "Brent Crude", "value": "$65.48", "unit": None, "change": "−4.1%", "change_dir": "down", "value_color": None, "source": "MarketWatch"},
            {"label": "BCC Reference", "value": "120.00", "unit": "CUP/$", "change": None, "change_dir": "down", "value_color": None, "source": "BCC Official"},
            {"label": "Tourist Arrivals", "value": "2.4M", "unit": "FY24", "change": None, "change_dir": "up", "value_color": None, "source": "ONEI"},
        ])
    else:
        items.extend([
            {"label": "Brent Crude", "value": "$65.48", "unit": None, "change": "−4.1%", "change_dir": "down", "value_color": None, "source": "MarketWatch"},
            {"label": "Inflation '24", "value": "31.0%", "unit": None, "change": None, "change_dir": "down", "value_color": None, "source": "ONEI"},
            {"label": "Tourist Arrivals", "value": "2.4M", "unit": "FY24", "change": None, "change_dir": "up", "value_color": None, "source": "ONEI"},
            {"label": "Nickel + Cobalt", "value": "49.5kt", "unit": "FY24", "change": None, "change_dir": "up", "value_color": None, "source": "Sherritt / ONEI"},
        ])

    return items


# Sort order for calendar urgency tiers — lowest int = shown first.
_URGENCY_ORDER = {
    "today": 0,
    "imminent": 1,
    "dated": 2,
    "pending": 3,
    "ongoing": 4,
    "longterm": 5,
}

# Small set of *standing* calendar items — long-horizon programs whose
# presence in the calendar is a function of "investors should always be
# aware of these", not of any one news article. Daily news scraping
# wouldn't naturally surface "OFAC GLs 46A-50A are still active" because
# their continued existence isn't news. These get appended after the
# dynamically-extracted items, only if they aren't already covered by
# something dynamic with a similar title.
_STANDING_CALENDAR_ITEMS: list[dict] = [
    {
        "date_label": "Ongoing",
        "title": "CACR §515 General Licenses",
        "subtitle": "Active",
        "note": "Travel, telecom, agricultural-export and humanitarian authorizations under 31 CFR Part 515. Revocable.",
        "link": "https://ofac.treasury.gov/sanctions-programs-and-country-information/cuba-sanctions",
        "link_label": "OFAC",
        "css_class": "cal-positive",
        "urgency": "ongoing",
    },
    {
        "date_label": "Annual",
        "title": "UN General Assembly anti-embargo vote",
        "subtitle": "October–November (annual)",
        "note": "32nd consecutive year of the UNGA resolution calling for an end to the US embargo on Cuba.",
        "link": "https://www.un.org/en/ga/",
        "link_label": "UN",
        "css_class": "",
        "urgency": "longterm",
    },
    {
        "date_label": "Ongoing",
        "title": "Cuba Restricted List (CRL)",
        "subtitle": "State Department list under §515.209",
        "note": "GAESA holdings, CIMEX, Gaviota, FINCIMEX and 200+ subentities prohibited as direct counterparties.",
        "link": "https://www.state.gov/cuba-restricted-list/",
        "link_label": "State",
        "css_class": "cal-negative",
        "urgency": "ongoing",
    },
]


def _calendar_dedup_score(ev: dict) -> tuple:
    """Higher tuple wins when collapsing duplicate calendar events.

    Priority order: most-urgent tier first (lowest urgency_order int),
    then highest source-article relevance, then most recent article.
    """
    return (
        -_URGENCY_ORDER.get(ev.get("urgency", "dated"), 99),
        ev.get("_relevance", 0),
        (ev.get("_published") - date.min).days if ev.get("_published") else 0,
    )


def _deduplicate_calendar_events(events: list[dict]) -> list[dict]:
    """Two-pass dedup of calendar candidates.

    Pass 1: Exclusive topic tags. The LLM frequently rephrases the same
    underlying event ("Foreign Investment Law Reform" vs "Ley 118
    Amendment Window", "Nationwide March Against the Blockade" vs
    "National Mobilization Against the Embargo"), but the topic tag
    system pins both to the same canonical event
    (`foreign_investment_law`, `anti_embargo_protest`). At most one
    event per exclusive tag survives, with the highest-priority one
    kept.

    Pass 2: Jaccard fallback on title tokens for any pair the topic
    system didn't catch (threshold = CALENDAR_JACCARD_THRESHOLD).

    Standing fixtures are passed through this same pipeline so they
    also dedupe against dynamic items if they overlap.
    """
    if not events:
        return events

    kept: list[dict] = []
    sigs: list[set[str]] = []
    by_topic: dict[str, int] = {}

    for ev in events:
        topic = ev.get("_topic")
        sig = _topic_signature(ev.get("title", "") + " " + (ev.get("subtitle") or ""))

        if topic and topic in _EXCLUSIVE_TOPIC_TAGS:
            if topic in by_topic:
                idx = by_topic[topic]
                if _calendar_dedup_score(ev) > _calendar_dedup_score(kept[idx]):
                    logger.info(
                        "Calendar dedup [%s exclusive]: replacing '%s' with '%s'",
                        topic,
                        kept[idx].get("title", "")[:50],
                        ev.get("title", "")[:50],
                    )
                    kept[idx] = ev
                    sigs[idx] = sig
                else:
                    logger.info(
                        "Calendar dedup [%s exclusive]: dropping '%s' (kept '%s')",
                        topic,
                        ev.get("title", "")[:50],
                        kept[idx].get("title", "")[:50],
                    )
                continue
            by_topic[topic] = len(kept)
            kept.append(ev)
            sigs.append(sig)
            continue

        # Jaccard fallback for events outside the exclusive-tag system.
        merged_idx: int | None = None
        for i, ksig in enumerate(sigs):
            if not sig or not ksig:
                continue
            jacc = len(sig & ksig) / len(sig | ksig)
            if jacc >= CALENDAR_JACCARD_THRESHOLD:
                merged_idx = i
                break
        if merged_idx is not None:
            if _calendar_dedup_score(ev) > _calendar_dedup_score(kept[merged_idx]):
                logger.info(
                    "Calendar dedup [jacc>=%.2f]: replacing '%s' with '%s'",
                    CALENDAR_JACCARD_THRESHOLD,
                    kept[merged_idx].get("title", "")[:50],
                    ev.get("title", "")[:50],
                )
                kept[merged_idx] = ev
                sigs[merged_idx] = sig
            else:
                logger.info(
                    "Calendar dedup [jacc>=%.2f]: dropping '%s' (kept '%s')",
                    CALENDAR_JACCARD_THRESHOLD,
                    ev.get("title", "")[:50],
                    kept[merged_idx].get("title", "")[:50],
                )
        else:
            kept.append(ev)
            sigs.append(sig)

    return kept


def _refresh_calendar_label(
    raw_urgency: str,
    raw_date_label: str,
    published_date: date,
) -> tuple[str, str]:
    """Recompute a calendar event's urgency + date_label against today.

    The LLM writes urgency="today" + date_label="…— TODAY" into
    analysis_json on the day the article is analyzed. Those values
    are then frozen in the DB, so an event analyzed on Apr 17 still
    renders as "TODAY" on Apr 19 unless we re-anchor at render time.

    Behavior:
      • If the LLM said "today" but the source article isn't actually
        from today, demote urgency → "dated" and rewrite the label to
        a relative-day form ("Yesterday", "2 days ago", "Apr 17", etc).
      • If urgency != "today" but the date_label literally contains
        "TODAY"/"Today"/"today" while the article isn't from today,
        strip the stale "TODAY" suffix.
      • Otherwise return the LLM's values unchanged.

    Anchored to UTC date because the cron + reader timezones diverge
    enough that anything else is misleading (Render cron runs UTC,
    reader is in Medellín, content is global).
    """
    today = date.today()
    age_days = (today - published_date).days

    # Case 1: explicit urgency=today on a stale event → recompute fully.
    if raw_urgency == "today" and age_days != 0:
        return "dated", _relative_date_label(published_date, age_days)

    # Case 2: urgency is fine, but the LLM-baked label has a stale
    # "— TODAY" suffix. Strip it and fall back to a real date.
    if age_days != 0 and re.search(r"\bTODAY\b", raw_date_label, flags=re.IGNORECASE):
        return raw_urgency, _relative_date_label(published_date, age_days)

    # Case 3: urgency=today AND it actually is today — keep the
    # LLM label, just normalise to ALL-CAPS for visual consistency
    # with the existing template styling.
    if raw_urgency == "today" and age_days == 0:
        return "today", raw_date_label

    return raw_urgency, raw_date_label


_MONTH_ABBR_TO_NUM = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def _parse_event_sort_date(date_label: str, published: date | None) -> date | None:
    """Best-effort extraction of a sortable event date from a date_label.

    The LLM and our own helpers serialize event dates as short strings
    like "MAY 1 — IMMINENT", "APR 14 – APR 21", "APR 17 (3 DAYS AGO)",
    "TODAY", "YESTERDAY", "Pending Promulgation", "Ongoing", "2026
    Target". We only need a key for sorting; for ranges we use the
    start date, and for non-dated labels we return None (those sort
    to the end of the calendar).

    Year inference: if the label has an explicit 4-digit year we use
    it; otherwise we anchor to the source article's published date and
    pick the year that puts the event closest to that anchor (handles
    Dec/Jan boundary crossings).
    """
    if not date_label:
        return None

    label = date_label.upper()

    if re.search(r"\bTODAY\b", label):
        return date.today()
    if re.search(r"\bYESTERDAY\b", label):
        return date.today() - timedelta(days=1)

    m = re.search(r"\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+(\d{1,2})\b", label)
    if not m:
        return None

    month = _MONTH_ABBR_TO_NUM[m.group(1)]
    day = int(m.group(2))

    explicit_year = re.search(r"\b(20\d{2})\b", label)
    if explicit_year:
        try:
            return date(int(explicit_year.group(1)), month, day)
        except ValueError:
            return None

    anchor = published or date.today()
    best: date | None = None
    for candidate_year in (anchor.year - 1, anchor.year, anchor.year + 1):
        try:
            cand = date(candidate_year, month, day)
        except ValueError:
            continue
        if best is None or abs((cand - anchor).days) < abs((best - anchor).days):
            best = cand
    return best


def _relative_date_label(d: date, age_days: int) -> str:
    """Short human label for a past date, mirroring the LLM style.

    Examples:
      0       → "TODAY"
      1       → "YESTERDAY"
      2-6     → "APR 17 (3 DAYS AGO)"
      7-89    → "APR 17"  (drop year for current year)
      else    → "APR 17, 2025"
    """
    if age_days <= 0:
        return "TODAY"
    if age_days == 1:
        return "YESTERDAY"
    base = d.strftime("%b %d").upper()
    if age_days <= 6:
        return f"{base} ({age_days} DAYS AGO)"
    if d.year == date.today().year:
        return base
    return d.strftime("%b %d, %Y").upper()


def _build_calendar(ext_articles, assembly_news) -> list[dict]:
    """Forward-looking investor calendar built from recent analyzed news.

    The LLM analyzer extracts a `calendar_event` object on entries that
    describe a specific time-bounded event (a scheduled discussion,
    march, license expiration, pending promulgation, etc). This pulls
    those out, runs them through topic-tag + Jaccard dedup, sorts by
    urgency, and appends a small set of standing items (active OFAC
    GLs, the 2026 legislative target) that wouldn't naturally surface
    in daily news. Standing items go through the same dedup pass.
    """
    candidates: list[dict] = []

    # Newest entries first so when the same event is mentioned twice
    # we keep the freshest framing.
    for item in sorted(
        list(ext_articles) + list(assembly_news),
        key=lambda x: x.published_date,
        reverse=True,
    ):
        analysis = item.analysis_json or {}
        ev = analysis.get("calendar_event")
        if not ev or not isinstance(ev, dict):
            continue
        title = (ev.get("title") or "").strip()
        if not title:
            continue

        # Compute the topic from the calendar event's own fields. We
        # intentionally do NOT mix in the source article body here —
        # the topic should describe the *event*, not the article that
        # mentioned it, otherwise broad articles incidentally referencing
        # an exclusive-tag keyword would steamroll legitimately distinct
        # calendar items.
        topic = _topic_tag(
            " ".join(filter(None, [title, ev.get("subtitle"), ev.get("note")]))
        )

        raw_urgency = (ev.get("urgency") or "dated").lower()
        raw_date_label = ev.get("date_label") or item.published_date.strftime("%b %d, %Y")

        # Re-anchor to today. The LLM serialized "today"/"TODAY" into
        # analysis_json on the day the article was first analyzed, so
        # those labels go stale as soon as the calendar rolls forward
        # (e.g. an Apr 17 event still rendering as "APR 17 — TODAY"
        # on Apr 19). We trust the article's published_date as the
        # event-anchor date — for the LLM to have set urgency="today"
        # the event almost always coincided with the article's date.
        urgency, date_label = _refresh_calendar_label(
            raw_urgency, raw_date_label, item.published_date,
        )

        candidates.append({
            "date_label": date_label,
            "title": title,
            "subtitle": ev.get("subtitle"),
            "note": ev.get("note") or "",
            "link": item.source_url,
            "link_label": _calendar_link_label(item),
            "css_class": ev.get("css_class") or "",
            "urgency": urgency,
            "_topic": topic,
            "_relevance": analysis.get("relevance_score", 0),
            "_published": item.published_date,
        })

    # Append standing items into the same pool so they dedupe against
    # any dynamic event that's already covering the same ground.
    for fixture in _STANDING_CALENDAR_ITEMS:
        candidates.append({
            **fixture,
            "_topic": _topic_tag(
                " ".join(filter(None, [fixture.get("title"), fixture.get("subtitle"), fixture.get("note")]))
            ),
            "_relevance": 0,
            "_published": date.min,
        })

    pre = len(candidates)
    candidates = _deduplicate_calendar_events(candidates)
    if len(candidates) < pre:
        logger.info(
            "Calendar dedup total: %d -> %d events",
            pre,
            len(candidates),
        )

    # Sort chronologically by the actual event date (parsed out of
    # date_label). Events without a parseable date — "Ongoing",
    # "Pending Promulgation", "2026 Target" — fall to the bottom,
    # ordered amongst themselves by urgency tier so standing items
    # land in a stable spot. Within the dated bucket we go ascending
    # so the closest-in-time items appear first.
    def _sort_key(c: dict) -> tuple:
        ev_date = _parse_event_sort_date(c["date_label"], c.get("_published"))
        if ev_date is None:
            return (1, _URGENCY_ORDER.get(c["urgency"], 99), 0)
        return (0, ev_date.toordinal(), -c.get("_relevance", 0))

    candidates.sort(key=_sort_key)

    cleaned = []
    for c in candidates[:8]:
        cleaned.append({k: v for k, v in c.items() if not k.startswith("_")})

    if len(cleaned) <= 2:
        # Almost-empty calendar: fall back to standing items only so the
        # box doesn't render as a barren single line.
        cleaned = list(_STANDING_CALENDAR_ITEMS)

    return cleaned


def _calendar_link_label(item) -> str:
    """Short pill-friendly label for the calendar event source link."""
    if hasattr(item, "source"):
        if item.source == SourceType.FEDERAL_REGISTER:
            return "Federal Register"
        if item.source == SourceType.TRAVEL_ADVISORY:
            return "State Dept"
        if item.source == SourceType.OFAC_SDN:
            return "OFAC"
        if item.source == SourceType.GACETA_OFICIAL_CU:
            return "Gaceta CU"
        if item.source == SourceType.MINREX:
            return "MINREX"
        if item.source == SourceType.ONEI:
            return "ONEI"
    if hasattr(item, "source_url") and "parlamentocubano" in (item.source_url or ""):
        return "ANPP"
    return "Source"


def _build_climate() -> dict:
    """Investment climate tracker payload for the report template.

    Reads the latest ClimateSnapshot row written by the weekly climate
    refresh job (src.climate.runner). Falls back to a static literal if
    the snapshots table is empty (cold start, before the first weekly
    cron has run). The literal mirrors the schema the template expects,
    so the page never breaks while the framework is bootstrapping.
    """
    try:
        from src.models import SessionLocal, ClimateSnapshot
        db = SessionLocal()
        try:
            snap = (
                db.query(ClimateSnapshot)
                .order_by(ClimateSnapshot.quarter_start.desc())
                .first()
            )
            if snap and snap.bars_json:
                return {
                    "period": snap.period_label or snap.quarter_label,
                    "bars": snap.bars_json,
                    "methodology": snap.methodology or "",
                }
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 - never break the report
        import logging
        logging.getLogger(__name__).warning(
            "Climate snapshot read failed, using literal fallback: %s", exc
        )

    return {
        "period": "Q2 2026 vs. Q1 2026 (baseline)",
        "bars": [
            {"label": "Embargo Posture", "score": 3, "trend_dir": "flat", "trend_value": "", "bar_color": "red", "why": "Awaiting first weekly climate refresh — showing manual baseline."},
            {"label": "Diplomatic Engagement", "score": 4, "trend_dir": "flat", "trend_value": "", "bar_color": "yellow", "why": "Awaiting first weekly climate refresh — showing manual baseline."},
            {"label": "MIPYME & FDI Framework", "score": 4, "trend_dir": "flat", "trend_value": "", "bar_color": "yellow", "why": "Awaiting first weekly climate refresh — showing manual baseline."},
            {"label": "Political Stability", "score": 3, "trend_dir": "flat", "trend_value": "", "bar_color": "red", "why": "Awaiting first weekly climate refresh — showing manual baseline."},
            {"label": "Property Rights", "score": 3, "trend_dir": "flat", "trend_value": "", "bar_color": "red", "why": "Awaiting first weekly climate refresh — showing manual baseline."},
            {"label": "Macro Stability", "score": 2, "trend_dir": "flat", "trend_value": "", "bar_color": "red", "why": "Awaiting first weekly climate refresh — showing manual baseline."},
        ],
        "methodology": (
            "Cold-start fallback. The live scorecard is computed weekly by "
            "src.climate.runner.run_weekly_climate_refresh from BCC reference + "
            "elTOQUE TRMI FX, OFAC SDN (Cuba program) / Federal Register "
            "activity, US State Dept Cuba travel advisory, GDELT tone, "
            "and Gaceta Oficial CU + ANPP / Granma keyword counts on "
            "MIPYME, FDI, Helms-Burton Title III, 11J / apagón, and "
            "migration themes, with QoQ deltas against the previous "
            "quarter's stored snapshot."
        ),
    }


def _attach_blog_links(db, entries: list[dict]) -> None:
    """
    For each entry whose underlying source row has a published BlogPost,
    attach `blog_slug` so the template can link to /briefing/{blog_slug}.
    Entries without a blog post get blog_slug=None and the template hides
    the 'Read full analysis' link.
    """
    try:
        from src.models import BlogPost
    except Exception:
        for e in entries:
            e.setdefault("blog_slug", None)
        return

    keys = [
        ("external_articles" if e.get("item_type") == "external" else "assembly_news",
         e.get("db_id"))
        for e in entries
        if e.get("db_id") is not None
    ]
    if not keys:
        for e in entries:
            e.setdefault("blog_slug", None)
        return

    rows = db.query(BlogPost.source_table, BlogPost.source_id, BlogPost.slug).all()
    lookup = {(r[0], r[1]): r[2] for r in rows}
    for e in entries:
        table = "external_articles" if e.get("item_type") == "external" else "assembly_news"
        e["blog_slug"] = lookup.get((table, e.get("db_id")))


def _build_jsonld(entries: list[dict], seo: dict, generated_at: datetime) -> str:
    """
    Build a JSON-LD blob containing Organization, WebSite, BreadcrumbList,
    ItemList (latest briefings), and NewsArticle (the lead entry).
    Returned as a JSON-encoded string ready to drop into a single
    <script type="application/ld+json"> tag.
    """
    import json as _json

    base = settings.site_url.rstrip("/")
    iso_now = generated_at.replace(tzinfo=timezone.utc).isoformat()

    organization = {
        "@type": "Organization",
        "@id": f"{base}/#organization",
        "name": settings.site_name,
        "url": f"{base}/",
        "logo": {
            "@type": "ImageObject",
            "url": f"{base}/static/og-image.png?v=3",
            "width": 1200,
            "height": 630,
        },
    }

    website = {
        "@type": "WebSite",
        "@id": f"{base}/#website",
        "url": f"{base}/",
        "name": settings.site_name,
        "description": seo.get("description", ""),
        "inLanguage": "en-US",
        "publisher": {"@id": f"{base}/#organization"},
    }

    breadcrumbs = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": 1,
                "name": "Home",
                "item": f"{base}/",
            },
            {
                "@type": "ListItem",
                "position": 2,
                "name": "Daily Briefing",
                "item": f"{base}/",
            },
        ],
    }

    item_list_elements = []
    for idx, entry in enumerate(entries[:20], start=1):
        blog_slug = entry.get("blog_slug")
        if blog_slug:
            url_target = f"{base}/briefing/{blog_slug}"
        else:
            url_target = f"{base}/#dev-{entry.get('id', '')}"
        headline = entry.get("headline_short") or entry.get("headline") or ""
        item_list_elements.append({
            "@type": "ListItem",
            "position": idx,
            "url": url_target,
            "name": headline,
        })
    item_list = {
        "@type": "ItemList",
        "name": "Latest Cuba investment & sanctions briefings",
        "itemListOrder": "https://schema.org/ItemListOrderDescending",
        "numberOfItems": len(item_list_elements),
        "itemListElement": item_list_elements,
    }

    graph: list[dict] = [organization, website, breadcrumbs, item_list]

    if entries:
        lead = entries[0]
        blog_slug = lead.get("blog_slug")
        article_url = f"{base}/briefing/{blog_slug}" if blog_slug else f"{base}/"
        article_headline = (
            lead.get("headline_short") or lead.get("headline") or seo.get("title", "")
        )
        article_body = (
            lead.get("takeaway_plain")
            or lead.get("summary")
            or seo.get("description", "")
        )
        published = lead.get("published_iso") or iso_now
        modified = lead.get("modified_iso") or published

        keywords = seo.get("keywords", "")
        if isinstance(keywords, str):
            keywords_list = [k.strip() for k in keywords.split(",") if k.strip()]
        else:
            keywords_list = list(keywords) if keywords else []

        news_article = {
            "@type": "NewsArticle",
            "@id": f"{article_url}#article",
            "mainEntityOfPage": {
                "@type": "WebPage",
                "@id": article_url,
                "name": article_headline[:110],
            },
            "headline": article_headline[:110],
            "description": (article_body[:300] + ("…" if len(article_body) > 300 else "")),
            "image": [seo.get("og_image", f"{base}/static/og-image.png?v=3")],
            "datePublished": published,
            "dateModified": modified,
            "author": {
                "@type": "Organization",
                "name": settings.site_name,
                "url": f"{base}/",
            },
            "publisher": {"@id": f"{base}/#organization"},
            "keywords": keywords_list,
            "isAccessibleForFree": True,
            "articleSection": "Cuba investment briefing",
            "inLanguage": "en-US",
        }
        graph.append(news_article)

    payload = {"@context": "https://schema.org", "@graph": graph}
    return _json.dumps(payload, ensure_ascii=False)


def _build_seo(entries: list[dict], generated_at: datetime) -> dict:
    """
    Build the SEO context (meta tags, Open Graph, Twitter, canonical) for
    the home report page.

    The <title> is intentionally pinned to a stable brand + value-prop
    pattern — only the trailing "Updated <date>" segment moves. A title
    that fully rotates day-to-day fragments Google's authority signal
    for the homepage URL; pinning the first half consolidates ranking
    weight on a single canonical phrase.

    The meta description still rotates with the freshest takeaway,
    since description churn is fine and helps SERP CTR.
    """
    base = settings.site_url.rstrip("/")

    sector_counter: dict[str, int] = {}
    for entry in entries[:25]:
        for sector in entry.get("sectors", []) or []:
            sector_counter[sector] = sector_counter.get(sector, 0) + 1
    top_sectors = [
        s for s, _ in sorted(sector_counter.items(), key=lambda kv: kv[1], reverse=True)
    ][:3]

    title = (
        "Cuban Insights — Cuba Investment Intelligence "
        f"| Updated {generated_at.strftime('%b %d, %Y')}"
    )

    if entries:
        first = entries[0]
        lead = first.get("takeaway_plain") or first.get("summary") or ""
        lead = " ".join(str(lead).split())
        if len(lead) > 220:
            lead = lead[:217].rsplit(" ", 1)[0] + "…"
        description = (
            f"Daily Cuba investment briefing — {lead} "
            "Tracking OFAC CACR sanctions, Helms-Burton Title III, the "
            "Cuba Restricted List, ANPP, Gaceta Oficial, BCC + elTOQUE TRMI rates."
        )
    else:
        description = (
            "Daily Cuba investment & sanctions briefing for global investors. "
            "Real-time monitoring of OFAC SDN (CACR / Cuba programs), the State "
            "Department's Cuba Restricted List and CPAL hotel blacklist, US "
            "Federal Register general licenses, Asamblea Nacional del Poder "
            "Popular legislation, Gaceta Oficial de la República de Cuba "
            "decrees, BCC reference + elTOQUE TRMI informal exchange rates, "
            "and US State Department travel advisories."
        )

    keywords = [
        "invest in Cuba",
        "Cuba investment opportunities",
        "OFAC Cuba sanctions",
        "Cuban Assets Control Regulations",
        "Helms-Burton Title III",
        "Cuba Restricted List",
        "Cuba general license",
        "Mariel ZED",
        "BioCubaFarma",
        "Asamblea Nacional del Poder Popular",
        "Gaceta Oficial de Cuba",
        "elTOQUE TRMI rate",
        "CUP USD MLC exchange rate",
        "MIPYMES Cuba",
        "doing business in Havana",
    ]
    for sector in top_sectors:
        keywords.append(f"Cuba {sector.lower()} sector")

    canonical = f"{base}/"
    og_image = f"{base}/static/og-image.png?v=3"

    return {
        "title": title,
        "description": description,
        "keywords": ", ".join(keywords),
        "canonical": canonical,
        "site_name": settings.site_name,
        "site_url": base,
        "locale": settings.site_locale,
        "og_image": og_image,
        "og_image_width": 1200,
        "og_image_height": 630,
        "og_type": "website",
        "twitter_card": "summary_large_image",
        "published_iso": generated_at.replace(tzinfo=timezone.utc).isoformat(),
        "modified_iso": generated_at.replace(tzinfo=timezone.utc).isoformat(),
        "top_sectors": top_sectors,
    }
