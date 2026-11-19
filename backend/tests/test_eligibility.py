"""Hard eligibility gate: work authorization, clearance and student-only roles."""

from __future__ import annotations

from app.agents import discovery
from app.models import Profile

INDIA = Profile(
    location="Delhi, India",
    resume_text="B.Tech Computer Science, graduating 2026. React, Node.js.",
    skills=["react", "node.js"],
    domain="tech",
)
US = Profile(
    location="Austin, United States",
    resume_text="B.S. Computer Science, 2024. React.",
    skills=["react"],
    domain="tech",
)
UNKNOWN = Profile(location="", resume_text="", skills=["react"], domain="tech")


def test_us_clearance_is_rejected_for_non_us_candidate():
    text = "Must be a US citizen and able to obtain a security clearance."
    assert discovery.eligibility_gap(INDIA, text) is not None
    assert discovery.eligibility_gap(US, text) is None


def test_unknown_location_is_rejected_for_us_only_roles():
    assert discovery.eligibility_gap(UNKNOWN, "US work authorization required") is not None


def test_no_sponsorship_is_rejected_for_non_us_candidate():
    text = "No visa sponsorship. Authorized to work in the US only."
    assert discovery.eligibility_gap(INDIA, text) is not None


def test_student_only_role_needs_a_matching_graduation_year():
    no_year = Profile(
        location="Delhi", resume_text="B.Tech Computer Science", skills=["react"], domain="tech"
    )
    assert discovery.eligibility_gap(no_year, "Final year students only") is not None
    assert discovery.eligibility_gap(INDIA, "Only the 2027 batch") is not None
    assert discovery.eligibility_gap(INDIA, "2026 batch welcome") is None


def test_normal_job_has_no_eligibility_gap():
    assert discovery.eligibility_gap(INDIA, "We are hiring a React developer. DM me.") is None
