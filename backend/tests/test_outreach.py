"""Outreach mechanics: follow-only-when-needed and fake-post guard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.agents import composer, spam
from app.database import SessionLocal
from app.models import ActionLog, AgentSettings, DraftExample, JobPost, Profile, Run, XAccount
from app.security import encrypt_credentials
from app.services import executor, pipeline


# --------------------------------------------------------------------- spam

def test_registration_fee_is_a_fake_post():
    result = spam.assess(
        "Hiring urgently! Work from home, earn 50000 per day. "
        "Registration fee 499 required. DM for details. WhatsApp me.",
        "quickjobs123456",
    )
    assert result["score"] >= spam.REJECT_THRESHOLD
    assert any("fee" in reason for reason in result["reasons"])


def test_real_posting_scores_low():
    result = spam.assess(
        "We're hiring a backend engineer at Acme Technologies. "
        "Python, FastAPI, PostgreSQL. 2-4 years. Remote. Apply via DM.",
        "acmehiring",
    )
    assert result["score"] < spam.REVIEW_THRESHOLD


def test_earnings_bait_is_flagged():
    result = spam.assess(
        "Earn up to 1 lakh monthly. No interview, direct joining. Any graduate. DM fast!",
        "easy_money",
    )
    assert result["score"] >= spam.REVIEW_THRESHOLD


# ------------------------------------------------------------------ fixtures

@pytest.fixture()
def db():
    session = SessionLocal()
    for model in (ActionLog, JobPost, Run, DraftExample):
        session.execute(delete(model))
    session.execute(delete(XAccount))
    session.execute(delete(AgentSettings))
    session.execute(delete(Profile))
    session.commit()

    session.add_all(
        [
            Profile(
                id=1,
                full_name="Dev",
                job_title="Full Stack Developer",
                target_roles=[],
                skills=["react", "python", "fastapi", "node"],
                domain="tech",
                experience_months=3,
            ),
            AgentSettings(
                id=1,
                enabled=True,
                relevance_threshold=50,
                auto_send_enabled=True,
                min_minutes_between_writes=0,
                quiet_hours="",
                use_public_reply=True,
                send_dms=True,
                follow_when_needed=True,
            ),
            XAccount(
                username="dev",
                session_ciphertext=encrypt_credentials({"auth_token": "a", "ct0": "b", "twid": "c"}),
            ),
        ]
    )
    session.commit()
    yield session
    session.close()


GOOD_POST = {
    "post_id": "9901",
    "post_url": "https://x.com/i/web/status/9901",
    "post_content": (
        "We're hiring a React developer at Acme Technologies. Stack: React, Node, "
        "Python, FastAPI. Fully remote, freshers welcome. DM me."
    ),
    "author_handle": "acmefounder",
    "author_name": "Acme Founder",
    "posted_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
}


def _prepare(db, monkeypatch, posts=None):
    posts = posts or [GOOD_POST]
    monkeypatch.setattr(
        executor,
        "run_script",
        lambda name, args=None, **kw: {"success": True, "code": "OK", "data": {"posts": posts}},
    )
    monkeypatch.setattr(
        composer,
        "compose",
        lambda profile, job, examples=None, **kwargs: {
            "reply_text": "Sent you a DM — this is exactly my stack.",
            "dm_text": "Hi! React + FastAPI dev here. Happy to share my work.",
            "confidence": 0.97,
            "uncertainties": [],
        },
    )
    pipeline.scan(db, manual=True)
    return db.scalar(select(JobPost))


def test_dm_works_without_following(db, monkeypatch):
    _prepare(db, monkeypatch)
    calls: list[str] = []

    def fake_write(name, args=None, **kwargs):
        calls.append(name)
        return {"success": True, "code": "OK", "data": {}}

    monkeypatch.setattr(executor, "run_script", fake_write)
    pipeline.send_batch(db)

    job = db.scalar(select(JobPost))
    db.refresh(job)
    assert calls == ["reply", "dm"]
    assert job.followed is False
    assert job.dm_status == "sent"


def test_follow_only_when_dm_is_locked(db, monkeypatch):
    _prepare(db, monkeypatch)
    calls: list[str] = []
    attempts = {"dm": 0}

    def fake_write(name, args=None, **kwargs):
        calls.append(name)
        if name == "dm":
            attempts["dm"] += 1
            if attempts["dm"] == 1:
                return {"success": False, "code": "DM_LOCKED", "error": "follow to message"}
            return {"success": True, "code": "OK", "data": {}}
        if name == "follow":
            return {"success": True, "code": "OK", "data": {"followed": True}}
        return {"success": True, "code": "OK", "data": {}}

    monkeypatch.setattr(executor, "run_script", fake_write)
    pipeline.send_batch(db)

    job = db.scalar(select(JobPost))
    db.refresh(job)
    assert calls == ["reply", "dm", "follow", "dm"]
    assert job.followed is True
    assert job.dm_status == "sent"
    assert any("followed @" in line for line in job.logs)


def test_follow_is_skipped_when_disabled(db, monkeypatch):
    _prepare(db, monkeypatch)
    settings_row = pipeline.get_settings_row(db)
    settings_row.follow_when_needed = False
    db.commit()

    calls: list[str] = []

    def fake_write(name, args=None, **kwargs):
        calls.append(name)
        if name == "dm":
            return {"success": False, "code": "DM_LOCKED", "error": "follow to message"}
        return {"success": True, "code": "OK", "data": {}}

    monkeypatch.setattr(executor, "run_script", fake_write)
    pipeline.send_batch(db)

    job = db.scalar(select(JobPost))
    db.refresh(job)
    assert "follow" not in calls
    assert job.followed is False
    # The account does not accept DMs: skip it, do not retry.
    assert job.dm_status == "skipped"
    assert job.status == "skipped"


def test_scan_rejects_a_fake_post(db, monkeypatch):
    fake_post = {
        **GOOD_POST,
        "post_id": "9902",
        "post_content": (
            "Urgent hiring! Work from home, earn 50000 per day. "
            "No interview, direct joining. Registration fee 499. WhatsApp me. DM fast."
        ),
    }
    monkeypatch.setattr(
        executor,
        "run_script",
        lambda name, args=None, **kw: {"success": True, "code": "OK", "data": {"posts": [fake_post]}},
    )
    pipeline.scan(db, manual=True)

    job = db.scalar(select(JobPost))
    assert job is not None
    assert job.status == "rejected"
    assert job.spam_score >= spam.REJECT_THRESHOLD
    assert any("fake-post score" in line for line in job.logs)


def test_reported_handles_are_skipped(db, monkeypatch):
    monkeypatch.setattr(
        executor,
        "run_script",
        lambda name, args=None, **kw: {"success": True, "code": "OK", "data": {"posts": [GOOD_POST]}},
    )
    settings_row = pipeline.get_settings_row(db)
    settings_row.reported_handles = ["acmefounder"]
    db.commit()

    pipeline.scan(db, manual=True)
    job = db.scalar(select(JobPost))
    assert job is not None
    assert job.status == "rejected"
    assert any("reported this account as fake" in line for line in job.logs)

def test_passcode_required_is_a_retryable_failure(db, monkeypatch):
    """No passcode saved + X asks for one = safe failure, not UNKNOWN, no follow."""
    _prepare(db, monkeypatch)
    calls: list[str] = []

    def fake_write(name, args=None, **kwargs):
        calls.append(name)
        if name == "dm":
            return {
                "success": False,
                "code": "PASSCODE_REQUIRED",
                "error": "X asked for your chat passcode and none is saved",
            }
        return {"success": True, "code": "OK", "data": {}}

    monkeypatch.setattr(executor, "run_script", fake_write)
    pipeline.send_batch(db)

    job = db.scalar(select(JobPost))
    db.refresh(job)
    assert calls == ["reply", "dm"]
    assert job.dm_status == "failed"
    assert job.followed is False
    assert "passcode" in (job.last_error or "").lower()


def test_set_and_clear_dm_passcode(db):
    from fastapi.testclient import TestClient

    from app.main import app

    account = db.scalar(select(XAccount))
    client = TestClient(app)

    res = client.put(f"/api/accounts/{account.id}/dm-passcode", json={"passcode": "1234"})
    assert res.status_code == 200
    assert res.json()["has_dm_passcode"] is True

    res = client.put(f"/api/accounts/{account.id}/dm-passcode", json={"passcode": None})
    assert res.status_code == 200
    assert res.json()["has_dm_passcode"] is False



