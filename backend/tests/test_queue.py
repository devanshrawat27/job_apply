"""The send queue: candidate-pitch posts and posts that waited too long."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete

from app.agents import discovery
from app.database import SessionLocal
from app.models import JobPost
from app.services import pipeline

USER = 99


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "Founders, looking for a dedicated Full-Stack Developer? "
            "I’m actively exploring opportunities and would love to connect with founders "
            "who are currently hiring. Let’s connect",
            "exploring opportunities",
        ),
        (
            "Full-stack engineer, AWS Certified. Exploring my next role: SDE, forward "
            "deployed engineer, or AI engineer. Hiring? Let's talk. Portfolio in the reply",
            "exploring my next role",
        ),
        (
            "Hello @tailorerp , I’m applying for the Full-Stack Software Engineer role at "
            "Tailor. I am currently becoming better in fullstack.",
            "applying for a role",
        ),
        (
            "NILE IS HIRING – FRONTEND INTERN! Looking to build your career in tech? "
            "Role: Frontend Intern. Apply: business@nile.ng",
            "",
        ),
        ("We are hiring a React developer. DM me your resume.", ""),
    ],
)
def test_candidate_pitches_are_not_hiring_posts(text, expected):
    assert discovery.job_seeker_reason(text) == expected
    assert discovery.looks_like_job_post(text) is (expected == "")


def test_bold_unicode_and_course_posts():
    bold = (
        "Apple is Hiring Junior Fullstack Engineers (0-2 Yrs)\n"
        "𝗔𝗽𝗽𝗹𝘆 𝗵𝗲𝗿𝗲 https://tinyurl.com/abc #hiring"
    )
    assert discovery.looks_like_job_post(bold)

    course = (
        "Microsoft quietly dropped one of the CLEANEST FREE AI agent courses on GitHub. "
        "Building AI agents is the skill companies are hiring for right now. 18 lessons. "
        "Real code. Design patterns. Tool use. Agentic RAG. Multi-agent systems."
    )
    assert not discovery.looks_like_job_post(course)

    news = (
        "terafab's first test chip is targeted for around june 2027, and musk is hiring "
        "engineers for it right now. the full texas site is planned at 100 million square feet."
    )
    assert not discovery.looks_like_job_post(news)


def test_old_queued_posts_expire_and_fresh_ones_stay():
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    try:
        db.execute(delete(JobPost).where(JobPost.user_id == USER))
        old = JobPost(
            user_id=USER,
            post_id="old-1",
            content="We are hiring a React developer. DM me your resume.",
            status="queued",
            discovered_at=now - timedelta(hours=30),
        )
        fresh = JobPost(
            user_id=USER,
            post_id="fresh-1",
            content="We are hiring a React developer. DM me your resume.",
            status="queued",
            discovered_at=now - timedelta(hours=1),
        )
        db.add_all([old, fresh])
        db.commit()

        assert pipeline._expire_queued(db, USER) == 1
        db.refresh(old)
        db.refresh(fresh)
        assert old.status == "skipped"
        assert "expired" in old.decision_reason
        assert fresh.status == "queued"
    finally:
        db.execute(delete(JobPost).where(JobPost.user_id == USER))
        db.commit()
        db.close()


def test_approving_an_old_post_keeps_it_alive():
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    try:
        db.execute(delete(JobPost).where(JobPost.user_id == USER))
        approved = JobPost(
            user_id=USER,
            post_id="approved-1",
            content="We are hiring a React developer. DM me your resume.",
            status="queued",
            discovered_at=now - timedelta(hours=30),
            # You edited this one and pressed send a minute ago.
            decided_at=now - timedelta(minutes=1),
        )
        db.add(approved)
        db.commit()

        assert pipeline._expire_queued(db, USER) == 0
        db.refresh(approved)
        assert approved.status == "queued"
    finally:
        db.execute(delete(JobPost).where(JobPost.user_id == USER))
        db.commit()
        db.close()
