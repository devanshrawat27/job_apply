"""Keyword level fit: intern words only for freshers, senior words only for seniors."""

from __future__ import annotations

from app.agents import query_lab
from app.models import Profile

FRESHER = Profile(
    job_title="Frontend Developer",
    seniority="fresher",
    experience_months=3,
    skills=["react"],
    domain="tech",
)
SENIOR = Profile(
    job_title="Software Engineer",
    seniority="experienced",
    experience_months=48,
    skills=["python"],
    domain="tech",
)


def test_senior_keywords_are_skipped_for_freshers():
    assert not query_lab.keyword_fits_profile("founding engineer", FRESHER)
    assert not query_lab.keyword_fits_profile("staff engineer", FRESHER)
    assert query_lab.keyword_fits_profile("sde intern", FRESHER)
    assert query_lab.keyword_fits_profile("frontend developer", FRESHER)


def test_intern_keywords_are_skipped_for_experienced_profiles():
    assert not query_lab.keyword_fits_profile("sde intern", SENIOR)
    assert not query_lab.keyword_fits_profile("junior developer", SENIOR)
    assert not query_lab.keyword_fits_profile("entry level developer", SENIOR)
    assert not query_lab.keyword_fits_profile("fresher developer", SENIOR)
    assert query_lab.keyword_fits_profile("software engineer", SENIOR)
    assert query_lab.keyword_fits_profile("python", SENIOR)
