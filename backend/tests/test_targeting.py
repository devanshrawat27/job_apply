"""Targeting rules: multi-role search, domain gating, experience and avoid."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.agents import discovery
from app.database import SessionLocal
from app.models import ActionLog, AgentSettings, DraftExample, JobPost, Profile, Run, XAccount
from app.security import encrypt_credentials
from app.services import executor, pipeline


# ---------------------------------------------------------------- experience

@pytest.mark.parametrize(
    "text,expected",
    [
        ("We need 3+ years of experience", 36),
        ("2-5 years experience required", 24),
        ("minimum 1 year experience", 12),
        ("Freshers welcome, entry level", 0),
        ("No experience required", 0),
        ("Join our team as a React developer", 0),
    ],
)
def test_required_experience_parsing(text, expected):
    assert discovery.required_experience_months(text) == expected


# ----------------------------------------------------------------- roles

def test_selected_roles_are_not_a_limit():
    profile = Profile(
        id=1,
        job_title="Full Stack Developer",
        target_roles=["React Developer"],
        skills=["react", "next.js", "node.js", "nestjs", "python"],
        domain="tech",
    )
    adjacent = discovery.infer_adjacent_roles(profile)
    assert adjacent, "adjacent roles should be inferred from skills"
    assert all(role.lower() not in {"full stack developer", "react developer"} for role in adjacent)
    assert "Frontend Developer" in adjacent or "Node.js Developer" in adjacent


def test_non_tech_profile_gets_no_tech_roles():
    profile = Profile(id=1, job_title="Sales Executive", target_roles=[], skills=["sales"], domain="non-tech")
    assert discovery.infer_adjacent_roles(profile) == []


def test_queries_include_adjacent_roles():
    profile = Profile(
        id=1,
        job_title="Backend Developer",
        target_roles=[],
        skills=["python", "fastapi", "postgresql"],
        domain="tech",
    )
    settings_row = AgentSettings(id=1, lookback_hours=24)

    queries = discovery.build_queries(profile, settings_row)
    assert len(queries) >= 1
    joined = " ".join(queries).lower()
    assert "backend developer" in joined
    # An adjacent role query exists as well.
    assert any(role.lower() in joined for role in discovery.infer_adjacent_roles(profile))


# ------------------------------------------------------------------ domain

def test_domain_detection():
    from app.agents.resume import _detect_domain

    assert _detect_domain("Software engineer with React and Python experience") == "tech"
    assert _detect_domain("Sales and marketing manager, business development") == "non-tech"


# --------------------------------------------------------------- pipeline

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
                target_roles=["Frontend Developer"],
                skills=["react", "python", "fastapi", "node"],
                domain="tech",
                experience_months=3,
                avoid=["sales"],
            ),
            AgentSettings(id=1, enabled=True, relevance_threshold=50, auto_send_enabled=False),
            XAccount(
                username="dev",
                session_ciphertext=encrypt_credentials({"auth_token": "a", "ct0": "b", "twid": "c"}),
            ),
        ]
    )
    session.commit()
    yield session
    session.close()


def _post(post_id: str, text: str) -> dict:
    return {
        "post_id": post_id,
        "post_url": f"https://x.com/i/web/status/{post_id}",
        "post_content": text,
        "author_handle": "hiringguy",
        "author_name": "Hiring",
        "posted_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    }


def test_scan_rejects_post_that_needs_more_experience(db, monkeypatch):
    text = (
        "We're hiring a React developer. React, Node, Python and FastAPI. "
        "Fully remote. 5+ years of experience required. DM me."
    )
    monkeypatch.setattr(
        executor,
        "run_script",
        lambda name, args=None, **kw: {"success": True, "code": "OK", "data": {"posts": [_post("901", text)]}},
    )

    run = pipeline.scan(db, manual=True)
    assert run.status == "completed", run.error

    job = db.scalar(select(JobPost))
    assert job is not None
    assert job.status == "rejected"
    assert job.required_experience_months == 60
    assert any("needs 5 yrs" in line for line in job.logs)


def test_scan_rejects_avoided_role(db, monkeypatch):
    text = (
        "We're hiring for a sales role. React experience is a plus. "
        "Fully remote. DM me if interested in this sales position."
    )
    monkeypatch.setattr(
        executor,
        "run_script",
        lambda name, args=None, **kw: {"success": True, "code": "OK", "data": {"posts": [_post("902", text)]}},
    )

    pipeline.scan(db, manual=True)
    job = db.scalar(select(JobPost))
    assert job is not None
    assert job.status == "rejected"
    assert any("not a fit" in line for line in job.logs)


def test_scan_keeps_fresher_role(db, monkeypatch):
    text = (
        "We're hiring a React developer. React, Node, Python and FastAPI. "
        "Fully remote, freshers welcome. DM me."
    )
    monkeypatch.setattr(
        executor,
        "run_script",
        lambda name, args=None, **kw: {"success": True, "code": "OK", "data": {"posts": [_post("903", text)]}},
    )

    pipeline.scan(db, manual=True)
    job = db.scalar(select(JobPost))
    assert job is not None
    assert job.status == "pending_approval"
    assert job.required_experience_months == 0


def test_tech_resume_rejects_non_tech_post(db, monkeypatch):
    text = (
        "We are hiring a marketing manager to run campaigns. "
        "Fully remote, great culture. DM me if interested."
    )
    monkeypatch.setattr(
        executor,
        "run_script",
        lambda name, args=None, **kw: {"success": True, "code": "OK", "data": {"posts": [_post("904", text)]}},
    )

    pipeline.scan(db, manual=True)
    job = db.scalar(select(JobPost))
    assert job is not None
    assert job.status == "rejected"
    assert any("non-tech" in line for line in job.logs)


def test_business_developer_is_not_a_tech_role():
    profile = Profile(id=1, job_title="Full Stack Developer", skills=["react", "python"], domain="tech")
    text = (
        "We're hiring an International Business Developer. You will break into new "
        "markets, generate new revenue and forge strategic partnerships."
    )
    assert discovery.domain_mismatch(profile, text) == "looks like a non-tech role"


def test_one_dm_per_person_history_is_counted(db):
    first = JobPost(
        post_id="dm1", post_url="", author_handle="test_person", content="hiring",
        dm_status="sent", status="sent", sent_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    second = JobPost(
        post_id="dm2", post_url="", author_handle="test_person", content="hiring",
        dm_status="none", status="queued",
    )
    stranger = JobPost(
        post_id="dm3", post_url="", author_handle="fresh_person", content="hiring",
        dm_status="none", status="queued",
    )
    db.add_all([first, second, stranger])
    db.commit()

    count, _last = pipeline.dm_stats(db, second)
    assert count == 1
    allowed, follow_up, _reason = pipeline.dm_followup_allowed(db, second)
    assert allowed is True
    assert follow_up == 1
    assert pipeline.dm_stats(db, stranger)[0] == 0


def test_dm_cap_forces_public_reply(db):
    for index in range(pipeline.DM_MAX_PER_PERSON):
        db.add(
            JobPost(
                post_id=f"cap{index}", post_url="", author_handle="chatty_dev",
                content="hiring", dm_status="sent", status="sent",
                sent_at=datetime.now(timezone.utc) - timedelta(days=3),
            )
        )
    target = JobPost(
        post_id="cap-new", post_url="", author_handle="chatty_dev", content="hiring",
    )
    db.add(target)
    db.commit()

    allowed, count, reason = pipeline.dm_followup_allowed(db, target)
    assert allowed is False
    assert count == pipeline.DM_MAX_PER_PERSON
    assert "public reply only" in reason


def test_recent_dm_blocks_an_immediate_follow_up(db):
    db.add(
        JobPost(
            post_id="recent1", post_url="", author_handle="recent_dev", content="hiring",
            dm_status="sent", status="sent", sent_at=datetime.now(timezone.utc),
        )
    )
    target = JobPost(post_id="recent2", post_url="", author_handle="recent_dev", content="hiring")
    db.add(target)
    db.commit()

    allowed, _count, reason = pipeline.dm_followup_allowed(db, target)
    assert allowed is False
    assert "follow-up in about" in reason


def test_unknown_dm_is_counted_too(db):
    job = JobPost(post_id="dm4", post_url="", author_handle="someone", content="hiring")
    db.add(job)
    db.commit()
    db.add(ActionLog(job_id=job.id, action="dm", status="unknown", target="@someone", content="hi"))
    db.commit()
    count, _last = pipeline.dm_stats(db, job)
    assert count == 1


def test_feed_only_scan_skips_keyword_searches(db, monkeypatch):
    calls = []

    def fake_run(name, args=None, **kwargs):
        calls.append((name, args))
        return {"success": True, "code": "OK", "data": {"posts": []}}

    monkeypatch.setattr(executor, "run_script", fake_run)
    run = pipeline.scan(
        db, user_id=None, feed_only=True, feed_count=70, feed_scrolls=14
    )
    assert run.status == "completed", run.error
    assert [name for name, _ in calls] == ["feed"]
    feed_args = calls[0][1]
    assert feed_args["count"] == 70
    assert feed_args["scrolls"] == 14


def test_individual_founder_outranks_a_job_board():
    profile = Profile(
        id=1,
        job_title="Full Stack Developer",
        skills=["react", "node.js"],
        domain="tech",
        experience_months=12,
    )
    text = (
        "We're hiring a Founding Engineer. React + Node. Early stage, 0 to 1. "
        "1+ years is fine. DM me your resume."
    )
    founder = JobPost(
        post_id="a1", post_url="", author_handle="rahul_founder",
        author_name="Rahul", content=text,
    )
    board = JobPost(
        post_id="a2", post_url="", author_handle="jobsfordevs_com",
        author_name="Jobs for Devs", content=text,
    )

    scored = discovery.score_posts(profile, [founder, board])
    assert scored["a1"]["author_type"] == "person"
    assert scored["a2"]["author_type"] == "job_board"
    assert scored["a1"]["relevance"] > scored["a2"]["relevance"]
    assert scored["a1"]["relevance"] >= 85
