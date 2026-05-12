"""
Pydantic response models for the public API.

Each model mirrors a database row or computed object, exposing only the
fields appropriate for external consumers.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel


class BriefingSummary(BaseModel):
    slug: str
    title: str
    subtitle: Optional[str] = None
    summary: Optional[str] = None
    primary_sector: Optional[str] = None
    sectors: Optional[list[str]] = None
    published_date: date
    word_count: Optional[int] = None
    reading_minutes: Optional[int] = None
    url: str


class BriefingDetail(BriefingSummary):
    body_html: str
    keywords: Optional[list[str]] = None
    canonical_source_url: Optional[str] = None


class FXRate(BaseModel):
    usd_cup: Optional[float] = None
    eur_cup: Optional[float] = None
    mlc_cup: Optional[float] = None
    usdt_cup: Optional[float] = None
    date: Optional[str] = None
    attribution: str = "Tasa Representativa del Mercado Informal — elTOQUE (tasas.eltoque.com)"


class FXRateHistoryPoint(BaseModel):
    date: str
    usd_cup: Optional[float] = None
    mlc_cup: Optional[float] = None
    usdt_cup: Optional[float] = None


class CompanySummary(BaseModel):
    ticker: str
    name: str
    sector: str
    sub_industry: str
    slug: str
    has_curated_exposure: bool


class CompanyExposure(BaseModel):
    ticker: str
    name: str
    sector: str
    classification: str
    headline: str
    summary: str
    exposure_level: Optional[str] = None
    ofac_licenses: Optional[list[str]] = None
    subsidiaries: Optional[list[str]] = None
    sdn_matches: list[dict[str, Any]] = []
    corpus_mentions: int = 0
    edgar_hits: int = 0
    generated_at: str = ""


class SanctionEntry(BaseModel):
    id: int
    source: str
    headline: str
    published_date: date
    source_url: str
    source_name: Optional[str] = None
    article_type: Optional[str] = None
    extra_metadata: Optional[dict[str, Any]] = None


class ClimateScorecard(BaseModel):
    quarter_label: str
    composite_score: Optional[float] = None
    period_label: Optional[str] = None
    bars: Any = None
    computed_at: Optional[datetime] = None


class PaginatedResponse(BaseModel):
    data: list[Any]
    page: int
    per_page: int
    total: int
    has_more: bool
