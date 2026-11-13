"""ChatGPT job-fit screen for Approvals and Apply links (offline tests)."""

from __future__ import annotations

from sqlalchemy import delete, select

from app.agents import job_filter
from app.database import SessionLocal
from app.models import JobPost, Profile


def _setup():
    db = SessionLocal()
    db.execute(delete(JobPost))
    db.execute(delete(Profile))
    db.add(
        Profile(
            id=1,
            job_title="Full Stack Developer",
            skills=["react", "node.js", "python"],
            domain="tech",
            seniority="fresher",
            experience_months=3,
        )
    )
    pending = JobPost(
        post_id="fit1",
        post_url="https://x.com/i/web/status/1",
        author_handle="founder",
        content="Hiring a junior React developer, 0-2 years. DM me.",
        role="Frontend Developer",
        relevance=80,
        status="pending_approval",
    )
    mismatch = JobPost(
        post_id="fit2",
        post_url="https://x.com/i/web/status/2",
        author_handle="salesguy",
        content="Hiring an International Business Developer for global expansion.",
        role="Business Developer",
        relevance=70,
        status="pending_approval",
    )
    link = JobPost(
        post_id="fit3",
        post_url="https://x.com/i/web/status/3",
        author_handle="company",
        content="We are hiring a backend engineer. Apply: https://company.com/jobs/1",
        role="Backend Engineer",
        relevance=75,
        status="new",
        apply_url="https://company.com/jobs/1",
    )
    db.add_all([pending, mismatch, link])
    db.commit()
    return db, pending, mismatch, link


def test_review_batch_rejects_mismatches(monkeypatch):
    db, pending, mismatch, link = _setup()

    def fake_complete(system, prompt, **kwargs):
        assert str(pending.id) in prompt
        return {
            "verdicts": [
                {"id": pending.id, "match": True, "fit": 85, "reason": "junior react role"},
                {"id": mismatch.id, "match": False, "fit": 10, "reason": "sales role, not engineering"},
                {"id": link.id, "match": True, "fit": 78, "reason": "backend role with link"},
            ]
        }

    monkeypatch.setattr(job_filter, "complete_json", fake_complete)

    result = job_filter.review_batch(db, None, "pending", limit=10, browser=False)
    assert result["checked"] == 2
    assert result["rejected"] == 1
    assert result["matched"] == 1

    db.refresh(mismatch)
    db.refresh(pending)
    assert mismatch.status == "rejected"
    assert "ChatGPT filter" in mismatch.decision_reason
    assert pending.status == "pending_approval"
    assert pending.ai_reviewed is True
    assert pending.ai_fit == 85
    assert job_filter.remaining(db, None, "pending") == 0
    db.close()


def test_apply_link_scope_only_reviews_links(monkeypatch):
    db, pending, mismatch, link = _setup()

    def fake_complete(system, prompt, **kwargs):
        assert f"id={link.id} |" in prompt
        assert f"id={pending.id} |" not in prompt
        return {
            "verdicts": [
                {"id": link.id, "match": False, "fit": 15, "reason": "senior backend stack"},
            ]
        }

    monkeypatch.setattr(job_filter, "complete_json", fake_complete)

    result = job_filter.review_batch(db, None, "apply_links", limit=10, browser=False)
    assert result["checked"] == 1
    assert result["rejected"] == 1
    assert job_filter.remaining(db, None, "apply_links") == 0

    db.refresh(link)
    assert link.status == "rejected"
    db.close()
