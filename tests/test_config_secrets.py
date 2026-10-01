"""Secret settings must never appear when the settings object is printed (e.g. in an error message)."""

from app.config import Settings

SECRET_FIELDS = ["secret_key", "proxy_auth_secret"]


def test_secret_fields_are_hidden_from_repr():
    s = Settings(_env_file=None, **{f: f"FAKE-{f}" for f in SECRET_FIELDS})
    text = repr(s) + str(s)
    leaked = [f for f in SECRET_FIELDS if f"FAKE-{f}" in text]   # names only, never values
    assert leaked == []
