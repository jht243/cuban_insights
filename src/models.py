import enum
from datetime import datetime, date
from threading import Lock

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    Float,
    Date,
    DateTime,
    Enum,
    Boolean,
    JSON,
    LargeBinary,
    UniqueConstraint,
)
from sqlalchemy import inspect as sa_inspect, text as sa_text
from sqlalchemy.orm import declarative_base, sessionmaker

from src.config import settings

Base = declarative_base()


def _snake_case(name: str) -> str:
    """SourceType -> source_type"""
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0 and not name[i - 1].isupper():
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def _enum_values(enum_cls):
    """Tell SQLAlchemy to use enum .value (lowercase) instead of .name (uppercase)
    when serializing to Postgres, and bind to the snake_case Postgres enum type
    name (e.g. SourceType -> source_type). Without values_callable, inserts send
    the uppercase Python identifier (e.g. "GDELT") which doesn't match the
    lowercase Postgres enum values (e.g. "gdelt").
    """
    return Enum(
        enum_cls,
        values_callable=lambda x: [e.value for e in x],
        name=_snake_case(enum_cls.__name__),
    )


class SourceType(str, enum.Enum):
    # ── Cuba sources ──────────────────────────────────────────────────
    # Cuban official gazette — Gaceta Oficial de la República de Cuba
    # (gacetaoficial.gob.cu).
    GACETA_OFICIAL_CU = "gaceta_oficial_cu"
    # Asamblea Nacional del Poder Popular (parlamentocubano.gob.cu) and
    # Granma legislative coverage.
    ASAMBLEA_NACIONAL_CU = "asamblea_nacional_cu"
    # Banco Central de Cuba — official CUP/USD reference rate.
    BCC_RATES = "bcc_rates"
    # El Toque informal/parallel CUP/MLC/USD rate — the most-watched FX
    # number on the island.
    ELTOQUE_RATE = "eltoque_rate"
    # MINREX (Ministerio de Relaciones Exteriores) press releases.
    MINREX = "minrex"
    # ONEI (Oficina Nacional de Estadística e Información) macro stats.
    ONEI = "onei"
    # Note: EU sanctions intentionally absent. Cuba is not in the EU
    # consolidated financial sanctions list (the EU replaced its 1996
    # Common Position with the 2016 PDCA, which is engagement-based, not
    # restrictive). See docs/scraper_research.md §"EU sanctions".

    # ── Cross-cutting sources (unchanged) ─────────────────────────────
    FEDERAL_REGISTER = "federal_register"
    OFAC_SDN = "ofac_sdn"
    GDELT = "gdelt"
    TRAVEL_ADVISORY = "travel_advisory"
    NEWSDATA = "newsdata"
    EIA = "eia"

    # ── Cuba-specific U.S. lists (added in Phase 2b) ──────────────────
    # State Department's Cuba Restricted List (CRL) — entities and
    # subentities the executive branch has prohibited direct financial
    # transactions with under §515.209. Distinct from OFAC SDN; most CRL
    # entries are NOT on the SDN.
    STATE_DEPT_CRL = "state_dept_crl"
    # State Department's Cuba Prohibited Accommodations List (CPAL) —
    # specific hotels / casas particulares that fail the "no commerce
    # with the Cuban government" test under §515.210. Hotel-blacklist;
    # used by the company-exposure tooling to flag MAR/HLT/IHG/etc.
    STATE_DEPT_CPAL = "state_dept_cpal"

    # ── Press RSS aggregator (added in Phase 2d) ──────────────────────
    # All Cuban press outlets consumed via RSS share this SourceType so
    # we don't grow the enum to one-per-outlet. Per-outlet attribution
    # (Granma, Cubadebate, 14ymedio, OnCuba, Diario de Cuba, Havana
    # Times) is preserved in `ExternalArticleEntry.source_name`. See
    # `src/scraper/rss.py` for the outlet whitelist + credibility
    # tiering rationale.
    PRESS_RSS = "press_rss"

    # International Trade Administration / Trade.gov — U.S. export
    # market intelligence, trade leads, events, contacts, and export
    # guidance for U.S. companies evaluating Cuba or Caribbean trade
    # opportunities. Subtypes live in ExternalArticleEntry.article_type.
    ITA_TRADE = "ita_trade"


class CredibilityTier(str, enum.Enum):
    OFFICIAL = "official"
    TIER1 = "tier1"
    TIER2 = "tier2"
    STATE = "state"


class GazetteStatus(str, enum.Enum):
    SCRAPED = "scraped"
    OCR_COMPLETE = "ocr_complete"
    OCR_FAILED = "ocr_failed"
    ANALYZED = "analyzed"
    APPROVED = "approved"
    SENT = "sent"


class GazetteType(str, enum.Enum):
    ORDINARIA = "ordinaria"
    EXTRAORDINARIA = "extraordinaria"


class GazetteEntry(Base):
    __tablename__ = "gazette_entries"
    __table_args__ = (UniqueConstraint("source", "source_url", name="uq_source_url"),)

    id = Column(Integer, primary_key=True, autoincrement=True)

    gazette_number = Column(String(50), nullable=True, index=True)
    gazette_type = Column(_enum_values(GazetteType), default=GazetteType.ORDINARIA)
    published_date = Column(Date, nullable=False, index=True)
    source = Column(_enum_values(SourceType), nullable=False)
    source_url = Column(String(500), nullable=False)

    title = Column(Text, nullable=True)
    sumario_raw = Column(Text, nullable=True)

    pdf_path = Column(String(500), nullable=True)
    pdf_hash = Column(String(64), nullable=True, unique=True)
    pdf_download_url = Column(String(500), nullable=True)

    ocr_text = Column(Text, nullable=True)
    ocr_confidence = Column(Integer, nullable=True)

    analysis_json = Column(JSON, nullable=True)
    status = Column(_enum_values(GazetteStatus), default=GazetteStatus.SCRAPED)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AssemblyNewsEntry(Base):
    __tablename__ = "assembly_news"
    __table_args__ = (UniqueConstraint("source_url", name="uq_assembly_url"),)

    id = Column(Integer, primary_key=True, autoincrement=True)

    headline = Column(Text, nullable=False)
    published_date = Column(Date, nullable=False, index=True)
    source_url = Column(String(500), nullable=False)
    body_text = Column(Text, nullable=True)
    commission = Column(String(200), nullable=True)

    analysis_json = Column(JSON, nullable=True)
    status = Column(_enum_values(GazetteStatus), default=GazetteStatus.SCRAPED)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ExternalArticleEntry(Base):
    """Articles from external sources (Federal Register, GDELT, OFAC, etc.)."""

    __tablename__ = "external_articles"
    __table_args__ = (UniqueConstraint("source", "source_url", name="uq_ext_source_url"),)

    id = Column(Integer, primary_key=True, autoincrement=True)

    source = Column(_enum_values(SourceType), nullable=False, index=True)
    source_url = Column(String(1000), nullable=False)
    source_name = Column(String(200), nullable=True)
    credibility = Column(_enum_values(CredibilityTier), default=CredibilityTier.TIER2)

    headline = Column(Text, nullable=False)
    published_date = Column(Date, nullable=False, index=True)
    body_text = Column(Text, nullable=True)
    article_type = Column(String(100), nullable=True)

    tone_score = Column(Float, nullable=True)
    extra_metadata = Column(JSON, nullable=True)

    analysis_json = Column(JSON, nullable=True)
    status = Column(_enum_values(GazetteStatus), default=GazetteStatus.SCRAPED)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BlogPost(Base):
    """
    Long-form LLM-generated analysis post tied to a source entry.
    One blog post per ExternalArticle or AssemblyNews row that crosses the
    relevance threshold and has not yet been written about. Generated on
    a separate budget so the daily report run can stay cheap.
    """

    __tablename__ = "blog_posts"
    __table_args__ = (
        UniqueConstraint("source_table", "source_id", name="uq_blog_source"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    source_table = Column(String(50), nullable=False, index=True)
    source_id = Column(Integer, nullable=False, index=True)

    slug = Column(String(200), nullable=False, unique=True, index=True)
    title = Column(Text, nullable=False)
    subtitle = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    body_html = Column(Text, nullable=False)

    # Conversational, ~180-250 char "social hook" — written from one
    # analyst to another. Surfaces the tension or insight without
    # restating the title. Generated in the same LLM call as the post
    # body for new briefings; backfilled separately for old ones.
    # Used by social syndication (Bluesky etc.) so posts read like a
    # human wrote them rather than an RSS bot.
    social_hook = Column(Text, nullable=True)

    # Pre-rendered 1200x630 PNG bytes of the briefing's per-post Open
    # Graph card. Rendered once at blog-creation time (and backfilled
    # for old posts via scripts/backfill_og_images.py) so every share
    # preview shows the briefing's own headline rather than a generic
    # site-wide tile. Served by /og/briefing/<slug>.png. Typically
    # ~50-80 KB; well under any DB row limit.
    og_image_bytes = Column(LargeBinary, nullable=True)

    primary_sector = Column(String(80), nullable=True, index=True)
    sectors_json = Column(JSON, nullable=True)
    keywords_json = Column(JSON, nullable=True)
    related_slugs_json = Column(JSON, nullable=True)

    word_count = Column(Integer, nullable=True)
    reading_minutes = Column(Integer, nullable=True)

    published_date = Column(Date, nullable=False, index=True)
    canonical_source_url = Column(String(1000), nullable=True)

    llm_model = Column(String(100), nullable=True)
    llm_input_tokens = Column(Integer, nullable=True)
    llm_output_tokens = Column(Integer, nullable=True)
    llm_cost_usd = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LandingPage(Base):
    """
    Evergreen landing pages — the pillar /invest-in-cuba, the
    sector pages, the explainers. Generated less frequently than blog
    posts (e.g. weekly) and with the premium LLM model. Stored as
    pre-rendered HTML so the request path stays cheap.
    """

    __tablename__ = "landing_pages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    page_key = Column(String(120), nullable=False, unique=True, index=True)
    page_type = Column(String(40), nullable=False, index=True)

    title = Column(Text, nullable=False)
    subtitle = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    body_html = Column(Text, nullable=False)
    keywords_json = Column(JSON, nullable=True)
    sections_json = Column(JSON, nullable=True)

    sector_slug = Column(String(80), nullable=True, index=True)
    canonical_path = Column(String(200), nullable=False)
    word_count = Column(Integer, nullable=True)

    llm_model = Column(String(120), nullable=True)
    llm_input_tokens = Column(Integer, nullable=True)
    llm_output_tokens = Column(Integer, nullable=True)
    llm_cost_usd = Column(Float, nullable=True)

    last_generated_at = Column(DateTime, default=datetime.utcnow, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DistributionLog(Base):
    """
    Tracks every outbound distribution event (Google Indexing ping,
    Bluesky post, Mastodon post, Telegram broadcast, etc.). One row per
    (url, channel) attempt. Used both for idempotency (don't re-ping the
    same URL on the same channel within a cooldown window) and for
    operational diagnostics.

    Channels we plan to write into this table:
      - google_indexing      Google's Indexing API URL_UPDATED notification
      - bluesky              atproto post
      - mastodon             status post
      - telegram             channel broadcast
      - linkedin             company-page post
      - threads              Meta Threads post
      - medium               Medium import / canonical post
    """

    __tablename__ = "distribution_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    channel = Column(String(40), nullable=False, index=True)
    url = Column(String(1000), nullable=False, index=True)

    entity_type = Column(String(40), nullable=True)  # blog_post | landing_page | static
    entity_id = Column(Integer, nullable=True)

    success = Column(Boolean, nullable=False, default=False, index=True)
    response_code = Column(Integer, nullable=True)
    response_snippet = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class ClimateSnapshot(Base):
    """One row per calendar quarter. Stores the computed Investment
    Climate Tracker scorecard for that quarter plus the raw evidence
    used to derive it. Recomputed weekly by the climate runner; the row
    for the current quarter is upserted in place (keyed on quarter_label).
    Older rows are immutable and serve as the QoQ baseline for the next
    quarter.

    The report generator reads the most recent two rows: the latest is
    rendered as the current scorecard, and the one before it provides
    the deltas that produce the trend arrows on each bar.
    """

    __tablename__ = "climate_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)

    quarter_label = Column(String(16), nullable=False, unique=True, index=True)
    quarter_start = Column(Date, nullable=False, index=True)

    composite_score = Column(Float, nullable=True)
    period_label = Column(String(64), nullable=True)
    methodology = Column(Text, nullable=True)

    bars_json = Column(JSON, nullable=False)
    evidence_json = Column(JSON, nullable=True)

    computed_at = Column(DateTime, default=datetime.utcnow, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ScrapeLog(Base):
    """Tracks every scrape attempt for diagnostics and retry logic."""

    __tablename__ = "scrape_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(_enum_values(SourceType), nullable=False)
    scrape_date = Column(Date, nullable=False)
    success = Column(Boolean, nullable=False)
    entries_found = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ApiTier(str, enum.Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class ApiKey(Base):
    """Issued API keys for the public /api/v1/* surface."""

    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)

    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    key_prefix = Column(String(16), nullable=False)
    tier = Column(_enum_values(ApiTier), nullable=False, default=ApiTier.FREE)

    owner_email = Column(String(320), nullable=False, index=True)
    label = Column(String(200), nullable=True)

    stripe_customer_id = Column(String(200), nullable=True, index=True)
    stripe_subscription_id = Column(String(200), nullable=True)

    active = Column(Boolean, nullable=False, default=True, index=True)
    requests_today = Column(Integer, nullable=False, default=0)
    last_request_date = Column(Date, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FeedbackSubmission(Base):
    """User-submitted product feedback and tool ideas."""

    __tablename__ = "feedback_submissions"

    id = Column(Integer, primary_key=True, autoincrement=True)

    message = Column(Text, nullable=False)
    email = Column(String(320), nullable=True)
    page_url = Column(String(1000), nullable=True)
    page_path = Column(String(500), nullable=True, index=True)
    referrer = Column(String(1000), nullable=True)
    user_agent = Column(String(500), nullable=True)
    site_name = Column(String(120), nullable=False, default="Cuban Insights")

    status = Column(String(40), nullable=False, default="new", index=True)
    email_sent = Column(Boolean, nullable=False, default=False)
    email_error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)


engine = create_engine(settings.database_url, echo=False)
SessionLocal = sessionmaker(bind=engine)
_init_lock = Lock()
_db_initialized = False


def init_db(*, force: bool = False):
    """Create tables once per process, not once per request.

    Also runs lightweight, idempotent column-additions for ALTERations
    that can't be expressed by `create_all` on a pre-existing table.
    We deliberately stop short of a full Alembic setup — for a single-
    writer schema this stays simpler and safer.
    """
    global _db_initialized
    if _db_initialized and not force:
        return
    with _init_lock:
        if _db_initialized and not force:
            return
        Base.metadata.create_all(engine)
        _ensure_columns()
        _db_initialized = True


def _ensure_columns() -> None:
    """Add columns that were introduced after the table was first
    created. Cross-DB (SQLite + Postgres) safe — uses the SQLAlchemy
    inspector to check for existence before issuing an ALTER.
    """
    insp = sa_inspect(engine)
    dialect = engine.dialect.name

    # Per-dialect column type. SQLite uses BLOB for binary, Postgres BYTEA.
    blob_type = "BYTEA" if dialect == "postgresql" else "BLOB"

    additions = [
        ("blog_posts", "social_hook", "TEXT"),
        ("blog_posts", "og_image_bytes", blob_type),
    ]

    for table_name, column_name, column_type in additions:
        if table_name not in insp.get_table_names():
            continue
        existing = {c["name"] for c in insp.get_columns(table_name)}
        if column_name in existing:
            continue
        with engine.begin() as conn:
            conn.execute(
                sa_text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
            )

    if dialect == "postgresql":
        with engine.begin() as conn:
            for value in (e.value for e in SourceType):
                safe_value = value.replace("'", "''")
                conn.execute(sa_text(
                    "DO $$ BEGIN "
                    f"ALTER TYPE source_type ADD VALUE IF NOT EXISTS '{safe_value}'; "
                    "EXCEPTION WHEN duplicate_object THEN NULL; "
                    "END $$;"
                ))
            for value in (e.value for e in ApiTier):
                safe_value = value.replace("'", "''")
                conn.execute(sa_text(
                    "DO $$ BEGIN "
                    f"ALTER TYPE api_tier ADD VALUE IF NOT EXISTS '{safe_value}'; "
                    "EXCEPTION WHEN duplicate_object THEN NULL; "
                    "END $$;"
                ))
