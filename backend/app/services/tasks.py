"""Run a pipeline pass in the background so the API never blocks for minutes."""

from __future__ import annotations

import logging
import threading

from app.database import SessionLocal
from app.models import Run
from app.services import pipeline

logger = logging.getLogger(__name__)


def _worker(run_id: int, kind: str, job_ids: list[int] | None, user_id: int | None) -> None:
    db = SessionLocal()
    try:
        run = db.get(Run, run_id)
        if run is None:
            return
        if kind == "scan":
            pipeline.scan(db, manual=True, run=run, user_id=user_id)
        else:
            pipeline.send_batch(db, job_ids=job_ids, run=run, user_id=user_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("background %s failed", kind)
        run = db.get(Run, run_id)
        if run is not None:
            run.status = "failed"
            run.error = str(exc)
            db.commit()
    finally:
        db.close()


def start(kind: str, job_ids: list[int] | None = None, user_id: int | None = None) -> Run:
    """Create the run row, then execute the pass on a daemon thread."""
    db = SessionLocal()
    try:
        run = Run(kind=kind, status="running", user_id=user_id)
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
        snapshot = run
        db.expunge(snapshot)
    finally:
        db.close()

    threading.Thread(
        target=_worker,
        args=(run_id, kind, job_ids, user_id),
        name=f"{kind}-run-{run_id}",
        daemon=True,
    ).start()
    return snapshot
