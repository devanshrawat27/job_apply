"""Turn LinkedIn job listings into scored jobs, or throw them away.

The jobs board is much cleaner than the LinkedIn feed, but it still carries
staffing-agency reposts, ghost listings and outright scams. Everything here is
deterministic: no model call. The expensive AI fit screen runs later, and only
on jobs that survive this pass.

Rules, in order:
1. real title + company
2. title must match the candidate's roles, and must not be a senior title for
   an early-career candidate
3. the candidate's avoid-list, discipline and experience gates
4. location / work-authorization gate (remote is always fine)
5. scam signals (pay to apply, WhatsApp-only, "no interview", MLM)
6. a relevance score from role, skills and freshness
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from app.agents import discovery
from app.models import Profile

# Titles that are never an early-career software job.
SENIOR_TITLE_RE = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|head|director|vp|vice president|chief|"
    r"architect|manager|founding|co-?founder|distinguished|expert)\b",
    re.I,
)

# "Software Engineer 2" / "Developer II" / "Engineer - II" is a mid-level
# title even without the word "senior". An early-career candidate should not
# get it. The separator is optional because listings write it both ways.
LEVEL_NUMBER_RE = re.compile(
    r"\b(?:engineer|developer|sde|analyst|consultant|programmer)\s*[-–—/]?\s*(?:2|ii|3|iii|iv)\b",
    re.I,
)

# The work has to be a build job, not a sales/support job with "engineer" in it.
TECH_TITLE_RE = re.compile(
    r"\b(software|developer|engineer|engineering|sde|programmer|full[ -]?stack|"
    r"mern|mean|mongodb|express|nestjs|"
    r"front[ -]?end|back[ -]?end|web|mobile|android|ios|python|java|javascript|"
    r"typescript|react|node|golang|rust|php|\.net|data|machine learning|ml|ai|"
    r"artificial intelligence|genai|llm|devops|cloud|platform|qa|test automation|"
    r"site reliability|sre|database|security)\b",
    re.I,
)

NON_TECH_TITLE_RE = re.compile(
    r"\b(sales|telesales|tele[- ]sales|business development|marketing|digital marketing|seo|content writer|"
    r"copywriter|hr|human resources|recruiter|talent acquisition|customer support|"
    r"customer service|telecaller|bpo|operations|accountant|finance|fin|insurance|"
    r"field agent|relationship manager|loan|real estate|driver|delivery|"
    r"data entry|back office|receptionist)\b",
    re.I,
)

AGENCY_SIGNALS = (
    "staffing",
    "manpower",
    "placement services",
    "recruitment agency",
    "consultancy",
    "consulting services",
    "third party payroll",
    "contract to hire",
    "c2h",
)

SCAM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "asks for money",
        re.compile(
            r"(registration|training|onboarding|security|joining)\s*(fee|charge|deposit)|"
            r"pay\s*(a\s*)?(fee|amount)|\brefundable deposit\b",
            re.I,
        ),
    ),
    ("no interview", re.compile(r"no interview|direct joining|without interview", re.I)),
    (
        "MLM / commission-only",
        re.compile(r"\b(mlm|network marketing|commission only|unpaid internship)\b", re.I),
    ),
    (
        "money-transfer task",
        re.compile(r"(daily payout|earn .{0,20}per day|investment required|deposit and earn)", re.I),
    ),
    (
        "chat-app only",
        re.compile(r"(whatsapp|telegram)\s*(only|me|us|number)", re.I),
    ),
)

FREE_MAIL_RE = re.compile(r"@(gmail|yahoo|outlook|hotmail|rediffmail|proton)\.", re.I)


def is_junior(profile: Profile) -> bool:
    seniority = (profile.seniority or "").lower()
    if any(word in seniority for word in ("intern", "fresher", "entry", "junior", "trainee", "graduate")):
        return True
    return (profile.experience_months or 0) <= 12


INTERN_TITLE_RE = re.compile(
    r"\b(intern|internship|trainee|campus|fresher|graduate|apprentice)\b", re.I
)

# Stricter than TECH_TITLE_RE: "data" in "data entry" must not make an admin
# internship look like a software role.
_INTERN_CONTEXT_RE = re.compile(
    r"\b(software|developer|engineer|engineering|sde|programmer|full[ -]?stack|"
    r"mern|mean|front[ -]?end|back[ -]?end|web|react|node|python|java|javascript|"
    r"typescript|golang|rust|php|\.net|devops|cloud|qa|test automation|database|"
    r"sql|api|backend|frontend)\b",
    re.I,
)


def is_student(profile: Profile) -> bool:
    """True while the candidate is still studying / has not graduated.

    ``graduation_year`` is structured, so use it first. Older profiles without
    it fall back to the role/seniority text.
    """
    if (profile.work_authorization or "").lower() == "student":
        return True
    year = int(profile.graduation_year or 0)
    if year and year >= datetime.now(timezone.utc).year:
        return True
    text = f"{profile.current_role or ''} {profile.seniority or ''}".lower()
    return any(word in text for word in ("intern", "student", "pursuing", "final year", "trainee"))


def context_matches(profile: Profile, text: str) -> bool:
    """Does the description/skills mention the candidate's roles or skills?

    Used for generic intern titles ("Campus Intern", "Intern") where the title
    alone cannot tell whether the work is software.
    """
    lowered = (text or "").lower()
    if not lowered:
        return False
    if any(role and role in lowered for role in _role_terms(profile)):
        return True
    if skill_points(profile, "", lowered) >= 8:
        return True
    return bool(is_tech_profile(profile) and _INTERN_CONTEXT_RE.search(lowered))


def _role_terms(profile: Profile) -> list[str]:
    return [role.lower() for role in discovery.selected_roles(profile) if role]


def role_points(profile: Profile, title: str) -> int:
    """45 exact role phrase, 30 strong role words, 0 no match."""
    lowered = (title or "").lower()
    if not lowered:
        return 0
    for role in _role_terms(profile):
        if role and role in lowered:
            return 45
    words = {
        word
        for role in _role_terms(profile)
        for word in re.findall(r"[a-z]{3,}", role)
        if word not in {"developer", "engineer", "senior", "junior", "lead", "software"}
    }
    if any(word in lowered for word in words):
        return 30
    if is_tech_profile(profile) and TECH_TITLE_RE.search(lowered):
        return 25
    return 0


def is_tech_profile(profile: Profile) -> bool:
    return (profile.domain or "tech") != "non-tech"


def skill_points(profile: Profile, title: str, text: str) -> int:
    skills = [str(skill).strip().lower() for skill in (profile.skills or []) if str(skill).strip()]
    in_title = 0
    in_text = 0
    for skill in skills:
        if len(skill) < 2:
            continue
        if skill in title:
            in_title += 1
        elif skill in text:
            in_text += 1
    return min(30, in_title * 8 + in_text * 4)


def scam_flags(text: str) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    for label, pattern in SCAM_PATTERNS:
        if pattern.search(text):
            score += 35 if label != "chat-app only" else 20
            reasons.append(label)
    if FREE_MAIL_RE.search(text) and "linkedin.com" not in text:
        score += 15
        reasons.append("personal email only")
    if "company website" in text and "linkedin.com/company" not in text:
        score += 5
    return min(100, score), reasons


def _experience_reason(profile: Profile, text: str) -> str:
    required = discovery.required_experience_months(text)
    if required <= 0:
        return ""
    limit = discovery.experience_limit(profile)
    if required <= limit:
        return ""
    years = required / 12
    return f"needs about {years:.0f} year(s) of experience, you have less"


def assess(profile: Profile, card: dict, detail: dict) -> dict:
    """Score one listing. ``ok`` False carries the plain-language reason."""
    title = str(detail.get("title") or card.get("title") or "").strip()
    company = str(detail.get("company") or card.get("company") or "").strip()
    location = str(detail.get("location") or card.get("location") or "").strip()
    description = str(detail.get("description") or "").strip()
    seniority = str(detail.get("seniority") or "").strip()
    employment = str(detail.get("employment_type") or "").strip()
    header = " ".join(part for part in (title, company, location, seniority, employment) if part)
    text = f"{header}\n{description}".strip()
    lowered = text.lower()

    result = {
        "ok": False,
        "reason": "",
        "relevance": 0,
        "title": title,
        "company": company,
        "location": location,
        "required_experience_months": discovery.required_experience_months(description),
        "scam_score": 0,
        "scam_reasons": [],
        "agency": any(signal in lowered for signal in AGENCY_SIGNALS),
        "detail_missing": not bool(description),
    }

    if not title:
        result["reason"] = "listing has no job title"
        return result
    if not company:
        result["reason"] = "listing has no company name"
        return result

    if is_junior(profile) and (
        SENIOR_TITLE_RE.search(title) or LEVEL_NUMBER_RE.search(title)
    ):
        result["reason"] = f"senior or mid-level title for an early-career candidate ({title})"
        return result
    if NON_TECH_TITLE_RE.search(title) and is_tech_profile(profile):
        result["reason"] = f"not a software role ({title})"
        return result

    points = role_points(profile, title)
    if not points and INTERN_TITLE_RE.search(title) and (
        is_junior(profile) or is_student(profile)
    ):
        # A student/fresher is allowed to apply to a generic intern title when
        # the description is clearly in their domain.
        intern_context = " ".join(
            part for part in (description, seniority, employment) if part
        )
        if context_matches(profile, intern_context):
            points = 40
    if not points:
        result["reason"] = f"not one of your target roles ({title})"
        return result

    avoid = discovery.matches_avoid(profile, lowered)
    if avoid:
        result["reason"] = f"you marked '{avoid}' as not a fit"
        return result

    mismatch = discovery.domain_mismatch(profile, header)
    if mismatch:
        result["reason"] = mismatch
        return result

    experience = _experience_reason(profile, description) if description else ""
    if experience:
        result["reason"] = experience
        return result

    eligibility = discovery.eligibility_gap(profile, text)
    if eligibility:
        result["reason"] = eligibility
        return result

    if description and len(description) < 250 and len(header) < 60:
        result["reason"] = "job description is too short to judge"
        return result

    scam_score, scam_reasons = scam_flags(lowered)
    result["scam_score"] = scam_score
    result["scam_reasons"] = scam_reasons
    if scam_score >= 50:
        result["reason"] = "looks like a fake listing: " + "; ".join(scam_reasons[:3])
        return result

    # Score: role fit dominates, skills and freshness add, agency reposts lose.
    score = points
    score += skill_points(profile, title.lower(), lowered)
    posted = card.get("posted_at") or detail.get("posted_at")
    if posted:
        score += 8
    if detail.get("salary"):
        score += 6
    if detail.get("company_url") or card.get("company_url"):
        score += 4
    if "intern" in title.lower() and not is_junior(profile):
        score -= 20
    if result["agency"]:
        score -= 18
    if result["detail_missing"]:
        # The card alone is a weaker signal than a checked job page.
        score -= 5

    result["ok"] = True
    result["relevance"] = max(0, min(100, score))
    result["reason"] = "matches your role and skills"
    return result


def search_terms(profile: Profile) -> list[tuple[str, str]]:
    """Role and skill searches for the LinkedIn jobs board.

    LinkedIn's search corrects fuzzy text, so plain role names work best. The
    level suffix is only added for early-career candidates, where it changes
    which listings LinkedIn ranks first.
    """
    terms: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(term: str, source: str) -> None:
        clean = " ".join((term or "").split())[:80]
        key = clean.lower()
        if not clean or key in seen or len(clean) < 3:
            return
        seen.add(key)
        terms.append((clean, source))

    for role in discovery.selected_roles(profile)[:3]:
        add(role, "role")
    for role in discovery.infer_adjacent_roles(profile, limit=2):
        add(role, "role")

    junior = is_junior(profile)
    for role in list(discovery.selected_roles(profile))[:2]:
        if junior:
            add(f"{role} fresher", "level")
            add(f"{role} internship", "level")
        else:
            add(f"{role} jobs", "level")

    for skill in (profile.skills or [])[:8]:
        clean = " ".join(str(skill).split())
        if 2 < len(clean) <= 30 and len(clean.split()) <= 3:
            add(f"{clean} developer", "skill")

    for role in (
        "software engineer",
        "full stack developer",
        "frontend developer",
        "backend developer",
        "python developer",
        "react developer",
        "node.js developer",
        "ai engineer",
        "data engineer",
        "junior software engineer",
        "software engineer intern",
    ):
        add(role, "curated")

    if not is_tech_profile(profile):
        terms = [(term, source) for term, source in terms if source != "curated"]
    return terms
