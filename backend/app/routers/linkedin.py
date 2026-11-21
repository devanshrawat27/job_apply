from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import CurrentUser
from app.models import LinkedInAccount
from app.schemas import LinkedInAccountOut, LinkedInConnectIn
from app.services import linkedin_accounts

router = APIRouter(prefix="/linkedin", tags=["linkedin"])


def _uid(user: CurrentUser) -> int | None:
    return user.id if user is not None else None


def _to_out(account: LinkedInAccount) -> LinkedInAccountOut:
    return LinkedInAccountOut(
        id=account.id,
        email=account.email,
        display_name=account.display_name,
        vanity_name=account.vanity_name,
        status=account.status,
        has_session=bool(account.session_ciphertext),
        last_checked_at=account.last_checked_at,
    )


@router.get("", response_model=LinkedInAccountOut | None)
def read_account(user: CurrentUser = None, db: Session = Depends(get_db)):
    account = linkedin_accounts.active_account(db, _uid(user))
    return _to_out(account) if account else None


@router.post("/connect", response_model=LinkedInAccountOut)
def connect(
    payload: LinkedInConnectIn, user: CurrentUser = None, db: Session = Depends(get_db)
) -> LinkedInAccountOut:
    uid = _uid(user)
    existing = linkedin_accounts.active_account(db, uid)
    if existing is not None:
        db.delete(existing)
        db.commit()
    result = linkedin_accounts.connect_with_password(
        db,
        payload.email,
        payload.password,
        user_id=uid,
        verification_code=payload.verification_code,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or result.get("code"))
    account = linkedin_accounts.active_account(db, uid)
    if account is None:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail="LinkedIn account was not stored")
    return _to_out(account)


@router.delete("/{account_id}")
def disconnect(account_id: int, user: CurrentUser = None, db: Session = Depends(get_db)) -> dict:
    account = db.get(LinkedInAccount, account_id)
    uid = _uid(user)
    if account is None or (uid is not None and account.user_id != uid):
        raise HTTPException(status_code=404, detail="LinkedIn account not found")
    linkedin_accounts.disconnect(db, account)
    return {"deleted": True}
