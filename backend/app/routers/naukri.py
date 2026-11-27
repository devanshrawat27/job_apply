from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import CurrentUser
from app.models import NaukriAccount
from app.schemas import NaukriAccountOut, NaukriConnectIn
from app.services import naukri_accounts, pipeline

router = APIRouter(prefix="/naukri", tags=["naukri"])


def _uid(user: CurrentUser) -> int | None:
    return user.id if user is not None else None


def _to_out(account: NaukriAccount) -> NaukriAccountOut:
    return NaukriAccountOut(
        id=account.id,
        email=account.email,
        display_name=account.display_name,
        status=account.status,
        has_session=bool(account.session_ciphertext),
        last_checked_at=account.last_checked_at,
    )


@router.get("", response_model=NaukriAccountOut | None)
def read_account(user: CurrentUser = None, db: Session = Depends(get_db)):
    account = naukri_accounts.active_account(db, _uid(user))
    return _to_out(account) if account else None


@router.post("/connect", response_model=NaukriAccountOut)
def connect(
    payload: NaukriConnectIn, user: CurrentUser = None, db: Session = Depends(get_db)
) -> NaukriAccountOut:
    """Open a real Chrome window for the human to sign in to Naukri once."""
    uid = _uid(user)
    result = naukri_accounts.connect_manual(db, email=payload.email, user_id=uid)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or result.get("code"))
    account = naukri_accounts.active_account(db, uid)
    if account is None:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail="Naukri account was not stored")
    return _to_out(account)


@router.post("/window")
def open_window(
    payload: dict | None = None,
    user: CurrentUser = None,
    db: Session = Depends(get_db),
) -> dict:
    """Bring the logged-in Naukri Chrome window on screen."""
    account = naukri_accounts.active_account(db, _uid(user))
    if account is None:
        raise HTTPException(status_code=409, detail="Connect Naukri first")
    requested = str((payload or {}).get("url") or "").strip()
    if requested and not requested.startswith("https://www.naukri.com/"):
        raise HTTPException(status_code=400, detail="only naukri.com URLs can be opened")
    result = naukri_accounts.open_window(requested or "https://www.naukri.com/")
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error") or "could not open Chrome")
    return {"ok": True}


@router.post("/refresh-resume")
def refresh_resume(user: CurrentUser = None, db: Session = Depends(get_db)) -> dict:
    """Rename the Naukri resume with today's date and upload it again."""
    uid = _uid(user)
    account = naukri_accounts.active_account(db, uid)
    if account is None:
        raise HTTPException(status_code=409, detail="Connect Naukri first")
    profile = pipeline.get_profile(db, uid)
    if profile is None:
        raise HTTPException(status_code=400, detail="complete your profile first")
    result = naukri_accounts.refresh_resume(db, account, profile)
    if not result.get("ok"):
        raise HTTPException(
            status_code=500,
            detail=result.get("error") or "Could not refresh the resume",
        )
    return result


@router.delete("/{account_id}")
def disconnect(account_id: int, user: CurrentUser = None, db: Session = Depends(get_db)) -> dict:
    account = db.get(NaukriAccount, account_id)
    uid = _uid(user)
    if account is None or (uid is not None and account.user_id != uid):
        raise HTTPException(status_code=404, detail="Naukri account not found")
    naukri_accounts.disconnect(db, account)
    return {"deleted": True}
