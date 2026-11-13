"""End-to-end flow tests with the X executor faked out.

They prove the pipeline logic: filtering, ranking, drafting, the auto-send vs
approval decision, and the write bookkeeping.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.agents import composer
from app.database import SessionLocal
from app.models import ActionLog, AgentSettings, DraftExample, JobPost, Profile, Run, XAccount
from app.security import encrypt_credentials
from app.services import executor, pipeline


@pytest.fixture()
def db():
    session = SessionLocal()
    for model in (ActionLog, JobPost, Run, DraftExample):
        session.execute(delete(model))
    session.execute(delete(XAccount))
    session.execute(delete(AgentSettings))
    session.execute(delete(Profile))
    session.commit()

    profile = Profile(
        id=1,
        full_name="Dev Rawat",
        seniority="junior",
        experience_months=14,
        current_role="Full Stack Developer",
        current_company="Freelance",
        skills=["react", "python", "fastapi", "node"],
        target_roles=["react developer", "backend engineer"],
        locations=["remote"],
        remote_ok=True,
    )
    settings_row = AgentSettings(id=1, enabled=True, relevance_threshold=60, auto_send_enabled=False)
    account = XAccount(
        username="devrawat",
        display_name="Dev",
        session_ciphertext=encrypt_credentials(
            {"auth_token": "a", "ct0": "b", "twid": "u=1"}
        ),
    )
    session.add_all([profile, settings_row, account])
    session.commit()

    yield session
    session.close()


def post(post_id: str, text: str, *, age_hours: int = 2, handle: str = "startupguy") -> dict:
    posted = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    return {
        "post_id": post_id,
        "post_url": f"https://x.com/i/web/status/{post_id}",
        "post_content": text,
        "author_handle": handle,
        "author_name": "Startup Guy",
        "posted_at": posted.isoformat(),
    }


GOOD_TEXT = (
    "We're hiring a React developer for our platform team. "
    "Stack: React, Node, Python and FastAPI. Fully remote, DM me if interested!"
)


def fake_search(posts):
    def runner(name, args=None, **kwargs):
        # The scan now also scrolls the home feed; return the same fixture there.
        assert name in ("search", "feed")
        return {"success": True, "code": "OK", "data": {"posts": posts}}

    return runner


def test_scan_filters_and_drafts(db, monkeypatch):
    posts = [
        post("111", GOOD_TEXT),
        post("222", GOOD_TEXT, age_hours=24 * 10),          # too old
        post("333", GOOD_TEXT, handle="devrawat"),          # own post
        post("444", "lol same"),                            # not a job post
    ]
    monkeypatch.setattr(executor, "run_script", fake_search(posts))

    run = pipeline.scan(db, manual=True)

    assert run.status == "completed", run.error
    assert run.stats["posts_new"] == 1
    assert run.stats["relevant"] == 1

    job = db.scalar(select(JobPost))
    assert job is not None
    assert job.post_id == "111"
    assert job.relevance >= 60
    assert job.reply_text
    assert job.dm_text
    # Offline template has confidence 0.35 -> always needs a human.
    assert job.status == "pending_approval"
    assert job.confidence < 0.8


def test_auto_send_when_confident(db, monkeypatch):
    monkeypatch.setattr(executor, "run_script", fake_search([post("555", GOOD_TEXT)]))

    monkeypatch.setattr(
        composer,
        "compose",
        lambda profile, job, examples=None, **kwargs: {
            "reply_text": "Sent you a DM — this is exactly my stack.",
            "dm_text": "Hi! React + FastAPI dev here. Happy to share my work.",
            "confidence": 0.95,
            "uncertainties": [],
        },
    )

    settings_row = pipeline.get_settings_row(db)
    settings_row.auto_send_enabled = True
    settings_row.min_minutes_between_writes = 0
    settings_row.quiet_hours = ""
    db.commit()

    pipeline.scan(db, manual=True)
    job = db.scalar(select(JobPost))
    assert job.status == "queued", job.logs

    calls: list[str] = []

    def fake_write(name, args=None, **kwargs):
        calls.append(name)
        return {"success": True, "code": "OK", "data": {}}

    monkeypatch.setattr(executor, "run_script", fake_write)

    send_run = pipeline.send_batch(db)
    assert send_run.status == "completed", send_run.error

    db.refresh(job)
    assert job.status == "sent"
    assert job.reply_status == "sent"
    assert job.dm_status == "sent"
    assert calls == ["reply", "dm"]

    logs = list(db.scalars(select(ActionLog)).all())
    assert {log.action for log in logs} == {"reply", "dm"}


def test_unknown_write_is_not_retried(db, monkeypatch):
    monkeypatch.setattr(executor, "run_script", fake_search([post("777", GOOD_TEXT)]))
    monkeypatch.setattr(
        composer,
        "compose",
        lambda profile, job, examples=None, **kwargs: {
            "reply_text": "reply",
            "dm_text": "dm",
            "confidence": 0.99,
            "uncertainties": [],
        },
    )

    settings_row = pipeline.get_settings_row(db)
    settings_row.auto_send_enabled = True
    settings_row.min_minutes_between_writes = 0
    settings_row.quiet_hours = ""
    db.commit()

    pipeline.scan(db, manual=True)

    calls: list[str] = []

    def fake_write(name, args=None, **kwargs):
        calls.append(name)
        return {"success": False, "code": "UNKNOWN", "error": "no confirmation"}

    monkeypatch.setattr(executor, "run_script", fake_write)
    pipeline.send_batch(db)

    job = db.scalar(select(JobPost))
    db.refresh(job)
    assert job.reply_status == "unknown"
    assert job.status == "failed"
    # The DM must not be attempted after an unknown reply.
    assert calls == ["reply"]

    # A second batch must not touch it again: the job is no longer queued.
    pipeline.send_batch(db)
    assert calls == ["reply"]


def test_red_flag_always_needs_approval(db, monkeypatch):
    text = (
        "Hiring a React developer, fully remote. Stack React Node Python FastAPI. "
        "This is an unpaid internship, DM me."
    )
    monkeypatch.setattr(executor, "run_script", fake_search([post("888", text)]))

    job = JobPost(
        post_id="888",
        post_url="https://x.com/i/web/status/888",
        author_handle="cheapguy",
        content=text,
    )
    db.add(job)
    db.commit()

    result = composer.compose(db.get(Profile, 1), job)
    assert any("red flag" in u for u in result["uncertainties"])
    assert result["confidence"] <= 0.2



def test_apply_link_count_ignores_rejected_and_applied(db):
    from app.services import pipeline as flow

    def make(post_id: str, status: str, url: str) -> JobPost:
        job = JobPost(
            post_id=post_id,
            post_url=f"https://x.com/i/web/status/{post_id}",
            author_handle="someone",
            content="hiring",
            status=status,
            apply_url=url,
        )
        db.add(job)
        return job

    make("900", "queued", "https://acme.com/apply")
    make("901", "skipped", "https://acme.com/apply2")
    make("902", "rejected", "https://acme.com/apply3")
    make("903", "sent", "https://acme.com/apply4")
    make("904", "queued", "")
    db.commit()

    assert flow.apply_link_count(db) == 2
