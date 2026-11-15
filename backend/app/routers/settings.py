from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import CurrentUser
from app.schemas import SettingsIn, SettingsOut
from app.security import decrypt_credentials
from app.services import email_accounts, executor, limits, pipeline, scheduler

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
        "email_configured": email_accounts.configured(db, uid),
    }


class EmailIn(BaseModel):
    host: str = Field(min_length=1, max_length=200)
    port: int = Field(default=587, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=400)
    from_address: str = Field(default="", max_length=200)
    starttls: bool = True


class EmailTestIn(BaseModel):
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    starttls: bool = True


@router.get("/email")
def read_email(user: CurrentUser = None, db: Session = Depends(get_db)) -> dict:
    return email_accounts.public(db, _uid(user))


@router.put("/email")
def save_email(payload: EmailIn, user: CurrentUser = None, db: Session = Depends(get_db)) -> dict:
    email_accounts.save(
        db,
        _uid(user),
        host=payload.host,
        port=payload.port,
        username=payload.username,
        password=payload.password,
        from_address=payload.from_address,
        starttls=payload.starttls,
    )
    return email_accounts.public(db, _uid(user))


@router.post("/email/test")
def test_email(
    payload: EmailTestIn | None = None,
    user: CurrentUser = None,
    db: Session = Depends(get_db),
) -> dict:
    uid = _uid(user)
    cfg = email_accounts.config(db, uid)
    provided = payload is not None and bool(payload.host and payload.username and payload.password)
    if provided:
        cfg = {
            "host": payload.host,
            "port": payload.port,
            "username": payload.username,
            "password": payload.password,
            "starttls": payload.starttls,
        }
    if cfg is None:
        # The saved row may not be verified yet; test it directly.
        row = email_accounts.get(db, uid)
        if row is None:
            raise HTTPException(status_code=400, detail="Connect an email address first")
        creds = decrypt_credentials(row.password_ciphertext) or {}
        cfg = {
            "host": row.host,
            "port": row.port,
            "username": row.username,
            "password": creds.get("password", ""),
            "starttls": row.starttls,
        }
    result = email_accounts.test_connection(cfg)
    if not provided:
        email_accounts.mark_verified(db, uid, bool(result.get("ok")))
    return result


@router.delete("/email")
def delete_email(user: CurrentUser = None, db: Session = Depends(get_db)) -> dict:
    return {"deleted": email_accounts.delete(db, _uid(user))}
