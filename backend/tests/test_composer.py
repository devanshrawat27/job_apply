"""DM composer: eligibility and the 'no project names' rule."""

from __future__ import annotations

from app.agents import composer
from app.models import JobPost, Profile

PROFILE = Profile(
    full_name="Dev Rawat",
    skills=["python", "react", "postgresql"],
    links={"portfolio": "dev.example", "github": "github.com/dev"},
    current_role="SDE Intern",
    experience_months=6,
)

JOB = JobPost(
    company="Acme",
    role="Backend Engineer",
    content="Hiring a Backend Engineer with Python and PostgreSQL. Apply now.",
)


def test_not_eligible_never_gets_a_template_dm():
    result = composer._build_result(
        PROFILE,
        JOB,
        {
            "eligible": False,
            "eligibility_reason": "needs US work authorization",
            "dm_text": "Hi, I am interested.",
        },
    )
    assert result["eligible"] is False
    assert result["dm_text"] == ""
    assert result["reply_text"] == ""
    assert "US work authorization" in result["eligibility_reason"]


def test_fallback_talks_about_the_stack_not_projects():
    draft = composer._fallback(PROFILE, JOB)
    lowered = draft["dm_text"].lower()
    assert "project" not in lowered
    assert "python" in lowered or "postgresql" in lowered
    assert "dev.example" in lowered or "github.com/dev" in lowered


def test_project_sentences_are_removed():
    result = {
        "reply_text": "",
        "dm_text": (
            "Your post mentions Python and Postgres APIs.\n"
            "I built a project called CQL for that.\n"
            "Would you be open to a short chat?"
        ),
        "confidence": 0.8,
        "uncertainties": [],
    }
    cleaned = composer._apply_safety(JOB, result)
    assert "CQL" not in cleaned["dm_text"]
    assert "Python" in cleaned["dm_text"]
    assert "short chat" in cleaned["dm_text"]
