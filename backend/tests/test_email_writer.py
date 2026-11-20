"""Application-email writer: structure, links and phone number."""

from __future__ import annotations

from app.agents import email_writer
from app.models import JobPost, Profile

PROFILE = Profile(
    full_name="Dev Rawat",
    phone="+91 90000 00000",
    skills=["python", "postgresql"],
    links={"github": "github.com/dev", "portfolio": "dev.dev"},
    current_role="SDE Intern",
    experience_months=4,
    location="Dehradun",
    country="India",
    domain="tech",
)
JOB = JobPost(
    company="Acme",
    role="Backend Engineer",
    content="We are hiring a Backend Engineer with Python and PostgreSQL. Mail your resume to hr@acme.com.",
    contact_email="hr@acme.com",
)


def test_fallback_email_is_complete():
    draft = email_writer.fallback(PROFILE, JOB)
    assert "Backend Engineer" in draft["subject"]
    assert "Dev Rawat" in draft["subject"]
    assert draft["body"].startswith("Hello Acme team,")
    assert "resume is attached" in draft["body"].lower()
    assert "Would you be open to a short call" in draft["body"]
    assert "+91 90000 00000" in draft["body"]
    assert "github.com/dev" in draft["body"]


def test_phone_is_kept_even_when_the_model_drops_it():
    body = "Hi,\n\nText.\n\nBest regards,\nDev Rawat"
    fixed = email_writer._ensure_phone(body, "Dev Rawat", "+91 90000 00000")
    assert fixed.splitlines()[-1] == "+91 90000 00000"
