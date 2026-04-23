"""Compute dashboard statistics from backup_runs."""

import calendar
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


def get_daily_durations(db: DBSession, days: int = 30) -> list[dict]:
    """Get daily backup durations for trend chart."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(
            func.date(BackupRun.started_at).label("day"),
            func.max(BackupRun.duration_seconds).label("duration"),
        )
        .filter(
            BackupRun.started_at >= cutoff,
            BackupRun.status == "success",
            BackupRun.backup_type == "daily_mirror",
            BackupRun.duration_seconds.isnot(None),
        )
        .group_by(func.date(BackupRun.started_at))
        .order_by(func.date(BackupRun.started_at))
        .all()
    )
    return [{"date": str(row.day), "minutes": round(row.duration / 60, 1)} for row in rows]


def get_calendar_data(db: DBSession, months: int = 4) -> list[dict]:
    """Get month-by-month backup status for heatmap calendar.

    Returns a list of month dicts, newest first:
    [{"year": 2026, "month": 4, "label": "Apr 2026", "days_in_month": 30,
      "statuses": {"1": "success", "5": "failure", ...}}]
    Days not in statuses = no backup attempt.
    """
    today = datetime.now(timezone.utc).date()
    result = []

    for i in range(months):
        # Walk backwards by month
        year = today.year
        month = today.month - i
        while month <= 0:
            month += 12
            year -= 1

        days_in = calendar.monthrange(year, month)[1]
        month_start = datetime(year, month, 1, tzinfo=timezone.utc)
        month_end = datetime(year, month, days_in, 23, 59, 59, tzinfo=timezone.utc)

        rows = (
            db.query(
                func.date(BackupRun.started_at).label("day"),
                BackupRun.status,
            )
            .filter(
                BackupRun.started_at >= month_start,
                BackupRun.started_at <= month_end,
                BackupRun.backup_type == "daily_mirror",
            )
            .all()
        )

        statuses = {}
        for row in rows:
            day_str = str(row.day)
            day_num = int(day_str.split("-")[2])
            existing = statuses.get(day_num)
            if existing == "failure":
                continue
            statuses[day_num] = row.status

        month_name = calendar.month_abbr[month]
        result.append({
            "year": year,
            "month": month,
            "label": f"{month_name} {year}",
            "days_in_month": days_in,
            "statuses": statuses,
        })

    return result


def get_failure_clusters(db: DBSession, days: int = 30) -> list[dict]:
    """Detect failure patterns: consecutive streaks vs isolated one-offs.

    Returns a list of cluster dicts:
    [{"type": "streak", "count": 3, "start": "Apr 15", "end": "Apr 17",
      "message": "3 consecutive failures Apr 15–17"},
     {"type": "isolated", "date": "Apr 20",
      "message": "Isolated failure on Apr 20"}]
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(BackupRun.started_at, BackupRun.status)
        .filter(
            BackupRun.started_at >= cutoff,
            BackupRun.backup_type == "daily_mirror",
        )
        .order_by(BackupRun.started_at)
        .all()
    )

    if not rows:
        return []

    clusters = []
    streak_start = None
    streak_count = 0

    for i, row in enumerate(rows):
        if row.status == "failure":
            if streak_count == 0:
                streak_start = row.started_at
            streak_count += 1
        else:
            if streak_count > 0:
                _emit_cluster(clusters, streak_start, rows[i - 1].started_at, streak_count)
            streak_count = 0
            streak_start = None

    if streak_count > 0:
        _emit_cluster(clusters, streak_start, rows[-1].started_at, streak_count)

    return clusters


def _emit_cluster(clusters: list, start_dt, end_dt, count: int):
    start_str = start_dt.strftime("%b %d")
    if count == 1:
        clusters.append({
            "type": "isolated",
            "count": 1,
            "date": start_str,
            "message": f"Isolated failure on {start_str}",
        })
    else:
        end_str = end_dt.strftime("%b %d")
        clusters.append({
            "type": "streak",
            "count": count,
            "start": start_str,
            "end": end_str,
            "message": f"{count} consecutive failures {start_str}–{end_str}",
        })
