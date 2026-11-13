"""Discovery: turn the profile into X search queries and rank the results.

This is the "find jobs" half of the flow. It never writes to X.

Rules that matter here:
  * The roles the human picked are the strongest signal, but the agent also
    searches adjacent roles inferred from the resume - it never limits itself
    to the picked list.
  * A tech resume never searches non-tech roles (and vice versa).
  * Location is not a filter. It is only compared when a post explicitly
    demands on-site work somewhere else.
  * If a post needs more experience than the candidate has, it is worthless:
    the pipeline rejects it before any drafting.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from app.agents.resume import format_experience
from app.llm import LLMUnavailable, complete_json
from app.models import JobPost, Profile

logger = logging.getLogger(__name__)

MAX_QUERY_LEN = 480
HIRING_TERMS = (
    '"we\'re hiring"',
    '"we are hiring"',
    '"is hiring"',
    '"hiring"',
    '"job opening"',
    '"open role"',
    '"looking for"',
    '"join our team"',
)

# skill -> adjacent role worth searching. Order matters: more specific first.
ROLE_FROM_SKILL: tuple[tuple[str, str], ...] = (
    ("react native", "React Native Developer"),
    ("next.js", "Frontend Developer"),
    ("react", "React Developer"),
    ("vue", "Frontend Developer"),
    ("angular", "Frontend Developer"),
    ("nestjs", "Backend Developer"),
    ("node.js", "Node.js Developer"),
    ("express", "Backend Developer"),
    ("fastapi", "Python Developer"),
    ("django", "Python Developer"),
    ("flask", "Python Developer"),
    ("typescript", "Full Stack Developer"),
    ("javascript", "Frontend Developer"),
    ("python", "Python Developer"),
    ("spring", "Java Developer"),
    ("java", "Java Developer"),
    ("golang", "Go Developer"),
    ("kotlin", "Android Developer"),
    ("swift", "iOS Developer"),
    ("flutter", "Mobile Developer"),
    ("docker", "DevOps Engineer"),
    ("kubernetes", "DevOps Engineer"),
    ("aws", "Cloud Engineer"),
    ("pytorch", "ML Engineer"),
    ("tensorflow", "ML Engineer"),
    ("postgresql", "Backend Developer"),
)

# "we've been around 5 years" is not a requirement, but this is a reasonable
# trade-off; the cap keeps outliers out.
_DASHES = "-\u2013\u2014"
_EXP_RANGE_RE = re.compile(
    r"(\d{1,2})\s*(?:[" + _DASHES + r"]|to)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)", re.I
)
_EXP_PLUS_RE = re.compile(r"(\d{1,2})\s*\+\s*(?:years?|yrs?)", re.I)
_EXP_MIN_RE = re.compile(r"(?:min(?:imum)?\.?|at least)\s*[:\-]?\s*(\d{1,2})\s*(?:years?|yrs?)", re.I)
_EXP_ALL_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)", re.I)
_FRESHER_RE = re.compile(r"\b(fresher|entry[ -]level|no experience required|0\s*-\s*1\s*year)", re.I)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}")
_URL_RE = re.compile(r"https?://[^\s)>\]]+")
_APPLY_LINK_RE = re.compile(
    r"apply\s+(?:here|at|via|through|using|on)|application\s+(?:link|form|portal)|"
    r"fill\s+(?:out|in)|link\s+below|careers?\s+(?:page|portal)|job\s+board",
    re.I,
)
_BAD_URL_PARTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".svg")
_BARE_DOMAIN_RE = re.compile(
    r"(?<![\w.@/-])(?:[a-z0-9-]+\.)+(?:com|io|in|dev|app|co|net|org|ai|me|xyz|so|site|link|ly)"
    r"(?:/[^\s)>\]]*)?",
    re.I,
)
_APPLY_URL_HINTS = ("apply", "job", "career", "hiring", "form", "link", "position", "role")

_JOB_BOARD_HANDLE_RE = re.compile(r"(jobs?|hiring|careers?|vacanc|recruit|jobalert|jobboard)", re.I)
_JOB_BOARD_NAME_RE = re.compile(
    r"\b(jobs?|hiring|careers?|vacanc\w*|job board|job alerts?|remote jobs|internships?)\b", re.I
)
_ORG_NAME_RE = re.compile(
    r"\b(inc|ltd|llc|technologies|solutions|labs|systems|company|studio|community|network|"
    r"hub|official|team|foundation|group|agency|consulting|services)\b",
    re.I,
)


def content_fingerprint(text: str) -> str:
    """Stable fingerprint for a post body.

    Lowercases, drops links/hashtags/punctuation and collapses whitespace, so
    the same job reposted by another account (or with different emoji) collapses
    to the same hash.
    """
    import hashlib

    body = (text or "").lower()
    body = re.sub(r"https?://\S+", " ", body)
    body = re.sub(r"#\w+", " ", body)
    body = re.sub(r"[^a-z0-9 ]+", " ", body)
    body = re.sub(r"\s+", " ", body).strip()
    if not body:
        return ""
    return hashlib.sha1(body[:400].encode("utf-8")).hexdigest()


def classify_author(handle: str, name: str) -> str:
    """person | company | job_board

    Job boards and community pages rarely read DMs; individual founders and
    engineers do. The pipeline only DMs people/companies and just replies to
    job boards.
    """
    clean_handle = (handle or "").lstrip("@")
    display = name or ""

    if _JOB_BOARD_HANDLE_RE.search(clean_handle) or _JOB_BOARD_NAME_RE.search(display):
        return "job_board"
    if _ORG_NAME_RE.search(display):
        return "company"
    return "person"


def _join_broken_urls(text: str) -> str:
    """X line-wraps long links: 'https://\\nlinks.example.com/x' -> one URL."""
    joined = re.sub(r"https?://[ \t]*\r?\n[ \t]*", "https://", text or "")
    return re.sub(r"https?://[ \t]+", "https://", joined)


def extract_contact_email(text: str) -> str:
    match = _EMAIL_RE.search(text or "")
    return match.group(0).strip(".,;:") if match else ""


def extract_apply_url(text: str) -> str:
    normalized = _join_broken_urls(text)

    candidates: list[str] = []
    for url in _URL_RE.findall(normalized):
        cleaned = url.rstrip(".,);]")
        if any(part in cleaned.lower() for part in _BAD_URL_PARTS):
            continue
        candidates.append(cleaned)

    if not candidates:
        for url in _BARE_DOMAIN_RE.findall(normalized):
            cleaned = url.rstrip(".,);]")
            lowered = cleaned.lower()
            if any(part in lowered for part in _BAD_URL_PARTS):
                continue
            if lowered.startswith(("github.com", "twitter.com", "x.com")):
                continue
            candidates.append(cleaned if lowered.startswith("http") else f"https://{cleaned}")

    if not candidates:
        return ""

    candidates.sort(key=lambda url: 0 if any(h in url.lower() for h in _APPLY_URL_HINTS) else 1)
    return candidates[0]


def detect_apply_method(text: str, *, email: str = "", url: str = "") -> str:
    """email | link | dm | unknown"""
    if email:
        return "email"
    lowered = (text or "").lower()
    mentions_dm = bool(re.search(r"\bdm\b|message me|send me a message|inbox me", lowered))
    if mentions_apply_link(text) and not url:
        # The link lives in the post's link card, not the text. Never fall back
        # to a DM just because the URL could not be scraped.
        return "link"
    if url:
        if _APPLY_LINK_RE.search(text or ""):
            return "link"
        if not mentions_dm:
            return "link"
    if mentions_dm:
        return "dm"
    return "unknown"


_APPLY_LINK_PHRASE_RE = re.compile(
    r"\b("
    r"apply\s+link|application\s+link|link\s+to\s+apply|link\s+below|"
    r"application\s+form|google\s+form|form\s+link|register\s+here|apply\s+here|"
    r"apply\s+at|apply\s+on|application\s+process"
    r")\b",
    re.I,
)


def mentions_apply_link(text: str) -> bool:
    """True when the post points at an external application link/form.

    Catches posts like "Apply Link:" where X kept the URL in a link card and the
    scraped text contains no URL at all. Such posts must never get a DM.
    """
    lowered = (text or "").lower()
    if re.search(r"apply\s+via\s+dm|dm\s+to\s+apply|apply\s+by\s+dm", lowered):
        return False
    return bool(_APPLY_LINK_PHRASE_RE.search(text or ""))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        clean = (value or "").strip()
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            out.append(clean)
    return out


def selected_roles(profile: Profile) -> list[str]:
    return _dedupe([profile.job_title, *(profile.target_roles or [])])


def infer_adjacent_roles(profile: Profile, limit: int = 2) -> list[str]:
    """Roles implied by the resume that the human did not pick."""
    if (profile.domain or "tech") != "tech":
        return []

    chosen = {role.lower() for role in selected_roles(profile)}
    skills = " ".join((profile.skills or [])).lower()
    inferred: list[str] = []
    for skill, role in ROLE_FROM_SKILL:
        if skill in skills and role.lower() not in chosen and role not in inferred:
            inferred.append(role)
        if len(inferred) >= limit:
            break
    return inferred


def build_queries(profile: Profile, settings_row, *, now: datetime | None = None) -> list[str]:
    """Build 1-3 X search queries aimed at fresh hiring posts."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(hours=max(1, settings_row.lookback_hours))).strftime("%Y-%m-%d")

    primary = selected_roles(profile)[:5]
    adjacent = infer_adjacent_roles(profile)

    if not primary and not adjacent:
        fallback_role = profile.current_role or (
            "software engineer" if (profile.domain or "tech") == "tech" else profile.job_title
        )
        primary = [fallback_role] if fallback_role else ["software engineer"]

    hiring_clause = " OR ".join(HIRING_TERMS)
    filters = f"-filter:replies -filter:nativeretweets lang:en since:{since}"

    def clause(terms: list[str]) -> str:
        joined = " OR ".join(f'"{t}"' if " " in t else t for t in terms)
        return f"({joined})"

    queries: list[str] = []
    if primary:
        queries.append(f"({hiring_clause}) {clause(primary)} {filters}")

    # Adjacent roles get their own query so the picked list never narrows us.
    if adjacent:
        queries.append(f"({hiring_clause}) {clause(adjacent)} {filters}")

    for custom in (settings_row.extra_queries or [])[:2]:
        custom = str(custom).strip()
        if custom:
            queries.append(custom if "since:" in custom else f"{custom} since:{since}")

    seen: set[str] = set()
    out: list[str] = []
    for query in queries:
        query = query[:MAX_QUERY_LEN].strip()
        if query and query not in seen:
            seen.add(query)
            out.append(query)
    return out[:3]


# --------------------------------------------------------------- experience

def required_experience_months(text: str) -> int:
    """Lowest stated experience requirement in months (0 when none)."""
    raw = text or ""
    if _FRESHER_RE.search(raw):
        return 0

    lows: list[int] = []
    for match in _EXP_RANGE_RE.finditer(raw):
        lows.append(int(match.group(1)))
    for match in _EXP_PLUS_RE.finditer(raw):
        lows.append(int(match.group(1)))
    for match in _EXP_MIN_RE.finditer(raw):
        lows.append(int(match.group(1)))
    if not lows:
        for match in _EXP_ALL_RE.finditer(raw):
            lows.append(int(match.group(1)))

    lows = [value for value in lows if 0 <= value <= 20]
    if not lows:
        return 0
    return min(lows) * 12


def matches_avoid(profile: Profile, text: str) -> str | None:
    lowered = (text or "").lower()
    for term in profile.avoid or []:
        clean = str(term).strip().lower()
        if len(clean) >= 4 and clean in lowered:
            return str(term)
    return None


_TECH_SIGNALS = (
    "developer", "engineer", "software", "react", "next.js", "python", "node",
    "java", "typescript", "javascript", "backend", "frontend", "full stack",
    "devops", "data scientist", "ml engineer", "qa engineer", "api", "database",
    "cloud", "android", "ios", "flutter",
)
_NON_TECH_SIGNALS = (
    "sales", "marketing", "business development", "business developer",
    "account executive", "account manager", "sales executive", "sales manager",
    "recruiter", "customer support", "customer success", "content writer",
    "graphic designer", "operations manager", "human resources", "inside sales",
    "lead generation", "partnerships manager", "growth manager",
)

# Terms that genuinely describe a software job. Generic words like "developer"
# appear in "business developer", so they must not cancel a non-tech signal.
_STRONG_TECH_SIGNALS = (
    "software engineer", "software developer", "sde", "swe", "full stack",
    "fullstack", "frontend", "front-end", "backend", "back-end", "python",
    "javascript", "typescript", "java", "react", "node.js", "next.js", "golang",
    "rust", "data engineer", "devops", "machine learning", "ml engineer",
    "android", "ios", "flutter", "qa engineer", "database", "kubernetes",
    "docker", "sql", "git", "rest api",
)


def domain_mismatch(profile: Profile, text: str) -> str | None:
    """Stop a tech resume from getting non-tech posts, and vice versa."""
    domain = profile.domain or "tech"
    lowered = (text or "").lower()
    looks_tech = any(signal in lowered for signal in _TECH_SIGNALS)
    looks_strong_tech = any(signal in lowered for signal in _STRONG_TECH_SIGNALS)
    looks_non_tech = any(signal in lowered for signal in _NON_TECH_SIGNALS)

    if domain == "tech" and looks_non_tech and not looks_strong_tech:
        return "looks like a non-tech role"
    if domain == "non-tech" and looks_tech and not looks_non_tech:
        return "looks like a tech role"
    return None


# ------------------------------------------------------------------ scoring
#
# Relevance is decided deterministically: fast, free, and predictable. The LLM
# is reserved for writing the reply/DM, where language quality actually matters.

_HIRING_SIGNALS = (
    "hiring",
    "opening",
    "looking for",
    "join our team",
    "vacancy",
    "opportunity",
    "referral",
    "happy to refer",
    "is hiring for",
)
_DM_SIGNALS = ("dm ", "dm me", "dm us", "message me", "inbox me", "send me a message")
_GENERIC_ROLE_SIGNALS = (
    "developer", "engineer", "sde", "intern", "full stack", "fullstack",
    "backend", "frontend", "software", "programmer",
)

# Posts written by a founder / early-stage team, in their own words.
_FOUNDER_SIGNALS = (
    "founding engineer",
    "first engineer",
    "first hire",
    "co-founder",
    "cofounder",
    "0 to 1",
    "we're building",
    "we are building",
    "building our team",
    "small team",
    "early stage",
    "seed stage",
    "stealth",
)
_FIRST_PERSON_HIRING = (
    "i'm hiring",
    "i am hiring",
    "hiring for my team",
    "join my team",
    "my team is",
    "dm me your resume",
    "dm your resume",
    "referrals open",
    "happy to refer",
    "can refer",
)


def _role_match(profile: Profile, text: str) -> int:
    """45 for an exact role phrase, 25/20 for strong role words, else 0."""
    roles = selected_roles(profile) + infer_adjacent_roles(profile, limit=3)
    for role in roles:
        if role and role.lower() in text:
            return 45

    role_words = {
        word
        for role in roles
        for word in re.findall(r"[a-z]{3,}", role.lower())
        if word not in {"developer", "engineer", "senior", "junior", "lead"}
    }
    if any(word in text for word in role_words):
        return 25
    if any(signal in text for signal in _GENERIC_ROLE_SIGNALS):
        return 30
    return 0


def _fallback_score(profile: Profile, post: JobPost) -> dict:
    """Deterministic relevance score (no model call)."""
    text = (post.content or "").lower()
    required = required_experience_months(post.content or "")
    email = extract_contact_email(post.content or "")
    url = extract_apply_url(post.content or "")

    if matches_avoid(profile, text):
        return {
            "post_id": post.post_id,
            "relevance": 0,
            "company": "",
            "role": "",
            "job_location": "",
            "apply_method": detect_apply_method(post.content or "", email=email, url=url),
            "contact": email or post.author_handle,
            "contact_email": email,
            "apply_url": url,
            "required_experience_months": required,
            "reason": "matches a role you said is not a fit",
        }

    score = 0
    reasons: list[str] = []

    role_points = _role_match(profile, text)
    if role_points:
        score += role_points
        reasons.append("role match")

    skill_hits = [skill for skill in (profile.skills or []) if skill and skill.lower() in text]
    if skill_hits:
        points = min(40, len(skill_hits) * 8)
        score += points
        reasons.append(f"{len(skill_hits)} skill match")

    if any(signal in text for signal in _HIRING_SIGNALS):
        score += 20
        reasons.append("hiring post")

    if any(signal in text for signal in _DM_SIGNALS):
        score += 5

    author = classify_author(post.author_handle, post.author_name)
    if author == "person":
        score += 20
        reasons.append("individual author")
        if any(signal in text for signal in _FOUNDER_SIGNALS):
            score += 10
            reasons.append("founder / early-stage")
        if any(signal in text for signal in _FIRST_PERSON_HIRING):
            score += 8
            reasons.append("hiring directly")
    elif author == "job_board":
        score -= 15
        reasons.append("job-board account")
    elif author == "company":
        score += 3

    if required:
        # Not a hard reject here - the pipeline owns that gate - but a role that
        # wants far more experience should not look attractive.
        if required > profile.experience_months + 3:
            score = min(score, 15)
            reasons.append("experience gap")

    return {
        "post_id": post.post_id,
        "relevance": min(100, score),
        "company": "",
        "role": "",
        "job_location": "remote" if "remote" in text else "",
        "apply_method": detect_apply_method(post.content or "", email=email, url=url),
        "contact": email or post.author_handle,
        "contact_email": email,
        "apply_url": url,
        "required_experience_months": required,
        "author_type": author,
        "reason": ", ".join(reasons) or "weak match",
    }


def score_posts(profile: Profile, posts: list[JobPost]) -> dict[str, dict]:
    """Deterministic scoring for every discovered post. No LLM involved."""
    return {post.post_id: _fallback_score(profile, post) for post in posts}



def _llm_ready() -> bool:
    from app.config import settings

    return settings.llm_enabled


def is_fresh(posted_at: datetime | None, lookback_hours: int, now: datetime | None = None) -> bool:
    if posted_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=timezone.utc)
    return posted_at >= now - timedelta(hours=lookback_hours)


_JOB_SEEKER_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("open to work", re.compile(r"open\s+to\s+work\b(?!\s*-?\s*from)", re.I)),
    ("#opentowork", re.compile(r"#\s*opentowork\b", re.I)),
    (
        "looking for a job",
        re.compile(
            r"\b(?:looking|searching|seeking)\s+(?:for\s+)?(?:a\s+|an\s+)?"
            r"(?:new\s+)?(?:job|role|position|opportunit(?:y|ies)|internship)\b",
            re.I,
        ),
    ),
    (
        "need a referral",
        re.compile(
            r"\b(?:need|needing|looking\s+for|seeking|want|wanting|asking\s+for|require|requiring)"
            r"\s+(?:a\s+|some\s+)?referrals?",
            re.I,
        ),
    ),
    ("refer me", re.compile(r"\brefer\s+me\b", re.I)),
    (
        "can someone refer",
        re.compile(r"\bcan\s+(?:anyone|someone|somebody)\s+refer\b", re.I),
    ),
    ("please refer", re.compile(r"\bplease\s+(?:do\s+)?refer\b", re.I)),
    ("referral please", re.compile(r"\breferrals?\s+(?:please|needed|required)\b", re.I)),
    (
        "if anyone is hiring",
        re.compile(r"\bif\s+(?:anyone|someone|somebody)\s+is\s+hiring\b", re.I),
    ),
    ("anyone hiring", re.compile(r"\banyone\s+hiring\??\b", re.I)),
    ("job seeker", re.compile(r"\bjob\s+seeker\b|#\s*jobseeker\b", re.I)),
    ("actively looking", re.compile(r"\bactively\s+looking\b", re.I)),
    (
        "dm me for referral",
        re.compile(r"\bdm\s+me\s+(?:for\s+)?(?:a\s+)?referrals?\b", re.I),
    ),
)


def job_seeker_reason(text: str) -> str:
    """Return why a post is a job seeker (not a hiring post), or ''.

    These posts ask *for* a job/referral. The agent must never DM them: the
    author is a candidate, not someone who can hire.
    """
    for label, pattern in _JOB_SEEKER_PATTERNS:
        if pattern.search(text or ""):
            return label
    return ""


def looks_like_job_post(text: str) -> bool:
    lowered = (text or "").lower()
    if len(lowered) < 40:
        return False
    if job_seeker_reason(text):
        return False
    signals = (
        "hiring",
        "opening",
        "looking for",
        "join our",
        "role",
        "position",
        "vacancy",
        "opportunity",
        "apply",
    )
    return any(signal in lowered for signal in signals)


def is_own_post(author_handle: str, own_username: str) -> bool:
    return author_handle.lstrip("@").lower() == (own_username or "").lstrip("@").lower()


def extract_status_id(url: str) -> str | None:
    match = re.search(r"/status/(\d+)", url or "")
    return match.group(1) if match else None

