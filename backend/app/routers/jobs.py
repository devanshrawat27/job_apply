from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

import threading
from datetime import datetime, timezone

from app.agents import composer, job_filter
from app.database import SessionLocal, get_db
from app.deps import CurrentUser
from app.llm import LLMUnavailable
from app.models import ActionLog, DraftExample, JobPost, Resume
from app.schemas import ApproveIn, JobOut
from app.services import browser_chatgpt, email_accounts, limits, pipeline, tasks

router = APIRouter(prefix="/jobs", tags=["jobs"])

VALID_STATUSES = {
    "new",
    "rejected",
    "pending_approval",
    "queued",
    "sending",
    "sent",
    "failed",
    "skipped",
}


def _uid(user: CurrentUser) -> int | None:
    return user.id if user is not None else None


def _owned(db: Session, job_id: int, user: CurrentUser) -> JobPost:
    job = db.get(JobPost, job_id)
    uid = _uid(user)
    if job is None or (uid is not None and job.user_id != uid):
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.get("", response_model=list[JobOut])
def list_jobs(
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    has_link: bool = Query(default=False),
    open_only: bool = Query(default=False),
    sort: str | None = Query(default=None),
    limit: int = Query(default=100, le=300),
    user: CurrentUser = None,
    db: Session = Depends(get_db),
) -> list[JobPost]:
    uid = _uid(user)
    stmt = select(JobPost)
    if sort == "best":
        # Apply links: direct-hire posts (founders / individuals) are the ones
        # most likely to answer. Job boards and aggregators go last.
        founder = func.lower(JobPost.reason).like("%founder%") | func.lower(
            JobPost.reason
        ).like("%hiring directly%")
        stmt = stmt.order_by(
            case((founder, 0), else_=1),
            case((JobPost.author_type == "person", 0), else_=1),
            case((JobPost.contact_email != "", 0), else_=1),
            JobPost.relevance.desc(),
            JobPost.discovered_at.desc(),
            JobPost.id.desc(),
        )
    else:
        stmt = stmt.order_by(JobPost.discovered_at.desc(), JobPost.id.desc())
    if uid is not None:
        stmt = stmt.where(JobPost.user_id == uid)
    if status and status != "all":
        if status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"unknown status '{status}'")
        stmt = stmt.where(JobPost.status == status)
    if has_link:
        stmt = stmt.where(
            JobPost.apply_url.isnot(None),
            JobPost.apply_url != "",
            JobPost.link_dead.is_(False),
        )
    if open_only:
        stmt = stmt.where(JobPost.status.in_(pipeline.OPEN_LINK_STATUSES))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            func.lower(JobPost.content).like(like)
            | func.lower(JobPost.author_handle).like(like)
            | func.lower(JobPost.company).like(like)
        )
    return list(db.scalars(stmt.limit(limit)).all())


@router.get("/stats")
def job_stats(user: CurrentUser = None, db: Session = Depends(get_db)) -> dict:
    uid = _uid(user)
    stmt = select(JobPost.status, func.count(JobPost.id))
    if uid is not None:
        stmt = stmt.where(JobPost.user_id == uid)
    rows = db.execute(stmt.group_by(JobPost.status)).all()
    by_status = {status: count for status, count in rows}
    sent_stmt = select(func.count(JobPost.id)).where(JobPost.status == "sent")
    if uid is not None:
        sent_stmt = sent_stmt.where(JobPost.user_id == uid)
    sent = db.scalar(sent_stmt) or 0
    return {
        "by_status": by_status,
        "total": sum(by_status.values()),
        "sent": int(sent),
        "pending_approval": by_status.get("pending_approval", 0),
        "queued": by_status.get("queued", 0),
        "apply_links": pipeline.apply_link_count(db, uid),
    }


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int, user: CurrentUser = None, db: Session = Depends(get_db)) -> JobPost:
    return _owned(db, job_id, user)


@router.post("/{job_id}/decide", response_model=JobOut)
def decide(
    job_id: int, payload: ApproveIn, user: CurrentUser = None, db: Session = Depends(get_db)
) -> JobPost:
    job = _owned(db, job_id, user)
    if job.status in ("sent", "sending"):
        raise HTTPException(status_code=409, detail="this job is already sent or sending")
    return pipeline.approve(
        db,
        job,
        approved=payload.approved,
        reply_text=payload.reply_text,
        dm_text=payload.dm_text,
    )


@router.post("/{job_id}/send", response_model=JobOut)
def send_now(
    job_id: int,
    payload: ApproveIn | None = None,
    user: CurrentUser = None,
    db: Session = Depends(get_db),
) -> JobPost:
    job = _owned(db, job_id, user)
    if job.status in ("sent", "sending"):
        raise HTTPException(status_code=409, detail="this job is already sent or sending")

    payload = payload or ApproveIn(approved=True)

    settings_row = pipeline.get_settings_row(db, job.user_id)
    if job.outreach_method == "email" and not email_accounts.configured(db, job.user_id):
        raise HTTPException(
            status_code=409,
            detail="Email is not verified. Connect it in Settings, then try again.",
        )
    action = "email" if job.outreach_method == "email" else (
        "reply" if settings_row.use_public_reply else "dm"
    )
    state = limits.check(db, settings_row, action, ignore_gap=True)
    if not state.allowed:
        raise HTTPException(status_code=409, detail=state.reason)

    job = pipeline.approve(
        db,
        job,
        approved=True,
        reply_text=payload.reply_text,
        dm_text=payload.dm_text,
    )
    tasks.start("send", [job.id], user_id=job.user_id, force=True)
    db.refresh(job)
    return job


@router.post("/{job_id}/retry-dm", response_model=JobOut)
def retry_dm(job_id: int, user: CurrentUser = None, db: Session = Depends(get_db)) -> JobPost:
    """Retry when the last DM clearly did not land.

    `unknown` is never retried automatically - it needs a human. A skipped DM
    (chat did not render, follow blocked, passcode) is safe to retry.
    """
    job = _owned(db, job_id, user)
    if job.dm_status == "unknown":
        raise HTTPException(
            status_code=409,
            detail="the last DM outcome is unknown - check X manually before retrying",
        )
    if job.dm_status not in ("failed", "none", "skipped"):
        raise HTTPException(status_code=409, detail="the DM does not need a retry")

    job.status = "queued"
    job.dm_status = "none"
    job.last_error = ""
    db.commit()
    db.refresh(job)
    tasks.start("send", [job.id], user_id=job.user_id)
    return job


@router.post("/{job_id}/mark-applied", response_model=JobOut)
def mark_applied(
    job_id: int, user: CurrentUser = None, db: Session = Depends(get_db)
) -> JobPost:
    """The human applied through the post's link; close the loop."""
    job = _owned(db, job_id, user)

    job.status = "sent"
    job.sent_at = pipeline._now()
    job.decided_at = job.sent_at
    job.decision_reason = "applied manually through the link"
    db.add(
        ActionLog(
            user_id=job.user_id,
            job_id=job.id,
            action="apply",
            status="sent",
            target=(job.apply_url or job.post_url or "")[:300],
            content=job.role or "",
            detail="applied manually from the job link",
        )
    )
    db.commit()
    db.refresh(job)
    return job


@router.post("/{job_id}/report-fake", response_model=JobOut)
def report_fake(
    job_id: int, user: CurrentUser = None, db: Session = Depends(get_db)
) -> JobPost:
    """Mark a post as fake and remember the author so their posts are skipped."""
    job = _owned(db, job_id, user)
    uid = _uid(user)

    handle = (job.author_handle or "").lstrip("@")
    settings_row = pipeline.get_settings_row(db, uid)
    reported = list(settings_row.reported_handles or [])
    if handle and handle.lower() not in {str(h).lstrip("@").lower() for h in reported}:
        reported.append(handle)
        settings_row.reported_handles = reported

    job.status = "rejected"
    job.decided_at = pipeline._now()
    job.last_error = "reported as fake by you"

    # Hide other posts from the same account too.
    if handle:
        others_stmt = select(JobPost).where(
            JobPost.id != job.id,
            func.lower(JobPost.author_handle) == handle.lower(),
            JobPost.status.notin_(["sent", "sending"]),
        )
        if uid is not None:
            others_stmt = others_stmt.where(JobPost.user_id == uid)
        for other in db.scalars(others_stmt).all():
            other.status = "rejected"

    db.commit()
    db.refresh(job)
    return job


@router.delete("/{job_id}")
def delete_job(job_id: int, user: CurrentUser = None, db: Session = Depends(get_db)) -> dict:
    job = _owned(db, job_id, user)
    db.delete(job)
    db.commit()
    return {"deleted": True}


@router.post("/{job_id}/redraft", response_model=JobOut)
def redraft_job(job_id: int, user: CurrentUser = None, db: Session = Depends(get_db)) -> JobPost:
    """Rewrite a pending draft with ChatGPT when the API model is unavailable."""
    uid = _uid(user)
    job = _owned(db, job_id, user)
    profile = pipeline.get_profile(db, uid)
    if profile is None:
        raise HTTPException(status_code=400, detail="Set up your profile first")

    settings_row = pipeline.get_settings_row(db, uid)
    providers = pipeline.llm_providers(db, uid)
    use_browser = bool(settings_row.chatgpt_browser_enabled) and browser_chatgpt.connected(uid)

    examples_stmt = select(DraftExample).order_by(DraftExample.id.desc()).limit(3)
    if uid is not None:
        examples_stmt = examples_stmt.where(DraftExample.user_id == uid)
    examples = list(db.scalars(examples_stmt).all())

    try:
        draft = composer.compose(
            profile,
            job,
            examples,
            budget_s=120,
            providers=providers,
            browser_fallback=use_browser,
            browser_user_id=uid,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI
        raise HTTPException(status_code=502, detail=str(exc)[:300])

    job.reply_text = draft["reply_text"]
    job.dm_text = draft["dm_text"]
    # The stored email is the old one; rebuild it from the new text.
    job.email_subject = ""
    job.email_body = ""
    job.confidence = float(draft["confidence"])
    job.uncertainties = draft["uncertainties"]
    job.generic_draft = bool(draft.get("generic"))
    if job.status == "rejected":
        job.status = "pending_approval"
    job.decision_reason = (
        f"re-drafted with ChatGPT - confidence {job.confidence:.2f}, review before sending"
    )
    job.logs = [*(job.logs or []), job.decision_reason][-60:]
    db.commit()
    db.refresh(job)
    return job


class AIFilterIn(BaseModel):
    scope: str = Field(default="all", max_length=20)
    limit: int = Field(default=10, ge=1, le=20)
    force: bool = False


class EmailDraftIn(BaseModel):
    subject: str = Field(default="", max_length=300)
    body: str = Field(default="", max_length=8000)


class JobResumeIn(BaseModel):
    resume_id: int


@router.get("/{job_id}/email-preview")
def email_preview(
    job_id: int, user: CurrentUser = None, db: Session = Depends(get_db)
) -> dict:
    """Exactly what will be sent, so the human can read and edit it first."""
    job = _owned(db, job_id, user)
    if job.outreach_method != "email":
        raise HTTPException(status_code=400, detail="this post is not an email application")

    profile = pipeline.get_profile(db, job.user_id)
    subject, body = (
        pipeline._email_body(profile, job)
        if profile is not None
        else (f"Application: {job.role or 'role'}", job.dm_text or "")
    )
    if not (job.email_body or "").strip():
        job.email_subject = subject[:300]
        job.email_body = body
        db.commit()

    resumes = []
    stmt = select(Resume).where(Resume.user_id == job.user_id)
    for row in db.scalars(stmt.order_by(Resume.id)).all():
        resumes.append(
            {
                "id": row.id,
                "label": row.label or row.filename,
                "filename": row.filename,
            }
        )

    return {
        "to": job.contact_email,
        "subject": job.email_subject or subject,
        "body": job.email_body or body,
        "attachment": job.resume_label
        or (profile.resume_filename if profile is not None else ""),
        "resume_id": job.resume_id or 0,
        "resumes": resumes,
    }


@router.post("/{job_id}/email-draft")
def save_email_draft(
    job_id: int,
    payload: EmailDraftIn,
    user: CurrentUser = None,
    db: Session = Depends(get_db),
) -> dict:
    job = _owned(db, job_id, user)
    if payload.subject.strip():
        job.email_subject = payload.subject.strip()[:300]
    if payload.body.strip():
        job.email_body = payload.body
        job.dm_text = payload.body
    job.logs = [*(job.logs or []), "email edited by you"][-60:]
    db.commit()
    return {"ok": True, "subject": job.email_subject, "body": job.email_body}


@router.post("/{job_id}/resume", response_model=JobOut)
def set_job_resume(
    job_id: int,
    payload: JobResumeIn,
    user: CurrentUser = None,
    db: Session = Depends(get_db),
) -> JobPost:
    """Pick which of the uploaded resumes gets attached to this application."""
    job = _owned(db, job_id, user)
    resume = db.get(Resume, payload.resume_id)
    if resume is None or (job.user_id is not None and resume.user_id != job.user_id):
        raise HTTPException(status_code=404, detail="Resume not found")
    job.resume_id = resume.id
    job.resume_label = (resume.label or resume.filename)[:120]
    job.logs = [*(job.logs or []), f"resume attached: {job.resume_label}"][-60:]
    db.commit()
    db.refresh(job)
    return job


@router.post("/ai-filter")
def ai_filter(payload: AIFilterIn, user: CurrentUser = None, db: Session = Depends(get_db)) -> dict:
    """Reject Approvals / Apply-link posts that do not match the candidate.

    Call it repeatedly with ``limit``; each call reviews one batch and returns
    how many posts are still un-reviewed for that scope.
    """
    uid = _uid(user)
    if payload.scope not in ("pending", "apply_links", "all"):
        raise HTTPException(status_code=400, detail="scope must be pending, apply_links or all")

    settings_row = pipeline.get_settings_row(db, uid)
    providers = pipeline.llm_providers(db, uid)
    use_browser = bool(settings_row.chatgpt_browser_enabled) and browser_chatgpt.connected(uid)
    if not (providers or settings.llm_enabled or use_browser):
        raise HTTPException(status_code=400, detail="No AI is configured for this workspace")

    try:
        return job_filter.review_batch(
            db,
            uid,
            payload.scope,
            limit=payload.limit,
            force=payload.force,
            providers=providers,
            browser=use_browser,
        )
    except LLMUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:300])
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:300])


_AI_FILTER: dict[int | None, dict] = {}
_AI_FILTER_LOCK = threading.Lock()


class AIFilterStartIn(BaseModel):
    scope: str = "apply_links"
    force: bool = False


def _ai_state(user_id: int | None) -> dict:
    with _AI_FILTER_LOCK:
        return dict(
            _AI_FILTER.get(user_id)
            or {
                "running": False,
                "checked": 0,
                "rejected": 0,
                "remaining": 0,
                "error": "",
            }
        )


def _ai_filter_worker(user_id: int | None, scope: str, force: bool) -> None:
    db = SessionLocal()
    checked = 0
    rejected = 0
    remaining = 0
    error = ""
    try:
        for _ in range(200):
            settings_row = pipeline.get_settings_row(db, user_id)
            providers = pipeline.llm_providers(db, user_id)
            use_browser = bool(settings_row.chatgpt_browser_enabled) and browser_chatgpt.connected(
                user_id
            )
            result = job_filter.review_batch(
                db,
                user_id,
                scope,
                limit=5,
                force=force,
                providers=providers,
                browser=use_browser,
            )
            checked += int(result.get("checked") or 0)
            rejected += int(result.get("rejected") or 0)
            remaining = int(result.get("remaining") or 0)
            with _AI_FILTER_LOCK:
                _AI_FILTER[user_id] = {
                    "running": True,
                    "checked": checked,
                    "rejected": rejected,
                    "remaining": remaining,
                    "error": "",
                }
            if remaining == 0 or not result.get("checked"):
                break
    except Exception as exc:  # noqa: BLE001 - reported to the page
        error = str(exc)[:300]
    finally:
        with _AI_FILTER_LOCK:
            _AI_FILTER[user_id] = {
                "running": False,
                "checked": checked,
                "rejected": rejected,
                "remaining": remaining,
                "error": error,
            }
        db.close()


@router.post("/ai-filter/start")
def ai_filter_start(
    payload: AIFilterStartIn, user: CurrentUser = None, db: Session = Depends(get_db)
) -> dict:
    """Run the review in the background so a slow batch never kills the request."""
    uid = _uid(user)
    if payload.scope not in ("pending", "apply_links", "all"):
        raise HTTPException(status_code=400, detail="scope must be pending, apply_links or all")

    with _AI_FILTER_LOCK:
        current = _AI_FILTER.get(uid) or {}
        if current.get("running"):
            return dict(current)
        _AI_FILTER[uid] = {
            "running": True,
            "checked": 0,
            "rejected": 0,
            "remaining": job_filter.remaining(db, uid, payload.scope),
            "error": "",
        }

    threading.Thread(
        target=_ai_filter_worker,
        args=(uid, payload.scope, bool(payload.force)),
        name=f"ai-filter-{uid}",
        daemon=True,
    ).start()
    return _ai_state(uid)


@router.get("/ai-filter/status")
def ai_filter_status(user: CurrentUser = None) -> dict:
    return _ai_state(_uid(user))


@router.get("/ai-filter/remaining")
def ai_filter_remaining(
    scope: str = Query(default="all"),
    user: CurrentUser = None,
    db: Session = Depends(get_db),
) -> dict:
    return {"remaining": job_filter.remaining(db, _uid(user), scope)}
