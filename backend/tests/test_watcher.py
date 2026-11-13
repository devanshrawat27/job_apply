"""The background watcher: gathers activity and stores ChatGPT's verdict."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select

from app.agents import watcher
from app.database import SessionLocal
from app.models import ActionLog, Insight, JobPost, Run


def _reset():
    db = SessionLocal()
    for model in (Insight, ActionLog, JobPost, Run):
        db.execute(delete(model))
    db.commit()
    return db


def test_collect_summarises_scans_and_failures():
    db = _reset()
    run = Run(
        kind="scan",
        status="completed",
        started_at=datetime.now(timezone.utc),
        stats={
            "posts_seen": 60,
            "posts_new": 5,
            "relevant": 2,
            "rejected": 3,
            "feed_posts": 40,
            "queries": 3,
            "keywords": ["software engineer intern"],
        },
    )
    db.add(run)
    db.commit()

    job = JobPost(post_id="w1", post_url="", author_handle="someone", content="hiring")
    db.add(job)
    db.commit()
    db.add(
        ActionLog(
            job_id=job.id,
            action="dm",
            status="skipped",
            target="@someone",
            detail="Chat did not finish loading",
        )
    )
    db.commit()

    since = datetime.now(timezone.utc) - watcher.REPORT_AFTER
    data = watcher.collect(db, None, since)
    assert data["totals"]["seen"] == 60
    assert "dm:skipped=1" in data["outreach"]
    assert any("did not finish loading" in item for item in data["failures"])
    db.close()


def test_review_stores_a_report(monkeypatch):
    db = _reset()
    db.add(
        Run(
            kind="scan",
            status="completed",
            started_at=datetime.now(timezone.utc),
            stats={"posts_seen": 10, "posts_new": 1},
        )
    )
    db.commit()

    monkeypatch.setattr(
        watcher,
        "complete_json",
        lambda *a, **kw: {
            "health": "warning",
            "summary": "One DM failed while loading chat.",
            "problems": ["Chat did not finish loading"],
            "next_actions": ["Retry the DM"],
            "note_for_user": "Check the skipped DM.",
        },
    )

    result = watcher.review(db, None, providers=None, browser=False)
    assert result["health"] == "warning"
    assert watcher.latest(db, None) is not None
    assert watcher.needs_report(db, None) is False

    db.close()
