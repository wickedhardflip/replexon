"""In-app scheduler: presets, validation, due-job detection, and starting jobs through the runner."""
from datetime import datetime, timezone

import pytest

from app.services import app_settings, scheduler_service as sched


def test_defaults_are_created_once(db):
    sched.initialize_schedules(db)
    sched.update_schedule(db, "daily_backup", "0 5 * * *", True)
    sched.initialize_schedules(db)
    ids = [s.id for s in sched.get_schedules(db)]
    assert ids == ["daily_backup", "weekly_cleanup"]
    assert sched.get_schedule(db, "daily_backup").cron_expr == "0 5 * * *"


@pytest.mark.parametrize("expr,ok", [
    ("0 3 * * *", True), ("0 3,15 * * *", True), ("*/30 * * * *", True),
    ("0 3 * *", False), ("not a cron", False), ("", False), ("0 3 * * * *", False), ("61 3 * * *", False),
])
def test_cron_validation(expr, ok):
    assert sched.valid_cron(expr) is ok


def test_invalid_update_is_refused(db):
    sched.initialize_schedules(db)
    assert sched.update_schedule(db, "daily_backup", "garbage", True) is False
    assert sched.update_schedule(db, "nope", "0 3 * * *", True) is False


def test_preset_lookup():
    assert sched.preset_for("0 3 * * *", sched.BACKUP_PRESETS) == "daily"
    assert sched.preset_for("15 2 * * 1", sched.BACKUP_PRESETS) == "custom"


@pytest.mark.parametrize("expr,expected", [
    ("0 3 * * *", "Every day at 3:00 AM"),
    ("0 3,15 * * *", "Every day at 3:00 AM and 3:00 PM"),
    ("30 4 * * 0", "Sundays at 4:30 AM"),
    ("0 4 1 * *", "1st of each month at 4:00 AM"),
])
def test_schedule_display(expr, expected):
    assert sched.ScheduleEntry("x", "x", "backup", expr, True).schedule_display == expected


def test_due_jobs():
    raw = [
        {"id": "a", "cron_expr": "0 3 * * *", "enabled": True, "last_run": "2026-10-06T02:00:00+00:00"},
        {"id": "b", "cron_expr": "0 3 * * *", "enabled": False, "last_run": "2026-10-06T02:00:00+00:00"},
        {"id": "c", "cron_expr": "0 3 * * *", "enabled": True, "last_run": "2026-10-06T03:30:00+00:00"},
        {"id": "d", "cron_expr": "0 3 * * *", "enabled": True, "last_run": None},
    ]
    assert sched.due_jobs(raw, datetime(2026, 10, 6, 3, 0, 30, tzinfo=timezone.utc), timezone.utc) == ["a"]


def test_next_backup_time_ignores_disabled_and_cleanup(db):
    sched.initialize_schedules(db)
    assert sched.get_next_backup_time(db) is not None
    sched.update_schedule(db, "daily_backup", "0 3 * * *", False)
    assert sched.get_next_backup_time(db) is None


class Runner:
    def __init__(self, result=None):
        self.calls, self.result = [], result

    def __call__(self, db, kind, triggered_by):
        self.calls.append((kind, triggered_by))
        return self.result if self.result is not None else object()


def _due_state(db):
    sched.initialize_schedules(db)
    raw = sched._read(db)
    for e in raw:
        e["last_run"] = "2020-01-01T00:00:00"
    sched._write(db, raw)


def test_nothing_runs_before_setup_is_finished(db, monkeypatch):
    runner = Runner()
    monkeypatch.setattr("app.services.backup_runner.start_job", runner)
    _due_state(db)
    sched.check_and_run_due_jobs(db)
    assert runner.calls == []


def test_due_jobs_start_one_at_a_time(db, monkeypatch):
    runner = Runner()
    monkeypatch.setattr("app.services.backup_runner.start_job", runner)
    app_settings.set_setting(db, "setup_complete", "1")
    _due_state(db)
    sched.check_and_run_due_jobs(db)
    assert runner.calls == [("backup", "scheduled")]
    sched.check_and_run_due_jobs(db)
    assert runner.calls == [("backup", "scheduled"), ("cleanup", "scheduled")]
    sched.check_and_run_due_jobs(db)
    assert len(runner.calls) == 2


def test_busy_runner_retries_next_tick(db, monkeypatch):
    runner = Runner(result="A backup is already running")
    monkeypatch.setattr("app.services.backup_runner.start_job", runner)
    app_settings.set_setting(db, "setup_complete", "1")
    _due_state(db)
    sched.check_and_run_due_jobs(db)
    assert sched.get_schedule(db, "daily_backup").last_run.startswith("2020")


def test_first_sight_starts_counting_from_now(db, monkeypatch):
    runner = Runner()
    monkeypatch.setattr("app.services.backup_runner.start_job", runner)
    app_settings.set_setting(db, "setup_complete", "1")
    sched.initialize_schedules(db)
    sched.check_and_run_due_jobs(db)
    assert runner.calls == []
    assert all(s.last_run for s in sched.get_schedules(db))
