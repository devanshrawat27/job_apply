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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.discovery import HIRING_TERMS, MAX_QUERY_LEN, selected_roles
from app.agents import keywords as keyword_sets
from app.models import Profile, SearchQuery

logger = logging.getLogger(__name__)

MAX_KEYWORDS_PER_SCAN = 4
PINNED_PER_SCAN = 3
ACTIVATE_SCORE = 0.30
RETIRE_SCORE = 0.08
MAX_ROWS = 80

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
    """Senior-level keywords are skipped for junior candidates."""
    if not is_junior_profile(profile):
        return True
    lowered = (keyword or "").lower().strip()
    return not any(signal in lowered for signal in SENIOR_KEYWORD_SIGNALS)


def keyword_pool(profile: Profile) -> tuple[str, ...]:
    return keyword_sets.keyword_pool()


def seed_keywords(profile: Profile) -> list[str]:
    """Roles the human picked, plus a few concrete skill words."""
    seeds = selected_roles(profile)[:3]
    seen = {seed.lower() for seed in seeds}

    for skill in (profile.skills or [])[:6]:
        clean = str(skill).strip()
        if len(clean) < 3:
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


def select_keywords(db: Session, profile: Profile, user_id: int | None = None) -> list[SearchQuery]:
    """Pick up to 3 keywords for this scan and mark them as used."""
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

    # A fresher profile should never burn scans on "founding engineer" style
    # keywords. Retire them once, then they stay out of the candidate list.
    if junior:
        for row in rows:
            if row.status in ("active", "candidate") and not keyword_fits_profile(row.keyword, profile):
                row.status = "retired"
                logger.info("retiring senior keyword %r for a junior profile", row.keyword)
        db.flush()

    for keyword in seed_keywords(profile):
        if keyword.lower() not in known and keyword_fits_profile(keyword, profile):
            _add(db, rows, known, keyword, user_id, source="seed")

    # Make sure the curated roles exist as candidates so the exploration slot
    # rotates through them instead of only ever trying profile roles.
    for keyword in CURATED_KEYWORDS:
        if keyword.lower() not in known and keyword_fits_profile(keyword, profile):
            _add(db, rows, known, keyword, user_id, source="curated")
    db.flush()

    active = [row for row in rows if row.status == "active"][:2]
    pinned_rows = sorted(
        [
            row
            for row in rows
            if row.pinned and row.status in ("active", "candidate")
        ],
        key=lambda row: (row.last_used_at is not None, row.last_used_at or datetime.min, row.uses, row.id),
    )
    # Try never-used keywords first, so the curated roles actually get a turn;
    # then fall back to proven-but-not-active ones by score.
    untried = sorted(
        [row for row in rows if row.status == "candidate" and not row.uses],
        key=lambda row: row.id,
    )
    tried = sorted(
        [row for row in rows if row.status == "candidate" and row.uses],
        key=lambda row: (-row.score, row.uses, row.id),
    )
    candidates = untried + tried

    # Fresh exploration pool, shared by both scheduling modes below.
    fresh = [row for row in candidates if row.uses == 0]
    analyst_new = [row for row in fresh if (row.source or "") == "analyst"]
    hiring_phrases = {term.lower() for term in keyword_sets.HIRING_PHRASE_KEYWORDS}
    hiring = [row for row in fresh if row.keyword.lower() in hiring_phrases]
    parity = sum(int(row.uses or 0) for row in rows) % 2
    exploration_pool = (
        (analyst_new or hiring or fresh) if parity == 0 else (hiring or analyst_new or fresh)
    )

    if pinned_rows:
        # Pinned keywords are guaranteed work: rotate the least recently used
        # ones, then add one exploration keyword.
        chosen = list(pinned_rows[:PINNED_PER_SCAN])
        for row in active + candidates:
            if len(chosen) >= MAX_KEYWORDS_PER_SCAN:
                break
            if row not in chosen:
                chosen.append(row)
                break
        if exploration_pool:
            pick = exploration_pool[0]
            if pick not in chosen:
                chosen.append(pick)
    elif active:
        chosen = list(active)
        # One exploration slot. Alternate between ChatGPT's suggestions and
        # plain hiring phrases so neither kind starves the other.
        if exploration_pool:
            chosen.append(exploration_pool[0])
    else:
        # Cold start: try several candidates at once so we get signal fast.
        chosen = candidates[:MAX_KEYWORDS_PER_SCAN]

    if len(chosen) < MAX_KEYWORDS_PER_SCAN:
        for keyword in keyword_pool(profile):
            if keyword.lower() in known:
                continue
            if not keyword_fits_profile(keyword, profile):
                continue
            chosen.append(_add(db, rows, known, keyword, user_id, source="pool"))
            if len(chosen) >= MAX_KEYWORDS_PER_SCAN:
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

        if row.uses >= 2 and row.score >= ACTIVATE_SCORE:
            row.status = "active"
        elif (
            row.uses >= 3
            and row.score < RETIRE_SCORE
            and not bool(getattr(row, "pinned", False))
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
    overflow = len(rows) - MAX_ROWS
    for row in rows[: max(0, overflow)]:
        db.delete(row)
    db.commit()


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
