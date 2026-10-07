"""Secrets never show up in repr/str, and UI secrets are encrypted at rest."""

import pytest

from app.config import Settings
from app.models.setting import AppSetting
from app.services import app_settings

SECRET_FIELDS = ["secret_key", "proxy_auth_secret", "admin_password"]


def test_secret_fields_are_hidden_from_repr():
    s = Settings(_env_file=None, **{f: f"FAKE-{f}" for f in SECRET_FIELDS})
    text = repr(s) + str(s)
    leaked = [f for f in SECRET_FIELDS if f"FAKE-{f}" in text]   # names only, never values
    assert leaked == []


@pytest.mark.parametrize("key", sorted(app_settings.SECRET_KEYS))
def test_secrets_are_encrypted_at_rest_and_round_trip(db, key):
    app_settings.set_secret(db, key, "FAKE-pw-123")
    stored = db.get(AppSetting, key).value
    assert "FAKE-pw-123" not in stored and stored.startswith("enc:v1:")
    assert app_settings.get_secret(db, key) == "FAKE-pw-123"


def test_secrets_are_not_in_the_settings_dict(db):
    app_settings.set_secret(db, "smtp_password", "FAKE-pw-123")
    assert "FAKE-pw-123" not in repr(app_settings.get_config(db))


def test_plain_set_refuses_secret_keys(db):
    with pytest.raises(ValueError):
        app_settings.set_setting(db, "smtp_password", "x")


def test_wrong_key_reads_as_empty_not_a_crash(db, monkeypatch):
    app_settings.set_secret(db, "smtp_password", "FAKE-pw-123")
    monkeypatch.setattr(app_settings.settings, "secret_key", "a-different-key")
    assert app_settings.get_secret(db, "smtp_password") == ""


def test_clearing_a_secret(db):
    app_settings.set_secret(db, "rsync_password", "FAKE")
    app_settings.set_secret(db, "rsync_password", "")
    assert app_settings.get_secret(db, "rsync_password") == "" and not app_settings.has_secret(db, "rsync_password")


def test_legacy_tls_values_are_mapped(db):
    app_settings.set_setting(db, "smtp_tls", "on")
    assert app_settings.get_config(db)["smtp_tls"] == "starttls"
    app_settings.set_setting(db, "smtp_tls", "off")
    assert app_settings.get_config(db)["smtp_tls"] == "none"


def test_secret_key_file_is_created_private(tmp_path):
    import os, stat
    from app.config import _load_or_create_secret_key
    key = _load_or_create_secret_key(tmp_path)
    assert len(key) == 64 and _load_or_create_secret_key(tmp_path) == key
    if os.name == "posix":
        assert stat.S_IMODE((tmp_path / ".secret_key").stat().st_mode) == 0o600
