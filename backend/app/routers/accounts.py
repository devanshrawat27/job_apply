from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import CurrentUser
from app.models import XAccount
from app.schemas import AccountOut, ConnectIn, DmPasscodeIn
from app.services import accounts

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _uid(user: CurrentUser) -> int | None:
    return user.id if user is not None else None


def _to_out(account: XAccount) -> AccountOut:
    return AccountOut(
        id=account.id,
        username=account.username,
        display_name=account.display_name,
        status=account.status,
        has_session=bool(account.session_ciphertext),
        has_dm_passcode=bool(account.dm_passcode),
        last_checked_at=account.last_checked_at,
    )


@router.get("", response_model=list[AccountOut])
def list_accounts(user: CurrentUser = None, db: Session = Depends(get_db)) -> list[AccountOut]:
    uid = _uid(user)
    stmt = select(XAccount)
    if uid is not None:
        stmt = stmt.where(XAccount.user_id == uid)
    rows = db.scalars(stmt.order_by(XAccount.id.desc())).all()
    return [_to_out(row) for row in rows]


@router.post("/connect", response_model=AccountOut)
def connect(
    payload: ConnectIn, user: CurrentUser = None, db: Session = Depends(get_db)
) -> AccountOut:
    result = accounts.connect_with_password(
        db,
        payload.username,
        payload.password,
        user_id=_uid(user),
        verification_code=payload.verification_code,
        dm_passcode=payload.dm_passcode,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or result.get("code"))

    account = db.scalar(select(XAccount).where(XAccount.username == payload.username.lstrip("@")))
    if account is None:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail="account was not stored")
    return _to_out(account)


@router.put("/{account_id}/dm-passcode", response_model=AccountOut)
def update_dm_passcode(
    account_id: int,
    payload: DmPasscodeIn,
    user: CurrentUser = None,
    db: Session = Depends(get_db),
) -> AccountOut:
    """Add, change, or clear the (optional) X chat passcode."""
    uid = _uid(user)
    account = db.get(XAccount, account_id)
    if account is None or (uid is not None and account.user_id != uid):
        raise HTTPException(status_code=404, detail="account not found")
    accounts.set_dm_passcode(db, account, payload.passcode)
    return _to_out(account)


@router.delete("/{account_id}")
def disconnect(
    account_id: int, user: CurrentUser = None, db: Session = Depends(get_db)
) -> dict:
    uid = _uid(user)
    account = db.get(XAccount, account_id)
    if account is None or (uid is not None and account.user_id != uid):
        raise HTTPException(status_code=404, detail="account not found")
    db.delete(account)
    db.commit()
    return {"deleted": True}
