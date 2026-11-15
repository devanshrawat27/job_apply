"""Purpose threads: one conversation per task, resumed across runs."""

from __future__ import annotations

from app.database import SessionLocal
from app.services import chat_threads


def test_thread_is_created_once_and_reused():
    db = SessionLocal()
    try:
        first = chat_threads.ensure(db, 1, "fit")
        second = chat_threads.ensure(db, 1, "fit")
        assert first.id == second.id
        assert first.title == "JobPilot · Job fit checks"
        assert first.url == ""
    finally:
        db.close()


def test_record_keeps_url_and_counts_messages():
    db = SessionLocal()
    try:
        chat_threads.record(
            db,
            1,
            "draft",
            url="https://chatgpt.com/c/abc",
            project_url="https://chatgpt.com/g/g-p-1/project",
        )
        row = chat_threads.record(db, 1, "draft", url="https://chatgpt.com/c/abc")
        assert row.url == "https://chatgpt.com/c/abc"
        assert row.messages == 2
        assert row.last_used_at is not None
    finally:
        db.close()


def test_overview_lists_every_purpose_in_order():
    db = SessionLocal()
    try:
        data = chat_threads.overview(
            db, 1, project_url="https://chatgpt.com/g/g-p-1/project"
        )
        assert data["project_url"].endswith("/project")
        assert [t["purpose"] for t in data["threads"]] == list(chat_threads.PURPOSES)
        assert all("label" in thread for thread in data["threads"])
    finally:
        db.close()


def test_reset_forgets_links_after_disconnect():
    db = SessionLocal()
    try:
        chat_threads.record(db, 2, "watch", url="https://chatgpt.com/c/w")
        chat_threads.reset(db, 2)
        data = chat_threads.overview(db, 2)
        assert all(thread["url"] == "" for thread in data["threads"])
    finally:
        db.close()
