"""Compute dashboard statistics from backup_runs."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from app.models.backup import BackupRun


def get_dashboard_stats(db: DBSession, days: int = 30) -> dict:
    """Compute summary stats for the dashboard."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Total backups in period
    total_backups = (
        db.query(func.count(BackupRun.id))
        .filter(BackupRun.started_at >= cutoff)
        .scalar()
    ) or 0

    # Success count
    success_count = (
        db.query(func.count(BackupRun.id))
        .filter(BackupRun.started_at >= cutoff, BackupRun.status == "success")
        .scalar()
    ) or 0

    # Failure count
    failure_count = (
        db.query(func.count(BackupRun.id))
        .filter(BackupRun.started_at >= cutoff, BackupRun.status == "failure")
        .scalar()
    ) or 0

    # Success rate
    success_rate = (success_count / total_backups * 100) if total_backups > 0 else 0

    # Latest backup
    last_backup = (
        db.query(BackupRun)
        .filter(BackupRun.status != "running")
        .order_by(BackupRun.started_at.desc())
        .first()
    )

    # Total size from most recent successful backup
    latest_size = (
        db.query(BackupRun.total_size_bytes)
        .filter(BackupRun.status == "success", BackupRun.total_size_bytes.isnot(None))
        .order_by(BackupRun.started_at.desc())
        .first()
    )

    # Average duration for successful backups in period
    avg_duration = (
        db.query(func.avg(BackupRun.duration_seconds))
        .filter(
            BackupRun.started_at >= cutoff,
            BackupRun.status == "success",
            BackupRun.duration_seconds.isnot(None),
        )
        .scalar()
    )

    return {
        "total_backups": total_backups,
        "success_count": success_count,
        "failure_count": failure_count,
        "success_rate": round(success_rate, 1),
        "last_backup": last_backup,
        "latest_size_bytes": latest_size[0] if latest_size else None,
        "avg_duration_seconds": round(avg_duration, 0) if avg_duration else None,
    }


def get_backup_type_counts(db: DBSession, days: int = 30) -> dict:
    """Get backup counts grouped by type for chart."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(BackupRun.backup_type, func.count(BackupRun.id))
        .filter(BackupRun.started_at >= cutoff)
        .group_by(BackupRun.backup_type)
        .all()
    )
    return {row[0]: row[1] for row in rows}


def get_daily_sizes(db: DBSession, days: int = 30) -> list[dict]:
    """Get daily backup sizes for bar chart."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(
            func.date(BackupRun.started_at).label("day"),
            func.max(BackupRun.total_size_bytes).label("size"),
        )
        .filter(
            BackupRun.started_at >= cutoff,
            BackupRun.status == "success",
            BackupRun.total_size_bytes.isnot(None),
        )
        .group_by(func.date(BackupRun.started_at))
        .order_by(func.date(BackupRun.started_at))
        .all()
    )
    return [{"date": str(row.day), "size": row.size} for row in rows]


def get_recent_backups(db: DBSession, limit: int = 10) -> list[BackupRun]:
    """Get most recent backup runs."""
    return (
        db.query(BackupRun)
        .order_by(BackupRun.started_at.desc())
        .limit(limit)
        .all()
    )
