"""Incoming reply tracking + outcome-based keyword scoring."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select

from app.agents import inbox, query_lab
from app.database import SessionLocal
from app.models import ActionLog, JobPost, SearchQuery


def _reset():
    db = SessionLocal()
    for model in (ActionLog, JobPost, SearchQuery):
        db.execute(delete(model))
    db.commit()
    return db


def test_reply_marks_job_and_bumps_keyword(monkeypatch):
    db = _reset()
    job = JobPost(
        post_id="reply1",
        post_url="https://x.com/i/web/status/1",
        author_handle="hiringguy",
        content="hiring react dev",
        status="sent",
        dm_status="sent",
        sent_at=datetime.now(timezone.utc),
        query_text="react developer",
    )
    keyword = SearchQuery(
        keyword="react developer",
        status="active",
        posts_seen=10,
        posts_relevant=2,
        replies=0,
        score=0.2,
    )
    db.add_all([job, keyword])
    db.commit()

    monkeypatch.setattr(
        inbox.executor,
        "run_script",
        lambda *a, **kw: {
            "success": True,
            "code": "OK",
            "data": {
                "dms": [{"handle": "hiringguy", "text": "sure, send your resume", "incoming": True}],
                "mentions": [],
            },
        },
    )

    result = inbox.sync(db, None, {"auth_token": "a"})
    assert result["ok"] is True
    assert result["matched"] == 1

    db.refresh(job)
    assert job.incoming_reply_at is not None
    assert "resume" in job.incoming_reply_text

    db.refresh(keyword)
    assert keyword.replies == 1
    # relevance 2 + 2*1 reply, over 10 seen + 2
    assert keyword.score == round((2 + 2 + 0.5) / 12, 3)

    # A second run must not double count the same reply.
    assert inbox.sync(db, None, {"auth_token": "a"})["matched"] == 0
    db.close()


def test_score_values_replies_more_than_relevance():
    quiet = SearchQuery(posts_seen=10, posts_relevant=3, replies=0)
    talking = SearchQuery(posts_seen=10, posts_relevant=1, replies=3)
    assert query_lab._score(talking) > query_lab._score(quiet)


def test_inbox_ignores_our_own_last_message(monkeypatch):
    db = _reset()
    job = JobPost(
        post_id="reply2",
        post_url="https://x.com/i/web/status/2",
        author_handle="someone",
        content="hiring",
        status="sent",
        dm_status="sent",
        sent_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.commit()

    monkeypatch.setattr(
        inbox.executor,
        "run_script",
        lambda *a, **kw: {
            "success": True,
            "code": "OK",
            "data": {
                "dms": [{"handle": "someone", "text": "You: hello", "incoming": False}],
                "mentions": [],
            },
        },
    )
    assert inbox.sync(db, None, {"auth_token": "a"})["matched"] == 0
    db.refresh(job)
    assert job.incoming_reply_at is None
    db.close()
