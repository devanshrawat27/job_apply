"""Search vocabulary and the query formula.

X search is literal and has a 512-character limit, so the query is assembled
from short signal groups:

    (hiring signals) (level) (keyword) (negatives) -filter:replies
    -filter:nativeretweets lang:en since:YYYY-MM-DD

The level group is the big one for this product: the candidate is a fresher, so
"senior" and "5+ years" posts are worth excluding at query time (they are also
filtered later, but this saves quota and noise).
"""

from __future__ import annotations

import hashlib

HIRING_SIGNALS = (
    '"is hiring for"',
    '"hiring for"',
    '"we\'re hiring"',
    '"we are hiring"',
    '"now hiring"',
    '"hiring alert"',
    '"open role"',
    '"join our team"',
    '"looking to hire"',
    '"I\'m hiring"',
    '"opening for"',
    '"open position"',
)

# Referral posts are hiring posts with a different phrasing - people offering
# to refer candidates. They are worth the same as a "we're hiring" signal.
REFERRAL_SIGNALS = (
    '"referrals open"',
    '"happy to refer"',
    '"can refer"',
    '"open to referrals"',
    '"referral available"',
    '"drop your resume"',
    '"DM me your resume"',
)

INTENT_SIGNALS = HIRING_SIGNALS + REFERRAL_SIGNALS

# Short words used inside the X query. Quoted multi-word phrases ("is hiring for")
# and the level group made the query too narrow - real searches returned 0 posts.
INTENT_QUERY_TERMS = ("hiring", "opening", "refer", "referral", "apply")

LEVEL_FRESHER = (
    "intern",
    "internship",
    "fresher",
    '"new grad"',
    '"2027 batch"',
    '"2026 batch"',
    '"2025 batch"',
    "junior",
    '"entry level"',
    "graduate",
    "trainee",
    '"0-1 years"',
    '"0-2 years"',
    '"1+ years"',
    '"1-2 years"',
    '"SDE-1"',
)

LEVEL_EXPERIENCED = (
    '"2+ years"',
    '"3+ years"',
    '"4+ years"',
    '"mid level"',
    "SDE-2",
)

TECH_KEYWORDS = (
    "react",
    '"react.js"',
    "next.js",
    "node.js",
    "express",
    "mongodb",
    "firebase",
    "javascript",
    "typescript",
    '"full stack"',
    "fullstack",
    "MERN",
    "frontend",
    "backend",
    "python",
    "fastapi",
    "postgresql",
)

AI_KEYWORDS = (
    '"AI engineer"',
    '"AI developer"',
    "agentic",
    '"AI agents"',
    "LLM",
    "RAG",
    "GenAI",
    '"generative AI"',
    "langchain",
    "langgraph",
    '"prompt engineer"',
    '"applied AI"',
)

ROLE_TITLES = (
    '"software engineer"',
    '"software developer"',
    '"web developer"',
    "SDE",
    '"full stack developer"',
    '"frontend developer"',
    '"backend developer"',
    '"SDE intern"',
    '"software engineer intern"',
    '"full stack intern"',
    '"developer internship"',
    '"junior developer"',
    '"entry level developer"',
    '"associate software engineer"',
    '"graduate engineer trainee"',
    "fresher",
    '"AI engineer"',
)

# Senior titles only make sense for candidates who actually have the years.
SENIOR_ROLE_TITLES = (
    '"founding engineer"',
    '"first technical hire"',
    '"founding full stack engineer"',
    '"forward deployed engineer"',
    '"staff engineer"',
    '"principal engineer"',
)

STARTUP_SIGNALS = (
    "startup",
    '"early stage"',
    "seed",
    "YC",
    '"Series A"',
    "funded",
    '"founding team"',
    '"0 to 1"',
)

HIRING_PHRASE_KEYWORDS = (
    "hiring",
    "we are hiring",
    "we're hiring",
    "now hiring",
    "hiring alert",
    "hiring interns",
    "hiring freshers",
    "hiring developers",
    "hiring engineers",
    "immediate hiring",
    "join our team",
)

DIRECT_APPLY = (
    '"DM me"',
    '"DM open"',
    '"send your resume"',
    '"drop your resume"',
    '"send your CV"',
    '"email me"',
    '"apply here"',
    '"apply now"',
    '"reach out"',
    '"comment below"',
)

NEGATIVES = (
    "-senior",
    "-founding",
    "-lead",
    "-principal",
    "-staff",
    "-architect",
    "-manager",
    "-director",
    '-"10+ years"',
    '-"8+ years"',
    '-"5+ years"',
    "-unpaid",
    "-crypto",
    '-"commission only"',
    '-"earn from home"',
    '-"work and earn"',
)

MAX_QUERY_LEN = 512


def _or(terms: tuple[str, ...], limit: int | None = None) -> str:
    chunk = terms[:limit] if limit else terms
    return " OR ".join(chunk)


def _rotate(terms: tuple[str, ...], count: int, seed: str) -> tuple[str, ...]:
    """Stable slice of a signal group, so different keywords probe different
    phrasings instead of every query using the same five."""
    if len(terms) <= count:
        return terms
    start = int(hashlib.md5(seed.lower().encode()).hexdigest()[:8], 16) % len(terms)
    return tuple(terms[(start + i) % len(terms)] for i in range(count))


def _group_fit(terms: tuple[str, ...], budget: int, min_terms: int) -> str:
    """Largest ``(a OR b OR ...)`` group that fits the remaining budget."""
    for count in range(len(terms), min_terms - 1, -1):
        text = f"({_or(terms[:count])})"
        if len(text) <= budget:
            return text
    return f"({_or(terms[:min_terms])})"


def _fit(parts: list[str], limit: int = MAX_QUERY_LEN) -> str:
    """Join as many parts as fit, keeping the filters last and intact."""
    out: list[str] = []
    for part in parts:
        candidate = " ".join([*out, part])
        if len(candidate) <= limit:
            out.append(part)
    return " ".join(out)


def is_junior_seniority(seniority: str) -> bool:
    lowered = (seniority or "").strip().lower()
    return any(
        word in lowered
        for word in ("intern", "fresher", "entry", "junior", "trainee", "student", "graduate")
    )


def build_query(keyword: str, seniority: str, since: str, *, with_level: bool = True) -> str:
    """Full X search query for one keyword.

    Live testing showed the old ``(exact signal phrases) AND (intern/fresher
    level words)`` combination returned 0 posts for niche roles ("founding
    engineer" 0 vs 15 with broad intent). So the query now uses short intent
    words and leaves level filtering to the deterministic scoring stage.

    ``seniority`` / ``with_level`` are kept for callers but no longer change the
    query, and every match still passes the experience gate before drafting.
    Senior-level words are negated for junior candidates so "founding engineer"
    type posts never eat the search quota.
    """
    keyword = (keyword or "").strip().strip('"').strip()
    quoted = f'"{keyword}"' if " " in keyword else keyword

    intent = f"({_or(INTENT_QUERY_TERMS)})"
    target = f"({quoted})" if quoted else ""
    negatives = " ".join(NEGATIVES[:8] if is_junior_seniority(seniority) else NEGATIVES[-6:])
    filters = f"-filter:replies -filter:nativeretweets lang:en since:{since}"

    # The role phrase and the intent words do the work; filters must survive.
    return _fit([target, intent, negatives, filters])


def keyword_pool() -> tuple[str, ...]:
    """Broader set the agent explores when learning which keywords work."""
    seen: set[str] = set()
    out: list[str] = []
    for group in (TECH_KEYWORDS, AI_KEYWORDS, ROLE_TITLES, HIRING_PHRASE_KEYWORDS, STARTUP_SIGNALS):
        for term in group:
            key = term.lower().strip('"')
            if key not in seen:
                seen.add(key)
                out.append(term.strip('"'))
    return tuple(out)
