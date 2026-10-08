"""Time zone: stored UTC is shown, bucketed and scheduled in the configured zone."""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.database import SessionLocal
from app.models.backup import BackupRun
from app.services import app_settings, metrics, timefmt
from app.services import scheduler_service as sched
from tests.test_setup_flow import admin, client, csrf, no_lifespan  # noqa: F401  (fixtures)

NY = "America/New_York"


@pytest.fixture
def ny(db):
    app_settings.set_setting(db, "timezone", NY)
    return timefmt.zone(db)


# ---------- conversion ----------

@pytest.mark.parametrize("utc,local,offset", [
    (datetime(2026, 11, 1, 5, 30), "1:30 AM", -4),   # still EDT
    (datetime(2026, 11, 1, 6, 30), "1:30 AM", -5),   # the repeated hour, now EST
    (datetime(2026, 11, 1, 7, 30), "2:30 AM", -5),
    (datetime(2026, 3, 8, 7, 30), "3:30 AM", -4),    # spring forward: 2:xx never happens
])
def test_dst_boundaries(ny, utc, local, offset):
    assert timefmt.fmt_time(utc) == local
    assert timefmt.to_local(utc).utcoffset() == timedelta(hours=offset)


def test_formats_and_inputs(ny):
    run = datetime(2026, 10, 8, 7, 0, 46, 450057)  # naive UTC, as stored
    assert timefmt.fmt_datetime(run) == "Oct 8, 2026, 3:00 AM"
    assert timefmt.fmt_date(run) == "Oct 8, 2026"
    assert timefmt.fmt_datetime("2026-10-08T07:00:46+00:00") == "Oct 8, 2026, 3:00 AM"
    assert timefmt.fmt_datetime(None) == "-"
    assert timefmt.iso_utc(run) == "2026-10-08T07:00:46Z"
    assert timefmt.fmt_time_range(run, run + timedelta(minutes=15)) == "3:00 AM – 3:15 AM"
    assert timefmt.fmt_time_range(run, run + timedelta(seconds=5)) == "3:00 AM"  # zero-length marker rows
    assert timefmt.fmt_time_range(run, None) == "3:00 AM"


def test_local_day_and_bounds(ny):
    late = datetime(2026, 10, 9, 2, 30)  # 10:30 PM on Oct 8 in New York
    assert timefmt.local_day(late) == date(2026, 10, 8)
    start, end = timefmt.day_bounds_utc(date(2026, 10, 8))
    assert (start, end) == (datetime(2026, 10, 8, 4, 0), datetime(2026, 10, 9, 4, 0))
    start, end = timefmt.day_bounds_utc(date(2026, 11, 1))  # 25-hour day
    assert end - start == timedelta(hours=25)


# ---------- the setting ----------

def test_default_comes_from_tz_env(db, monkeypatch):
    monkeypatch.setenv("TZ", "Europe/London")
    assert app_settings.get_config(db)["timezone"] == "Europe/London"
    monkeypatch.setenv("TZ", "Not/AZone")
    assert app_settings.get_config(db)["timezone"] == "UTC"


@pytest.mark.parametrize("bad", ["", "Mars/Olympus_Mons", "../../etc/passwd", "/etc/localtime", "EST5EDT nope"])
def test_invalid_zone_is_rejected(db, bad):
    assert "Unknown time zone" in app_settings.set_timezone(db, bad)
    with pytest.raises(ValueError):
        app_settings.set_setting(db, "timezone", bad)


def test_zone_names_for_the_picker():
    names = timefmt.zone_names()
    assert NY in names and "UTC" in names and names == sorted(names)


# ---------- day bucketing ----------

def _run(db, started, minutes=15, status="success", kind="daily_mirror", size=10 * 2**30):
    run = BackupRun(backup_type=kind, status=status, started_at=started, triggered_by="cron",
                    finished_at=started + timedelta(minutes=minutes), duration_seconds=minutes * 60,
                    total_size_bytes=size)
    db.add(run)
    db.commit()
    return run


def test_late_evening_run_counts_on_the_local_day(db, ny):
    local_day = timefmt.now_local(ny).date() - timedelta(days=2)
    started = timefmt.to_utc_naive(datetime.combine(local_day, datetime.min.time()).replace(hour=22, minute=30))
    assert started.date() == local_day + timedelta(days=1)  # the UTC day is the next one
    _run(db, started, status="failure")

    assert [d["date"] for d in metrics.get_daily_sizes(db, 30)] == []  # failures have no size bar
    cal = next(m for m in metrics.get_calendar_data(db, 2) if m["month"] == local_day.month)
    assert cal["statuses"] == {local_day.day: "failure"}  # not the UTC day after
    assert metrics.get_failure_clusters(db, 30)[0]["message"] == f"Isolated failure on {timefmt.fmt_date(local_day)}"

    _run(db, started + timedelta(minutes=1))
    assert [d["date"] for d in metrics.get_daily_sizes(db, 30)] == [local_day.isoformat()]
    assert [d["date"] for d in metrics.get_daily_durations(db, 30)] == [local_day.isoformat()]


def test_tracking_file_import_stores_utc(db, ny, tmp_path):
    from app.services.log_parser import import_from_tracking_file
    tracking = tmp_path / "plex-backup-tracking.log"
    tracking.write_text("2026-10-08:success\n")
    assert import_from_tracking_file(db, str(tracking)) == 1
    assert db.query(BackupRun).one().started_at == datetime(2026, 10, 8, 7, 0)  # 3 AM EDT
    assert import_from_tracking_file(db, str(tracking)) == 0  # same local day: not imported twice


# ---------- scheduler ----------

def test_cron_is_read_in_the_configured_zone():
    raw = [{"id": "a", "cron_expr": "0 3 * * *", "enabled": True, "last_run": "2026-10-08T06:00:00+00:00"}]
    now = datetime(2026, 10, 8, 7, 0, 30, tzinfo=timezone.utc)  # 3:00:30 AM in New York
    assert sched.due_jobs(raw, now, timefmt.load_zone(NY)) == ["a"]
    assert sched.due_jobs(raw, now, timezone.utc) == []  # 03:00 UTC already passed before last_run


def test_next_run_and_zone_change_reschedule(db, ny):
    sched.initialize_schedules(db)
    nxt = sched.get_next_backup_time(db)
    assert (nxt.hour, nxt.minute) == (3, 0) and timefmt.zone_name(nxt.tzinfo) == NY

    raw = sched._read(db)
    for e in raw:
        e["last_run"] = "2020-01-01T00:00:00+00:00"
    sched._write(db, raw)
    app_settings.set_setting(db, "timezone", "Asia/Tokyo")  # no restart
    assert all(s.last_run > "2026" for s in sched.get_schedules(db))  # counts from now: no catch-up burst
    nxt = sched.get_next_backup_time(db)
    assert nxt.hour == 3 and nxt.utcoffset() == timedelta(hours=9)


# ---------- email ----------

def test_email_body_uses_the_zone(db, ny, monkeypatch):
    from app.services import email_service
    sent = []
    monkeypatch.setattr(email_service, "_send", lambda _db, subject, text: sent.append(text) or (True, ""))
    app_settings.set_setting(db, "notify_on", "both")
    app_settings.set_setting(db, "email_recipient", "b@example.com")
    email_service.notify_backup_result(db, _run(db, datetime(2026, 10, 8, 7, 0)))
    assert f"Started:     Oct 8, 2026, 3:00 AM ({NY})" in sent[0]


# ---------- pages ----------

def test_pages_show_local_time_and_follow_a_change(client):  # noqa: F811
    admin(client)
    db = SessionLocal()
    app_settings.set_setting(db, "setup_complete", "1")
    app_settings.set_setting(db, "timezone", NY)
    sched.initialize_schedules(db)
    _run(db, datetime(2026, 10, 8, 7, 0, 46))  # 3:00 AM EDT, as stored by the backup runner
    raw = sched._read(db)
    raw[0]["last_run"] = "2026-10-08T07:00:46+00:00"
    sched._write(db, raw)
    db.close()

    dash = client.get("/dashboard?days=365").text
    assert "Oct 8, 2026, 3:00 AM" in dash and "7:00 AM" not in dash
    logs = client.get("/logs").text
    assert "3:00 AM – 3:15 AM" in logs and "7:00" not in logs
    schedules = client.get("/schedules").text
    assert "Last: Oct 8, 2026, 3:00 AM" in schedules and ", 3:00 AM" in schedules.split("Next:")[1][:40]
    assert client.get("/logs?date_from=2026-10-08&date_to=2026-10-08").text.count("3:00 AM – 3:15 AM") == 1

    token = csrf(client, "/settings")
    r = client.post("/settings/section/schedule", data={
        "csrf_token": token, "next": "/settings", "timezone": "Mars/Olympus",
        "backup_preset": "daily", "cleanup_preset": "weekly", "backup_enabled": "on"})
    assert "Unknown+time+zone" in r.headers["location"]
    r = client.post("/settings/section/schedule", data={
        "csrf_token": token, "next": "/settings", "timezone": "UTC",
        "backup_preset": "daily", "cleanup_preset": "weekly", "backup_enabled": "on"})
    assert "success=" in r.headers["location"]
    assert "3:00 AM – 3:15 AM" not in client.get("/logs").text  # applies at once
    assert "7:00 AM – 7:15 AM" in client.get("/logs").text
    page = client.get("/settings").text
    assert 'value="UTC"' in page and f'<option value="{NY}">' in page


# ---------- one-time fix of 1.x-imported times ----------

@pytest.fixture
def filedb(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    engine = create_engine(f"sqlite:///{tmp_path / 'replexon.db'}")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    app_settings.set_setting(session, "timezone", NY)
    yield session, tmp_path / "replexon.db.pre-tzfix"
    session.close()
    engine.dispose()


def _add(db, started, finished=None, by="cron"):
    run = BackupRun(backup_type="daily_mirror", status="success", started_at=started,
                    finished_at=finished, triggered_by=by)
    db.add(run)
    db.commit()
    return run.id


def test_imported_local_times_become_utc_once(filedb):
    from app.services.log_parser import migrate_import_times
    db, backup = filedb
    winter = _add(db, datetime(2026, 1, 25, 3, 0), datetime(2026, 1, 25, 3, 14, 7))   # EST: +5h
    summer = _add(db, datetime(2026, 7, 5, 3, 0))                                       # EDT: +4h
    new = _add(db, datetime(2026, 10, 8, 7, 0, 46, 450057), by="scheduled")             # 2.x row
    odd_end = _add(db, datetime(2026, 2, 1, 3, 0), datetime(2026, 2, 1, 8, 9, 1, 123))  # end not whole-second

    assert migrate_import_times(db) == 3
    assert backup.exists()
    db.expire_all()
    get = lambda i: db.get(BackupRun, i)  # noqa: E731
    assert (get(winter).started_at, get(winter).finished_at) == (datetime(2026, 1, 25, 8, 0), datetime(2026, 1, 25, 8, 14, 7))
    assert get(summer).started_at == datetime(2026, 7, 5, 7, 0) and get(summer).finished_at is None
    assert get(new).started_at == datetime(2026, 10, 8, 7, 0, 46, 450057)
    assert get(odd_end).started_at == datetime(2026, 2, 1, 8, 0)
    assert get(odd_end).finished_at == datetime(2026, 2, 1, 8, 9, 1, 123)

    stamp = backup.stat().st_mtime_ns
    assert migrate_import_times(db) == 0  # second start: nothing changes
    db.expire_all()
    assert get(winter).started_at == datetime(2026, 1, 25, 8, 0)
    assert backup.stat().st_mtime_ns == stamp


def test_migration_on_an_empty_db_is_a_no_op(filedb):
    from app.services.log_parser import IMPORT_TIMES_FLAG, migrate_import_times
    db, backup = filedb
    _add(db, datetime(2026, 10, 8, 7, 0, 46, 450057), by="manual")
    assert migrate_import_times(db) == 0
    assert not backup.exists()
    assert app_settings.get_setting(db, IMPORT_TIMES_FLAG) == "1"
