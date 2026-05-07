#!/usr/bin/env python3
"""
CLI entry point for the SEO audit.

Usage:
    python scripts/seo_audit.py                   # Human-readable summary
    python scripts/seo_audit.py --json              # Machine-readable JSON
    python scripts/seo_audit.py --verbose          # Show all findings (not just errors/warnings)
    python scripts/seo_audit.py --fail-on-error    # Exit 1 if any errors found
    python scripts/seo_audit.py --max-pages 50     # Limit crawl depth
    python scripts/seo_audit.py --no-follow        # Don't follow internal links (seeds only)
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("SITE_URL", "https://cubaninsights.com")

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


@click.command()
@click.option("--json", "json_out", is_flag=True, help="Output as JSON")
@click.option("--verbose", is_flag=True, help="Show info-level findings too")
@click.option("--fail-on-error", is_flag=True, help="Exit 1 if any errors")
@click.option("--max-pages", type=int, default=200, help="Max pages to crawl")
@click.option("--no-follow", is_flag=True, help="Don't follow internal links")
def main(json_out: bool, verbose: bool, fail_on_error: bool, max_pages: int, no_follow: bool):
    """Run the Cuban Insights SEO audit."""
    if not json_out:
        console.print(Panel("[bold]Cuban Insights — SEO Audit[/bold]", style="blue"))
        console.print("Crawling local Flask app...\n")

    start = time.time()

    from src.seo.audit import run_audit
    report = run_audit(max_pages=max_pages, follow_links=not no_follow)

    elapsed = time.time() - start

    if json_out:
        out = report.to_dict()
        out["elapsed_seconds"] = round(elapsed, 1)
        print(json.dumps(out, indent=2))
    else:
        # Summary table
        summary = Table(title="SEO Audit Summary")
        summary.add_column("Metric", style="bold")
        summary.add_column("Value")
        summary.add_row("Pages crawled", str(report.pages_crawled))
        summary.add_row("Pages OK (200)", str(report.pages_ok))
        summary.add_row("Errors", f"[red]{len(report.errors)}[/red]" if report.errors else "[green]0[/green]")
        summary.add_row("Warnings", f"[yellow]{len(report.warnings)}[/yellow]" if report.warnings else "[green]0[/green]")
        summary.add_row("Info", str(len(report.info)))
        summary.add_row("Duration", f"{elapsed:.1f}s")
        console.print(summary)

        # Findings
        if report.errors:
            console.print(f"\n[bold red]ERRORS ({len(report.errors)}):[/bold red]")
            for f in report.errors:
                console.print(f"  [red]✗[/red] [{f.category}] {f.path}  {f.message}")

        if report.warnings:
            console.print(f"\n[bold yellow]WARNINGS ({len(report.warnings)}):[/bold yellow]")
            for f in report.warnings[:50]:
                console.print(f"  [yellow]![/yellow] [{f.category}] {f.path}  {f.message}")
            remaining = len(report.warnings) - 50
            if remaining > 0:
                console.print(f"  ... and {remaining} more")

        if verbose and report.info:
            console.print(f"\n[bold]INFO ({len(report.info)}):[/bold]")
            for f in report.info[:30]:
                console.print(f"  [dim]·[/dim] [{f.category}] {f.path}  {f.message}")
            remaining = len(report.info) - 30
            if remaining > 0:
                console.print(f"  ... and {remaining} more")

    if fail_on_error and report.errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
