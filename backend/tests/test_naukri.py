"""Naukri.com: card filtering, freshness and the review-only scan."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.agents import naukri
from app.database import SessionLocal
from app.models import AgentSettings, JobPost, NaukriAccount, Profile, Run
from app.security import encrypt_credentials
from app.services import executor, pipeline

CARD = {
    "id": "271126016736",
    "title": "Python Developer",
    "company": "Acme Labs",
    "experience": "0-1 Yrs",
    "location": "Remote",
    "snippet": "Build FastAPI services with PostgreSQL. Freshers welcome.",
    "posted": "Just now",
    "skills": ["Python", "FastAPI", "PostgreSQL"],
    "url": "https://www.naukri.com/job-listings-python-developer-acme-271126016736",
    "query": "python developer",
}

PROFILE = Profile(
    id=1,
    full_name="Dev Rawat",
    seniority="junior",
    experience_months=4,
    current_role="SDE Intern",
    skills=["python", "fastapi", "postgresql"],
    target_roles=["python developer", "backend developer"],
    country="India",
    location="Dehradun",
    domain="tech",
    willing_to_relocate=True,
)


@pytest.fixture()
def db():
    session = SessionLocal()
    for model in (JobPost, Run, NaukriAccount, AgentSettings, Profile):
        session.execute(delete(model))
    session.commit()
    session.add_all(
        [
            PROFILE,
            AgentSettings(id=1, enabled=True, relevance_threshold=60),
            NaukriAccount(
                user_id=None,
                email="dev@example.com",
                session_ciphertext=encrypt_credentials({"naukri_user": "x"}),
                status="connected",
            ),
        ]
    )
    session.commit()
    yield session
    session.close()


def test_fresher_remote_card_passes():
    verdict = naukri.assess(PROFILE, CARD)
    assert verdict["ok"] is True, verdict["reason"]
    assert verdict["relevance"] >= 45
    assert verdict["required_experience_months"] == 0


def test_senior_and_experienced_cards_are_rejected():
    senior = {**CARD, "title": "Senior Python Developer"}
    assert naukri.assess(PROFILE, senior)["ok"] is False

    experienced = {**CARD, "experience": "3-5 Yrs"}
    verdict = naukri.assess(PROFILE, experienced)
    assert verdict["ok"] is False
    assert "experience" in verdict["reason"]


def test_posted_time_parsing():
    now = datetime(2026, 11, 27, 10, 0, tzinfo=timezone.utc)
    assert naukri.posted_datetime("Just now", now=now) == now
    assert naukri.posted_datetime("2 hours ago", now=now) == now - timedelta(hours=2)
    assert naukri.posted_datetime("1 day ago", now=now) == now - timedelta(days=1)


def test_scan_adds_a_reviewable_apply_link_and_dedupes(db, monkeypatch):
    monkeypatch.setattr(
        executor,
        "run_script",
        lambda name, args=None, **kwargs: {
            "success": True,
            "code": "OK",
            "data": {"jobs": [CARD], "queries": ["python developer"]},
        },
    )

    run = pipeline.scan_naukri(db, user_id=None)
    assert run.status == "completed", run.error
    assert run.stats["source"] == "naukri"
    assert run.stats["posts_new"] == 1

    job = db.scalar(select(JobPost).where(JobPost.source == "naukri"))
    assert job is not None
    assert job.post_id == "naukri:271126016736"
    assert job.status == "new"
    assert job.outreach_method == "link"
    assert job.apply_url.endswith("271126016736")
    assert job.company == "Acme Labs"

    again = pipeline.scan_naukri(db, user_id=None)
    assert again.status == "completed"
    assert again.stats["posts_new"] == 0
    assert again.stats["duplicates"] == 1
    assert len(list(db.scalars(select(JobPost).where(JobPost.source == "naukri")))) == 1


def test_stale_naukri_jobs_leave_the_list(db):
    old = JobPost(
        post_id="naukri:old",
        source="naukri",
        status="new",
        outreach_method="link",
        posted_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    fresh = JobPost(
        post_id="naukri:fresh",
        source="naukri",
        status="new",
        outreach_method="link",
        posted_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    db.add_all([old, fresh])
    db.commit()

    assert pipeline.expire_stale_naukri(db) == 1
    db.refresh(old)
    db.refresh(fresh)
    assert old.status == "rejected"
    assert fresh.status == "new"
