"""Connect a Naukri.com account and keep its session cookies encrypted.

The user signs in once in a real Chrome window (Naukri blocks headless
Chromium). Only the resulting cookies are stored; the password is never kept.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NaukriAccount
from app.security import decrypt_credentials, encrypt_credentials
from app.services import executor


def active_account(db: Session, user_id: int | None = None) -> NaukriAccount | None:
    stmt = select(NaukriAccount)
    if user_id is not None:
        stmt = stmt.where(NaukriAccount.user_id == user_id)
    return db.scalar(stmt.order_by(NaukriAccount.id.desc()))


def cookies(account: NaukriAccount | None) -> dict[str, str]:
    if account is None or not account.session_ciphertext:
        return {}
    return decrypt_credentials(account.session_ciphertext) or {}


def connect_manual(
    db: Session,
    *,
    email: str = "",
    user_id: int | None = None,
) -> dict:
    """Open Naukri in Chrome and wait for the human to finish signing in."""
    result = executor.run_script(
        "naukri_login",
        {"email": (email or "").strip()},
        user_id=user_id,
        timeout=360,
    )
    if not result.get("success"):
        return {
            "success": False,
            "code": str(result.get("code") or "LOGIN_FAILED"),
            "error": str(result.get("error") or "Naukri did not sign in"),
        }

    data = result.get("data") or {}
    stored = data.get("credentials") or {}
    if not stored:
        return {
            "success": False,
            "code": "LOGIN_FAILED",
            "error": "Naukri did not return a usable session",
        }

    address = (email or "").strip()
    account = None
    if address:
        account = db.scalar(select(NaukriAccount).where(NaukriAccount.email == address))
    if account is None and user_id is not None:
        account = active_account(db, user_id)
    if account is None:
        account = NaukriAccount(email=address, user_id=user_id)
        db.add(account)
    elif user_id is not None and account.user_id is None:
        account.user_id = user_id

    account.email = address or account.email or ""
    account.display_name = str(data.get("name") or account.display_name or "")[:200]
    account.session_ciphertext = encrypt_credentials(stored)
    account.status = "connected"
    db.commit()
    db.refresh(account)

    return {
        "success": True,
        "code": "OK",
        "account": {
            "id": account.id,
            "email": account.email,
            "display_name": account.display_name,
            "status": account.status,
        },
    }


def mark_status(db: Session, account: NaukriAccount, status: str) -> None:
    if account.status != status:
        account.status = status
        db.commit()


def disconnect(db: Session, account: NaukriAccount) -> None:
    db.delete(account)
    db.commit()
