#!/usr/bin/env python3
"""
CLI tool to generate, list, or revoke API keys.

Usage:
    python scripts/generate_api_key.py create --email user@example.com --tier pro
    python scripts/generate_api_key.py list
    python scripts/generate_api_key.py revoke --email user@example.com
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import click

from src.api.auth import generate_raw_key, hash_key, _get_prefix
from src.models import ApiKey, ApiTier, SessionLocal, init_db


@click.group()
def cli():
    """Manage Cuban Insights API keys."""
    pass


@cli.command()
@click.option("--email", required=True, help="Owner email address")
@click.option("--tier", type=click.Choice(["free", "pro", "enterprise"]), default="free")
@click.option("--label", default=None, help="Optional label for the key")
@click.option("--send-email/--no-send-email", default=False, help="Send the key via Resend")
def create(email: str, tier: str, label: str | None, send_email: bool):
    """Create a new API key."""
    init_db()
    db = SessionLocal()
    try:
        raw = generate_raw_key()
        row = ApiKey(
            key_hash=hash_key(raw),
            key_prefix=_get_prefix(raw),
            tier=ApiTier(tier),
            owner_email=email.lower(),
            label=label or f"{tier.capitalize()} tier (CLI)",
        )
        db.add(row)
        db.commit()

        click.echo(f"\nAPI key created:")
        click.echo(f"  Key:   {raw}")
        click.echo(f"  Tier:  {tier}")
        click.echo(f"  Email: {email}")
        click.echo(f"\n  ** Save this key — it cannot be recovered. **\n")

        if send_email:
            from src.api.email import send_api_key_email
            ok = send_api_key_email(to_email=email.lower(), raw_key=raw, tier=tier)
            click.echo(f"  Email sent: {'yes' if ok else 'FAILED'}")
    finally:
        db.close()


@cli.command("list")
def list_keys():
    """List all API keys."""
    init_db()
    db = SessionLocal()
    try:
        keys = db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()
        if not keys:
            click.echo("No API keys found.")
            return
        click.echo(f"\n{'ID':<5} {'Prefix':<18} {'Tier':<12} {'Email':<30} {'Active':<8} {'Req Today':<10} {'Created'}")
        click.echo("-" * 110)
        for k in keys:
            tier_val = k.tier.value if hasattr(k.tier, 'value') else k.tier
            click.echo(
                f"{k.id:<5} {k.key_prefix:<18} {tier_val:<12} {k.owner_email:<30} "
                f"{'yes' if k.active else 'no':<8} {k.requests_today:<10} {k.created_at}"
            )
        click.echo()
    finally:
        db.close()


@cli.command()
@click.option("--email", required=True, help="Revoke all active keys for this email")
def revoke(email: str):
    """Revoke all active API keys for an email."""
    init_db()
    db = SessionLocal()
    try:
        keys = (
            db.query(ApiKey)
            .filter(ApiKey.owner_email == email.lower(), ApiKey.active.is_(True))
            .all()
        )
        if not keys:
            click.echo(f"No active keys found for {email}")
            return
        for k in keys:
            k.active = False
        db.commit()
        click.echo(f"Revoked {len(keys)} key(s) for {email}")
    finally:
        db.close()


if __name__ == "__main__":
    cli()
