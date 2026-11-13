"""ChatGPT key storage and analyst keyword adoption (offline)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.agents import analyst
from app.database import SessionLocal
from app.main import app
from app.models import LLMApiKey, Profile, SearchQuery


def client() -> TestClient:
    return TestClient(app)


def _clear():
    db = SessionLocal()
    db.execute(delete(LLMApiKey))
    db.execute(delete(SearchQuery))
    db.execute(delete(Profile))
    db.commit()
    db.close()


def test_chatgpt_key_is_stored_encrypted_and_never_returned():
    _clear()
    c = client()
    res = c.post(
        "/api/llm/keys",
        json={
            "label": "ChatGPT",
            "provider": "openai",
            "api_key": "sk-test-123456789",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["masked"] == "sk-t...6789"
    assert "api_key" not in body

    listing = c.get("/api/llm/keys").json()
    assert len(listing) == 1
    assert listing[0]["label"] == "ChatGPT"

    db = SessionLocal()
    row = db.scalar(select(LLMApiKey))
    assert row is not None
    assert "sk-test-123456789" not in (row.key_ciphertext or "")
    db.close()

    assert c.delete(f"/api/llm/keys/{body['id']}").status_code == 200
    assert c.get("/api/llm/keys").json() == []


def test_analyst_only_adopts_fitting_keywords():
    _clear()
    db = SessionLocal()
    db.add(
        Profile(
            id=1,
            job_title="Full Stack Developer",
            skills=["react", "python"],
            domain="tech",
            seniority="fresher",
            experience_months=3,
        )
    )
    db.commit()

    analyst._adopt_keywords(
        db,
        None,
        {
            "new_keywords": [
                {"keyword": "junior react developer", "why": "fresher friendly"},
                {"keyword": "founding engineer", "why": "too senior"},
            ]
        },
    )
    known = {row.keyword for row in db.scalars(select(SearchQuery)).all()}
    assert "junior react developer" in known
    assert "founding engineer" not in known
    db.close()
