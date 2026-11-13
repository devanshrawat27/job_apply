"""Resume extraction should return only useful fields, with months support."""

from __future__ import annotations

from app.agents.resume import _fallback, format_experience


def test_months_only_experience():
    resume = (
        "Test Candidate\n"
        "springfield\n"
        "candidate@example.com\n"
        "4 months experience as a frontend developer\n"
        "GitHub: github.com/test-candidate\n"
    )
    data = _fallback(resume)
    assert data["experience_months"] == 4
    assert data["seniority"] == "fresher"


def test_years_and_months_combine():
    data = _fallback("1 year 6 months experience with React and Python")
    assert data["experience_months"] == 18
    assert data["seniority"] == "experienced"


def test_no_useless_fields():
    data = _fallback("Test Candidate\n4 months experience\nReact, Node, SQL")
    assert "headline" not in data
    assert "pitch" not in data
    assert "years_experience" not in data


def test_name_and_links():
    resume = (
        "Test Candidate\n"
        "candidate@example.com | +91 9000000000\n"
        "github.com/test-candidate\n"
        "https://portfolio.example.com\n"
        "linkedin.com/in/test-candidate\n"
    )
    data = _fallback(resume)
    assert data["full_name"] == "Test Candidate"
    assert data["links"]["github"] == "github.com/test-candidate"
    assert data["links"]["portfolio"].startswith("portfolio.example.com")
    assert data["links"]["linkedin"] == "linkedin.com/in/test-candidate"
    assert data["phone"].strip().startswith("+91")


def test_skills_are_technologies():
    data = _fallback("Skills: React, TypeScript, Python, FastAPI, Docker")
    lowered = [s.lower() for s in data["skills"]]
    assert "react" in lowered and "python" in lowered and "docker" in lowered


def test_format_experience():
    assert format_experience(0) == "no professional experience"
    assert format_experience(4) == "4 mo"
    assert format_experience(18) == "1 yr 6 mo"
    assert format_experience(24) == "2 yrs"


def test_bom_and_duplicate_skills():
    resume = "\ufeffTest Candidate\nReact, Next.js, Node.js, PostgreSQL, Node, SQL\n"
    data = _fallback(resume)
    assert data["full_name"] == "Test Candidate"
    lowered = [s.lower() for s in data["skills"]]
    assert "node" not in lowered  # covered by node.js
    assert "sql" not in lowered  # covered by postgresql
    assert "node.js" in lowered and "postgresql" in lowered


SAMPLE_RESUME = """Test Candidate
phone +91 9000000000 ? candidate@example.com /linkedin LinkedIn /github GitHub /portfolio Portfolio
Education
Example University , Springfield Aug 2023 - May 2027
B.Tech in Computer Science & Engineering
Experience & Selected Programs
Example T echnologies - SDE Intern            Aug 2026 - Present
Software Engineering Internship Remote
Develop and integrate NestJS/TypeScript REST APIs.
Sample Program 2025 - Software Engineering Program     Jun 2025
Technical Skills
Languages: TypeScript, JavaScript, Python
Backend: NestJS, Node.js, Express.js, PostgreSQL, Docker
Frontend: React.js, Next.js, Tailwind CSS
Links:
https://www.linkedin.com/in/test-candidate/
https://github.com/test-candidate
https://github.com/test-candidate/sample-project
https://portfolio.example.com
"""


def test_current_role_company_and_months_from_present_line():
    data = _fallback(SAMPLE_RESUME)
    assert data["current_company"] == "Example Technologies"  # kerning fixed
    assert data["current_role"] == "SDE Intern"
    assert data["experience_months"] >= 1
    assert data["location"]  # "Remote" or the city line, but never empty


def test_links_prefer_profile_urls():
    data = _fallback(SAMPLE_RESUME)
    assert data["links"]["github"] == "github.com/test-candidate"  # not a repo
    assert data["links"]["linkedin"] == "linkedin.com/in/test-candidate"
    assert data["links"]["portfolio"] == "portfolio.example.com"


def test_job_title_is_not_an_intern_title():
    data = _fallback(SAMPLE_RESUME)
    assert "intern" not in data["job_title"].lower()
    assert data["job_title"] == "Full Stack Developer"
