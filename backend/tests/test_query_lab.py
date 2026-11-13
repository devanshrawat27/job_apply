"""The keyword lab: try keywords, keep the winners, drop the losers."""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from app.agents import query_lab
from app.database import SessionLocal
from app.models import Profile, SearchQuery


@pytest.fixture()
def db():
    session = SessionLocal()
    session.execute(delete(SearchQuery))
    session.execute(delete(Profile))
    session.commit()

    session.add(
        Profile(
            id=1,
            full_name="Dev",
            job_title="Full Stack Developer",
            target_roles=["Frontend Developer"],
            skills=["react", "node.js", "python"],
            domain="tech",
            experience_months=3,
        )
    )
    session.commit()
    yield session
    session.close()


def test_seeds_come_from_roles_and_skills(db):
    seeds = query_lab.seed_keywords(db.get(Profile, 1))
    assert "Full Stack Developer" in seeds
    assert "Frontend Developer" in seeds
    assert any(seed.lower() in {"react", "node.js", "python"} for seed in seeds)


def test_cold_start_tries_several_keywords(db):
    keywords = query_lab.select_keywords(db, db.get(Profile, 1))
    assert len(keywords) == query_lab.MAX_KEYWORDS_PER_SCAN
    assert all(row.uses == 1 for row in keywords)
    assert len({row.keyword for row in keywords}) == query_lab.MAX_KEYWORDS_PER_SCAN


def test_good_keyword_becomes_active_and_bad_one_is_retired(db):
    keywords = query_lab.select_keywords(db, db.get(Profile, 1))
    winner, loser = keywords[0], keywords[1]
    winner.uses = 2  # it has now been tried twice
    loser.uses = 1

    # Winner: 10 posts read, 4 relevant. Loser: 10 read, 0 relevant.
    query_lab.record_results(
        db,
        keywords,
        {
            winner.keyword: {"seen": 10, "relevant": 4},
            loser.keyword: {"seen": 10, "relevant": 0},
            keywords[2].keyword: {"seen": 10, "relevant": 1},
        },
    )

    db.refresh(winner)
    assert winner.status == "active"
    assert winner.score >= query_lab.ACTIVATE_SCORE

    # Run twice more so the retire rule (uses >= 3) kicks in.
    for _ in range(2):
        rows = [row for row in db.scalars(select(SearchQuery)).all() if row.keyword == loser.keyword]
        for row in rows:
            row.uses += 1
        query_lab.record_results(db, rows, {loser.keyword: {"seen": 10, "relevant": 0}})

    remaining = {row.keyword: row for row in db.scalars(select(SearchQuery)).all()}
    assert remaining[loser.keyword].status == "retired"
    assert winner.keyword in remaining

    # A retired keyword is never picked again, and is not re-added by the
    # curated seed list.
    chosen = query_lab.select_keywords(db, db.get(Profile, 1))
    assert loser.keyword not in {row.keyword for row in chosen}
    assert sum(1 for row in db.scalars(select(SearchQuery)).all() if row.keyword == loser.keyword) == 1


def test_active_keywords_are_reused(db, monkeypatch):
    keywords = query_lab.select_keywords(db, db.get(Profile, 1))
    winner = keywords[0]
    winner.status = "active"
    winner.score = 0.9
    winner.uses = 5
    db.commit()

    chosen = query_lab.select_keywords(db, db.get(Profile, 1))
    assert winner.keyword in {row.keyword for row in chosen}


def test_wrap_query_contains_filters():
    from app.models import AgentSettings

    query = query_lab.wrap_query("React Developer", AgentSettings(id=1, lookback_hours=24))
    assert "React Developer" in query
    assert "hiring" in query.lower()
    assert "-filter:replies" in query
    assert "since:" in query


def test_snapshot_shape(db):
    query_lab.select_keywords(db, db.get(Profile, 1))
    snap = query_lab.snapshot(db)
    assert set(snap) == {"active", "testing"}
    assert len(snap["testing"]) >= 1


def test_curated_roles_enter_the_pool(db):
    query_lab.select_keywords(db, db.get(Profile, 1))
    known = {row.keyword.lower() for row in db.scalars(select(SearchQuery)).all()}
    for keyword in ("sde intern", "full stack intern", "junior developer", "we are hiring", "hiring interns"):
        assert keyword in known
    for senior in ("founding engineer", "first technical hire"):
        assert senior not in known


def test_pinned_keywords_are_never_retired(db):
    row = SearchQuery(
        keyword="hiring engineers",
        status="candidate",
        pinned=True,
        uses=5,
        posts_seen=40,
        posts_relevant=0,
        score=0.0,
    )
    db.add(row)
    db.commit()

    query_lab.record_results(
        db, [row], {"hiring engineers": {"seen": 10, "relevant": 0}}
    )
    db.refresh(row)
    assert row.status != "retired"
    assert row.pinned is True


def test_untried_keywords_are_tried_before_used_ones(db):
    # A used-but-mediocre keyword must not block a never-tried curated one.
    db.add(
        SearchQuery(
            keyword="frontend developer",
            status="candidate",
            uses=9,
            posts_seen=40,
            posts_relevant=9,
            score=0.21,
        )
    )
    db.commit()

    chosen = query_lab.select_keywords(db, db.get(Profile, 1))
    names = {row.keyword.lower() for row in chosen}
    assert "frontend developer" not in names
    assert len(chosen) >= 3
