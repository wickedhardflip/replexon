"""List the dated weekly snapshots at the backup destination (local folder or rsync daemon)."""

import json
import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.services.app_settings import get_config, get_setting, script_env, set_setting

logger = logging.getLogger("replexon")

DATE_DIR_RE = re.compile(r"(\d{4}-\d{2}-\d{2})/?$")


def _list_names(db: DBSession) -> list:
    cfg = get_config(db)
    if cfg["dest_mode"] == "local":
        snap_dir = Path(cfg["backup_dir"]) / settings.snapshot_dir
        return [p.name for p in snap_dir.iterdir() if p.is_dir()] if snap_dir.is_dir() else []

    if not (cfg["nas_host"] and cfg["rsync_user"] and cfg["rsync_module"]):
        return []
    env = script_env(db)  # carries RSYNC_PASSWORD when one is saved
    cmd = ["rsync", "--list-only"]
    if "RSYNC_PASSWORD" not in env:
        cmd += ["--password-file", env["RSYNC_PASSWORD_FILE"]]
    cmd.append(f"{cfg['rsync_user']}@{cfg['nas_host']}::{cfg['rsync_module']}/{settings.snapshot_dir}/")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        logger.warning("rsync --list-only failed or timed out")
        return []
    if result.returncode != 0:
        logger.warning("rsync --list-only exit %s", result.returncode)
        return []
    return [line.split()[-1] for line in result.stdout.splitlines() if line.split()]


def fetch_snapshots(db: DBSession) -> list:
    """Find snapshot folders (YYYY-MM-DD) and cache them in AppSetting."""
    now = datetime.now(timezone.utc)
    snapshots = []
    for name in _list_names(db):
        match = DATE_DIR_RE.search(name)
        if not match:
            continue
        try:
            snap_date = datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        snapshots.append({"date": match.group(1), "age_days": (now - snap_date).days})

    snapshots.sort(key=lambda s: s["date"], reverse=True)
    set_setting(db, "snapshot_list", json.dumps(snapshots))
    set_setting(db, "snapshot_last_check", now.isoformat())
    return snapshots


def get_cached_snapshots(db: DBSession) -> dict:
    """Read cached snapshot data from AppSettings."""
    try:
        snapshots = json.loads(get_setting(db, "snapshot_list", "[]"))
    except (json.JSONDecodeError, TypeError):
        snapshots = []
    return {
        "snapshots": snapshots,
        "count": len(snapshots),
        "keep_count": get_config(db)["snapshot_keep_count"],
        "last_check": get_setting(db, "snapshot_last_check") or None,
    }
