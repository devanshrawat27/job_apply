"""Account helpers: connect, fetch stored session, health."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
    remember_password: bool = True,
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
        user_id=user_id,
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
    account.dm_status = "ok"
    account.reconnect_attempts = 0
    account.last_reconnect_at = None
    if remember_password:
        # Kept encrypted only so the agent can sign in again by itself when X
        # expires the session. Never returned by the API.
        account.password_ciphertext = encrypt_credentials({"password": password})
    else:
        account.password_ciphertext = ""
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


# Auto-reconnect: sign in again with the saved password when X expires the
# session. X sometimes asks for a code, which only the human can read, so the
# number of attempts is capped and a failure just falls back to the
# "Reconnect" prompt.
MAX_RECONNECT_ATTEMPTS = 3
RECONNECT_WINDOW_HOURS = 24


def password_saved(account: XAccount | None) -> bool:
    return bool(account is not None and account.password_ciphertext)


def saved_password(account: XAccount | None) -> str | None:
    if account is None or not account.password_ciphertext:
        return None
    payload = decrypt_credentials(account.password_ciphertext)
    if not payload:
        return None
    return payload.get("password") or None


def forget_password(db: Session, account: XAccount) -> XAccount:
    account.password_ciphertext = ""
    db.commit()
    db.refresh(account)
    return account


def remember_password(db: Session, account: XAccount, password: str) -> XAccount:
    clean = (password or "").strip()
    account.password_ciphertext = encrypt_credentials({"password": clean}) if clean else ""
    db.commit()
    db.refresh(account)
    return account


def _reconnect_attempts_left(account: XAccount, now: datetime) -> bool:
    last = account.last_reconnect_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if last is None or (now - last) >= timedelta(hours=RECONNECT_WINDOW_HOURS):
        return True
    return int(account.reconnect_attempts or 0) < MAX_RECONNECT_ATTEMPTS


def auto_reconnect(db: Session, account: XAccount) -> dict:
    """Sign in again with the saved password. Safe to call when X expired.

    Returns ``{"ok": True}`` on a fresh session, or ``{"ok": False, "code": ...,
    "error": ...}``. Never raises for a normal failure: the caller falls back to
    asking the human to reconnect.
    """
    if account is None:
        return {"ok": False, "code": "NO_ACCOUNT", "error": "no X account"}
    password = saved_password(account)
    if not password:
        return {
            "ok": False,
            "code": "NO_PASSWORD",
            "error": "no saved password - reconnect from Settings",
        }

    now = datetime.now(timezone.utc)
    if not _reconnect_attempts_left(account, now):
        return {
            "ok": False,
            "code": "LIMIT",
            "error": "auto-reconnect already tried a few times - reconnect from Settings",
        }

    account.reconnect_attempts = int(account.reconnect_attempts or 0) + 1
    account.last_reconnect_at = now
    db.commit()

    try:
        result = executor.run_script(
            "login",
            {
                "handle": account.username,
                "password": password,
                "verification_code": "",
            },
            user_id=account.user_id,
        )
    except Exception as exc:  # noqa: BLE001 - automation can fail at any point
        return {"ok": False, "code": "ERROR", "error": str(exc)[:200]}

    if not result.get("success"):
        return {
            "ok": False,
            "code": str(result.get("code") or "LOGIN_FAILED"),
            "error": str(result.get("error") or "X did not sign in")[:200],
        }

    data = result.get("data") or {}
    creds = data.get("credentials") or {}
    if not creds.get("auth_token") or not creds.get("ct0"):
        return {
            "ok": False,
            "code": "LOGIN_FAILED",
            "error": "X did not return a usable session",
        }

    account.session_ciphertext = encrypt_credentials(creds)
    account.status = "connected"
    account.dm_status = "ok"
    account.reconnect_attempts = 0
    account.last_reconnect_at = None
    db.commit()
    return {"ok": True, "code": "OK", "error": ""}
