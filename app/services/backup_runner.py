"""Run the backup and cleanup scripts (manual or scheduled), one at a time, and record the result."""

import logging
import shlex
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, Union

from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.models.backup import BackupRun

logger = logging.getLogger("replexon")

_last_trigger_time: float = 0
_running_process: Optional[subprocess.Popen] = None
_running_job: dict = {}

RAW_LOG_LINES = 300  # tail of the script output kept on the run record


def can_trigger_backup() -> Tuple[bool, str]:
    """Check if a manual backup can be triggered. Returns (can_trigger, reason_if_not)."""
    if _running_process is not None and _running_process.poll() is None:
        return False, "A backup is already running"

    elapsed = time.time() - _last_trigger_time
    if elapsed < settings.backup_cooldown:
        remaining = int(settings.backup_cooldown - elapsed)
        return False, f"Cooldown active. Try again in {remaining}s"

    return True, ""


def _script_for(kind: str, script_path: Optional[str]) -> str:
    backup_script = script_path or settings.backup_script_path
    if kind == "cleanup":
        return str(Path(backup_script).with_name("cleanup-snapshots.sh"))
    return backup_script


def start_job(db: DBSession, kind: str = "backup", triggered_by: str = "manual",
              script_path: Optional[str] = None) -> Union[BackupRun, str]:
    """Start the backup ("backup") or snapshot cleanup ("cleanup") script in the background.

    Returns the new BackupRun, or an error string. Settings from the UI reach the
    script as environment variables (secrets included, never on the command line).
    """
    global _running_process, _running_job, _last_trigger_time

    if _running_process is not None and _running_process.poll() is None:
        return "A backup is already running"

    script = _script_for(kind, script_path)
    if kind == "backup" and settings.backup_command:
        cmd = shlex.split(settings.backup_command)
    elif not Path(script).exists():
        return f"Backup script not found: {script}"
    else:
        cmd = ["bash", script]

    from app.services.app_settings import script_env
    env = script_env(db)

    if kind == "cleanup":
        backup_type = "cleanup"
    else:
        backup_type = "manual" if triggered_by == "manual" else "daily_mirror"
    run = BackupRun(
        backup_type=backup_type,
        status="running",
        started_at=datetime.now(timezone.utc),
        triggered_by=triggered_by,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    out_dir = Path(settings.data_dir) / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"last-{kind}.out"

    try:
        with open(out_path, "w") as out:
            _running_process = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, env=env)
    except OSError as e:
        run.status = "failure"
        run.error_message = str(e)
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        return str(e)

    _running_job = {"run_id": run.id, "kind": kind, "out_path": str(out_path)}
    if triggered_by == "manual":
        _last_trigger_time = time.time()
    return run


def trigger_backup(db: DBSession, script_path: Optional[str] = None) -> Union[BackupRun, str]:
    """Manual "Run now": rate limited, then start_job."""
    can, reason = can_trigger_backup()
    if not can:
        return reason
    return start_job(db, "backup", "manual", script_path)


def check_running_backup(db: DBSession) -> None:
    """If the running job has finished, record its result and send the notification."""
    global _running_process, _running_job

    if _running_process is None or _running_process.poll() is None:
        return

    returncode = _running_process.returncode
    job = _running_job
    _running_process = None
    _running_job = {}

    run = db.get(BackupRun, job.get("run_id")) if job.get("run_id") else None
    if run is None:
        return

    try:
        output = Path(job["out_path"]).read_text(errors="replace")
    except OSError:
        output = ""
    finish_run(db, run, returncode, output, job.get("kind", "backup"))


def finish_run(db: DBSession, run: BackupRun, returncode: int, output: str, kind: str = "backup") -> None:
    """Fill in a finished run from the script's exit code and output."""
    from app.services.log_parser import SNAPSHOT_RE, parse_marker_lines

    run.finished_at = datetime.now(timezone.utc)
    run.raw_log = "\n".join(output.splitlines()[-RAW_LOG_LINES:])
    started = run.started_at if run.started_at.tzinfo else run.started_at.replace(tzinfo=timezone.utc)
    run.duration_seconds = (run.finished_at - started).total_seconds()

    if kind == "backup":
        entries = parse_marker_lines(output)
        entry = entries[-1] if entries else {}
        run.db_safe = bool(entry.get("db_safe"))
        run.total_size_bytes = entry.get("total_size")
        run.transferred_bytes = entry.get("sent")

    if returncode == 0:
        run.status = "success"
    else:
        run.status = "failure"
        run.error_message = f"Script exited with code {returncode}"
        if kind == "backup" and not run.db_safe:
            run.error_message += " - Plex database was NOT backed up"
    db.commit()

    if kind == "backup" and run.status == "success" and SNAPSHOT_RE.search(output):
        db.add(BackupRun(backup_type="snapshot", status="success", started_at=run.finished_at,
                         finished_at=run.finished_at, triggered_by=run.triggered_by))
        db.commit()

    try:
        from app.services.email_service import notify_backup_result
        notify_backup_result(db, run)
    except Exception:
        logger.exception("Backup notification failed")
