"""NAS health check — verify Synology reachability and backup freshness."""

import subprocess
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session as DBSession

from app.models.backup import BackupRun
from app.models.setting import AppSetting


def _get_setting(db: DBSession, key: str, default: str = "") -> str:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    return row.value if row else default


def _set_setting(db: DBSession, key: str, value: str) -> None:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.commit()


def _ping_host(host: str) -> bool:
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "3", host],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def check_nas_health(db: DBSession) -> dict:
    """Run NAS health checks and store results.

    Returns dict with: reachable, last_check, last_backup_age_hours, status.
    """
    backup_dest = _get_setting(db, "backup_destination")

    # Extract host from rsync-style paths like rsync://user@host/module
    # or plain paths like /mnt/nas/backups (local = always reachable)
    host = None
    if backup_dest:
        if "://" in backup_dest:
            part = backup_dest.split("://", 1)[1]
            if "@" in part:
                part = part.split("@", 1)[1]
            host = part.split("/")[0].split(":")[0]
        elif ":" in backup_dest and not backup_dest.startswith("/"):
            host = backup_dest.split(":")[0]
            if "@" in host:
                host = host.split("@")[1]

    reachable = True
    if host:
        reachable = _ping_host(host)

    now = datetime.now(timezone.utc)
    _set_setting(db, "nas_reachable", "true" if reachable else "false")
    _set_setting(db, "nas_last_check", now.isoformat())
    if host:
        _set_setting(db, "nas_host", host)

    # Backup freshness
    last_success = (
        db.query(BackupRun)
        .filter(BackupRun.status == "success", BackupRun.backup_type == "daily_mirror")
        .order_by(BackupRun.started_at.desc())
        .first()
    )

    age_hours = None
    if last_success and last_success.started_at:
        started = last_success.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        age_hours = round((now - started).total_seconds() / 3600, 1)

    status = "healthy"
    if not reachable:
        status = "unreachable"
    elif age_hours is not None and age_hours > 48:
        status = "stale"
    elif age_hours is not None and age_hours > 26:
        status = "warning"

    return {
        "reachable": reachable,
        "host": host,
        "last_check": now.isoformat(),
        "last_backup_age_hours": age_hours,
        "status": status,
    }


def get_nas_status(db: DBSession) -> dict:
    """Read cached NAS health status from AppSettings (no network call)."""
    reachable = _get_setting(db, "nas_reachable", "unknown")
    last_check = _get_setting(db, "nas_last_check")
    host = _get_setting(db, "nas_host")

    last_success = (
        db.query(BackupRun)
        .filter(BackupRun.status == "success", BackupRun.backup_type == "daily_mirror")
        .order_by(BackupRun.started_at.desc())
        .first()
    )

    now = datetime.now(timezone.utc)
    age_hours = None
    if last_success and last_success.started_at:
        started = last_success.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        age_hours = round((now - started).total_seconds() / 3600, 1)

    status = "unknown"
    if reachable == "true":
        status = "healthy"
        if age_hours is not None and age_hours > 48:
            status = "stale"
        elif age_hours is not None and age_hours > 26:
            status = "warning"
    elif reachable == "false":
        status = "unreachable"

    return {
        "reachable": reachable,
        "host": host or "—",
        "last_check": last_check or None,
        "last_backup_age_hours": age_hours,
        "status": status,
    }
