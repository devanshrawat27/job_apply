"""ChatGPT job-fit screen for the Approvals and Apply links queues.

Some posts in those queues look like jobs but do not match the candidate at all
(a sales role, a senior role, an unrelated stack). This module asks the model
once per batch and rejects the clear mismatches, so the human only reviews posts
that are actually worth their time.

The model sees the candidate profile and a compact list of posts, and returns
one verdict per post. It never sends anything.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.llm import LLMUnavailable, complete_json
from app.models import JobPost, Profile

logger = logging.getLogger(__name__)

BATCH_SIZE = 10
MAX_TEXT = 700

SYSTEM = """You screen job posts for ONE candidate. Be strict: a post is a match
only if this candidate could realistically apply and be considered - same
domain, similar role, and experience level the post accepts.

Reject when: the role is a different domain (sales, marketing, HR, support,
design, finance), the stack/role is unrelated to the candidate's skills, the
post demands clearly more experience than the candidate has, or the post is not
a real hiring post.

Return one verdict per post, in the same order. Never invent ids. JSON only."""

PROMPT = """CANDIDATE
role: {role}
level: {seniority} ({experience})
domain: {domain}
skills: {skills}
looking for: {targets}

POSTS
{posts}

Return JSON exactly in this shape:
{{
  "verdicts": [
    {{"id": 123, "match": true, "fit": 0, "reason": "one short line"}}
  ]
}}
fit is 0-100: how well the candidate's real skills match this post."""


def _profile(db: Session, user_id: int | None) -> Profile | None:
    stmt = select(Profile)
    if user_id is None:
        stmt = stmt.where(Profile.user_id.is_(None))
    else:
        stmt = stmt.where(Profile.user_id == user_id)
    return db.scalar(stmt)


def _jobs_stmt(user_id: int | None, scope: str, *, force: bool):
    stmt = select(JobPost)
    if scope == "pending":
        stmt = stmt.where(JobPost.status == "pending_approval")
    elif scope == "apply_links":
        stmt = stmt.where(
            JobPost.status == "new",
            JobPost.apply_url.isnot(None),
            JobPost.apply_url != "",
        )
    else:  # everything that still needs a decision
        stmt = stmt.where(
            JobPost.status.in_(("pending_approval", "new")),
        )
    if not force:
        stmt = stmt.where(JobPost.ai_reviewed.is_(False))
    if user_id is not None:
        stmt = stmt.where(JobPost.user_id == user_id)
    else:
        stmt = stmt.where(JobPost.user_id.is_(None))
    return stmt.order_by(JobPost.relevance.desc(), JobPost.id)


def remaining(db: Session, user_id: int | None, scope: str) -> int:
    stmt = _jobs_stmt(user_id, scope, force=False).with_only_columns(func.count(JobPost.id))
    return int(db.scalar(stmt) or 0)


def _prompt_for(profile: Profile | None, jobs: list[JobPost]) -> str:
    profile_data = {
        "role": (profile.job_title if profile else "") or "developer",
        "seniority": (profile.seniority if profile else "") or "fresher",
        "experience": f"{(profile.experience_months if profile else 0) or 0} months",
        "domain": (profile.domain if profile else "") or "tech",
        "skills": ", ".join((profile.skills if profile else [])[:14]),
        "targets": ", ".join(
            ((profile.target_roles if profile else []) or [])[:8]
        ),
    }
    lines = []
    for job in jobs:
        text = " ".join((job.content or "").split())[:MAX_TEXT]
        lines.append(
            f"id={job.id} | role={job.role or '?'} | company={job.company or '?'} | "
            f"location={job.job_location or '?'} | link={'yes' if job.apply_url else 'no'}\n{text}"
        )
    return PROMPT.format(**profile_data, posts="\n\n".join(lines))


def review_batch(
    db: Session,
    user_id: int | None,
    scope: str = "all",
    *,
    limit: int = BATCH_SIZE,
    force: bool = False,
    providers: list[dict] | None = None,
    browser: bool = False,
) -> dict:
    profile = _profile(db, user_id)
    jobs = list(db.scalars(_jobs_stmt(user_id, scope, force=force).limit(limit)).all())
    if not jobs:
        return {"checked": 0, "rejected": 0, "matched": 0, "remaining": 0}

    prompt = _prompt_for(profile, jobs)
    data: dict | None = None
    if browser:
        from app.services import browser_chatgpt

        try:
            data = browser_chatgpt.ask_json(SYSTEM, prompt)
        except Exception as exc:  # noqa: BLE001 - fall back to the API
            logger.warning("browser job filter failed: %s", exc)

    if data is None:
        data = complete_json(
            SYSTEM,
            prompt,
            temperature=0.2,
            max_tokens=1200,
            budget_s=70,
            providers=providers,
        )
    if not isinstance(data, dict):
        raise LLMUnavailable("job filter returned non-object JSON")

    by_id: dict[int, dict] = {}
    for item in data.get("verdicts") or []:
        if not isinstance(item, dict):
            continue
        try:
            job_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        by_id[job_id] = item

    rejected = 0
    matched = 0
    checked = 0
    for job in jobs:
        verdict = by_id.get(job.id)
        if verdict is None:
            continue
        checked += 1
        fit = max(0, min(100, int(verdict.get("fit") or 0)))
        reason = str(verdict.get("reason") or "")[:300]
        job.ai_reviewed = True
        job.ai_fit = fit
        job.ai_note = reason

        if bool(verdict.get("match")):
            matched += 1
            job.logs = [
                *(job.logs or []),
                f"ChatGPT fit {fit}/100: {reason}" if reason else f"ChatGPT fit {fit}/100",
            ][-60:]
        else:
            rejected += 1
            job.status = "rejected"
            job.decision_reason = f"ChatGPT filter: {reason or 'does not match your skills'}"
            job.reply_text = ""
            job.dm_text = ""
            job.confidence = 0.0
            job.logs = [
                *(job.logs or []),
                f"ChatGPT filter removed this post: {reason or 'no match'}",
            ][-60:]

    db.commit()
    return {
        "checked": checked,
        "rejected": rejected,
        "matched": matched,
        "remaining": remaining(db, user_id, scope),
    }
