"""Incoming reply tracking + outcome-based keyword scoring."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select

from app.agents import inbox, query_lab
from app.database import SessionLocal
from app.models import ActionLog, JobPost, SearchQuery, XAccount


def _reset():
    db = SessionLocal()
    for model in (ActionLog, JobPost, SearchQuery, XAccount):
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
        inbox.x_dm_api,
        "read_inbox",
        lambda *a, **kw: {
            "count": 1,
            "conversations": [
                {
                    "username": "hiringguy",
                    "messages": [{"sender": "hiringguy", "text": "sure, send your resume"}],
                }
            ],
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
    db.add(XAccount(username="dev", status="connected", dm_status="ok"))
    db.add(job)
    db.commit()

    monkeypatch.setattr(
        inbox.x_dm_api,
        "read_inbox",
        lambda *a, **kw: {
            "count": 1,
            "conversations": [
                {
                    "username": "someone",
                    "messages": [{"sender": "dev", "text": "You: hello"}],
                }
            ],
        },
    )
    assert inbox.sync(db, None, {"auth_token": "a"})["matched"] == 0
    db.refresh(job)
    assert job.incoming_reply_at is None
    db.close()


def test_read_inbox_picks_the_other_participant_not_ourselves(monkeypatch):
    from app.services import x_dm_api

    class _Response:
        status_code = 200

        def json(self):
            return {
                "inbox_initial_state": {
                    "users": {
                        "11111": {"id": 11111, "screen_name": "dev"},
                        "22222": {"id": 22222, "screen_name": "hiringguy"},
                    },
                    "conversations": {
                        "11111-22222": {
                            "participants": [{"user_id": "11111"}, {"user_id": "22222"}],
                            "sort_timestamp": "2",
                        }
                    },
                    "entries": [
                        {
                            "message": {
                                "conversation_id": "11111-22222",
                                "message_data": {
                                    "sender_id": "22222",
                                    "text": "sure, send your resume",
                                    "time": "1",
                                },
                            }
                        }
                    ],
                }
            }

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, *args, **kwargs):
            return _Response()

    monkeypatch.setattr(x_dm_api, "_client", lambda creds: _Client())
    data = x_dm_api.read_inbox({"twid": "u%3D11111"}, limit=5)
    conversation = data["conversations"][0]
    assert conversation["username"] == "hiringguy"
    assert conversation["messages"][0]["sender"] == "hiringguy"


def test_inbox_explains_when_xchat_messages_are_hidden(monkeypatch):
    db = _reset()
    db.add(XAccount(username="dev", status="connected", dm_status="ok"))
    db.commit()
    monkeypatch.setattr(
        inbox.x_dm_api,
        "read_inbox",
        lambda *a, **kw: {
            "count": 1,
            "conversations": [
                {
                    "username": "someone",
                    "messages": [{"sender": "dev", "text": "You: hello"}],
                }
            ],
        },
    )
    result = inbox.sync(db, None, {"auth_token": "a"})
    assert result["matched"] == 0
    assert "end-to-end encrypted" in result["note"]
    db.close()
