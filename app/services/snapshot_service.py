"""NAS snapshot enumeration via rsync --list-only."""

import json
import logging
import re
import subprocess
from datetime import datetime, timezone

from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.models.setting import AppSetting

logger = logging.getLogger("replexon")

DATE_DIR_RE = re.compile(r"(\d{4}-\d{2}-\d{2})/?$")


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


def _parse_rsync_dest(db: DBSession) -> tuple[str, str, str] | None:
    """Extract rsync user, host, and module from backup_destination setting.

    Returns (user, host, module) or None if not parseable.
    """
    dest = _get_setting(db, "backup_destination", settings.backup_destination)
    if not dest:
        return None

    # rsync://user@host/module/path or user@host::module/path
    if "://" in dest:
        part = dest.split("://", 1)[1]
        if "@" not in part:
            return None
        user, rest = part.split("@", 1)
        host = rest.split("/")[0].split(":")[0]
        parts = rest.split("/", 1)
        module = parts[1].split("/")[0] if len(parts) > 1 else ""
        if module:
            return user, host, module
    elif "::" in dest:
        user_host, rest = dest.split("::", 1)
        if "@" in user_host:
            user, host = user_host.split("@", 1)
        else:
            return None
        module = rest.split("/")[0]
        if module:
            return user, host, module

    return None


def fetch_snapshots(db: DBSession) -> list[dict]:
    """Query NAS via rsync --list-only for snapshot directories.

    Returns list of dicts with date, age_days, path.
    """
    parsed = _parse_rsync_dest(db)
    if not parsed:
        logger.debug("Cannot parse backup destination for snapshot listing")
        return []

    user, host, module = parsed
    snapshot_path = f"{user}@{host}::{module}/{settings.snapshot_dir}/"
    cmd = [
        "rsync", "--list-only",
        "--password-file", settings.rsync_password_file,
        snapshot_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        logger.warning("rsync --list-only failed or timed out")
        return []

    if result.returncode != 0:
        logger.warning(f"rsync --list-only exit {result.returncode}: {result.stderr[:200]}")
        return []

    now = datetime.now(timezone.utc)
    snapshots = []
    for line in result.stdout.splitlines():
        match = DATE_DIR_RE.search(line)
        if not match:
            continue
        date_str = match.group(1)
        try:
            snap_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        age_days = (now - snap_date).days
        snapshots.append({
            "date": date_str,
            "age_days": age_days,
        })

    snapshots.sort(key=lambda s: s["date"], reverse=True)

    _set_setting(db, "snapshot_list", json.dumps(snapshots))
    _set_setting(db, "snapshot_last_check", now.isoformat())

    return snapshots


def get_cached_snapshots(db: DBSession) -> dict:
    """Read cached snapshot data from AppSettings."""
    raw = _get_setting(db, "snapshot_list", "[]")
    last_check = _get_setting(db, "snapshot_last_check")

    try:
        snapshots = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        snapshots = []

    return {
        "snapshots": snapshots,
        "count": len(snapshots),
        "keep_count": settings.snapshot_keep_count,
        "last_check": last_check or None,
    }
