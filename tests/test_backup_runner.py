"""Backup runner: command choice, settings passed as env, and recording the finished run."""
import subprocess

import pytest

from app.config import settings
from app.models.backup import BackupRun
from app.services import app_settings, backup_runner


class FakePopen:
    calls = []

    def __init__(self, cmd, **kw):
        FakePopen.calls.append((cmd, kw.get("env") or {}))
        self.returncode = None

    def poll(self):
        return self.returncode


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    FakePopen.calls = []
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr(backup_runner, "_running_process", None)
    monkeypatch.setattr(backup_runner, "_running_job", {})
    monkeypatch.setattr(backup_runner, "_last_trigger_time", 0)
    monkeypatch.setattr(settings, "backup_command", "")


def test_plain_script_runs_with_bash(db, tmp_path):
    script = tmp_path / "b.sh"
    script.write_text("true")
    backup_runner.trigger_backup(db, str(script))
    assert FakePopen.calls[0][0] == ["bash", str(script)]


def test_configured_command_is_used_even_if_script_is_unreadable(db, monkeypatch):
    monkeypatch.setattr(settings, "backup_command", "sudo -n /usr/bin/systemctl start plex-backup-manual.service")
    backup_runner.trigger_backup(db, "/nonexistent/root-only.sh")
    assert FakePopen.calls[0][0] == ["sudo", "-n", "/usr/bin/systemctl", "start", "plex-backup-manual.service"]


def test_missing_script_without_command_is_an_error(db):
    assert "not found" in backup_runner.trigger_backup(db, "/nonexistent.sh")


def test_cleanup_uses_the_sibling_cleanup_script(db, tmp_path):
    (tmp_path / "backup-plex.sh").write_text("true")
    (tmp_path / "cleanup-snapshots.sh").write_text("true")
    run = backup_runner.start_job(db, "cleanup", "scheduled", str(tmp_path / "backup-plex.sh"))
    assert FakePopen.calls[0][0] == ["bash", str(tmp_path / "cleanup-snapshots.sh")]
    assert run.backup_type == "cleanup" and run.triggered_by == "scheduled"


def test_ui_settings_reach_the_script_as_env_and_password_stays_off_the_command_line(db, tmp_path):
    script = tmp_path / "b.sh"
    script.write_text("true")
    app_settings.set_setting(db, "dest_mode", "nas")
    app_settings.set_setting(db, "nas_host", "192.0.2.10")
    app_settings.set_setting(db, "backup_items", "databases,metadata")
    app_settings.set_setting(db, "db_safety", "pause_container")
    app_settings.set_secret(db, "rsync_password", "FAKE-rsync-pw")
    backup_runner.trigger_backup(db, str(script))
    cmd, env = FakePopen.calls[0]
    assert env["BACKUP_MODE"] == "nas" and env["NAS_IP"] == "192.0.2.10"
    assert env["BACKUP_ITEMS"] == "databases,metadata"
    assert env["DB_SAFETY"] == "pause_container"
    assert env["RSYNC_PASSWORD"] == "FAKE-rsync-pw"
    assert "FAKE-rsync-pw" not in " ".join(cmd)


def test_one_job_at_a_time(db, tmp_path):
    script = tmp_path / "b.sh"
    script.write_text("true")
    assert isinstance(backup_runner.start_job(db, "backup", "scheduled", str(script)), BackupRun)
    assert "already running" in backup_runner.start_job(db, "backup", "scheduled", str(script))


SUCCESS_OUTPUT = """=== Plex Backup Started: Mon Feb 23 03:00:01 AM EST 2026 ===
--- Safe database snapshot: complete (2 databases, 3s) ---
sent 1,024 bytes  received 64 bytes  2,176.00 bytes/sec
total size is 5,000  speedup is 4.60
Sunday detected - creating weekly snapshot
=== Plex Backup Completed Successfully: Mon Feb 23 03:01:01 AM EST 2026 ===
"""

DB_FAILED_OUTPUT = """=== Plex Backup Started: Mon Feb 23 03:00:01 AM EST 2026 ===
ERROR: Plex database backup FAILED (1 failed, 0 copied). Databases were NOT backed up this run.
=== Plex Backup FAILED with code 3: Mon Feb 23 03:01:01 AM EST 2026 ===
"""


def _run(db):
    from datetime import datetime, timezone
    run = BackupRun(backup_type="daily_mirror", status="running", started_at=datetime.now(timezone.utc),
                    triggered_by="scheduled")
    db.add(run)
    db.commit()
    return run


def test_finished_run_records_stats_db_safety_and_snapshot(db):
    run = _run(db)
    backup_runner.finish_run(db, run, 0, SUCCESS_OUTPUT)
    assert run.status == "success" and run.db_safe is True
    assert run.total_size_bytes == 5000 and run.transferred_bytes == 1024
    assert db.query(BackupRun).filter(BackupRun.backup_type == "snapshot").count() == 1


def test_failed_database_copy_is_a_red_failure(db):
    run = _run(db)
    backup_runner.finish_run(db, run, 3, DB_FAILED_OUTPUT)
    assert run.status == "failure" and run.db_safe is False
    assert "NOT backed up" in run.error_message
