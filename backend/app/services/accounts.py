"""Account helpers: connect, fetch stored session, health."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import XAccount
from app.security import decrypt_credentials, encrypt_credentials
from app.services import executor


def active_account(db: Session, user_id: int | None = None) -> XAccount | None:
    stmt = select(XAccount)
    if user_id is not None:
        stmt = stmt.where(XAccount.user_id == user_id)
    return db.scalar(stmt.order_by(XAccount.id.desc()))


def account_credentials(account: XAccount | None) -> dict[str, str] | None:
    if account is None or not account.session_ciphertext:
        return None
    return decrypt_credentials(account.session_ciphertext)


def connect_with_password(
    db: Session,
    username: str,
    password: str,
    *,
    user_id: int | None = None,
    verification_code: str | None = None,
    dm_passcode: str | None = None,
) -> dict:
    """Sign in through the executor and store only the resulting cookies."""
    handle = (username or "").strip().lstrip("@")
    if not handle or not password:
        return {"success": False, "code": "VALIDATION", "error": "handle and password are required"}

    if not account_encryption_ready():
        return {
            "success": False,
            "code": "CONFIG",
            "error": "CREDENTIALS_ENCRYPTION_KEY is not set, so the session cannot be stored safely.",
        }

    result = executor.run_script(
        "login",
        {"handle": handle, "password": password, "verification_code": verification_code or ""},
    )
    if not result.get("success"):
        return result

    data = result.get("data") or {}
    creds = data.get("credentials") or {}
    if not creds.get("auth_token") or not creds.get("ct0"):
        return {"success": False, "code": "LOGIN_FAILED", "error": "X did not return a usable session"}

    account = db.scalar(select(XAccount).where(XAccount.username == handle))
    if account is None:
        account = XAccount(username=handle, user_id=user_id)
        db.add(account)
    elif user_id is not None and account.user_id is None:
        # claim a legacy account for the first real user
        account.user_id = user_id

    account.display_name = str(data.get("display_name") or account.display_name or "")
    account.session_ciphertext = encrypt_credentials(creds)
    account.status = "connected"
    if dm_passcode:
        account.dm_passcode = encrypt_credentials({"passcode": dm_passcode})
    db.commit()
    db.refresh(account)

    return {
        "success": True,
        "code": "OK",
        "account": {
            "id": account.id,
            "username": account.username,
            "display_name": account.display_name,
            "has_session": True,
            "has_dm_passcode": bool(account.dm_passcode),
        },
    }


def dm_passcode(account: XAccount | None) -> str | None:
    if account is None or not account.dm_passcode:
        return None
    payload = decrypt_credentials(account.dm_passcode)
    if not payload:
        return None
    return payload.get("passcode") or None


def set_dm_passcode(db: Session, account: XAccount, passcode: str | None) -> XAccount:
    """Optional: the agent works without it until X asks for one."""
    clean = (passcode or "").strip()
    account.dm_passcode = encrypt_credentials({"passcode": clean}) if clean else ""
    db.commit()
    db.refresh(account)
    return account


def account_encryption_ready() -> bool:
    from app.config import settings

    return bool((settings.credentials_encryption_key or "").strip())
