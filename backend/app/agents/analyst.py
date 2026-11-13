"""LLM analyst: the "third person" that reads the agent's own results.

The agent does the work (finding posts, filtering, sending). This module only
looks at what happened and answers three questions:

1. which search keywords are producing real matches, and which are dead weight
2. which NEW junior-friendly keywords are worth trying next
3. what should the replies/DMs do better

It never sends anything. Its output is stored as an :class:`Insight` and its
keyword suggestions are added to the keyword lab as *candidates*, so they still
have to prove themselves against real results.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.llm import LLMUnavailable, complete_json
from app.models import Insight, JobPost, Profile, SearchQuery

logger = logging.getLogger(__name__)

REFRESH_AFTER = timedelta(hours=6)
MAX_NEW_KEYWORDS = 6

SYSTEM = """You are a job-search analyst for one candidate on X (Twitter).

You will get:
- the candidate profile (role, level, skills, experience)
- the search keywords the agent tried, with posts seen / relevant / score
- a sample of posts that were rejected and why
- a sample of posts that were sent and the reply/DM that went out

Your job:
1. Say which keywords are working, which are dead weight, and which are too
   senior for this candidate.
2. Suggest NEW search keywords that would find junior/fresher roles this
   candidate can actually win. Prefer concrete role names and hiring phrases.
   Never suggest senior/staff/principal/lead/founding/manager titles.
3. Give short, practical advice to make the outgoing replies and DMs better.

Be blunt and specific. No filler. Return strict JSON only."""

PROMPT = """CANDIDATE
role: {role}
level: {seniority} ({experience} experience)
skills: {skills}
domain: {domain}
github: {github}

KEYWORDS (keyword | status | uses | posts seen | relevant | replies | score)
{keywords}

REJECTED SAMPLE (reason)
{rejected}

SENT SAMPLE (reply / dm)
{sent}

Return JSON:
{{
  "summary": "2-3 sentences: what is working and what is broken",
  "keyword_verdicts": [
    {{"keyword": "exact keyword", "verdict": "keep|retire|try", "why": "one short line"}}
  ],
  "new_keywords": [
    {{"keyword": "search phrase for X", "why": "why it fits a fresher"}}
  ],
  "message_tips": ["specific change for the replies/DMs"],
  "best_post_types": ["what kind of post this candidate should aim at"]
}}
"""


def _profile_snapshot(profile: Profile | None) -> dict:
    if profile is None:
        return {
            "role": "unknown",
            "seniority": "unknown",
            "experience": "unknown",
            "skills": "",
            "domain": "tech",
            "github": "not linked",
        }
    return {
        "role": profile.job_title or "",
        "seniority": profile.seniority or "fresher",
        "experience": f"{profile.experience_months or 0} months",
        "skills": ", ".join((profile.skills or [])[:10]),
        "domain": profile.domain or "tech",
        "github": (getattr(profile, "github_summary", "") or "not linked")[:1200],
    }


def _keyword_lines(db: Session, user_id: int | None) -> list[str]:
    stmt = select(SearchQuery)
    if user_id is None:
        stmt = stmt.where(SearchQuery.user_id.is_(None))
    else:
        stmt = stmt.where(SearchQuery.user_id == user_id)
    rows = list(db.scalars(stmt.order_by(SearchQuery.score.desc(), SearchQuery.uses.desc())).all())
    lines = []
    for row in rows[:30]:
        lines.append(
            f"{row.keyword} | {row.status} | {row.uses} | {row.posts_seen} | "
            f"{row.posts_relevant} | {getattr(row, 'replies', 0)} | {row.score:.2f}"
        )
    return lines


def _rejected_lines(db: Session, user_id: int | None) -> list[str]:
    stmt = (
        select(JobPost.decision_reason, func.count(JobPost.id))
        .where(JobPost.status == "rejected")
        .group_by(JobPost.decision_reason)
        .order_by(func.count(JobPost.id).desc())
        .limit(8)
    )
    if user_id is not None:
        stmt = stmt.where(JobPost.user_id == user_id)
    return [f"{count}x {(reason or '')[:110]}" for reason, count in db.execute(stmt).all()]


def _sent_lines(db: Session, user_id: int | None) -> list[str]:
    stmt = select(JobPost).where(JobPost.status == "sent").order_by(JobPost.id.desc()).limit(5)
    if user_id is not None:
        stmt = stmt.where(JobPost.user_id == user_id)
    lines = []
    for job in db.scalars(stmt).all():
        role = job.role or "role"
        reply = (job.reply_text or "").replace("\n", " ")[:120]
        dm = (job.dm_text or "").replace("\n", " ")[:140]
        lines.append(f"{role}: reply={reply or '-'} | dm={dm or '-'}")
    return lines


def review_keywords(
    db: Session,
    user_id: int | None,
    *,
    providers: list[dict] | None = None,
    browser: bool = False,
) -> dict:
    """Ask the analyst to grade keywords and suggest better ones."""
    stmt = select(Profile)
    if user_id is None:
        stmt = stmt.where(Profile.user_id.is_(None))
    else:
        stmt = stmt.where(Profile.user_id == user_id)
    profile = db.scalar(stmt)

    prompt = PROMPT.format(
        **_profile_snapshot(profile),
        keywords="\n".join(_keyword_lines(db, user_id)) or "(none yet)",
        rejected="\n".join(_rejected_lines(db, user_id)) or "(none yet)",
        sent="\n".join(_sent_lines(db, user_id)) or "(none yet)",
    )

    data: dict | None = None
    if browser:
        from app.services import browser_chatgpt

        try:
            data = browser_chatgpt.ask_json(SYSTEM, prompt)
        except Exception as exc:  # noqa: BLE001 - fall back to the API path
            logger.warning("browser ChatGPT analysis failed: %s", exc)

    if data is None:
        data = complete_json(
            SYSTEM,
            prompt,
            temperature=0.35,
            max_tokens=1100,
            budget_s=60,
            providers=providers,
        )
    if not isinstance(data, dict):
        raise LLMUnavailable("analyst returned non-object JSON")

    payload = {
        "summary": str(data.get("summary") or "")[:1200],
        "keyword_verdicts": [
            {
                "keyword": str(item.get("keyword") or "")[:160],
                "verdict": str(item.get("verdict") or "").lower()[:20],
                "why": str(item.get("why") or "")[:300],
            }
            for item in (data.get("keyword_verdicts") or [])[:30]
            if isinstance(item, dict)
        ],
        "new_keywords": [
            {
                "keyword": str(item.get("keyword") or "")[:160],
                "why": str(item.get("why") or "")[:300],
            }
            for item in (data.get("new_keywords") or [])[:MAX_NEW_KEYWORDS]
            if isinstance(item, dict) and str(item.get("keyword") or "").strip()
        ],
        "message_tips": [str(tip)[:300] for tip in (data.get("message_tips") or [])][:8],
        "best_post_types": [str(tip)[:200] for tip in (data.get("best_post_types") or [])][:6],
    }

    insight = Insight(user_id=user_id, kind="keyword_review", summary=payload["summary"], payload=payload)
    db.add(insight)
    db.commit()
    db.refresh(insight)

    _adopt_keywords(db, user_id, payload)
    return {"id": insight.id, **payload}


def _adopt_keywords(db: Session, user_id: int | None, payload: dict) -> None:
    """Add suggested keywords as candidates so real results can judge them."""
    from app.agents import query_lab

    stmt = select(Profile)
    if user_id is None:
        stmt = stmt.where(Profile.user_id.is_(None))
    else:
        stmt = stmt.where(Profile.user_id == user_id)
    profile = db.scalar(stmt)
    if profile is None:
        return

    existing_stmt = select(SearchQuery.keyword)
    if user_id is None:
        existing_stmt = existing_stmt.where(SearchQuery.user_id.is_(None))
    else:
        existing_stmt = existing_stmt.where(SearchQuery.user_id == user_id)
    known = {str(keyword).lower() for keyword in db.scalars(existing_stmt).all()}

    for item in payload.get("new_keywords", []):
        keyword = str(item.get("keyword") or "")
        # ChatGPT sometimes wraps a phrase in quotes ("SDE 1" hiring); X query
        # building adds its own quotes, so keep the keyword clean. Apostrophes
        # are real text ("we're hiring"), so only double quotes are removed.
        keyword = keyword.replace('"', " ")
        keyword = " ".join(keyword.split()).strip()
        if not keyword or keyword.lower() in known:
            continue
        if not query_lab.keyword_fits_profile(keyword, profile):
            continue
        db.add(
            SearchQuery(
                user_id=user_id,
                keyword=keyword[:160],
                status="candidate",
                source="analyst",
                uses=0,
                posts_seen=0,
                posts_relevant=0,
                score=0.0,
            )
        )
        known.add(keyword.lower())
    db.commit()


def latest(db: Session, user_id: int | None) -> Insight | None:
    stmt = select(Insight).where(Insight.kind == "keyword_review")
    if user_id is None:
        stmt = stmt.where(Insight.user_id.is_(None))
    else:
        stmt = stmt.where(Insight.user_id == user_id)
    return db.scalar(stmt.order_by(Insight.id.desc()).limit(1))


def due(db: Session, user_id: int | None) -> bool:
    row = latest(db, user_id)
    if row is None:
        return True
    created = row.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - created >= REFRESH_AFTER
