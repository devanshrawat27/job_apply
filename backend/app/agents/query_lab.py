"""Keyword lab: the agent learns which X search keywords actually work.

How it behaves
--------------
* It starts from the roles you picked plus a few skill words (seeds).
* Every scan it runs up to 3 keywords: the two with the best track record plus
  one it has not tried yet.
* After the scan it scores each keyword by `relevant posts / posts read`.
* A keyword that keeps producing relevant posts becomes `active` and is reused.
* A keyword that produces nothing useful is deleted, not archived - the point
  is to keep a small set of winners.

Nothing here talks to X. The pipeline hands it the per-keyword counts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.agents.discovery import HIRING_TERMS, MAX_QUERY_LEN, selected_roles
from app.agents import keywords as keyword_sets
from app.models import Profile, SearchQuery

logger = logging.getLogger(__name__)

MAX_KEYWORDS_PER_SCAN = 4
PINNED_PER_SCAN = 1
ACTIVATE_SCORE = 0.30
RETIRE_SCORE = 0.12
MAX_ROWS = 50

# A keyword is "barren" when it has had a fair chance and produced nothing.
BARREN_MIN_USES = 2
BARREN_MIN_SEEN = 8

GENERAL_TECH_KEYWORDS = (
    "software engineer",
    "frontend developer",
    "backend developer",
    "full stack developer",
    "react developer",
    "node.js developer",
    "python developer",
    "typescript developer",
    "next.js developer",
    "mern stack",
    "junior developer",
    "entry level developer",
    "fresher developer",
    "trainee developer",
    "associate software engineer",
    "developer internship",
    "genai",
    "llm engineer",
    "ai engineer",
    "devops engineer",
    "data engineer",
    "machine learning engineer",
    "mobile developer",
    "java developer",
    "golang developer",
    "sde",
    "api developer",
    "cloud engineer",
    "qa automation",
)

GENERAL_NON_TECH_KEYWORDS = (
    "sales executive",
    "marketing manager",
    "customer support",
    "hr recruiter",
    "business development",
    "content writer",
    "operations executive",
    "account manager",
)

# High-intent role names that must always be in the candidate pool, even if the
# profile did not list them. They pair with the hiring/referral signals in
# keywords.INTENT_SIGNALS to form the curated search patterns.
#
# These are deliberately junior/fresher-oriented: "founding engineer", "first
# engineer" and similar senior titles pull 5+ years posts that this candidate
# can never apply to.
CURATED_KEYWORDS = (
    "sde intern",
    "software engineer intern",
    "full stack intern",
    "developer internship",
    "junior developer",
    "entry level developer",
    "fresher developer",
    "associate software engineer",
    "full stack developer",
    "frontend developer",
    "backend developer",
    "react developer",
    "node.js developer",
    "python developer",
    "software engineer",
    # Plain hiring phrases: a lot of founders write "we are hiring" and put the
    # role in the next lines, so these catch posts that role-only searches miss.
    # Kept to a short list so each one gets tested within a couple of hours.
    "we are hiring",
    "hiring",
    "we're hiring",
    "now hiring",
    "hiring interns",
    "hiring freshers",
)

# Titles/signals that make a keyword senior-level. For a fresher profile these
# waste search quota and produce posts that fail the experience gate anyway.
SENIOR_KEYWORD_SIGNALS = (
    "founding",
    "first engineer",
    "first technical",
    "senior",
    "sr.",
    "staff",
    "principal",
    "lead ",
    "lead engineer",
    "head of",
    "architect",
    "manager",
    "director",
    "vp ",
    "chief",
    "experienced",
    "expert",
)

JUNIOR_SENIORITIES = (
    "intern",
    "fresher",
    "entry",
    "junior",
    "trainee",
    "student",
    "graduate",
    "associate",
)


def is_junior_profile(profile: Profile) -> bool:
    """True for interns/freshers/entry-level candidates."""
    seniority = (profile.seniority or "").strip().lower()
    if any(word in seniority for word in JUNIOR_SENIORITIES):
        return True
    return (profile.experience_months or 0) <= 12


def keyword_fits_profile(keyword: str, profile: Profile) -> bool:
    """Skip keywords that clash with the candidate's real level.

    A fresher never gets "founding engineer" style keywords, and someone with
    years of experience never burns scans on "sde intern" / "junior developer".
    """
    lowered = (keyword or "").lower().strip()
    if is_junior_profile(profile):
        return not any(signal in lowered for signal in SENIOR_KEYWORD_SIGNALS)
    return not any(signal in lowered for signal in keyword_sets.JUNIOR_KEYWORD_SIGNALS)


def keyword_pool(profile: Profile) -> tuple[str, ...]:
    return keyword_sets.keyword_pool()


def seed_keywords(profile: Profile) -> list[str]:
    """Roles the human picked, plus a few concrete skill words."""
    seeds = selected_roles(profile)[:3]
    seen = {seed.lower() for seed in seeds}

    for skill in (profile.skills or [])[:8]:
        clean = " ".join(str(skill).split())
        if len(clean) < 3 or len(clean) > 40:
            continue
        # Resume extraction sometimes returns a whole sentence as a "skill".
        # Searching that literally returns nothing but noise.
        if any(char in clean for char in ".;,:!?()[]/"):
            continue
        if len(clean.split()) > 4:
            continue
        if clean.lower() in seen:
            continue
        # Skip skills that are already covered by a role name.
        if any(clean.lower() in seed.lower() for seed in seeds):
            continue
        seeds.append(clean)
        seen.add(clean.lower())
        if len(seeds) >= 5:
            break

    return seeds


def wrap_query(
    keyword: str,
    settings_row,
    *,
    profile: Profile | None = None,
    with_level: bool = True,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(hours=max(1, settings_row.lookback_hours))).strftime("%Y-%m-%d")
    seniority = (profile.seniority if profile else "") or ""
    return keyword_sets.build_query(keyword, seniority, since, with_level=with_level)


def _add(
    db: Session,
    rows: list[SearchQuery],
    known: set[str],
    keyword: str,
    user_id: int | None = None,
    source: str = "seed",
) -> SearchQuery:
    row = SearchQuery(
        user_id=user_id,
        keyword=keyword,
        status="candidate",
        source=source,
        uses=0,
        posts_seen=0,
        posts_relevant=0,
        score=0.0,
    )
    db.add(row)
    rows.append(row)
    known.add(keyword.lower())
    return row


def recent_yield(
    db: Session, user_id: int | None = None, *, days: int = 3, threshold: int = 60
) -> dict[str, dict[str, int]]:
    """What each search keyword actually produced recently.

    ``relevant`` is a keyword match; ``usable`` means the post survived the
    experience/author gates and became a sent job, a draft or an apply link.
    """
    from app.models import JobPost

    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    usable_statuses = ("sent", "new", "pending_approval", "queued")
    stmt = select(
        JobPost.query_text,
        func.count(JobPost.id),
        func.sum(case((JobPost.relevance >= threshold, 1), else_=0)),
        func.sum(case((JobPost.status.in_(usable_statuses), 1), else_=0)),
    ).where(
        JobPost.discovered_at >= cutoff,
        JobPost.query_text != "",
        func.lower(JobPost.query_text) != "home feed",
    )
    if user_id is not None:
        stmt = stmt.where(JobPost.user_id == user_id)

    out: dict[str, dict[str, int]] = {}
    for keyword, created, relevant, usable in db.execute(
        stmt.group_by(JobPost.query_text)
    ).all():
        if not keyword:
            continue
        out[str(keyword).lower()] = {
            "created": int(created or 0),
            "relevant": int(relevant or 0),
            "usable": int(usable or 0),
        }
    return out


def optimize(db: Session, user_id: int | None = None) -> int:
    """Retire dead keywords, revive productive ones, keep the winners active.

    Runs from every scan pick. Pinned keywords are protected while they still
    produce something; a clearly dead pinned keyword is unpinned and retired so
    it cannot keep taking a scan slot forever.
    """
    now = datetime.now(timezone.utc)
    stmt = select(SearchQuery)
    if user_id is not None:
        stmt = stmt.where(SearchQuery.user_id == user_id)
    rows = list(db.scalars(stmt).all())
    recent = recent_yield(db, user_id, days=7)
    changed = 0

    def _aware(value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    for row in rows:
        if row.status == "retired":
            # A keyword that was retired on its lifetime average can still be
            # bringing recent posts. Bring it back into the pool instead of
            # losing a productive broad term forever. Roles taken from the
            # human's profile are never left retired.
            if (row.source or "") == "seed" or int(
                recent.get(row.keyword.lower(), {}).get("relevant") or 0
            ) >= 2:
                row.status = "active"
                row.pinned = False
                changed += 1
                logger.info("revived keyword %r", row.keyword)
            continue
        seen = int(row.posts_seen or 0)
        relevant = int(row.posts_relevant or 0)
        uses = int(row.uses or 0)
        recent_row = recent.get(row.keyword.lower(), {})
        recent_relevant = int(recent_row.get("relevant") or 0)

        dead = (uses >= 20 and seen <= 1) or (seen >= 20 and relevant == 0)
        if dead:
            if (row.source or "") == "seed":
                # A role from the human's profile is never removed by the
                # optimizer, even on a bad run.
                if row.status != "active":
                    row.status = "active"
                    changed += 1
                continue
            if row.pinned:
                row.pinned = False
                logger.info("unpinned dead keyword %r", row.keyword)
            row.status = "retired"
            changed += 1
            continue

        if (
            row.status == "candidate"
            and (relevant >= 2 or recent_relevant >= 1)
            and (row.score or 0) >= ACTIVATE_SCORE
        ):
            row.status = "active"
            changed += 1

    # Candidates that were tried a while ago and never returned a single post
    # would otherwise sit in the exploration pool forever.
    for row in rows:
        if row.status != "candidate":
            continue
        if int(row.posts_seen or 0) != 0 or int(row.uses or 0) == 0:
            continue
        last_used = _aware(row.last_used_at)
        if last_used is not None and (now - last_used) >= timedelta(days=3):
            row.status = "retired"
            changed += 1

    if changed:
        db.commit()
        logger.info("keyword optimizer: %s change(s)", changed)
    return changed


def select_keywords(db: Session, profile: Profile, user_id: int | None = None) -> list[SearchQuery]:
    """Pick the best-performing keywords for this scan and mark them used."""
    optimize(db, user_id)
    stmt = select(SearchQuery)
    if user_id is not None:
        stmt = stmt.where(SearchQuery.user_id == user_id)
    rows = list(
        db.scalars(
            stmt.order_by(
                SearchQuery.score.desc(), SearchQuery.uses.asc(), SearchQuery.id.asc()
            )
        )
    )
    known = {row.keyword.lower() for row in rows}
    junior = is_junior_profile(profile)

    # A fresher never burns scans on "founding engineer" style keywords, and
    # someone with real experience never burns them on "sde intern" style ones.
    for row in rows:
        if row.status not in ("active", "candidate") or row.pinned:
            continue
        if (row.source or "") == "seed":
            # Roles taken from the resume / the human are always respected.
            continue
        if not keyword_fits_profile(row.keyword, profile):
            row.status = "retired"
            logger.info("retiring %r: it does not match the profile level", row.keyword)
    db.flush()

    chosen_roles = {role.lower() for role in selected_roles(profile)}
    for keyword in seed_keywords(profile):
        if keyword.lower() in known:
            continue
        # A role the resume itself names is never filtered out.
        if keyword.lower() in chosen_roles or keyword_fits_profile(keyword, profile):
            _add(db, rows, known, keyword, user_id, source="seed")

    # Make sure the curated roles exist as candidates so the exploration slot
    # rotates through them instead of only ever trying profile roles.
    for keyword in CURATED_KEYWORDS:
        if keyword.lower() not in known and keyword_fits_profile(keyword, profile):
            _add(db, rows, known, keyword, user_id, source="curated")
    db.flush()

    recent = recent_yield(db, user_id, days=7)

    def priority(row: SearchQuery) -> float:
        stats = recent.get(row.keyword.lower(), {})
        volume = float(stats.get("relevant") or 0) + 2.0 * float(stats.get("usable") or 0)
        seen = int(row.posts_seen or 0)
        relevant = int(row.posts_relevant or 0)
        quality = (relevant + 1) / (seen + 4)
        return volume + 3.0 * quality

    def order(row: SearchQuery) -> tuple:
        return (-priority(row), row.last_used_at or datetime.min, row.id)

    active = sorted([row for row in rows if row.status == "active"], key=order)
    # At most one pinned slot: pins are a human override, not a licence to keep
    # firing keywords that never find anything.
    pinned_rows = sorted(
        [
            row
            for row in rows
            if row.pinned and row.status in ("active", "candidate")
        ],
        key=order,
    )[:PINNED_PER_SCAN]

    # Try never-used keywords first, so the curated roles actually get a turn;
    # then fall back to proven-but-not-active ones by score.
    untried = sorted(
        [row for row in rows if row.status == "candidate" and not row.uses],
        key=order,
    )
    tried = sorted(
        [row for row in rows if row.status == "candidate" and row.uses],
        key=order,
    )
    candidates = untried + tried

    fresh = [row for row in candidates if row.uses == 0]
    analyst_new = [row for row in fresh if (row.source or "") == "analyst"]
    hiring_phrases = {term.lower() for term in keyword_sets.HIRING_PHRASE_KEYWORDS}
    hiring = [row for row in fresh if row.keyword.lower() in hiring_phrases]
    parity = sum(int(row.uses or 0) for row in rows) % 2
    exploration_pool = (
        (analyst_new or hiring or fresh) if parity == 0 else (hiring or analyst_new or fresh)
    )

    chosen: list[SearchQuery] = []
    if pinned_rows:
        chosen.append(pinned_rows[0])

    # Always take the single best producer, then rotate the remaining good slots
    # by least-recent use. This keeps the winners in play without firing the
    # exact same three queries every 20 minutes and seeing only duplicates.
    top_active = active[: max(6, MAX_KEYWORDS_PER_SCAN + 2)]
    for row in top_active:
        if row not in chosen:
            chosen.append(row)
            break
    rotating = sorted(
        [row for row in top_active if row not in chosen],
        key=lambda row: (
            row.last_used_at is not None,
            row.last_used_at or datetime.min,
            row.id,
        ),
    )
    for row in rotating:
        if len(chosen) >= MAX_KEYWORDS_PER_SCAN - 1:
            break
        chosen.append(row)

    # One exploration slot so a new keyword can still prove itself.
    exploration = next((row for row in exploration_pool if row not in chosen), None)
    if exploration is not None:
        chosen.append(exploration)

    # Cold start / sparse pool: fill from candidates, best first. Once there is
    # a working active set, do not pad the scan with a tried-and-empty keyword
    # just to reach four slots - three good queries beat three good + one dud.
    fill_target = MAX_KEYWORDS_PER_SCAN if not active else MAX_KEYWORDS_PER_SCAN - 1
    for row in candidates:
        if len(chosen) >= fill_target:
            break
        if row not in chosen:
            chosen.append(row)

    if len(chosen) < fill_target:
        for keyword in keyword_pool(profile):
            if keyword.lower() in known:
                continue
            if not keyword_fits_profile(keyword, profile):
                continue
            chosen.append(_add(db, rows, known, keyword, user_id, source="pool"))
            if len(chosen) >= fill_target:
                break

    chosen = chosen[:MAX_KEYWORDS_PER_SCAN]
    db.flush()
    now = datetime.now(timezone.utc)
    for row in chosen:
        row.uses = (row.uses or 0) + 1
        row.last_used_at = now
    db.commit()
    for row in chosen:
        db.refresh(row)
    return chosen


def _score(row: SearchQuery) -> float:
    """Relevance counts, but a real reply counts twice as much.

    A keyword that finds posts which never answer is worse than one that finds
    fewer posts but starts conversations.
    """
    seen = int(row.posts_seen or 0)
    relevant = int(row.posts_relevant or 0)
    replies = int(getattr(row, "replies", 0) or 0)
    return round((relevant + 2 * replies + 0.5) / (seen + 2), 3)


def bump_reply(db: Session, keyword: str, user_id: int | None = None) -> None:
    """A person answered a post found by this keyword."""
    if not keyword:
        return
    stmt = select(SearchQuery).where(func.lower(SearchQuery.keyword) == keyword.lower())
    if user_id is not None:
        stmt = stmt.where(SearchQuery.user_id == user_id)
    else:
        stmt = stmt.where(SearchQuery.user_id.is_(None))
    row = db.scalar(stmt)
    if row is None:
        return
    row.replies = int(getattr(row, "replies", 0) or 0) + 1
    row.score = _score(row)
    db.commit()


def record_results(db: Session, keywords: list[SearchQuery], per_keyword: dict[str, dict]) -> None:
    """Update the scoreboard. Good keywords stay, bad ones are removed."""
    recent = recent_yield(db, keywords[0].user_id if keywords else None, days=7)
    for row in keywords:
        stats = per_keyword.get(row.keyword, {"seen": 0, "relevant": 0})
        seen = int(stats.get("seen") or 0)
        relevant = int(stats.get("relevant") or 0)

        # No fresh posts this round = no signal. Leave the score alone.
        if seen == 0:
            continue

        row.posts_seen = (row.posts_seen or 0) + seen
        row.posts_relevant = (row.posts_relevant or 0) + relevant
        row.uses = row.uses or 1

        row.score = _score(row)
        recent_relevant = int(
            recent.get(row.keyword.lower(), {}).get("relevant") or 0
        )

        if row.uses >= 2 and row.score >= ACTIVATE_SCORE:
            row.status = "active"
        elif (
            row.uses >= 3
            and row.score < RETIRE_SCORE
            and not bool(getattr(row, "pinned", False))
            and (row.source or "") != "seed"
            and recent_relevant == 0
        ):
            logger.info("retiring weak keyword %r (score %.2f)", row.keyword, row.score)
            # Keep the row as a tombstone: deleting it would let the curated
            # seed list re-add and retry the same dead keyword forever.
            row.status = "retired"

    db.commit()
    _prune(db, user_id=keywords[0].user_id if keywords else None)


def _prune(db: Session, user_id: int | None = None) -> None:
    stmt = select(SearchQuery).where(
        SearchQuery.status == "candidate", SearchQuery.pinned.is_(False)
    )
    if user_id is not None:
        stmt = stmt.where(SearchQuery.user_id == user_id)
    rows = list(db.scalars(stmt.order_by(SearchQuery.score.asc(), SearchQuery.uses.asc())))
    now = datetime.now(timezone.utc)

    for row in list(rows):
        if int(row.uses or 0) > 0 or row.created_at is None:
            continue
        created = row.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if now - created > timedelta(days=2):
            db.delete(row)
            rows.remove(row)

    overflow = len(rows) - MAX_ROWS
    for row in rows[: max(0, overflow)]:
        db.delete(row)
    db.commit()


def barren_keywords(db: Session, user_id: int | None = None) -> list[SearchQuery]:
    """Keywords that had a fair chance and produced nothing usable.

    "Nothing usable" means no relevant post, or no post at all, after several
    scans. Pinned keywords are never counted - the human wants them tried.
    """
    stmt = select(SearchQuery).where(
        SearchQuery.status.in_(("active", "candidate")),
        SearchQuery.pinned.is_(False),
        (
            (SearchQuery.uses >= BARREN_MIN_USES)
            & (SearchQuery.posts_relevant == 0)
            & (SearchQuery.posts_seen >= BARREN_MIN_SEEN)
        )
        | ((SearchQuery.uses >= BARREN_MIN_USES + 2) & (SearchQuery.posts_seen == 0)),
    )
    if user_id is not None:
        stmt = stmt.where(SearchQuery.user_id == user_id)
    return list(db.scalars(stmt.order_by(SearchQuery.uses.desc())).all())


def snapshot(db: Session, user_id: int | None = None) -> dict:
    stmt = select(SearchQuery)
    if user_id is not None:
        stmt = stmt.where(SearchQuery.user_id == user_id)
    rows = list(db.scalars(stmt.order_by(SearchQuery.score.desc())))
    return {
        "active": [
            {
                "keyword": row.keyword,
                "score": row.score,
                "uses": row.uses,
                "posts_seen": row.posts_seen,
                "posts_relevant": row.posts_relevant,
                "replies": getattr(row, "replies", 0),
                "pinned": bool(getattr(row, "pinned", False)),
            }
            for row in rows
            if row.status == "active"
        ],
        "testing": [
            {
                "keyword": row.keyword,
                "score": row.score,
                "uses": row.uses,
                "posts_seen": row.posts_seen,
                "posts_relevant": row.posts_relevant,
                "replies": getattr(row, "replies", 0),
                "pinned": bool(getattr(row, "pinned", False)),
            }
            for row in rows
            if row.status == "candidate"
        ][:12],
    }
