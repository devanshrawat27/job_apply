"""Auth: bootstrap account, login, refresh, logout, protected routes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import User

EMAIL = "smoke@example.com"
PASSWORD = "correct-horse-battery"


def _client() -> TestClient:
    return TestClient(app)


def _clear_users() -> None:
    db = SessionLocal()
    try:
        for user in db.query(User).all():
            db.delete(user)
        db.commit()
    finally:
        db.close()


def test_status_reports_no_user_initially():
    _clear_users()
    body = _client().get("/api/auth/status").json()
    assert body["has_user"] is False


def test_register_login_refresh_and_logout():
    _clear_users()
    c = _client()

    res = c.post("/api/auth/register", json={"email": EMAIL, "password": PASSWORD})
    assert res.status_code == 201, res.text
    tokens = res.json()
    assert tokens["access_token"] and tokens["refresh_token"]

    # Multiple accounts are allowed, but the same email cannot register twice.
    res = c.post("/api/auth/register", json={"email": "other@example.com", "password": PASSWORD})
    assert res.status_code == 201
    res = c.post("/api/auth/register", json={"email": EMAIL, "password": PASSWORD})
    assert res.status_code == 409

    res = c.post("/api/auth/login", json={"email": EMAIL, "password": "wrong-password"})
    assert res.status_code == 401

    res = c.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert res.status_code == 200
    refresh = res.json()["refresh_token"]

    res = c.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert res.status_code == 200
    new_refresh = res.json()["refresh_token"]

    # Rotating the refresh token invalidates the previous one.
    res = c.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert res.status_code == 401

    res = c.post("/api/auth/logout", json={"refresh_token": new_refresh})
    assert res.status_code == 200
    res = c.post("/api/auth/refresh", json={"refresh_token": new_refresh})
    assert res.status_code == 401


def test_protected_route_needs_bearer_token(monkeypatch):
    _clear_users()
    c = _client()
    tokens = c.post(
        "/api/auth/register", json={"email": EMAIL, "password": PASSWORD}
    ).json()

    monkeypatch.setattr(settings, "auth_enabled", True)

    assert c.get("/api/profile").status_code == 401
    assert c.get("/api/jobs").status_code == 401

    res = c.get("/api/profile", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert res.status_code == 200

    res = c.get("/api/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert res.status_code == 200
    assert res.json()["email"] == EMAIL


def test_validation_errors_do_not_echo_password():
    res = TestClient(app).post(
        "/api/accounts/connect",
        json={"username": "someone", "password": ["secret-value"]},
    )
    assert res.status_code == 422
    assert "secret-value" not in res.text


def test_each_user_gets_an_isolated_workspace(monkeypatch):
    _clear_users()
    c = _client()
    monkeypatch.setattr(settings, "auth_enabled", True)

    a = c.post("/api/auth/register", json={"email": "a@example.com", "password": PASSWORD}).json()
    b = c.post("/api/auth/register", json={"email": "b@example.com", "password": PASSWORD}).json()
    ha = {"Authorization": f"Bearer {a['access_token']}"}
    hb = {"Authorization": f"Bearer {b['access_token']}"}

    res = c.put(
        "/api/profile",
        json={"full_name": "User A", "job_title": "Backend Developer"},
        headers=ha,
    )
    assert res.status_code == 200

    prof_a = c.get("/api/profile", headers=ha).json()
    prof_b = c.get("/api/profile", headers=hb).json()
    assert prof_a["full_name"] == "User A"
    assert prof_b["full_name"] == ""

    c.put("/api/settings", json={"relevance_threshold": 81}, headers=ha)
    assert c.get("/api/settings", headers=ha).json()["relevance_threshold"] == 81
    assert c.get("/api/settings", headers=hb).json()["relevance_threshold"] != 81

    assert c.get("/api/jobs", headers=hb).json() == []
