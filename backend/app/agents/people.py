"""Find the right people to message on LinkedIn for an apply-link job.

We never invent names or profile URLs. The model produces targeted LinkedIn
people-search queries and a short DM; the human clicks the search and sends it
from their own LinkedIn account.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

from app.llm import LLMUnavailable, complete_json
from app.models import JobPost, Profile

logger = logging.getLogger(__name__)

SYSTEM = """You help a job candidate find the right people to message on LinkedIn
for a job they found on X. You never invent personal names or profile URLs.
You only produce LinkedIn people-search queries and a short, specific DM.
Return strict JSON only."""

PROMPT = """JOB POST
{post}

CANDIDATE
title: {title}
level: {level}
skills: {skills}

Return JSON:
{{
  "company": "company name from the post, or empty",
  "role": "role title from the post",
  "queries": [
    "LinkedIn people-search query that includes the company name, e.g. '<company> technical recruiter'",
    "the same for talent acquisition / HR",
    "the same for the engineering manager or team lead",
    "the same for a software engineer who could refer the candidate"
  ],
  "message": "2-3 sentence LinkedIn DM to the recruiter. Mention the role, one concrete skill, and ask if they are open to a quick chat. No placeholders, no invented names."
}}
Rules:
- queries must contain the company name (when the post names one).
- Never write personal names, email addresses or linkedin.com/in URLs.
- Keep the message under 70 words."""


def _fallback(job: JobPost) -> dict:
    company = (job.company or "").strip()
    role = (job.role or "").strip()
    queries = []
    if company:
        queries = [
            f"{company} technical recruiter",
            f"{company} talent acquisition",
            f"{company} engineering manager",
            f"{company} software engineer referral",
        ]
    role_text = role or "open"
    message = (
        f"Hi — I saw {company or 'your company'} is hiring for the {role_text} role. "
        "I build production web apps (React, Node.js) and would love to apply. "
        "Would you be open to a quick chat?"
    )
    return {"company": company, "role": role, "queries": queries, "message": message}


def links_for(queries: list[str]) -> list[dict]:
    out = []
    for query in queries:
        lowered = query.lower()
        if "talent" in lowered or " hr" in f" {lowered}" or "human resources" in lowered:
            label = "HR / Talent"
        elif "recruit" in lowered:
            label = "Recruiter"
        elif "manager" in lowered or "lead" in lowered:
            label = "Hiring manager"
        elif "refer" in lowered:
            label = "Referral"
        else:
            label = "People"
        out.append(
            {
                "label": label,
                "query": query,
                "url": "https://www.linkedin.com/search/results/people/?keywords="
                + quote(query),
            }
        )
    return out


def _clean_queries(raw: list, company: str) -> list[str]:
    queries: list[str] = []
    for item in raw:
        query = " ".join(str(item or "").split())
        if not 5 <= len(query) <= 120:
            continue
        lowered = query.lower()
        if "linkedin.com" in lowered or "@" in query:
            continue
        if company and company.lower() not in lowered:
            continue
        if query.lower() not in {q.lower() for q in queries}:
            queries.append(query)
        if len(queries) >= 4:
            break
    return queries


def generate(
    db,
    job: JobPost,
    profile: Profile | None,
    user_id: int | None,
    *,
    providers: list[dict] | None = None,
    browser: bool = False,
) -> dict:
    fallback = _fallback(job)
    prompt = PROMPT.format(
        post=(job.content or "")[:1400],
        title=(job.role or (profile.job_title if profile else "") or "developer"),
        level=(profile.seniority if profile else "") or "early-career",
        skills=", ".join((profile.skills or [])[:8]) if profile else "",
    )

    data: dict | None = None
    if browser:
        from app.services import browser_chatgpt

        try:
            data = browser_chatgpt.ask_json(
                SYSTEM, prompt, user_id=user_id, purpose="people", timeout=120
            )
        except Exception as exc:  # noqa: BLE001 - fall back to the local queries
            logger.warning("browser people search failed: %s", exc)

    if data is None and providers:
        try:
            data = complete_json(
                SYSTEM, prompt, temperature=0.3, max_tokens=500, budget_s=45, providers=providers
            )
        except LLMUnavailable as exc:
            logger.warning("people search model unavailable: %s", exc)

    result = fallback
    if isinstance(data, dict):
        company = str(data.get("company") or fallback["company"]).strip()[:120]
        role = str(data.get("role") or fallback["role"]).strip()[:120]
        queries = _clean_queries(list(data.get("queries") or []), company)
        message = " ".join(str(data.get("message") or "").split())[:600]
        if not queries:
            queries = _fallback(JobPost(company=company, role=role)).get("queries") or []
        if not message:
            message = fallback["message"]
        result = {"company": company, "role": role, "queries": queries, "message": message}

    job.company = result["company"] or job.company
    job.role = result["role"] or job.role
    job.people_queries = result["queries"]
    job.linkedin_message = result["message"]
    from app.models import utcnow

    job.people_at = utcnow()
    db.commit()

    return {
        "company": result["company"],
        "role": result["role"],
        "queries": result["queries"],
        "links": links_for(result["queries"]),
        "message": result["message"],
        "generated": bool(data),
    }


def stored(job: JobPost) -> dict:
    queries = list(job.people_queries or [])
    if queries:
        return {
            "company": job.company,
            "role": job.role,
            "queries": queries,
            "links": links_for(queries),
            "message": job.linkedin_message or "",
            "generated": True,
        }
    base = _fallback(job)
    return {
        "company": base["company"],
        "role": base["role"],
        "queries": base["queries"],
        "links": links_for(base["queries"]),
        "message": base["message"],
        "generated": False,
    }
