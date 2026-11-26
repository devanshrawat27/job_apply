"""Incoming reply tracking.

The agent sends public replies and DMs; this module checks the X inbox and
notifications for answers, marks the matching job as replied and feeds the
keyword lab with the real outcome (a reply, not just "looks relevant").
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents import query_lab
from app.models import ActionLog, JobPost, XAccount
from app.services import x_dm_api

logger = logging.getLogger(__name__)

REPLY_STATUSES = ("sent", "skipped", "failed", "retry_wait")


def _match_job(db: Session, user_id: int | None, handle: str) -> JobPost | None:
    handle = (handle or "").strip().lstrip("@").lower()
    if not handle:
        return None
    stmt = (
        select(JobPost)
        .where(
            func.lower(JobPost.author_handle) == handle,
            JobPost.status.in_(REPLY_STATUSES),
            JobPost.incoming_reply_at.is_(None),
        )
        .order_by(JobPost.sent_at.desc(), JobPost.id.desc())
        .limit(1)
    )
    if user_id is not None:
        stmt = stmt.where(JobPost.user_id == user_id)
    else:
        stmt = stmt.where(JobPost.user_id.is_(None))
    return db.scalar(stmt)


def _mark(job: JobPost, text: str, kind: str) -> None:
    job.incoming_reply_at = datetime.now(timezone.utc)
    job.incoming_reply_text = (text or "")[:1000]
    job.logs = [*(job.logs or []), f"{kind} received from @{job.author_handle}"][-60:]


def sync(db: Session, user_id: int | None, creds: dict) -> dict:
    """Read the DM inbox through X's own endpoint and mark matching jobs."""
    try:
        payload = x_dm_api.read_inbox(creds, limit=40)
    except (x_dm_api.DMUnavailable, x_dm_api.DMError) as exc:
        return {"ok": False, "error": str(exc), "matched": 0}

    own_stmt = select(XAccount.username)
    if user_id is not None:
        own_stmt = own_stmt.where(XAccount.user_id == user_id)
    own = str(db.scalar(own_stmt) or "").lstrip("@").lower()

    dms: list[dict] = []
    for conversation in payload.get("conversations") or []:
        handle = str(conversation.get("username") or "").strip().lstrip("@")
        if not handle:
            continue
        incoming = [
            message
            for message in (conversation.get("messages") or [])
            if str(message.get("sender") or "").lstrip("@").lower() not in ("", own)
        ]
        if not incoming:
            continue
        last = incoming[-1]
        if not str(last.get("text") or "").strip():
            continue
        dms.append({"handle": handle, "text": str(last.get("text") or ""), "incoming": True})

    # Mentions/replies on public posts need a separate timeline search; the DM
    # inbox is the reliable API path and covers direct answers.
    mentions: list[dict] = []

    matched = 0
    seen_handles: set[str] = set()

    for kind, items in (("DM reply", dms), ("public reply", mentions)):
        for item in items:
            handle = str(item.get("handle") or "").strip().lstrip("@").lower()
            if not handle or handle in seen_handles:
                continue
            job = _match_job(db, user_id, handle)
            if job is None:
                continue

            _mark(job, str(item.get("text") or ""), kind)
            db.add(
                ActionLog(
                    user_id=job.user_id,
                    job_id=job.id,
                    action="reply_in",
                    status="sent",
                    target=f"@{handle}",
                    content="",
                    detail=f"{kind}: {str(item.get('text') or '')[:400]}",
                )
            )
            if job.query_text:
                query_lab.bump_reply(db, job.query_text, job.user_id)
            seen_handles.add(handle)
            matched += 1
            logger.info("inbox: %s from @%s matched job %s", kind, handle, job.id)

    db.commit()
    return {
        "ok": True,
        "matched": matched,
        "dms": len(dms),
        "mentions": len(mentions),
    }
