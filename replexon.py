#!/usr/bin/env python3
"""RePlexOn CLI - "Previously on your Plex server..."

TV-themed backup management commands:
  --broadcast   Start a backup ("the live show")
  --rerun       Restore the most recent backup
  --syndicate   Export backup to cloud/external drive
  --static      Health check on existing backup files

Admin commands:
  init-db       Initialize the database
  create-user   Create a new user account
  import-logs   Parse backup logs and import into database
  reset-password Reset a user's password
"""

import click
import sys

BANNER = r"""
  ____       ____  _            ___
 |  _ \ ___ |  _ \| | _____  __/ _ \ _ __
 | |_) / _ \| |_) | |/ _ \ \/ / | | | '_ \
 |  _ <  __/|  __/| |  __/>  <| |_| | | | |
 |_| \_\___||_|   |_|\___/_/\_\\___/|_| |_|
 ==========================================
      "Previously on your Plex server..."
"""


@click.group(invoke_without_command=True)
@click.option("--broadcast", is_flag=True, help='Start a backup ("the live show")')
@click.option("--rerun", is_flag=True, help="Restore the most recent backup")
@click.option("--syndicate", is_flag=True, help="Export backup to cloud/external drive")
@click.option("--static", "healthcheck", is_flag=True, help="Health check on backup files")
@click.pass_context
def cli(ctx, broadcast, rerun, syndicate, healthcheck):
    """RePlexOn - Plex Backup Dashboard CLI."""
    if ctx.invoked_subcommand is not None:
        return

    if broadcast:
        _broadcast()
    elif rerun:
        _rerun()
    elif syndicate:
        _syndicate()
    elif healthcheck:
        _healthcheck()
    else:
        click.echo(BANNER)
        click.echo("Use --help for available commands.")


def _broadcast():
    """Trigger a manual backup."""
    click.echo(BANNER)
    click.echo("[BROADCAST] Starting live backup...")
    from app.database import SessionLocal
    from app.services.backup_runner import trigger_backup

    db = SessionLocal()
    try:
        result = trigger_backup(db)
        if isinstance(result, str):
            click.echo(f"[ERROR] {result}")
            sys.exit(1)
        click.echo(f"[ON AIR] Backup #{result.id} started. Check the dashboard for progress.")
    finally:
        db.close()


def _rerun():
    """Show info about the most recent backup."""
    click.echo(BANNER)
    click.echo("[RERUN] Most recent backup:")
    from app.database import SessionLocal
    from app.models.backup import BackupRun

    db = SessionLocal()
    try:
        last = db.query(BackupRun).order_by(BackupRun.started_at.desc()).first()
        if not last:
            click.echo("  No backups recorded yet.")
            return
        click.echo(f"  Type:     {last.backup_type}")
        click.echo(f"  Status:   {last.status}")
        click.echo(f"  Started:  {last.started_at}")
        click.echo(f"  Duration: {last.duration_display}")
        click.echo(f"  Size:     {last.size_display}")
    finally:
        db.close()


def _syndicate():
    """Export info (placeholder for cloud/external export)."""
    click.echo(BANNER)
    click.echo("[SYNDICATE] Export to external storage - coming soon.")
    click.echo("  This feature will support cloud and external drive targets.")


def _healthcheck():
    """Run health checks on backup files."""
    click.echo(BANNER)
    click.echo("[STATIC] Running health check...")
    from pathlib import Path
    from app.config import settings

    log_path = Path(settings.backup_log_path)
    script_path = Path(settings.backup_script_path)

    checks = [
        ("Backup log exists", log_path.exists()),
        ("Backup script exists", script_path.exists()),
    ]

    if log_path.exists():
        size_mb = log_path.stat().st_size / (1024 * 1024)
        checks.append((f"Log file size: {size_mb:.1f} MB", True))

    for label, ok in checks:
        status = click.style("OK", fg="green") if ok else click.style("FAIL", fg="red")
        click.echo(f"  [{status}] {label}")


# ===== Admin Commands =====

@cli.command()
def init_db():
    """Initialize the database (create all tables)."""
    click.echo(BANNER)
    from pathlib import Path
    from app.database import Base, engine
    import app.models  # noqa: F401 — register all models with Base.metadata
    Path("data").mkdir(exist_ok=True)
    Base.metadata.create_all(bind=engine)
    click.echo("[OK] Database initialized successfully.")


@cli.command()
@click.option("--username", prompt=True, help="Username for the new user")
@click.option("--email", prompt=True, help="Email address")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True, help="Password")
@click.option("--admin", is_flag=True, default=False, help="Grant admin privileges")
def create_user(username, email, password, admin):
    """Create a new user account."""
    from app.database import SessionLocal
    from app.models.user import User
    from app.services.auth_service import hash_password

    db = SessionLocal()
    try:
        existing = db.query(User).filter(
            (User.username == username) | (User.email == email)
        ).first()
        if existing:
            click.echo(f"Error: User '{username}' or email '{email}' already exists.")
            sys.exit(1)

        user = User(
            username=username,
            email=email,
            password_hash=hash_password(password),
            is_admin=admin,
        )
        db.add(user)
        db.commit()
        click.echo(f"[OK] User '{username}' created{' (admin)' if admin else ''}.")
    finally:
        db.close()


@cli.command()
@click.option("--username", prompt=True, help="Username to reset")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True, help="New password")
def reset_password(username, password):
    """Reset a user's password."""
    from app.database import SessionLocal
    from app.models.user import User
    from app.services.auth_service import hash_password

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            click.echo(f"Error: User '{username}' not found.")
            sys.exit(1)

        user.password_hash = hash_password(password)
        db.commit()
        click.echo(f"[OK] Password reset for user '{username}'.")
    finally:
        db.close()


@cli.command()
def import_logs():
    """Parse backup logs and import historical records into the database."""
    click.echo(BANNER)
    from app.config import settings
    from app.database import SessionLocal
    from app.services.log_parser import (
        parse_full_log, extract_stats_file, enrich_from_stats,
    )

    # Step 1: Extract stats from the big log (one-time, slow but cached)
    click.echo("[IMPORT] Extracting stats from main log (this may take a few minutes)...")
    stats_path = extract_stats_file(settings.backup_log_path)
    if stats_path:
        click.echo(f"[OK] Stats extracted to {stats_path}")
    else:
        click.echo("[WARN] Could not extract stats from main log (file missing or timeout)")

    # Step 2: Import tracking file + enrich from stats
    click.echo("[IMPORT] Importing backup records...")
    db = SessionLocal()
    try:
        count = parse_full_log(db, settings.backup_log_path)
        click.echo(f"[OK] Imported {count} new backup records.")

        if stats_path:
            enriched = enrich_from_stats(db, stats_path)
            click.echo(f"[OK] Enriched {enriched} records with size/duration data.")
    finally:
        db.close()


if __name__ == "__main__":
    cli()
