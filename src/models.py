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
    UniqueConstraint,
)
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
    GACETA_OFICIAL = "gaceta_oficial"
    TU_GACETA = "tu_gaceta"
    ASAMBLEA_NACIONAL = "asamblea_nacional"
    TSJ = "tsj"
    FEDERAL_REGISTER = "federal_register"
    OFAC_SDN = "ofac_sdn"
    GDELT = "gdelt"
    BCV_RATES = "bcv_rates"
    TRAVEL_ADVISORY = "travel_advisory"
    NEWSDATA = "newsdata"
    EIA = "eia"


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
    Evergreen landing pages — the pillar /invest-in-venezuela, the
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


engine = create_engine(settings.database_url, echo=False)
SessionLocal = sessionmaker(bind=engine)
_init_lock = Lock()
_db_initialized = False


def init_db(*, force: bool = False):
    """Create tables once per process, not once per request."""
    global _db_initialized
    if _db_initialized and not force:
        return
    with _init_lock:
        if _db_initialized and not force:
            return
        Base.metadata.create_all(engine)
        _db_initialized = True
