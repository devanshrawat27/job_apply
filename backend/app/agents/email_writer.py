"""Write a real job-application email (subject + body) for email-only posts.

Research-backed structure: exact role + where it was seen, two concrete proofs
that answer what the post asks for, one line on logistics, one low-friction ask,
and a signature with the links once. 120-180 words, readable on a phone.
"""

from __future__ import annotations

import logging

from app.llm import LLMUnavailable, complete_json
from app.models import JobPost, Profile

logger = logging.getLogger(__name__)

SYSTEM = """You write short, specific job-application emails for one candidate.
Recruiters skim on a phone: 120-180 words, 3 short paragraphs, no filler.
Return strict JSON only."""

PROMPT = """CANDIDATE
name: {name}
current: {current_role} at {current_company}
level: {seniority}, experience: {experience}
skills: {skills}
github: {github}
links: {links}
location: {location}
country: {country}
work authorization: {work_authorization}
graduation year: {graduation_year}
willing to relocate: {relocate}

JOB POST
company: {company}
role: {role}
location: {job_location}
recipient: {contact}
text:
---
{content}
---

Write the application email a strong candidate would actually send.

Rules:
- Subject: "Application for <exact role from the post> — <name>" (max 70 chars).
- Greeting: a named person if the post names one, otherwise "Hello <company> team,".
- Paragraph 1: the role, where it was seen, and one line on who the candidate is.
- Paragraph 2: TWO concrete proofs (project, internship, measurable result) that
  answer what the post actually asks for. Use only real facts from the profile.
  No invented numbers, employers or projects.
- Paragraph 3: "My resume is attached as a PDF." + availability/relocation in one
  line + ONE easy question ("Would you be open to a short call this week?").
- Sign-off: "Best regards," + name + phone, then the links ONCE on the last line.
- Never repeat the resume sentence, never put links inside the body, never ask
  "would you like me to send my resume" (this IS the email), no placeholders,
  no "I am writing to express my interest", no "hardworking and dedicated".
- If the post lists several roles, use the one that best matches the candidate.
- If the candidate clearly cannot take the job (work authorization, batch,
  seniority), return eligible=false with a one-line reason and empty subject/body.

Return JSON:
{{
  "eligible": true,
  "reason": "",
  "subject": "...",
  "body": "...",
  "confidence": 0.0,
  "uncertainties": ["anything unclear that a human should check"]
}}"""


def _skills(profile: Profile, limit: int = 4) -> str:
    return ", ".join(str(skill) for skill in (profile.skills or [])[:limit])


def _links(profile: Profile) -> str:
    links = profile.links or {}
    values = [
        links.get("portfolio"),
        links.get("github"),
        links.get("linkedin"),
    ]
    return " · ".join(value for value in values if value)


def fallback(profile: Profile, job: JobPost) -> dict:
    role = (job.role or "").strip() or "Software Developer"
    company = (job.company or "").strip()
    name = profile.full_name or "the candidate"
    greeting = f"Hello {company} team," if company else "Hello Hiring Team,"
    skills = _skills(profile)
    current = (profile.current_role or "").strip()

    lines = [greeting, ""]
    lines.append(f"I saw your post for the {role} role and would like to apply.")
    lines.append("")
    if current:
        lines.append(
            f"I'm currently {current} with hands-on experience in {skills}."
            if skills
            else f"I'm currently {current}."
        )
    elif skills:
        lines.append(f"I work with {skills}.")
    lines.append("")
    lines.append("My resume is attached as a PDF.")
    lines.append("")
    lines.append("Would you be open to a short call this week?")
    lines.extend(["", "Best regards,", name])
    if profile.phone:
        lines.append(profile.phone)
    link_line = _links(profile)
    if link_line:
        lines.append(link_line)

    return {
        "eligible": True,
        "reason": "",
        "subject": f"Application for {role} — {name}"[:70],
        "body": "\n".join(lines),
        "confidence": 0.45,
        "uncertainties": ["template email (AI unavailable) - review the wording"],
        "template": True,
    }


def _ensure_phone(body: str, name: str, phone: str) -> str:
    """Keep the phone number in the sign-off even if the model drops it."""
    if not phone or phone in body:
        return body
    lines = body.rstrip().splitlines()
    for index in range(len(lines) - 1, -1, -1):
        if name and name.lower() in lines[index].lower():
            lines.insert(index + 1, phone)
            return "\n".join(lines)
    lines.append(phone)
    return "\n".join(lines)


def write(
    db,
    job: JobPost,
    profile: Profile,
    user_id: int | None,
    *,
    providers: list[dict] | None = None,
    browser: bool = False,
) -> dict:
    prompt = PROMPT.format(
        name=profile.full_name or "the candidate",
        current_role=profile.current_role or "not stated",
        current_company=profile.current_company or "",
        seniority=profile.seniority or "",
        experience=f"{profile.experience_months or 0} months",
        skills=_skills(profile, 12),
        github=(profile.github_summary or "not linked")[:800],
        links=profile.links or {},
        location=profile.location or "not stated",
        country=getattr(profile, "country", "") or "not stated",
        work_authorization=getattr(profile, "work_authorization", "") or "not stated",
        graduation_year=getattr(profile, "graduation_year", 0) or "not stated",
        relocate="yes" if getattr(profile, "willing_to_relocate", True) is not False else "no",
        company=job.company or "",
        role=job.role or "",
        job_location=job.job_location or "",
        contact=job.contact_email or job.contact or "",
        content=(job.content or "")[:1400],
    )

    data: dict | None = None
    if browser:
        from app.services import browser_chatgpt

        try:
            data = browser_chatgpt.ask_json(
                SYSTEM, prompt, user_id=user_id, purpose="draft", timeout=120
            )
        except Exception as exc:  # noqa: BLE001 - fall back to the template
            logger.warning("browser email writer failed: %s", exc)

    if data is None and providers:
        try:
            data = complete_json(
                SYSTEM, prompt, temperature=0.4, max_tokens=700, budget_s=45, providers=providers
            )
        except LLMUnavailable as exc:
            logger.warning("email writer model unavailable: %s", exc)

    if not isinstance(data, dict):
        return fallback(profile, job)

    subject = str(data.get("subject") or "").strip()[:200]
    body = str(data.get("body") or "").strip()[:6000]
    if not subject or not body:
        return fallback(profile, job)

    body = _ensure_phone(body, profile.full_name or "", profile.phone or "")

    return {
        "eligible": bool(data.get("eligible", True)),
        "reason": str(data.get("reason") or "")[:300],
        "subject": subject,
        "body": body,
        "confidence": float(data.get("confidence") or 0.6),
        "uncertainties": [str(item)[:200] for item in (data.get("uncertainties") or [])][:6],
        "template": False,
    }
