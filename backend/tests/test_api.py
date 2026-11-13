"""Offline smoke tests for the API. Run: .venv\\Scripts\\python.exe -m pytest -q

These never touch X or an LLM provider.
"""

from __future__ import annotations

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def client() -> TestClient:
    return TestClient(app)


def test_health():
    res = client().get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "executor" in body


def test_profile_roundtrip():
    c = client()
    payload = {
        "full_name": "Dev Rawat",
        "job_title": "Full Stack Developer",
        "skills": ["python", "react"],
        "locations": ["remote"],
        "seniority": "mid",
        "experience_months": 30,
    }
    res = c.put("/api/profile", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["full_name"] == "Dev Rawat"
    assert body["skills"] == ["python", "react"]

    res = c.get("/api/profile")
    assert res.status_code == 200
    assert res.json()["job_title"] == "Full Stack Developer"
    assert res.json()["experience_months"] == 30


def test_settings_defaults_and_update():
    c = client()
    res = c.get("/api/settings")
    assert res.status_code == 200
    assert res.json()["relevance_threshold"] >= 1

    res = c.put("/api/settings", json={"relevance_threshold": 70, "daily_dm_cap": 5})
    assert res.status_code == 200
    body = res.json()
    assert body["relevance_threshold"] == 70
    assert body["daily_dm_cap"] == 5


def test_scan_without_account_reports_clean_error():
    c = client()
    res = c.post("/api/runs/scan")
    assert res.status_code == 200
    run_id = res.json()["id"]

    import time

    for _ in range(50):
        run = c.get(f"/api/runs/{run_id}").json()
        if run["status"] != "running":
            break
        time.sleep(0.1)
    assert run["status"] == "failed"
    assert "Connect your X account" in run["error"]


def test_job_list_and_filters():
    c = client()
    res = c.get("/api/jobs")
    assert res.status_code == 200
    assert isinstance(res.json(), list)
    assert c.get("/api/jobs?status=nonsense").status_code == 400

    stats = c.get("/api/jobs/stats")
    assert stats.status_code == 200
    assert "by_status" in stats.json()


def test_dashboard():
    res = client().get("/api/dashboard")
    assert res.status_code == 200
    body = res.json()
    assert "usage" in body and "pending_approvals" in body
