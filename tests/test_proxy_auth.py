from types import SimpleNamespace

import pytest

from app import proxy_auth
from app.models.user import User


def req(peer="172.18.0.3", user="brian", secret="s3cret"):
    headers = {}
    if user is not None:
        headers["remote-user"] = user
    if secret is not None:
        headers["x-homelab-proxy"] = secret
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


@pytest.fixture
def on(monkeypatch):
    s = proxy_auth.settings
    monkeypatch.setattr(s, "trust_proxy_auth", True)
    monkeypatch.setattr(s, "proxy_auth_secret", "s3cret")
    monkeypatch.setattr(s, "trusted_proxy_networks", "172.16.0.0/12")
    monkeypatch.setattr(s, "proxy_auth_user_map", "")


def add_user(db, name="brian"):
    u = User(username=name, password_hash="x")
    db.add(u)
    db.commit()
    return u


def test_off_by_default(db):
    add_user(db)
    assert proxy_auth.proxy_user(req(), db) is None


def test_docker_peer_with_secret_signs_in_existing_user(db, on):
    add_user(db)
    assert proxy_auth.proxy_user(req(), db).username == "brian"


@pytest.mark.parametrize("r", [req(peer="192.168.4.20"), req(secret="wrong"), req(secret=None), req(user=None), req(user="nobody")])
def test_every_missing_lock_falls_back_to_normal_login(db, on, r):
    add_user(db)
    assert proxy_auth.proxy_user(r, db) is None


def test_user_map_translates_portal_names(db, on, monkeypatch):
    add_user(db, "bwagner")
    monkeypatch.setattr(proxy_auth.settings, "proxy_auth_user_map", "brian=bwagner")
    assert proxy_auth.proxy_user(req(), db).username == "bwagner"


def test_empty_secret_never_trusts(db, on, monkeypatch):
    add_user(db)
    monkeypatch.setattr(proxy_auth.settings, "proxy_auth_secret", "")
    assert proxy_auth.proxy_user(req(secret=""), db) is None


def test_non_ascii_secret_is_refused_not_a_crash(db, on):
    add_user(db)
    assert proxy_auth.proxy_user(req(secret="s3crét"), db) is None


def run(coro):
    import asyncio
    return asyncio.run(coro)


def test_login_page_sends_a_proxy_user_to_the_dashboard(db, on):
    from app.routers.auth import login_page
    add_user(db)
    r = run(login_page(req(), db))
    assert r.status_code == 303 and r.headers["location"] == "/dashboard"


def test_sign_out_under_sso_goes_to_the_proxy_sign_out(db, on, monkeypatch):
    from app.routers.auth import logout
    monkeypatch.setattr(proxy_auth.settings, "proxy_auth_logout_url", "https://sso.example.com/logout")
    add_user(db)
    request = req()
    request.cookies = {}
    r = run(logout(request, None, db))
    assert r.status_code == 303 and r.headers["location"] == "https://sso.example.com/logout"


def test_sign_out_without_sso_still_goes_to_login(db, monkeypatch):
    from app.routers.auth import logout
    monkeypatch.setattr(proxy_auth.settings, "proxy_auth_logout_url", "https://sso.example.com/logout")
    request = req(peer="192.168.4.20")
    request.cookies = {}
    r = run(logout(request, None, db))
    assert r.headers["location"] == "/login"
