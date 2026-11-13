"""Outreach timeline: what the agent actually sent, to whom, and when."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import CurrentUser
from app.models import ActionLog, JobPost
from app.utils.time import iso_utc

router = APIRouter(prefix="/outreach", tags=["outreach"])


@router.get("")
def list_outreach(
    limit: int = Query(default=100, le=300),
    action: str | None = Query(default=None),
    user: CurrentUser = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    uid = user.id if user is not None else None

    stmt = select(ActionLog).order_by(ActionLog.id.desc()).limit(limit)
    if uid is not None:
        stmt = stmt.where(ActionLog.user_id == uid)
    if action and action != "all":
        stmt = (
            select(ActionLog)
            .where(ActionLog.action == action)
            .order_by(ActionLog.id.desc())
            .limit(limit)
        )
        if uid is not None:
            stmt = stmt.where(ActionLog.user_id == uid)

    rows = list(db.scalars(stmt).all())
    job_ids = {row.job_id for row in rows}
    jobs = (
        {job.id: job for job in db.scalars(select(JobPost).where(JobPost.id.in_(job_ids))).all()}
        if job_ids
        else {}
    )

    out: list[dict] = []
    for row in rows:
        job = jobs.get(row.job_id)
        out.append(
            {
                "id": row.id,
                "action": row.action,
                "status": row.status,
                "target": row.target,
                "content": row.content,
                "detail": row.detail,
                "created_at": iso_utc(row.created_at),
                "job_id": row.job_id,
                "post_url": job.post_url if job else "",
                "author_handle": job.author_handle if job else "",
                "company": job.company if job else "",
                "role": job.role if job else "",
                "outreach_method": job.outreach_method if job else "",
            }
        )
    return out


@router.get("/summary")
def outreach_summary(user: CurrentUser = None, db: Session = Depends(get_db)) -> dict:
    from sqlalchemy import func

    uid = user.id if user is not None else None
    stmt = select(ActionLog.action, ActionLog.status, func.count(ActionLog.id))
    if uid is not None:
        stmt = stmt.where(ActionLog.user_id == uid)
    rows = db.execute(stmt.group_by(ActionLog.action, ActionLog.status)).all()

    totals = {"reply": 0, "dm": 0, "email": 0, "follow": 0, "apply": 0}
    for action, status, count in rows:
        # Only real deliveries count. A "skipped" DM was never sent.
        if action in totals and status == "sent":
            totals[action] += count
    return totals
