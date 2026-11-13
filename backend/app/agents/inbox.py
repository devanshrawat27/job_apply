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
from app.models import ActionLog, JobPost
from app.services import executor

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
    """Read the inbox once and mark any matching jobs as replied."""
    result = executor.run_script("check_inbox", {}, creds=creds)
    if not result.get("success"):
        return {
            "ok": False,
            "error": str(result.get("error") or result.get("code") or "inbox check failed"),
            "matched": 0,
        }

    data = result.get("data") or {}
    dms = [item for item in (data.get("dms") or []) if item.get("incoming")]
    mentions = [item for item in (data.get("mentions") or []) if item.get("incoming")]

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
