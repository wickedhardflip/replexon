"""Trigger manual backup via subprocess with rate limiting."""

import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, Union

from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.models.backup import BackupRun

_last_trigger_time: float = 0
_running_process: Optional[subprocess.Popen] = None


def can_trigger_backup() -> Tuple[bool, str]:
    """Check if a manual backup can be triggered.

    Returns (can_trigger, reason_if_not).
    """
    global _running_process

    if _running_process is not None and _running_process.poll() is None:
        return False, "A backup is already running"

    elapsed = time.time() - _last_trigger_time
    if elapsed < settings.backup_cooldown:
        remaining = int(settings.backup_cooldown - elapsed)
        return False, f"Cooldown active. Try again in {remaining}s"

    return True, ""


def trigger_backup(db: DBSession, script_path: Optional[str] = None) -> Union[BackupRun, str]:
    """Trigger a manual backup.

    Returns a BackupRun record on success, or an error string.
    """
    global _last_trigger_time, _running_process

    can, reason = can_trigger_backup()
    if not can:
        return reason

    if script_path is None:
        script_path = settings.backup_script_path

    if not Path(script_path).exists():
        return f"Backup script not found: {script_path}"

    run = BackupRun(
        backup_type="manual",
        status="running",
        started_at=datetime.now(timezone.utc),
        triggered_by="manual",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        _running_process = subprocess.Popen(
            ["bash", script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        _last_trigger_time = time.time()
    except OSError as e:
        run.status = "failure"
        run.error_message = str(e)
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        return str(e)

    return run


def check_running_backup(db: DBSession) -> None:
    """Check if a running backup has finished and update its record."""
    global _running_process

    if _running_process is None or _running_process.poll() is None:
        return

    returncode = _running_process.returncode
    stdout = _running_process.stdout.read() if _running_process.stdout else ""
    _running_process = None

    run = (
        db.query(BackupRun)
        .filter(BackupRun.status == "running", BackupRun.triggered_by == "manual")
        .order_by(BackupRun.started_at.desc())
        .first()
    )
    if not run:
        return

    run.finished_at = datetime.now(timezone.utc)
    run.raw_log = stdout
    if run.started_at:
        delta = run.finished_at - run.started_at
        run.duration_seconds = delta.total_seconds()

    if returncode == 0:
        run.status = "success"
    else:
        run.status = "failure"
        run.error_message = f"Script exited with code {returncode}"

    db.commit()
