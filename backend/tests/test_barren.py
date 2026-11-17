"""Barren keywords: plenty of scans, nothing usable to show for them."""

from __future__ import annotations

from sqlalchemy import delete

from app.agents import query_lab
from app.database import SessionLocal
from app.models import SearchQuery

USER = 98


def test_barren_keywords_ignore_good_and_pinned_ones():
    db = SessionLocal()
    try:
        db.execute(delete(SearchQuery).where(SearchQuery.user_id == USER))
        db.add_all(
            [
                SearchQuery(
                    user_id=USER,
                    keyword="ai engineer",
                    status="active",
                    uses=5,
                    posts_seen=60,
                    posts_relevant=0,
                    score=0.0,
                ),
                SearchQuery(
                    user_id=USER,
                    keyword="sde",
                    status="active",
                    uses=9,
                    posts_seen=80,
                    posts_relevant=10,
                    score=0.7,
                ),
                SearchQuery(
                    user_id=USER,
                    keyword="hiring developers",
                    status="active",
                    pinned=True,
                    uses=9,
                    posts_seen=80,
                    posts_relevant=0,
                    score=0.0,
                ),
            ]
        )
        db.commit()

        names = [row.keyword for row in query_lab.barren_keywords(db, USER)]
        assert names == ["ai engineer"]
    finally:
        db.execute(delete(SearchQuery).where(SearchQuery.user_id == USER))
        db.commit()
        db.close()
