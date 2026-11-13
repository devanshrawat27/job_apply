from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import CurrentUser
from app.schemas import SettingsIn, SettingsOut
from app.services import executor, limits, pipeline, scheduler

router = APIRouter(prefix="/settings", tags=["settings"])


def _uid(user: CurrentUser) -> int | None:
    return user.id if user is not None else None


@router.get("", response_model=SettingsOut)
def read_settings(user: CurrentUser = None, db: Session = Depends(get_db)):
    return pipeline.get_settings_row(db, _uid(user))


@router.put("", response_model=SettingsOut)
def update_settings(
    payload: SettingsIn, user: CurrentUser = None, db: Session = Depends(get_db)
):
    row = pipeline.get_settings_row(db, _uid(user))
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.get("/status")
def agent_status(user: CurrentUser = None, db: Session = Depends(get_db)) -> dict:
    uid = _uid(user)
    row = pipeline.get_settings_row(db, uid)
    return {
        "agent": scheduler.status(),
        "usage": limits.stats(db, row),
        "pending_approvals": pipeline.pending_count(db, uid),
        "executor": executor.executor_health(),
    }
