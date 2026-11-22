"""Keyword scoreboard for LinkedIn hiring posts.

Every post search records how many posts a term returned and how many survived
the individual-hirer filter. The analyst (ChatGPT) reads this table and suggests
better terms; suggestions enter as candidates and must prove themselves too.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import discovery
from app.models import LinkedInPostQuery, Profile

MAX_TERMS_PER_SCAN = 3
MAX_ROWS = 80
RETIRE_AFTER_USES = 3
RETIRE_MIN_SEEN = 8


def _score(row: LinkedInPostQuery) -> float:
    seen = int(row.posts_seen or 0)
    relevant = int(row.posts_relevant or 0)
    return round((relevant + 0.5) / (seen + 2), 3)


def seed_terms(profile: Profile) -> list[tuple[str, str]]:
    roles = list(discovery.selected_roles(profile)[:4]) + list(
        discovery.infer_adjacent_roles(profile, limit=2)
    )
    skills = [str(skill).strip() for skill in (profile.skills or []) if str(skill).strip()][:3]
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(term: str, source: str) -> None:
        clean = " ".join(str(term or "").split())[:120]
        key = clean.lower()
        if not clean or key in seen:
            return
        seen.add(key)
        out.append((clean, source))

    for skill in skills:
        add(f"hiring {skill} developer", "skill")
    for role in roles[:3]:
        add(f"I am hiring {role}", "role")
        add(f"we are hiring {role}", "role")
    for role in roles[:2]:
        add(f"looking for {role}", "role")
        add(f"hiring for my team {role}", "role")
    add("I am hiring", "phrase")
    add("we are hiring", "phrase")
    return out


def _ensure(db: Session, profile: Profile, user_id: int | None) -> list[LinkedInPostQuery]:
    stmt = select(LinkedInPostQuery)
    if user_id is None:
        stmt = stmt.where(LinkedInPostQuery.user_id.is_(None))
    else:
        stmt = stmt.where(LinkedInPostQuery.user_id == user_id)
    rows = list(db.scalars(stmt.order_by(LinkedInPostQuery.id)).all())
    known = {row.keyword.lower() for row in rows}
    for keyword, source in seed_terms(profile):
        if keyword.lower() in known:
            continue
        row = LinkedInPostQuery(
            user_id=user_id,
            keyword=keyword,
            source=source,
            status="candidate",
            uses=0,
            posts_seen=0,
            posts_relevant=0,
            score=0.0,
        )
        db.add(row)
        rows.append(row)
        known.add(keyword.lower())
    db.flush()
    return rows


def pick(db: Session, profile: Profile, user_id: int | None = None) -> list[LinkedInPostQuery]:
    rows = _ensure(db, profile, user_id)
    for row in rows:
        if row.status not in ("candidate", "active"):
            continue
        uses = int(row.uses or 0)
        seen = int(row.posts_seen or 0)
        relevant = int(row.posts_relevant or 0)
        if uses >= RETIRE_AFTER_USES and seen >= RETIRE_MIN_SEEN and relevant == 0:
            row.status = "retired"
        elif uses >= RETIRE_AFTER_USES + 3 and seen == 0:
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


def record(db: Session, rows: list[LinkedInPostQuery], per_keyword: dict[str, dict]) -> None:
    for row in rows:
        stats = per_keyword.get(row.keyword, {"seen": 0, "relevant": 0})
        seen = int(stats.get("seen") or 0)
        relevant = int(stats.get("relevant") or 0)
        row.posts_seen = int(row.posts_seen or 0) + seen
        row.posts_relevant = int(row.posts_relevant or 0) + relevant
        row.score = _score(row)
        if row.score >= 0.30 and int(row.uses or 0) >= 2:
            row.status = "active"
    db.commit()
    _prune(db, rows[0].user_id if rows else None)


def _prune(db: Session, user_id: int | None) -> None:
    stmt = select(LinkedInPostQuery).where(LinkedInPostQuery.status == "candidate")
    if user_id is not None:
        stmt = stmt.where(LinkedInPostQuery.user_id == user_id)
    rows = list(
        db.scalars(stmt.order_by(LinkedInPostQuery.score.asc(), LinkedInPostQuery.uses.asc()))
    )
    for row in rows[: max(0, len(rows) - MAX_ROWS)]:
        db.delete(row)
    db.commit()


def add_suggestions(db: Session, user_id: int | None, suggestions: list[str]) -> int:
    stmt = select(LinkedInPostQuery.keyword)
    if user_id is None:
        stmt = stmt.where(LinkedInPostQuery.user_id.is_(None))
    else:
        stmt = stmt.where(LinkedInPostQuery.user_id == user_id)
    known = {str(keyword).lower() for keyword in db.scalars(stmt).all()}
    added = 0
    for keyword in suggestions:
        clean = " ".join(str(keyword or "").replace('"', " ").split())[:160]
        if not clean or clean.lower() in known:
            continue
        db.add(
            LinkedInPostQuery(
                user_id=user_id,
                keyword=clean,
                source="analyst",
                status="candidate",
                uses=0,
                posts_seen=0,
                posts_relevant=0,
                score=0.0,
            )
        )
        known.add(clean.lower())
        added += 1
    db.commit()
    return added


def snapshot(db: Session, user_id: int | None = None) -> dict:
    stmt = select(LinkedInPostQuery)
    if user_id is not None:
        stmt = stmt.where(LinkedInPostQuery.user_id == user_id)
    rows = list(db.scalars(stmt.order_by(LinkedInPostQuery.score.desc())).all())

    def item(row: LinkedInPostQuery) -> dict:
        return {
            "keyword": row.keyword,
            "status": row.status,
            "score": row.score,
            "uses": row.uses,
            "posts_seen": row.posts_seen,
            "posts_relevant": row.posts_relevant,
        }

    return {
        "active": [item(row) for row in rows if row.status == "active"],
        "testing": [item(row) for row in rows if row.status == "candidate"][:15],
        "retired": len([row for row in rows if row.status == "retired"]),
    }
