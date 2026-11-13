from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import CurrentUser
from app.models import Run
from app.schemas import RunOut
from app.services import limits, pipeline, scheduler, tasks
from app.utils.time import iso_utc

router = APIRouter(tags=["runs"])


def _uid(user: CurrentUser) -> int | None:
    return user.id if user is not None else None


@router.post("/runs/scan", response_model=RunOut)
def scan_now(user: CurrentUser = None, db: Session = Depends(get_db)) -> Run:
    uid = _uid(user)
    pipeline.get_settings_row(db, uid)
    if pipeline.get_profile(db, uid) is None:
        raise HTTPException(status_code=400, detail="Set up your profile first.")
    run = tasks.start("scan", user_id=uid)
    scheduler.trigger_now()
    return run


@router.post("/runs/send", response_model=RunOut)
def send_now(user: CurrentUser = None, db: Session = Depends(get_db)) -> Run:
    uid = _uid(user)
    stmt = select(Run.id).where(Run.status == "running", Run.kind == "send")
    if uid is not None:
        stmt = stmt.where(Run.user_id == uid)
    if db.scalar(stmt) is not None:
        raise HTTPException(status_code=409, detail="a send run is already in progress")
    return tasks.start("send", user_id=uid)


@router.get("/runs", response_model=list[RunOut])
def list_runs(
    limit: int = Query(default=40, le=200),
    user: CurrentUser = None,
    db: Session = Depends(get_db),
) -> list[Run]:
    uid = _uid(user)
    stmt = select(Run)
    if uid is not None:
        stmt = stmt.where(Run.user_id == uid)
    return list(db.scalars(stmt.order_by(Run.id.desc()).limit(limit)).all())


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: int, user: CurrentUser = None, db: Session = Depends(get_db)) -> Run:
    uid = _uid(user)
    run = db.get(Run, run_id)
    if run is None or (uid is not None and run.user_id != uid):
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.get("/dashboard")
def dashboard(user: CurrentUser = None, db: Session = Depends(get_db)) -> dict:
    uid = _uid(user)
    settings_row = pipeline.get_settings_row(db, uid)

    last_stmt = select(Run)
    scan_stmt = select(Run).where(Run.kind == "scan", Run.status == "completed")
    if uid is not None:
        last_stmt = last_stmt.where(Run.user_id == uid)
        scan_stmt = scan_stmt.where(Run.user_id == uid)

    last = db.scalar(last_stmt.order_by(Run.id.desc()))
    last_scan = db.scalar(scan_stmt.order_by(Run.id.desc()))
    agent = scheduler.status()
    # The in-memory timer resets on restart; fall back to the newest scan in the DB.
    if not agent.get("last_scan") and last_scan is not None:
        agent["last_scan"] = iso_utc(last_scan.finished_at)
    return {
        "agent": agent,
        "enabled": settings_row.enabled,
        "usage": limits.stats(db, settings_row),
        "pending_approvals": pipeline.pending_count(db, uid),
        "apply_links": pipeline.apply_link_count(db, uid),
        "last_run": (
            {
                "id": last.id,
                "kind": last.kind,
                "status": last.status,
                "stats": last.stats or {},
                "finished_at": iso_utc(last.finished_at),
            }
            if last is not None
            else None
        ),
    }
