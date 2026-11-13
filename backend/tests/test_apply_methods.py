"""Apply-method routing, specificity, learning, and the outreach timeline."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.agents import composer, discovery
from app.database import SessionLocal
from app.main import app
from app.models import ActionLog, AgentSettings, DraftExample, JobPost, Profile, Run, XAccount
from app.security import encrypt_credentials
from app.services import executor, pipeline


# ------------------------------------------------------- method detection

@pytest.mark.parametrize(
    "text,email,url,expected",
    [
        ("Mail your resume to jobs@acme.com", "jobs@acme.com", "", "email"),
        ("Apply here: https://forms.gle/abc123", "", "https://forms.gle/abc123", "link"),
        ("DM me if interested", "", "", "dm"),
        ("Fill the form: https://acme.com/careers", "", "https://acme.com/careers", "link"),
        ("We are hiring a developer", "", "", "unknown"),
    ],
)
def test_detect_apply_method(text, email, url, expected):
    if email:
        assert discovery.extract_contact_email(text) == email
    if url:
        assert discovery.extract_apply_url(text) == url
    assert discovery.detect_apply_method(text, email=email, url=url) == expected


def test_email_and_url_extraction():
    text = "Send your CV to hiring@acme.io or apply at https://acme.io/jobs/123"
    assert discovery.extract_contact_email(text) == "hiring@acme.io"
    assert discovery.extract_apply_url(text).startswith("https://acme.io/jobs/123")


# ---------------------------------------------------------- specificity

def _post(content: str, role: str = "Backend Engineer", company: str = "Acme") -> JobPost:
    return JobPost(
        post_id="1",
        post_url="https://x.com/i/web/status/1",
        author_handle="acmehiring",
        content=content,
        role=role,
        company=company,
    )


def test_generic_draft_is_detected():
    post = _post(
        "We're hiring a Backend Engineer at Acme. Python, FastAPI, PostgreSQL. DM me."
    )
    assert composer.is_generic("Hi, I am a software developer interested in this role.", post)
    assert not composer.is_generic(
        "Acme is building exactly the FastAPI + PostgreSQL stack I ship every day.", post
    )


def test_fallback_draft_is_specific():
    post = _post(
        "We're hiring a Backend Engineer at Acme. Python, FastAPI, PostgreSQL. DM me."
    )
    profile = Profile(
        id=1,
        full_name="Dev",
        job_title="Backend Developer",
        skills=["python", "fastapi", "postgresql"],
        experience_months=3,
        links={"portfolio": "dev.dev", "github": "github.com/dev"},
    )
    draft = composer.compose(profile, post)
    assert not draft["generic"]
    assert "Acme" in draft["dm_text"] or "Backend Engineer" in draft["dm_text"]
    assert "dev.dev" in draft["dm_text"] or "github.com/dev" in draft["dm_text"]


# --------------------------------------------------------------- fixtures

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
                job_title="Backend Developer",
                skills=["python", "fastapi", "node"],
                domain="tech",
                experience_months=3,
                links={"portfolio": "dev.dev"},
            ),
            AgentSettings(
                id=1,
                enabled=True,
                relevance_threshold=50,
                auto_send_enabled=True,
                min_minutes_between_writes=0,
                quiet_hours="",
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


def _raw(post_id: str, content: str) -> dict:
    return {
        "post_id": post_id,
        "post_url": f"https://x.com/i/web/status/{post_id}",
        "post_content": content,
        "author_handle": "acmefounder",
        "author_name": "Acme Founder",
        "posted_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    }


def _scan_with(db, monkeypatch, content: str):
    monkeypatch.setattr(
        executor,
        "run_script",
        lambda name, args=None, **kw: {
            "success": True,
            "code": "OK",
            "data": {"posts": [_raw("7001", content)]},
        },
    )
    pipeline.scan(db, manual=True)
    return db.scalar(select(JobPost))


def test_email_post_is_routed_to_approval_when_smtp_missing(db, monkeypatch):
    job = _scan_with(
        db,
        monkeypatch,
        "We're hiring a Python backend engineer. Python, FastAPI. "
        "Mail your resume to jobs@acme.com.",
    )
    assert job.outreach_method == "email"
    assert job.contact_email == "jobs@acme.com"
    assert job.status == "pending_approval"
    assert any("apply by email" in line for line in job.logs)


def test_link_post_is_applied_manually_and_never_messaged(db, monkeypatch):
    job = _scan_with(
        db,
        monkeypatch,
        "Hiring a Python backend engineer (FastAPI). Apply here: https://forms.gle/abc123",
    )
    assert job.outreach_method == "link"
    assert job.apply_url.startswith("https://forms.gle/")
    # External apply link: no reply/DM draft, just a manual apply item.
    assert job.status == "new"
    assert job.reply_text == ""
    assert job.dm_text == ""
    assert "external apply link" in job.decision_reason

    job.status = "queued"
    db.commit()

    calls: list[str] = []

    def fake_write(name, args=None, **kwargs):
        calls.append(name)
        return {"success": True, "code": "OK", "data": {}}

    monkeypatch.setattr(executor, "run_script", fake_write)
    pipeline.send_batch(db)

    db.refresh(job)
    assert calls == [], "a link post must never send a reply or DM"
    assert job.status == "new"


def test_dm_post_still_auto_queues(db, monkeypatch):
    job = _scan_with(
        db,
        monkeypatch,
        "We're hiring a Python backend engineer. Python, FastAPI, Node. DM me if interested.",
    )
    assert job.outreach_method == "dm"
    # Without an LLM the template confidence is low, so it waits for approval.
    assert job.status in ("queued", "pending_approval")


def test_approval_teaches_the_composer(db):
    job = JobPost(
        post_id="7002",
        post_url="https://x.com/i/web/status/7002",
        author_handle="acmehiring",
        content="Hiring a Python engineer, DM me.",
        role="Backend Engineer",
        status="pending_approval",
        reply_text="edited reply",
        dm_text="edited dm",
    )
    db.add(job)
    db.commit()

    pipeline.approve(
        db,
        job,
        approved=True,
        reply_text="Hey — saw you need Python + FastAPI. I shipped exactly that.",
        dm_text="Hi! Python/FastAPI dev here, here is my portfolio.",
    )

    example = db.scalar(select(DraftExample))
    assert example is not None
    assert "saw you need Python" in example.reply_text
    assert example.role == "Backend Engineer"


def test_outreach_timeline_records_content_and_target(db, monkeypatch):
    job = _scan_with(
        db,
        monkeypatch,
        "We're hiring a Python backend engineer. Python, FastAPI. DM me if interested.",
    )
    job.status = "queued"
    db.commit()

    def fake_write(name, args=None, **kwargs):
        return {"success": True, "code": "OK", "data": {}}

    monkeypatch.setattr(executor, "run_script", fake_write)
    pipeline.send_batch(db)

    client = TestClient(app)
    rows = client.get("/api/outreach").json()
    assert rows, "timeline should have entries"
    actions = {row["action"] for row in rows}
    assert {"reply", "dm"} <= actions

    dm_row = next(row for row in rows if row["action"] == "dm")
    assert dm_row["target"].startswith("@")
    assert dm_row["content"]
    assert dm_row["post_url"].endswith("7001")

    summary = client.get("/api/outreach/summary").json()
    assert summary["reply"] >= 1 and summary["dm"] >= 1

def test_generic_draft_is_retried_once(monkeypatch):
    from app.agents import composer as composer_mod

    calls = {"n": 0}

    def fake_complete(system, user, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "reply_text": "Hi, I am interested in this role.",
                "dm_text": "Hello, please consider my application.",
                "confidence": 0.9,
                "uncertainties": [],
            }
        return {
            "reply_text": "Acme's FastAPI + PostgreSQL stack is exactly what I ship.",
            "dm_text": "Saw Acme is hiring a Backend Engineer for FastAPI work.",
            "confidence": 0.9,
            "uncertainties": [],
        }

    monkeypatch.setattr(composer_mod, "complete_json", fake_complete)
    monkeypatch.setattr(composer_mod, "_llm_ready", lambda: True)

    profile = Profile(
        id=1,
        full_name="Dev",
        job_title="Backend Developer",
        skills=["python", "fastapi"],
        experience_months=3,
        links={"portfolio": "dev.dev", "github": "github.com/dev"},
    )
    post = _post(
        "We're hiring a Backend Engineer at Acme. Python, FastAPI, PostgreSQL. DM me."
    )
    draft = composer_mod.compose(profile, post)

    assert calls["n"] == 2, "a generic first draft should trigger one retry"
    assert draft["generic"] is False


def test_dm_always_carries_portfolio_and_github(monkeypatch):
    from app.agents import composer as composer_mod

    monkeypatch.setattr(
        composer_mod,
        "complete_json",
        lambda system, user, **kwargs: {
            "reply_text": "Acme + FastAPI is my exact stack.",
            "dm_text": "Saw Acme is hiring a Backend Engineer. I ship FastAPI daily.",
            "confidence": 0.9,
            "uncertainties": [],
        },
    )
    monkeypatch.setattr(composer_mod, "_llm_ready", lambda: True)

    profile = Profile(
        id=1,
        full_name="Dev",
        job_title="Backend Developer",
        skills=["python", "fastapi"],
        experience_months=3,
        links={"portfolio": "dev.dev", "github": "github.com/dev"},
    )
    post = _post("We're hiring a Backend Engineer at Acme. FastAPI. DM me.")
    draft = composer_mod.compose(profile, post)

    assert "dev.dev" in draft["dm_text"]
    assert "github.com/dev" in draft["dm_text"]

def test_confident_non_generic_match_auto_queues(db, monkeypatch):
    from app.agents import composer as composer_mod

    monkeypatch.setattr(
        composer_mod,
        "complete_json",
        lambda system, user, **kwargs: {
            "reply_text": "Acme's FastAPI + PostgreSQL stack is exactly what I ship.",
            "dm_text": "Saw Acme is hiring a Python backend engineer for FastAPI work.",
            "confidence": 0.82,
            "uncertainties": ["start date is not stated"],
        },
    )
    monkeypatch.setattr(composer_mod, "_llm_ready", lambda: True)

    job = _scan_with(
        db,
        monkeypatch,
        "We're hiring a Python backend engineer. Python, FastAPI, PostgreSQL. DM me.",
    )
    assert job.status == "queued", job.logs
    assert job.generic_draft is False

def test_wrapped_apply_url_is_rebuilt():
    text = "Open Role! Apply:\nhttps://\nlinks.nearskill.in/heB7Dx"
    assert discovery.extract_apply_url(text) == "https://links.nearskill.in/heB7Dx"


def test_bare_domain_apply_link_is_detected():
    text = "Apply at jobs.acme.io/apply/123 and DM if you have questions"
    assert discovery.extract_apply_url(text) == "https://jobs.acme.io/apply/123"


def test_mark_applied_creates_an_outreach_entry(db):
    job = JobPost(
        post_id="7100",
        post_url="https://x.com/i/web/status/7100",
        author_handle="nearskill",
        content="Apply: https://links.nearskill.in/heB7Dx",
        role="Sr. Full-Stack Software Engineer",
        apply_url="https://links.nearskill.in/heB7Dx",
        outreach_method="link",
        status="pending_approval",
    )
    db.add(job)
    db.commit()

    client = TestClient(app)
    response = client.post(f"/api/jobs/{job.id}/mark-applied")
    assert response.status_code == 200
    assert response.json()["status"] == "sent"

    rows = client.get("/api/outreach?action=apply").json()
    assert rows
    assert rows[0]["target"] == "https://links.nearskill.in/heB7Dx"


def test_timestamps_are_utc(db):
    """The UI reads these as local time, so they must carry a UTC offset."""
    job = JobPost(
        post_id="7200",
        post_url="https://x.com/i/web/status/7200",
        author_handle="someone",
        content="Hiring a Python developer, DM me.",
        status="sent",
    )
    db.add(job)
    db.commit()

    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    rows = client.get("/api/jobs?status=sent").json()
    assert rows
    assert rows[0]["sent_at"] is None or rows[0]["sent_at"].endswith("+00:00")
    assert rows[0]["discovered_at"].endswith("+00:00")

def test_same_job_reposted_is_deduped(db, monkeypatch):
    text = "We're hiring a Python backend engineer. Python, FastAPI. DM me if interested."
    posts = [_raw("8001", text), _raw("8002", text)]  # different ids, same body

    monkeypatch.setattr(
        executor,
        "run_script",
        lambda name, args=None, **kw: {"success": True, "code": "OK", "data": {"posts": posts}},
    )
    run = pipeline.scan(db, manual=True)

    from sqlalchemy import func, select

    total = db.scalar(select(func.count(JobPost.id)))
    assert total == 1, "the repost must not create a second job"
    assert run.stats["duplicates"] >= 1

def test_strong_match_queues_below_confidence_bar():
    from app.services.pipeline import _decide

    settings_row = AgentSettings(id=1, auto_send_enabled=True, auto_send_confidence=0.7)
    job = JobPost(
        post_id="x1",
        post_url="",
        author_handle="someone",
        content="Hiring a Python engineer. DM me.",
        relevance=100,
        confidence=0.60,
        spam_score=0,
        outreach_method="dm",
        apply_method="dm",
        author_type="person",
    )
    status, _ = _decide(job, settings_row, [])
    assert status == "queued", "a 100-relevance clean draft should apply on its own"

    weak = JobPost(
        post_id="x2",
        post_url="",
        author_handle="someone",
        content="Hiring a Python engineer. DM me.",
        relevance=55,
        confidence=0.60,
        spam_score=0,
        outreach_method="dm",
        apply_method="dm",
        author_type="person",
    )
    status, _ = _decide(weak, settings_row, [])
    assert status == "pending_approval"


def test_apply_link_without_url_goes_to_apply_links_not_approvals(db, monkeypatch):
    job = _scan_with(
        db,
        monkeypatch,
        "Company name: Thales\nRole: Software Engineer Intern\nApply Link:",
    )
    assert job.outreach_method == "link"
    assert job.status == "new"
    assert job.apply_url == job.post_url
    assert job.reply_text == ""
    assert job.dm_text == ""
    assert "inside the post" in job.decision_reason


def test_job_seeker_phrases_are_detected():
    assert discovery.job_seeker_reason("I am open to work and looking for SDE roles")
    assert discovery.job_seeker_reason("Need a referral for backend roles, please refer me")
    assert discovery.job_seeker_reason("Looking for referrals for SDE roles")
    assert discovery.job_seeker_reason("Actively looking for opportunities in Bangalore")
    assert discovery.job_seeker_reason("#OpenToWork #Fresher")
    # Offering referrals / hiring is not a job seeker.
    assert not discovery.job_seeker_reason("We are hiring a backend developer. Referrals open.")
    assert not discovery.job_seeker_reason("Looking for a backend developer to join our team")


def test_job_seeker_post_is_never_saved_or_messaged(db, monkeypatch):
    text = "I am open to work. Looking for a backend role. Please refer me if you can."
    monkeypatch.setattr(
        executor,
        "run_script",
        lambda name, args=None, **kw: {
            "success": True,
            "code": "OK",
            "data": {"posts": [_raw("9001", text)]},
        },
    )

    pipeline.scan(db, manual=True)

    assert db.scalar(select(JobPost)) is None

    # Even a legacy queued row with the same text must not be messaged.
    job = JobPost(
        post_id="9002",
        post_url="https://x.com/i/web/status/9002",
        author_handle="seeker",
        content=text,
        status="queued",
        outreach_method="dm",
        reply_text="reply draft",
        dm_text="dm draft",
    )
    db.add(job)
    db.commit()

    calls: list[str] = []
    monkeypatch.setattr(
        executor, "run_script", lambda name, args=None, **kw: calls.append(name) or {"success": True}
    )
    pipeline.send_batch(db)

    db.refresh(job)
    assert calls == []
    assert job.status == "rejected"
    assert job.reply_text == ""
    assert job.dm_text == ""
