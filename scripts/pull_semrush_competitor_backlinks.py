#!/usr/bin/env python3
"""Pull SEMrush backlink competitor data into local CSV artifacts.

This is intentionally conservative with display limits because SEMrush
backlink reports are billed per returned line.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import urlopen


API_BASE = "https://api.semrush.com/analytics/v1/"
BALANCE_URL = "https://www.semrush.com/users/countapiunits.html"


def load_env_key(path: Path) -> str:
    if os.getenv("SEMRUSH_API_KEY"):
        return os.environ["SEMRUSH_API_KEY"].strip()

    if not path.exists():
        return ""

    pattern = re.compile(r"^SEMRUSH_API_KEY\s*=\s*(.*)$")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(raw_line.strip())
        if not match:
            continue
        value = match.group(1).strip().strip('"').strip("'")
        if value:
            return value
    return ""


def semrush_get(params: dict[str, str | int | list[str]]) -> str:
    query_items: list[tuple[str, str | int]] = []
    for key, value in params.items():
        if isinstance(value, list):
            query_items.extend((key, item) for item in value)
        else:
            query_items.append((key, value))

    url = f"{API_BASE}?{urlencode(query_items)}"
    try:
        with urlopen(url, timeout=60) as response:
            return response.read().decode("utf-8-sig")
    except HTTPError as exc:
        body = exc.read().decode("utf-8-sig", errors="replace").strip()
        raise RuntimeError(body or f"HTTP {exc.code}: {exc.reason}") from exc


def get_balance(api_key: str) -> str:
    url = f"{BALANCE_URL}?{urlencode({'key': api_key})}"
    with urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8").strip()


def parse_csv(text: str) -> list[dict[str, str]]:
    if text.startswith("ERROR"):
        raise RuntimeError(text.strip())
    rows = list(csv.DictReader(text.splitlines(), delimiter=";"))
    return rows


def write_rows(path: Path, rows: Iterable[dict[str, str]]) -> int:
    materialized = list(rows)
    if not materialized:
        path.write_text("", encoding="utf-8")
        return 0

    fieldnames: list[str] = []
    for row in materialized:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(materialized)
    return len(materialized)


def clean_domain(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^https?://", "", value)
    value = value.split("/", 1)[0]
    return value.lower()


def write_combined_refdomains(out_dir: Path) -> int:
    combined: dict[str, dict[str, object]] = {}
    for path in out_dir.glob("*_refdomains.csv"):
        competitor = path.name.removesuffix("_refdomains.csv")
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                domain = row.get("domain", "").strip()
                if not domain:
                    continue
                item = combined.setdefault(
                    domain,
                    {
                        "competitors": set(),
                        "max_ascore": 0,
                        "total_backlinks": 0,
                        "countries": set(),
                    },
                )
                item["competitors"].add(competitor)
                item["max_ascore"] = max(int(item["max_ascore"]), int(row.get("domain_ascore") or 0))
                item["total_backlinks"] = int(item["total_backlinks"]) + int(row.get("backlinks_num") or 0)
                country = row.get("country", "").strip()
                if country:
                    item["countries"].add(country)

    rows = [
        {
            "domain": domain,
            "competitor_count": len(item["competitors"]),
            "competitors": ";".join(sorted(item["competitors"])),
            "max_ascore": item["max_ascore"],
            "total_competitor_backlinks_in_pull": item["total_backlinks"],
            "countries": ";".join(sorted(item["countries"])),
        }
        for domain, item in combined.items()
    ]
    rows.sort(
        key=lambda row: (
            -int(row["competitor_count"]),
            -int(row["max_ascore"]),
            -int(row["total_competitor_backlinks_in_pull"]),
            str(row["domain"]),
        )
    )
    return write_rows(out_dir / "combined_refdomain_opportunities.csv", rows)


def extract_host(value: str) -> str:
    parsed = urlparse(value)
    host = parsed.netloc or urlparse(f"https://{value}").netloc
    return host.lower().removeprefix("www.")


def write_combined_backlink_prospects(out_dir: Path) -> int:
    rows: list[dict[str, str | int]] = []
    for path in out_dir.glob("*_backlinks.csv"):
        competitor = path.name.removesuffix("_backlinks.csv")
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                source_url = row.get("source_url", "").strip()
                target_url = row.get("target_url", "").strip()
                if not source_url or not target_url:
                    continue
                rows.append(
                    {
                        "competitor": competitor,
                        "source_domain": extract_host(source_url),
                        "source_url": source_url,
                        "source_title": row.get("source_title", "").strip(),
                        "competitor_target_url": target_url,
                        "anchor": row.get("anchor", "").strip(),
                        "page_ascore": row.get("page_ascore", "").strip(),
                        "first_seen": row.get("first_seen", "").strip(),
                        "last_seen": row.get("last_seen", "").strip(),
                        "nofollow": row.get("nofollow", "").strip(),
                        "sitewide": row.get("sitewide", "").strip(),
                        "external_num": row.get("external_num", "").strip(),
                        "internal_num": row.get("internal_num", "").strip(),
                    }
                )

    rows.sort(
        key=lambda row: (
            -int(row["page_ascore"] or 0),
            str(row["source_domain"]),
            str(row["competitor"]),
            str(row["source_url"]),
        )
    )
    return write_rows(out_dir / "combined_backlink_prospects.csv", rows)


def write_keyword_backlink_prospects(out_dir: Path, keywords: list[str]) -> int:
    combined_path = out_dir / "combined_backlink_prospects.csv"
    if not combined_path.exists() or not keywords:
        return 0

    lowered_keywords = [keyword.lower() for keyword in keywords if keyword.strip()]
    rows: list[dict[str, str]] = []
    with combined_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            haystack = " ".join(
                [
                    row.get("source_url", ""),
                    row.get("source_title", ""),
                    row.get("competitor_target_url", ""),
                    row.get("anchor", ""),
                ]
            ).lower()
            if any(keyword in haystack for keyword in lowered_keywords):
                rows.append(row)

    return write_rows(out_dir / "cuba_related_backlink_prospects.csv", rows)


def write_deduped_source_url_prospects(out_dir: Path, input_name: str, output_name: str) -> int:
    input_path = out_dir / input_name
    if not input_path.exists():
        return 0

    grouped: dict[str, dict[str, object]] = {}
    with input_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            source_url = row.get("source_url", "").strip()
            if not source_url:
                continue
            item = grouped.setdefault(
                source_url,
                {
                    "source_url": source_url,
                    "source_domain": row.get("source_domain", "").strip(),
                    "source_title": row.get("source_title", "").strip(),
                    "best_page_ascore": 0,
                    "nofollow_values": set(),
                    "sitewide_values": set(),
                    "competitors": set(),
                    "competitor_target_urls": set(),
                    "anchors": set(),
                    "first_seen_values": [],
                    "last_seen_values": [],
                    "rows": 0,
                },
            )
            item["rows"] = int(item["rows"]) + 1
            item["best_page_ascore"] = max(int(item["best_page_ascore"]), int(row.get("page_ascore") or 0))
            item["nofollow_values"].add(row.get("nofollow", "").strip())
            item["sitewide_values"].add(row.get("sitewide", "").strip())
            item["competitors"].add(row.get("competitor", "").strip())
            item["competitor_target_urls"].add(row.get("competitor_target_url", "").strip())
            item["anchors"].add(row.get("anchor", "").strip())
            if row.get("first_seen"):
                item["first_seen_values"].append(row["first_seen"])
            if row.get("last_seen"):
                item["last_seen_values"].append(row["last_seen"])

    rows: list[dict[str, str | int]] = []
    for item in grouped.values():
        first_seen_values = [value for value in item["first_seen_values"] if value]
        last_seen_values = [value for value in item["last_seen_values"] if value]
        rows.append(
            {
                "source_domain": item["source_domain"],
                "source_url": item["source_url"],
                "source_title": item["source_title"],
                "best_page_ascore": item["best_page_ascore"],
                "competitor_link_count_on_source_url": item["rows"],
                "competitor_count": len({value for value in item["competitors"] if value}),
                "competitors": ";".join(sorted(value for value in item["competitors"] if value)),
                "competitor_target_urls": ";".join(
                    sorted(value for value in item["competitor_target_urls"] if value)
                ),
                "anchors": ";".join(sorted(value for value in item["anchors"] if value)),
                "nofollow_values": ";".join(sorted(value for value in item["nofollow_values"] if value)),
                "sitewide_values": ";".join(sorted(value for value in item["sitewide_values"] if value)),
                "first_seen_min": min(first_seen_values) if first_seen_values else "",
                "last_seen_max": max(last_seen_values) if last_seen_values else "",
            }
        )

    rows.sort(
        key=lambda row: (
            -int(row["best_page_ascore"]),
            -int(row["competitor_count"]),
            -int(row["competitor_link_count_on_source_url"]),
            str(row["source_domain"]),
            str(row["source_url"]),
        )
    )
    return write_rows(out_dir / output_name, rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="cubaninsights.com")
    parser.add_argument("--target-type", default="root_domain", choices=["root_domain", "domain", "url"])
    parser.add_argument(
        "--competitors",
        default="",
        help="Comma-separated domains to pull instead of SEMrush-discovered backlink competitors.",
    )
    parser.add_argument("--competitor-limit", type=int, default=5)
    parser.add_argument("--backlinks-per-competitor", type=int, default=25)
    parser.add_argument("--refdomains-per-competitor", type=int, default=25)
    parser.add_argument("--target-url-or-anchor-contains", default="")
    parser.add_argument("--follow-only", action="store_true")
    parser.add_argument(
        "--local-keywords",
        default="cuba,cuban,havana,caribbean,ofac,sanctions,embargo",
        help="Comma-separated keywords used to create cuba_related_backlink_prospects.csv locally.",
    )
    parser.add_argument("--output-dir", default="storage/semrush_backlinks")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args()

    api_key = load_env_key(Path(args.env_file))
    if not api_key:
        raise SystemExit("SEMRUSH_API_KEY is not set")

    target = clean_domain(args.target)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.output_dir) / f"{target}_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    balance_before = get_balance(api_key)

    common_params = {
        "key": api_key,
        "target": target,
        "target_type": args.target_type,
    }

    explicit_competitors = [clean_domain(item) for item in args.competitors.split(",") if item.strip()]
    if explicit_competitors:
        competitors = [{"neighbour": domain} for domain in explicit_competitors]
    else:
        competitors_csv = semrush_get(
            {
                **common_params,
                "type": "backlinks_competitors",
                "export_columns": "ascore,neighbour,similarity,common_refdomains,domains_num,backlinks_num",
                "display_limit": args.competitor_limit,
            }
        )
        competitors = parse_csv(competitors_csv)
    write_rows(out_dir / "competitors.csv", competitors)

    backlinks_counts: dict[str, int] = {}
    refdomain_counts: dict[str, int] = {}
    errors: dict[str, str] = {}

    for competitor in competitors:
        domain = clean_domain(competitor.get("neighbour", ""))
        if not domain:
            continue

        safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", domain)

        backlink_params = {
                    "key": api_key,
                    "type": "backlinks",
                    "target": domain,
                    "target_type": "root_domain",
                    "export_columns": "page_ascore,source_title,source_url,target_url,anchor,external_num,internal_num,first_seen,last_seen,nofollow,sitewide,newlink,lostlink",
                    "display_sort": "page_ascore_desc",
                    "display_limit": args.backlinks_per_competitor,
                }
        if args.follow_only or args.target_url_or_anchor_contains:
            filters = []
            if args.follow_only:
                filters.append("+|type||follow")
            if args.target_url_or_anchor_contains:
                filters.append(f"+|urlanchor|Co|{args.target_url_or_anchor_contains}")
            backlink_params["display_filter"] = "".join(filters)

        if args.backlinks_per_competitor > 0:
            try:
                backlinks = parse_csv(semrush_get(backlink_params))
            except RuntimeError as exc:
                backlinks = []
                errors[f"{domain}:backlinks"] = str(exc)
            backlinks_counts[domain] = write_rows(out_dir / f"{safe_name}_backlinks.csv", backlinks)

        if args.refdomains_per_competitor > 0:
            try:
                refdomains = parse_csv(
                    semrush_get(
                        {
                    "key": api_key,
                    "type": "backlinks_refdomains",
                    "target": domain,
                    "target_type": "root_domain",
                    "export_columns": "domain_ascore,domain,backlinks_num,ip,country,first_seen,last_seen",
                    "display_sort": "domain_ascore_desc",
                    "display_limit": args.refdomains_per_competitor,
                        }
                    )
                )
            except RuntimeError as exc:
                refdomains = []
                errors[f"{domain}:refdomains"] = str(exc)
            refdomain_counts[domain] = write_rows(out_dir / f"{safe_name}_refdomains.csv", refdomains)

    combined_refdomain_count = write_combined_refdomains(out_dir)
    combined_backlink_count = write_combined_backlink_prospects(out_dir)
    keyword_backlink_count = write_keyword_backlink_prospects(
        out_dir, [keyword.strip() for keyword in args.local_keywords.split(",")]
    )
    deduped_source_url_count = write_deduped_source_url_prospects(
        out_dir, "combined_backlink_prospects.csv", "deduped_source_url_prospects.csv"
    )
    deduped_keyword_source_url_count = write_deduped_source_url_prospects(
        out_dir, "cuba_related_backlink_prospects.csv", "deduped_cuba_source_url_prospects.csv"
    )
    balance_after = get_balance(api_key)

    summary = {
        "target": target,
        "target_type": args.target_type,
        "pulled_at_utc": timestamp,
        "balance_before": balance_before,
        "balance_after": balance_after,
        "competitor_count": len(competitors),
        "backlinks_counts": backlinks_counts,
        "refdomain_counts": refdomain_counts,
        "combined_refdomain_count": combined_refdomain_count,
        "combined_backlink_count": combined_backlink_count,
        "keyword_backlink_count": keyword_backlink_count,
        "deduped_source_url_count": deduped_source_url_count,
        "deduped_keyword_source_url_count": deduped_keyword_source_url_count,
        "errors": errors,
        "files": sorted(path.name for path in out_dir.iterdir()),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"output_dir": str(out_dir), **summary}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
