"""LinkedIn jobs: parsing, filtering, dedupe and the scan pass.

Everything is offline: the guest endpoints are faked with small HTML fixtures.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from app.agents import linkedin_jobs, linkedin_post_keywords
from app.database import SessionLocal
from app.models import (
    AgentSettings,
    JobPost,
    LinkedInAccount,
    LinkedInPostQuery,
    LinkedInQuery,
    Profile,
    Run,
)
from app.security import encrypt_credentials
from app.services import linkedin_guest, linkedin_posts, pipeline

CARD = """
<li>
  <div class="base-card base-search-card" data-entity-urn="urn:li:jobPosting:4492573591">
    <a class="base-card__full-link" href="https://in.linkedin.com/jobs/view/python-developer-at-acme-4492573591?trk=x"></a>
    <div class="base-search-card__info">
      <h3 class="base-search-card__title"> Python Developer </h3>
      <h4 class="base-search-card__subtitle">
        <a href="https://www.linkedin.com/company/acme-labs?trk=x">Acme Labs</a>
      </h4>
      <span class="job-search-card__location">Remote, India</span>
      <time class="job-search-card__listdate" datetime="2026-11-21">1 hour ago</time>
    </div>
  </div>
</li>
"""

DETAIL = """
<html><body>
<h1 class="top-card-layout__title">Python Developer</h1>
<a class="topcard__org-name-link" href="https://www.linkedin.com/company/acme-labs?trk=x">Acme Labs</a>
<span class="topcard__flavor topcard__flavor--bullet">Remote, India</span>
<div class="show-more-less-html__markup">
  We are hiring a Python developer to build APIs with FastAPI and PostgreSQL.
  You will own services end to end, write tests and work with the product team.
  Remote friendly. 0-2 years of experience welcome. Apply with your resume.
</div>
<ul>
  <li class="job-criteria__item">
    <h3 class="job-criteria__subheader">Seniority level</h3>
    <span class="job-criteria__text">Entry level</span>
  </li>
  <li class="job-criteria__item">
    <h3 class="job-criteria__subheader">Employment type</h3>
    <span class="job-criteria__text">Full-time</span>
  </li>
</ul>
<span class="num-applicants__caption">12 applicants</span>
<span class="posted-time-ago__text">1 day ago</span>
</body></html>
"""

def make_profile() -> Profile:
    return Profile(
        id=1,
        full_name="Dev Rawat",
        seniority="junior",
        experience_months=6,
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
    linkedin_guest.reset_cooldown()
    session = SessionLocal()
    for model in (JobPost, Run, LinkedInQuery, LinkedInPostQuery, LinkedInAccount):
        session.execute(delete(model))
    session.execute(delete(AgentSettings))
    session.execute(delete(Profile))
    session.commit()
    yield session
    session.close()
    linkedin_guest.reset_cooldown()


def test_search_cards_are_parsed():
    cards = linkedin_guest.parse_search_cards(f"<ul>{CARD}</ul>")
    assert len(cards) == 1
    card = cards[0]
    assert card["job_id"] == "4492573591"
    assert card["title"] == "Python Developer"
    assert card["company"] == "Acme Labs"
    assert card["location"] == "Remote, India"
    assert card["url"] == "https://www.linkedin.com/jobs/view/4492573591/"
    assert card["company_url"].startswith("https://www.linkedin.com/company/acme-labs")
    assert card["posted_at"] == "2026-11-21"


def test_job_detail_is_parsed():
    detail = linkedin_guest.parse_detail(DETAIL, "4492573591")
    assert detail["title"] == "Python Developer"
    assert detail["company"] == "Acme Labs"
    assert detail["location"] == "Remote, India"
    assert "FastAPI" in detail["description"]
    assert detail["seniority"] == "Entry level"
    assert detail["employment_type"] == "Full-time"
    assert detail["applicants"] == "12 applicants"


def test_a_duplicated_card_title_is_cleaned():
    raw = (
        "AI-Assisted Full Stack DevelopeAI-Assisted Full Stack Developer "
        "Intern - Remoter (Part-Time)"
    )
    assert (
        linkedin_guest.clean_title(raw)
        == "AI-Assisted Full Stack Developer Intern - Remoter (Part-Time)"
    )
    assert linkedin_guest.clean_title("Python Developer") == "Python Developer"


def test_card_age_is_read_in_minutes():
    assert linkedin_guest.posted_age_minutes("30 minutes ago") == 30
    assert linkedin_guest.posted_age_minutes("1 hour ago") == 60
    assert linkedin_guest.posted_age_minutes("3 hours ago") == 180
    assert linkedin_guest.posted_age_minutes("1 day ago") == 1440
    assert linkedin_guest.posted_age_minutes("") is None


def test_a_good_listing_passes_and_scores():
    verdict = linkedin_jobs.assess(
        make_profile(), linkedin_guest.parse_search_cards(f"<ul>{CARD}</ul>")[0], linkedin_guest.parse_detail(DETAIL)
    )
    assert verdict["ok"] is True, verdict["reason"]
    assert verdict["relevance"] >= 45
    assert verdict["company"] == "Acme Labs"


def test_senior_and_non_tech_titles_are_rejected():
    senior = dict(linkedin_guest.parse_detail(DETAIL), title="Senior Python Developer")
    assert linkedin_jobs.assess(make_profile(), {}, senior)["ok"] is False

    mid = dict(linkedin_guest.parse_detail(DETAIL), title="Software Engineer 2")
    assert linkedin_jobs.assess(make_profile(), {}, mid)["ok"] is False

    dashed = dict(
        linkedin_guest.parse_detail(DETAIL), title="Software Development Engineer - II"
    )
    assert linkedin_jobs.assess(make_profile(), {}, dashed)["ok"] is False

    sales = dict(linkedin_guest.parse_detail(DETAIL), title="Sales Executive", company="Acme")
    verdict = linkedin_jobs.assess(make_profile(), {}, sales)
    assert verdict["ok"] is False
    assert "software role" in verdict["reason"]


def test_experience_gap_is_rejected():
    detail = dict(
        linkedin_guest.parse_detail(DETAIL),
        description="We need a Python developer with 5+ years of experience building APIs.",
    )
    verdict = linkedin_jobs.assess(make_profile(), {}, detail)
    assert verdict["ok"] is False
    assert "experience" in verdict["reason"]


def test_scam_and_pay_to_apply_are_rejected():
    detail = dict(
        linkedin_guest.parse_detail(DETAIL),
        description=(
            "Python developer wanted. A refundable security deposit and registration fee "
            "are required before joining. No interview, direct joining. Contact on WhatsApp only."
        ),
    )
    verdict = linkedin_jobs.assess(make_profile(), {}, detail)
    assert verdict["ok"] is False
    assert "fake" in verdict["reason"]


def test_on_site_abroad_without_visa_is_rejected_but_remote_is_not():
    filler = (
        " You will own services end to end, build APIs with FastAPI and PostgreSQL, "
        "write tests, review code and work with the product team. Apply with your resume "
        "and a short note about something you have built."
    )
    abroad = dict(
        linkedin_guest.parse_detail(DETAIL),
        location="Berlin, Germany",
        description="Python developer, on-site in Berlin. Build APIs with FastAPI. 0-2 years welcome." + filler,
    )
    assert linkedin_jobs.assess(make_profile(), {}, abroad)["ok"] is False

    remote = dict(
        abroad,
        location="Remote",
        description="Python developer, fully remote. Build APIs with FastAPI. 0-2 years welcome." + filler,
    )
    assert linkedin_jobs.assess(make_profile(), {}, remote)["ok"] is True


def test_a_blocked_request_sets_a_cooldown(monkeypatch):
    def handler(request):
        return linkedin_guest.httpx.Response(999, request=request)

    monkeypatch.setattr(
        linkedin_guest, "_client", linkedin_guest.httpx.Client(transport=linkedin_guest.httpx.MockTransport(handler))
    )
    with pytest.raises(linkedin_guest.LinkedInBlocked):
        linkedin_guest.search_jobs("python developer")
    assert linkedin_guest.cooldown_until() is not None

    calls = {"n": 0}

    def counting_handler(request):
        calls["n"] += 1
        return linkedin_guest.httpx.Response(200, text="")

    linkedin_guest._client.close()
    monkeypatch.setattr(
        linkedin_guest,
        "_client",
        linkedin_guest.httpx.Client(transport=linkedin_guest.httpx.MockTransport(counting_handler)),
    )
    with pytest.raises(linkedin_guest.LinkedInBlocked):
        linkedin_guest.search_jobs("python developer")
    assert calls["n"] == 0  # the cooldown is respected without touching LinkedIn


def test_scan_creates_a_linkedin_apply_link_and_dedupes(db, monkeypatch):
    db.add(make_profile())
    db.add(AgentSettings(id=1, enabled=True, linkedin_enabled=True))
    db.commit()

    monkeypatch.setattr(
        linkedin_guest, "search_jobs", lambda *a, **k: linkedin_guest.parse_search_cards(f"<ul>{CARD}</ul>")
    )
    monkeypatch.setattr(
        linkedin_guest, "job_detail", lambda job_id: linkedin_guest.parse_detail(DETAIL, str(job_id))
    )

    run = pipeline.scan_linkedin(db, manual=True)
    assert run.status == "completed", run.error
    job = db.scalar(select(JobPost).where(JobPost.source == "linkedin"))
    assert job is not None
    assert job.post_id == "li:4492573591"
    assert job.outreach_method == "link"
    assert job.apply_url.startswith("https://www.linkedin.com/jobs/view/4492573591")
    assert job.status == "new"
    assert job.company == "Acme Labs"

    again = pipeline.scan_linkedin(db, manual=True)
    assert again.status == "completed"
    assert again.stats["posts_new"] == 0
    assert again.stats["duplicates"] >= 1
    count = len(list(db.scalars(select(JobPost).where(JobPost.source == "linkedin"))))
    assert count == 1


def test_rejected_linkedin_cards_are_remembered_so_the_scan_advances(db, monkeypatch):
    """A card that was examined must be deduped next pass.

    Without a row the same top cards consumed the small detail budget on every
    scan, so newer listings were never read.
    """
    db.add(make_profile())
    db.add(AgentSettings(id=1, enabled=True, linkedin_enabled=True))
    db.commit()

    monkeypatch.setattr(
        linkedin_guest,
        "search_jobs",
        lambda *a, **k: linkedin_guest.parse_search_cards(f"<ul>{CARD}</ul>"),
    )

    def fake_assess(profile, card, detail):
        return {
            "ok": False,
            "reason": "needs about 5 year(s) of experience, you have less",
            "relevance": 40,
            "title": "Python Developer",
            "company": "Acme Labs",
            "location": "Remote, India",
            "required_experience_months": 60,
            "scam_score": 0,
            "scam_reasons": [],
        }

    monkeypatch.setattr(linkedin_jobs, "assess", fake_assess)

    first = pipeline.scan_linkedin(db, manual=True)
    assert first.status == "completed", first.error
    rows = list(db.scalars(select(JobPost).where(JobPost.source == "linkedin")))
    assert len(rows) == 1
    assert rows[0].post_id == "li:4492573591"
    assert rows[0].status == "rejected"
    assert "5 year" in rows[0].decision_reason

    second = pipeline.scan_linkedin(db, manual=True)
    assert second.status == "completed"
    assert second.stats["duplicates"] == 1
    assert len(list(db.scalars(select(JobPost).where(JobPost.source == "linkedin")))) == 1


def test_scan_is_skipped_when_linkedin_is_off(db):
    db.add(make_profile())
    db.add(AgentSettings(id=1, enabled=True, linkedin_enabled=False))
    db.commit()

    run = pipeline.scan_linkedin(db, manual=True)
    assert run.status == "skipped"
    assert "turned off" in run.stats["errors"][0]


def test_linkedin_post_scan_creates_a_post_card(db, monkeypatch):
    from datetime import datetime, timedelta, timezone

    db.add(make_profile())
    db.add(AgentSettings(id=1, enabled=True, linkedin_posts_enabled=True))
    db.add(
        LinkedInAccount(
            user_id=None,
            email="dev@example.com",
            session_ciphertext=encrypt_credentials(
                {"li_at": "cookie", "JSESSIONID": '"ajax:1"'}
            ),
            status="connected",
        )
    )
    db.commit()

    monkeypatch.setattr(linkedin_posts, "check_session", lambda creds: (True, ""))
    monkeypatch.setattr(
        linkedin_posts,
        "search_posts",
        lambda *args, **kwargs: [
            {
                "post_id": "7000000000000000009",
                "post_url": "https://www.linkedin.com/posts/jane-doe_hiring-activity-7000000000000000009/",
                "author_name": "Jane Doe",
                "author_profile_url": "https://www.linkedin.com/in/jane-doe/",
                "content": (
                    "We are hiring 4 React developers at Acme Labs. Remote, 0-2 years welcome. "
                    "Apply with your resume."
                ),
                "posted_at": datetime.now(timezone.utc) - timedelta(minutes=30),
            }
        ],
    )

    run = pipeline.scan_linkedin_posts(db, manual=True)
    assert run.status == "completed", run.error
    assert run.stats["posts_new"] == 1
    job = db.scalar(select(JobPost).where(JobPost.source_kind == "post"))
    assert job is not None
    assert job.source == "linkedin"
    assert job.author_name == "Jane Doe"
    assert job.author_type == "person"
    assert job.outreach_method == "link"
    assert job.status == "new"


def test_linkedin_post_keywords_track_relevance(db):
    db.add(make_profile())
    db.commit()

    rows = linkedin_post_keywords.pick(db, make_profile(), None)
    assert len(rows) == 3
    per_keyword = {row.keyword: {"seen": 10, "relevant": 1} for row in rows}
    linkedin_post_keywords.record(db, rows, per_keyword)
    snapshot = linkedin_post_keywords.snapshot(db, None)
    assert snapshot["active"] or snapshot["testing"]
    assert any(item["posts_seen"] == 10 for item in snapshot["active"] + snapshot["testing"])


def test_stale_linkedin_jobs_leave_the_list(db):
    from datetime import datetime, timedelta, timezone

    fresh = JobPost(
        user_id=None,
        post_id="li:fresh",
        source="linkedin",
        status="new",
        posted_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    )
    old = JobPost(
        user_id=None,
        post_id="li:old",
        source="linkedin",
        status="new",
        posted_at=datetime.now(timezone.utc) - timedelta(hours=7),
    )
    db.add_all([fresh, old])
    db.commit()

    expired = pipeline.expire_stale_linkedin(db)
    assert expired == 1
    db.refresh(fresh)
    db.refresh(old)
    assert fresh.status == "new"
    assert old.status == "rejected"
    assert "older than 6 hours" in old.decision_reason
