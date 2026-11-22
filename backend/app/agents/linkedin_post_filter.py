"""Judge a LinkedIn hiring post: real individual hiring, not community noise.

LinkedIn's feed is full of "comment INTERESTED", "follow for more", coaching
posts and repost bait. A post only becomes a job when it names a role that
matches the candidate and reads like a direct hiring post. Individual authors
rank above company pages and job boards.
"""

from __future__ import annotations

import re

from app.agents import discovery, linkedin_jobs
from app.models import Profile

# Engagement/community formats that never become a job card.
_COMMUNITY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("follow-for-more", re.compile(r"follow (me|us) for more|follow for more|hit follow", re.I)),
    ("repost bait", re.compile(r"repost (this|if)|share this post|tag someone who", re.I)),
    ("opinion bait", re.compile(r"\b(agree\?|thoughts\?|what do you think|hot take|unpopular opinion)\b", re.I)),
    ("webinar/course", re.compile(r"\b(webinar|masterclass|bootcamp|course|cohort|newsletter)\b", re.I)),
    ("link in bio", re.compile(r"link in bio|link in comments", re.I)),
    ("community", re.compile(r"join (our|the) community|community members|whatsapp group|telegram group", re.I)),
    ("engagement ask", re.compile(r"comment ['\"]?interested['\"]?|type ['\"]?interested['\"]?|drop a ['\"]?yes", re.I)),
)

_JOB_SEEKER = re.compile(
    r"\b(open to work|looking for (a )?(job|opportunit|role)|i am (a )?fresher|"
    r"need a referral|seeking (a )?(job|role|opportunit)|please refer me)\b",
    re.I,
)

_HIRING = re.compile(
    r"\b(hiring|we are hiring|we're hiring|now hiring|open role|open position|"
    r"looking for|join our team|join the team|multiple openings|walk-?in|"
    r"referral|referrals)\b",
    re.I,
)

_HIGH_VOLUME = re.compile(
    r"\b(hiring\s+\d+|hiring\s+(multiple|several|many)|multiple openings|"
    r"bulk hiring|mass hiring|walk-?in|openings across|several roles)\b",
    re.I,
)

_COMPANY_HINT = re.compile(
    r"\b(at|join|with)\s+([A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Z][A-Za-z0-9&.'-]*){0,3})"
)


def community_reason(text: str) -> str:
    for label, pattern in _COMMUNITY_PATTERNS:
        if pattern.search(text or ""):
            return label
    return ""


_AGENCY_NAME = re.compile(
    r"(hire|career|jobs?|talent|recruit|staffing|consult|solution|technolog|service|verse)",
    re.I,
)


def is_individual(post: dict) -> bool:
    url = str(post.get("author_profile_url") or "").lower()
    name = str(post.get("author_name") or "").strip()
    if not name:
        return False
    # Job boards and agency pages post the same listing from many accounts.
    agency = re.compile(
        r"(hire|career|jobs?|talent|recruit|staffing|consult|solution|technolog|service|verse|community|share)",
        re.I,
    )
    if agency.search(name.replace(" ", "")) or agency.search(url):
        return False
    if "/company/" in url:
        return False
    if "/in/" in url:
        # Real profile slugs can end in a few digits; a long activity id means
        # this "profile" was derived from a job-board post slug.
        return not re.search(r"\d{12,}", url)
    return True


def _company_from_text(text: str) -> str:
    match = _COMPANY_HINT.search(text or "")
    if not match:
        return ""
    value = " ".join(match.group(2).split())
    # Drop a role title that happened to follow "at".
    if re.match(r"^(a|an|the)\b", value, re.I):
        return ""
    return value[:80]


def _matched_role(profile: Profile, text: str) -> str:
    lowered = (text or "").lower()
    for role in discovery.selected_roles(profile):
        if role and role.lower() in lowered:
            return role
    for role in discovery.infer_adjacent_roles(profile, limit=3):
        if role and role.lower() in lowered:
            return role
    return ""


def assess(profile: Profile, post: dict) -> dict:
    text = str(post.get("content") or "").strip()
    result = {
        "ok": False,
        "reason": "",
        "relevance": 0,
        "role": "",
        "company": "",
        "location": "",
        "individual": is_individual(post),
        "high_volume": bool(_HIGH_VOLUME.search(text)),
    }

    if not text:
        result["reason"] = "empty post"
        return result
    if not result["individual"]:
        result["reason"] = "company page or unknown author - individual hiring posts only"
        return result
    if _JOB_SEEKER.search(text):
        result["reason"] = "job seeker post, not a hiring post"
        return result
    if not _HIRING.search(text):
        result["reason"] = "no hiring signal"
        return result
    if not discovery.looks_like_job_post(text):
        result["reason"] = "does not read like a direct hiring post"
        return result

    role = _matched_role(profile, text)
    points = linkedin_jobs.role_points(profile, text)
    if not role and not points:
        result["reason"] = "role does not match your target roles"
        return result
    if linkedin_jobs.is_junior(profile) and (
        linkedin_jobs.SENIOR_TITLE_RE.search(text[:300])
        or linkedin_jobs.LEVEL_NUMBER_RE.search(text[:300])
    ):
        result["reason"] = "senior or mid-level role for an early-career candidate"
        return result

    # Hard community formats stay rejected. "Repost / follow / comment" is only
    # a rejection when there is no concrete role in the post; a real hiring post
    # often ends with "repost to help".
    community = community_reason(text)
    if community:
        hard = {"webinar/course", "opinion bait", "link in bio", "community"}
        if community in hard or not role:
            result["reason"] = f"community post ({community})"
            return result

    avoid = discovery.matches_avoid(profile, text)
    if avoid:
        result["reason"] = f"you marked '{avoid}' as not a fit"
        return result
    mismatch = discovery.domain_mismatch(profile, text)
    if mismatch:
        result["reason"] = mismatch
        return result

    required = discovery.required_experience_months(text)
    if required > discovery.experience_limit(profile):
        result["reason"] = f"needs about {required // 12} years of experience, you have less"
        return result
    eligibility = discovery.eligibility_gap(profile, text)
    if eligibility:
        result["reason"] = eligibility
        return result

    company = _company_from_text(text)
    result.update(
        {
            "ok": True,
            "reason": "individual hiring post that matches your roles",
            "role": role or "",
            "company": company,
            "location": "remote" if re.search(r"\bremote\b", text, re.I) else "",
        }
    )

    score = points or 30
    score += linkedin_jobs.skill_points(profile, text.lower(), text.lower())
    score += 10  # an individual is more likely to read the message
    if result["high_volume"]:
        score += 8
    if post.get("posted_at") is not None:
        score += 5
    if company:
        score += 3
    result["relevance"] = max(0, min(100, score))
    return result
