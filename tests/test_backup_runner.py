"""Manual backup trigger: plain script vs a configured command (root-only script via sudo + systemd)."""
import subprocess

import pytest

from app.config import settings
from app.services import backup_runner


class FakePopen:
    calls = []

    def __init__(self, cmd, **kw):
        FakePopen.calls.append(cmd)

    def poll(self):
        return None


class FakeDB:
    def add(self, x): pass
    def commit(self): pass
    def refresh(self, x): pass


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    FakePopen.calls = []
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr(backup_runner, "_running_process", None)
    monkeypatch.setattr(backup_runner, "_last_trigger_time", 0)
    monkeypatch.setattr(settings, "backup_command", "")


def test_plain_script_runs_with_bash(tmp_path):
    script = tmp_path / "b.sh"
    script.write_text("true")
    backup_runner.trigger_backup(FakeDB(), str(script))
    assert FakePopen.calls == [["bash", str(script)]]


def test_configured_command_is_used_even_if_script_is_unreadable(monkeypatch):
    monkeypatch.setattr(settings, "backup_command", "sudo -n /usr/bin/systemctl start plex-backup-manual.service")
    backup_runner.trigger_backup(FakeDB(), "/nonexistent/root-only.sh")
    assert FakePopen.calls == [["sudo", "-n", "/usr/bin/systemctl", "start", "plex-backup-manual.service"]]


def test_missing_script_without_command_is_an_error():
    assert "not found" in backup_runner.trigger_backup(FakeDB(), "/nonexistent.sh")
