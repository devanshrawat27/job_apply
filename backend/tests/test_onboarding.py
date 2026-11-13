"""Onboarding API tests: resume upload, profile save, completion flag."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient

from app.main import app


def client() -> TestClient:
    return TestClient(app)


RESUME = """Dev Rawat
Full-stack engineer building agentic web apps.

dev@example.com | +91 98765 43210 | Remote, India
github.com/devrawat | devrawat.dev

Experience: 4 years
Skills: Python, FastAPI, React, TypeScript, PostgreSQL, Docker, AWS

Built and shipped an AI outreach platform. Led a 3-person team.
"""


def test_resume_upload_extracts_and_prefills():
    c = client()
    res = c.post(
        "/api/profile/resume",
        files={"file": ("resume.txt", io.BytesIO(RESUME.encode()), "text/plain")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["chars"] > 100
    extracted = body["extracted"]
    assert extracted["email"] == "dev@example.com"
    assert "python" in [s.lower() for s in extracted["skills"]]

    profile = c.get("/api/profile").json()
    assert profile["resume_filename"] == "resume.txt"
    assert profile["email"] == "dev@example.com"
    assert profile["experience_months"] == 48
    assert profile["onboarding_completed"] is False


def test_rejects_unsupported_file():
    res = client().post(
        "/api/profile/resume",
        files={"file": ("photo.png", io.BytesIO(b"\x89PNG"), "image/png")},
    )
    assert res.status_code == 400


def test_profile_save_and_complete_onboarding():
    c = client()

    res = c.put(
        "/api/profile",
        json={
            "full_name": "Dev Rawat",
            "job_title": "Full Stack Developer",
            "target_roles": ["Backend Engineer"],
            "locations": ["Remote", "Bangalore"],
            "seniority": "senior",
            "experience_months": 48,
            "remote_ok": True,
            "skills": ["Python", "React"],
        },
    )
    assert res.status_code == 200
    assert res.json()["job_title"] == "Full Stack Developer"
    assert res.json()["onboarding_completed"] is False

    res = c.put("/api/profile", json={"onboarding_completed": True})
    assert res.status_code == 200
    assert res.json()["onboarding_completed"] is True

    # The rest of the fields must survive a partial update.
    profile = c.get("/api/profile").json()
    assert profile["job_title"] == "Full Stack Developer"
    assert profile["locations"] == ["Remote", "Bangalore"]


def test_settings_has_dm_and_reply_switches():
    c = client()
    res = c.get("/api/settings")
    assert res.status_code == 200
    assert res.json()["send_dms"] is True

    res = c.put("/api/settings", json={"send_dms": False, "use_public_reply": True})
    assert res.status_code == 200
    assert res.json()["send_dms"] is False
