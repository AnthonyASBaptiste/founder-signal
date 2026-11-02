"""Authentication tests for Founder Signal single-founder sign-in."""

import os
import tempfile

from founder_signal.app import create_app
from founder_signal.auth import _reset_cache_for_testing
from founder_signal.config import Config


def _make_client(username="founder", password="secret"):
    """Create a test client with auth configured via env vars."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    os.environ["FS_ADMIN_USER"] = username
    os.environ["FS_ADMIN_PASSWORD"] = password
    os.environ["FLASK_SECRET_KEY"] = "test-secret-key"
    _reset_cache_for_testing()

    config = Config(ledger_backend="sqlite", ledger_sqlite_path=db_path)
    app = create_app(config)
    app.config["TESTING"] = True
    client = app.test_client()

    try:
        yield client
    finally:
        os.unlink(db_path)


def test_login_success_redirects_to_dashboard(monkeypatch):
    client = next(_make_client())
    resp = client.post(
        "/login",
        data={"username": "founder", "password": "secret"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Signed in successfully" in resp.data


def test_login_failure_shows_error(monkeypatch):
    client = next(_make_client())
    resp = client.post(
        "/login",
        data={"username": "founder", "password": "wrong"},
    )
    assert resp.status_code == 200
    assert b"Invalid username or password" in resp.data


# Regression: ISSUE-020 — Authenticated user accessing /login redirects to /dashboard
# Value: protects=authenticated users visiting /login are redirected to /dashboard; fails_when=authenticated user is sent to /; why_new=tests/test_auth.py covers unauthenticated only; seam=none; no_claim=none beyond protects
def test_authenticated_user_accessing_login_redirects_to_dashboard(monkeypatch):
    client = next(_make_client())
    # Sign in
    client.post("/login", data={"username": "founder", "password": "secret"})
    # Re-visiting /login while already signed in must redirect to cockpit dashboard
    resp = client.get("/login")
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["Location"]


def test_protected_route_redirects_to_login_when_unauthenticated(monkeypatch):
    client = next(_make_client())
    resp = client.get("/dashboard")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_logout_redirects_to_login(monkeypatch):
    client = next(_make_client())
    # Sign in first
    client.post("/login", data={"username": "founder", "password": "secret"})
    # Then sign out
    resp = client.get("/logout", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Signed out" in resp.data
    # After logout, protected routes should redirect again
    resp = client.get("/dashboard")
    assert resp.status_code == 302
