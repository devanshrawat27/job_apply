"""Turn Naukri.com search cards into reviewable apply-link jobs.

Naukri's cards are already structured by the browser script. This module only
decides whether a listing is a real, early-career software role and how well it
matches the profile. Nothing is submitted automatically: every job lands in
Apply links for the human to review and apply.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from app.agents import discovery, linkedin_jobs
from app.models import Profile

MIN_RELEVANCE = 45


def search_terms(profile: Profile, limit: int = 3) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        clean = " ".join(str(value or "").split())[:70]
        key = clean.lower()
        if not clean or key in seen or len(clean) < 3:
            return
        seen.add(key)
        terms.append(clean)

    for role in discovery.selected_roles(profile)[:2]:
        add(role)
    # A student/fresher should also see internships, not only full-time roles.
    if linkedin_jobs.is_junior(profile) or linkedin_jobs.is_student(profile):
        add("software intern")
        add("developer intern")
    for role in discovery.infer_adjacent_roles(profile, limit=1):
        add(role)
    for skill in (profile.skills or [])[:2]:
        clean = " ".join(str(skill).split())
        if 2 < len(clean) <= 30:
            add(f"{clean} developer")
    return terms[:limit]


def _lowest_years(value: str) -> int | None:
    text = str(value or "").lower()
    if not text or "fresher" in text:
        return 0
    match = re.search(r"(\d+)\s*(?:-|to)?\s*(\d+)?\s*y", text)
    if not match:
        return None
    return int(match.group(1))


def posted_datetime(value: str, *, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now(timezone.utc)
    text = str(value or "").strip().lower()
    if not text:
        return None
    if "just now" in text or "today" in text or "few minutes" in text:
        return now
    match = re.search(r"(\d+)\s*(minute|hour|day|week)s?\s*ago", text)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        delta = {
            "minute": timedelta(minutes=amount),
            "hour": timedelta(hours=amount),
            "day": timedelta(days=amount),
            "week": timedelta(weeks=amount),
        }[unit]
        return now - delta
    if "yesterday" in text:
        return now - timedelta(days=1)
    return None


def assess(profile: Profile, card: dict) -> dict:
    title = " ".join(str(card.get("title") or "").split())
    company = " ".join(str(card.get("company") or "").split())
    location = " ".join(str(card.get("location") or "").split())
    experience = str(card.get("experience") or "")
    snippet = str(card.get("snippet") or "")
    skills = " ".join(str(item) for item in (card.get("skills") or []))
    text = " ".join(part for part in (title, company, snippet, skills) if part).lower()

    result = {
        "ok": False,
        "reason": "",
        "relevance": 0,
        "title": title,
        "company": company,
        "location": location,
        "required_experience_months": 0,
    }

    if not title:
        result["reason"] = "listing has no title"
        return result
    if not company:
        result["reason"] = "listing has no company"
        return result

    junior = linkedin_jobs.is_junior(profile)
    if junior and (
        linkedin_jobs.SENIOR_TITLE_RE.search(title)
        or linkedin_jobs.LEVEL_NUMBER_RE.search(title)
    ):
        result["reason"] = f"senior or mid-level title for an early-career candidate ({title})"
        return result
    if linkedin_jobs.is_tech_profile(profile) and linkedin_jobs.NON_TECH_TITLE_RE.search(title):
        result["reason"] = f"not a software role ({title})"
        return result

    intern = linkedin_jobs.INTERN_TITLE_RE.search(title)
    query = str(card.get("query") or "").lower()
    query_is_intern = "intern" in query or "internship" in query
    points = linkedin_jobs.role_points(profile, title)
    if not points and intern and (
        linkedin_jobs.is_junior(profile) or linkedin_jobs.is_student(profile)
    ):
        # Generic "Intern"/"Campus Intern" cards are fine for a student when
        # the snippet/skills show software work, or when our own search query
        # was an intern search. Reject obvious non-software branches.
        if query_is_intern or linkedin_jobs.context_matches(profile, text):
            if re.search(
                r"\b(electronics|electrical|mechanical|civil|chemical|instrumentation)\b",
                text,
                re.I,
            ):
                result["reason"] = "not a software role"
                return result
            points = 40
    if not points:
        result["reason"] = f"not one of your target roles ({title})"
        return result

    avoid = discovery.matches_avoid(profile, text)
    if avoid:
        result["reason"] = f"you marked '{avoid}' as not a fit"
        return result

    if re.search(r"\b(?:male|female)\s+candidates?\s+only\b", text):
        result["reason"] = "restricts applications by gender"
        return result

    years = _lowest_years(experience)
    required_months = 0 if years is None else years * 12
    result["required_experience_months"] = required_months
    limit = discovery.experience_limit(profile)
    if required_months > limit:
        result["reason"] = (
            f"needs about {required_months / 12:.0f} year(s) of experience, you have less"
        )
        return result

    scam_score, scam_reasons = linkedin_jobs.scam_flags(text)
    if scam_score >= 50:
        result["reason"] = "looks like a fake listing: " + "; ".join(scam_reasons[:3])
        return result

    relevance = points + linkedin_jobs.skill_points(profile, title.lower(), text)
    if "remote" in location.lower() or "remote" in text:
        relevance += 8
    if years == 0 or "fresher" in experience.lower() or "fresher" in title.lower():
        relevance += 6
    relevance = max(0, min(100, relevance))
    if intern and (junior or linkedin_jobs.is_student(profile)) and (
        points >= 25 or query_is_intern or linkedin_jobs.context_matches(profile, text)
    ):
        # Internships are appropriate for this profile; do not lose one just
        # because the title carries less keyword weight than a full-time role.
        relevance = max(relevance, MIN_RELEVANCE)
    if relevance < MIN_RELEVANCE:
        result["reason"] = f"weak match (score {relevance})"
        return result

    result["ok"] = True
    result["relevance"] = relevance
    result["reason"] = "matches your role and skills"
    return result
