"""ChatGPT project and the purpose threads inside it.

Every agent task talks to one long-lived conversation instead of opening a new
chat each time:

    fit       job-fit screen
    draft     reply / DM drafts
    watch     activity reports
    keywords  search keyword review

Resuming the same thread is what gives ChatGPT the context of what it already
judged or wrote. Threads live in the user's "JobPilot" project so the human can
open the same conversation from ChatGPT and see exactly what happened.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChatThread

PROJECT_NAME = "JobPilot"

# Order matters: this is the order shown in Settings.
PURPOSES: dict[str, str] = {
    "fit": "Job fit checks",
    "draft": "Application drafts",
    "watch": "Agent activity reports",
    "keywords": "Search keywords",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def title_for(purpose: str) -> str:
    label = PURPOSES.get(purpose, purpose)
    # Plain ASCII: the title is typed into ChatGPT, and a "·" comes back mangled.
    return f"{PROJECT_NAME} - {label}"


def _scope(stmt, user_id: int | None):
    if user_id is None:
        return stmt.where(ChatThread.user_id.is_(None))
    return stmt.where(ChatThread.user_id == user_id)


def get(db: Session, user_id: int | None, purpose: str) -> ChatThread | None:
    return db.scalar(_scope(select(ChatThread), user_id).where(ChatThread.purpose == purpose).limit(1))


def ensure(db: Session, user_id: int | None, purpose: str) -> ChatThread:
    row = get(db, user_id, purpose)
    if row is not None:
        return row
    row = ChatThread(
        user_id=user_id,
        purpose=purpose,
        title=title_for(purpose),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def record(
    db: Session,
    user_id: int | None,
    purpose: str,
    *,
    url: str = "",
    project_url: str = "",
) -> ChatThread:
    row = ensure(db, user_id, purpose)
    if url:
        row.url = url[:500]
    if project_url:
        row.project_url = project_url[:500]
    row.messages = int(row.messages or 0) + 1
    row.last_used_at = _now()
    db.commit()
    db.refresh(row)
    return row


def clear_url(db: Session, user_id: int | None, purpose: str) -> None:
    """Forget a conversation that no longer opens (deleted in ChatGPT)."""
    row = get(db, user_id, purpose)
    if row is None:
        return
    row.url = ""
    db.commit()


def reset(db: Session, user_id: int | None) -> None:
    """Drop every stored thread, e.g. after the ChatGPT account is disconnected."""
    for row in db.scalars(_scope(select(ChatThread), user_id)).all():
        db.delete(row)
    db.commit()


def overview(db: Session, user_id: int | None, project_url: str = "") -> dict:
    rows = {
        row.purpose: row
        for row in db.scalars(_scope(select(ChatThread), user_id)).all()
    }
    threads = []
    for purpose, label in PURPOSES.items():
        row = rows.get(purpose)
        threads.append(
            {
                "purpose": purpose,
                "label": label,
                "title": row.title if row else title_for(purpose),
                "url": row.url if row else "",
                "messages": int(row.messages or 0) if row else 0,
                "last_used_at": row.last_used_at if row else None,
            }
        )
    return {"project_url": project_url, "threads": threads}
