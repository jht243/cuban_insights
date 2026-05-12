"""Company Cuba-exposure endpoints."""

from __future__ import annotations

from flask import jsonify

from src.api import api_v1
from src.api.auth import require_api_key
from src.api.serializers import CompanyExposure, CompanySummary


@api_v1.route("/companies")
@require_api_key
def companies_list():
    from src.data.sp500_companies import load_companies

    companies = load_companies()
    from src.data.curated_cuba_exposure import all_curated_tickers
    curated_tickers = all_curated_tickers()

    data = []
    for c in companies:
        data.append(CompanySummary(
            ticker=c.ticker,
            name=c.name,
            sector=c.sector,
            sub_industry=c.sub_industry,
            slug=c.slug,
            has_curated_exposure=c.ticker in curated_tickers,
        ).model_dump(mode="json"))

    return jsonify({"data": data, "count": len(data)})


@api_v1.route("/companies/<ticker>/exposure")
@require_api_key
def companies_exposure(ticker: str):
    from src.data.company_exposure import build_exposure_report, find_company_by_slug
    from src.data.sp500_companies import load_companies

    ticker_upper = ticker.upper()
    companies = load_companies()
    company = None
    for c in companies:
        if c.ticker == ticker_upper:
            company = c
            break

    if company is None:
        company = find_company_by_slug(ticker)

    if company is None:
        return jsonify({"error": f"Company not found: {ticker}"}), 404

    report = build_exposure_report(company)

    curated = report.curated
    return jsonify(CompanyExposure(
        ticker=company.ticker,
        name=company.name,
        sector=company.sector,
        classification=report.classification,
        headline=report.headline,
        summary=report.summary,
        exposure_level=curated.exposure_level if curated else None,
        ofac_licenses=list(curated.ofac_licenses) if curated else None,
        subsidiaries=list(curated.subsidiaries) if curated else None,
        sdn_matches=[
            {"name": m.name, "program": m.program, "sdn_type": m.sdn_type,
             "match_basis": m.match_basis}
            for m in report.sdn_matches
        ],
        corpus_mentions=len(report.corpus_mentions),
        edgar_hits=report.edgar_total_hits,
        generated_at=report.generated_at,
    ).model_dump(mode="json"))
