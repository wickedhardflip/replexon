"""First-run wizard and settings forms through the real app (TestClient, no lifespan)."""
import re

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.setting import AppSetting
from app.models.user import User
from app.services import app_settings

INNER = "Library/Application Support/Plex Media Server"


@pytest.fixture
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app, follow_redirects=False) as c:  # lifespan off: background tasks are not started
        yield c


@pytest.fixture(autouse=True)
def no_lifespan(monkeypatch):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def noop(_app):
        yield
    monkeypatch.setattr(app.router, "lifespan_context", noop)


def csrf(client, url):
    html = client.get(url).text
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def admin(client):
    token = csrf(client, "/setup")
    r = client.post("/setup/admin", data={"username": "admin", "password": "longenough1",
                                          "password_confirm": "longenough1", "csrf_token": token})
    assert r.status_code == 303 and r.headers["location"] == "/setup?step=plex"
    client.cookies.set("session_token", r.cookies["session_token"])


def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_fresh_install_goes_to_the_wizard(client):
    r = client.get("/dashboard")
    assert r.status_code == 303 and r.headers["location"] == "/setup"
    assert "Admin account" in client.get("/setup").text


def test_admin_can_only_be_created_once(client):
    admin(client)
    token = csrf(client, "/setup?step=plex")
    r = client.post("/setup/admin", data={"username": "evil", "password": "longenough1",
                                          "password_confirm": "longenough1", "csrf_token": token})
    assert r.headers["location"] == "/login"
    db = SessionLocal()
    assert [u.username for u in db.query(User).all()] == ["admin"]
    db.close()


def test_short_or_mismatched_password_refused(client):
    token = csrf(client, "/setup")
    r = client.post("/setup/admin", data={"username": "a", "password": "short",
                                          "password_confirm": "short", "csrf_token": token})
    assert "error=" in r.headers["location"]


def test_full_wizard(client, tmp_path):
    admin(client)
    # unfinished setup keeps sending a signed-in user back to the wizard
    assert client.get("/dashboard").headers["location"] == "/setup?step=plex"

    plex = tmp_path / "plexconfig"
    dbs = plex / INNER / "Plug-in Support" / "Databases"
    dbs.mkdir(parents=True)
    (dbs / "com.plexapp.plugins.library.db").write_bytes(b"x")
    (plex / INNER / "Preferences.xml").write_text("<Preferences/>")
    backups = tmp_path / "backups"
    backups.mkdir()

    def post(section, data, step):
        token = csrf(client, f"/setup?step={step}")
        data.update({"csrf_token": token, "next": "/setup?step=next", "here": f"/setup?step={step}"})
        return client.post(f"/settings/section/{section}", data=data)

    r = post("plex", {"plex_data_path": str(tmp_path / "nowhere")}, "plex")
    assert "error=" in r.headers["location"] and "step=plex" in r.headers["location"]
    r = post("plex", {"plex_data_path": str(plex)}, "plex")
    assert "success=" in r.headers["location"]

    assert "error=" not in post("items", {"preset": "essential", "db_safety": "safe_copy",
                                          "plex_container": "plex"}, "items").headers["location"]
    r = post("destination", {"dest_mode": "local", "backup_dir": str(plex / INNER / "sub"),
                             "snapshot_keep_count": "4"}, "destination")
    assert "inside" in r.headers["location"]
    assert "error=" not in post("destination", {"dest_mode": "local", "backup_dir": str(backups),
                                                "snapshot_keep_count": "6"}, "destination").headers["location"]
    r = post("schedule", {"backup_preset": "custom", "backup_cron": "nope", "cleanup_preset": "weekly"}, "schedule")
    assert "error=" in r.headers["location"]
    assert "error=" not in post("schedule", {"backup_preset": "custom", "backup_cron": "15 2 * * *",
                                             "cleanup_preset": "weekly", "backup_enabled": "on"},
                                "schedule").headers["location"]
    assert "error=" not in post("email", {"smtp_host": "smtp.example.com", "smtp_port": "587",
                                          "smtp_tls": "starttls", "smtp_user": "u",
                                          "smtp_password": "FAKE-smtp-pw", "smtp_from": "a@example.com",
                                          "email_recipient": "b@example.com", "notify_on": "both"},
                                "email").headers["location"]

    token = csrf(client, "/setup?step=done")
    assert client.post("/setup/finish", data={"csrf_token": token}).headers["location"].startswith("/dashboard")

    db = SessionLocal()
    cfg = app_settings.get_config(db)
    assert cfg["plex_data_path"].endswith("Plex Media Server")
    assert cfg["backup_items"] == "databases,preferences"
    assert cfg["backup_dir"] == str(backups) and cfg["snapshot_keep_count"] == "6"
    assert app_settings.get_secret(db, "smtp_password") == "FAKE-smtp-pw"
    assert "FAKE-smtp-pw" not in db.get(AppSetting, "smtp_password").value
    from app.services.scheduler_service import get_schedule
    assert get_schedule(db, "daily_backup").cron_expr == "15 2 * * *"
    db.close()

    page = client.get("/settings")
    assert page.status_code == 200
    assert "FAKE-smtp-pw" not in page.text  # password is never sent back to the browser
    assert "Safe copy" in page.text and "Pause Plex" in page.text


def test_blank_password_keeps_the_saved_one(client):
    admin(client)
    db = SessionLocal()
    app_settings.set_secret(db, "smtp_password", "FAKE-keep")
    db.close()
    token = csrf(client, "/setup?step=email")  # /settings redirects until setup is finished
    client.post("/settings/section/email", data={"csrf_token": token, "smtp_host": "h", "smtp_port": "25",
                                                 "smtp_tls": "none", "notify_on": "never", "smtp_password": ""})
    db = SessionLocal()
    assert app_settings.get_secret(db, "smtp_password") == "FAKE-keep"
    db.close()


def test_open_redirect_is_blocked(client):
    admin(client)
    token = csrf(client, "/setup?step=email")
    r = client.post("/settings/section/email", data={"csrf_token": token, "next": "//evil.example.com",
                                                     "smtp_tls": "none", "notify_on": "never"})
    assert r.headers["location"].startswith("/settings")


def test_every_page_renders_after_setup(client):
    admin(client)
    db = SessionLocal()
    app_settings.set_setting(db, "setup_complete", "1")
    db.close()
    for url in ("/dashboard", "/logs", "/schedules", "/restore", "/settings", "/login"):
        r = client.get(url)
        assert r.status_code == 200, url
        assert "/static/logo/replexon-sign.svg" in r.text, url
