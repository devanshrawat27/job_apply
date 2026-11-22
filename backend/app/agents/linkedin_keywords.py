"""LinkedIn keyword scoreboard and rotation.

LinkedIn is rate limited and fuzzy, so a pass runs only a few plain role
searches. Proven terms are reused, untried ones get a turn, and a term that
keeps returning nothing useful is retired instead of being retried forever.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import linkedin_jobs
from app.models import LinkedInQuery, Profile

MAX_TERMS_PER_SCAN = 1
MAX_ROWS = 60
RETIRE_AFTER_USES = 3
RETIRE_MIN_SEEN = 10


def _score(row: LinkedInQuery) -> float:
    seen = int(row.jobs_seen or 0)
    relevant = int(row.jobs_relevant or 0)
    return round((relevant + 0.5) / (seen + 2), 3)


def _ensure_terms(db: Session, profile: Profile, user_id: int | None) -> list[LinkedInQuery]:
    rows = list(
        db.scalars(
            select(LinkedInQuery)
            .where(LinkedInQuery.user_id == user_id if user_id is not None else LinkedInQuery.user_id.is_(None))
            .order_by(LinkedInQuery.id)
        ).all()
    )
    known = {row.keyword.lower() for row in rows}
    for keyword, source in linkedin_jobs.search_terms(profile):
        if keyword.lower() in known:
            continue
        row = LinkedInQuery(
            user_id=user_id,
            keyword=keyword,
            source=source,
            status="candidate",
            uses=0,
            jobs_seen=0,
            jobs_relevant=0,
            score=0.0,
        )
        db.add(row)
        rows.append(row)
        known.add(keyword.lower())
    db.flush()
    return rows


def pick_terms(db: Session, profile: Profile, user_id: int | None = None) -> list[LinkedInQuery]:
    """Least-recently-used terms, proven ones first, then untried ones."""
    rows = _ensure_terms(db, profile, user_id)

    for row in rows:
        if row.status not in ("candidate", "active"):
            continue
        seen = int(row.jobs_seen or 0)
        relevant = int(row.jobs_relevant or 0)
        uses = int(row.uses or 0)
        if uses >= RETIRE_AFTER_USES and relevant == 0 and seen >= RETIRE_MIN_SEEN:
            row.status = "retired"
            logging.getLogger(__name__).info("retiring barren LinkedIn keyword %r", row.keyword)
        elif uses >= RETIRE_AFTER_USES + 2 and seen == 0:
            row.status = "retired"
    db.flush()

    usable = [row for row in rows if row.status in ("candidate", "active")]
    usable.sort(
        key=lambda row: (
            0 if row.status == "active" else 1,
            row.last_used_at is not None,
            row.last_used_at or datetime.min,
            -_score(row),
            row.id,
        )
    )
    chosen = usable[:MAX_TERMS_PER_SCAN]
    now = datetime.now(timezone.utc)
    for row in chosen:
        row.uses = int(row.uses or 0) + 1
        row.last_used_at = now
    db.commit()
    for row in chosen:
        db.refresh(row)
    return chosen


def record(db: Session, rows: list[LinkedInQuery], per_keyword: dict[str, dict]) -> None:
    for row in rows:
        stats = per_keyword.get(row.keyword, {"seen": 0, "relevant": 0})
        seen = int(stats.get("seen") or 0)
        relevant = int(stats.get("relevant") or 0)
        if seen == 0 and relevant == 0:
            continue
        row.jobs_seen = int(row.jobs_seen or 0) + seen
        row.jobs_relevant = int(row.jobs_relevant or 0) + relevant
        row.score = _score(row)
        if row.score >= 0.30 and int(row.uses or 0) >= 2:
            row.status = "active"
    db.commit()
    _prune(db, rows[0].user_id if rows else None)


def _prune(db: Session, user_id: int | None) -> None:
    stmt = select(LinkedInQuery).where(LinkedInQuery.status == "candidate")
    if user_id is not None:
        stmt = stmt.where(LinkedInQuery.user_id == user_id)
    rows = list(db.scalars(stmt.order_by(LinkedInQuery.score.asc(), LinkedInQuery.uses.asc())))
    for row in rows[: max(0, len(rows) - MAX_ROWS)]:
        db.delete(row)
    db.commit()


def snapshot(db: Session, user_id: int | None = None) -> dict:
    stmt = select(LinkedInQuery)
    if user_id is not None:
        stmt = stmt.where(LinkedInQuery.user_id == user_id)
    rows = list(db.scalars(stmt.order_by(LinkedInQuery.score.desc())).all())
    def item(row: LinkedInQuery) -> dict:
        return {
            "keyword": row.keyword,
            "score": row.score,
            "uses": row.uses,
            "posts_seen": row.jobs_seen,
            "posts_relevant": row.jobs_relevant,
        }

    return {
        "active": [item(row) for row in rows if row.status == "active"],
        "testing": [item(row) for row in rows if row.status == "candidate"][:12],
        "retired": len([row for row in rows if row.status == "retired"]),
    }
