"""Connect a LinkedIn account and keep its session cookies encrypted.

The account is used read-only: search hiring posts and open the member's own
inbox later. The password is used for the one sign-in and is never stored.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LinkedInAccount
from app.security import decrypt_credentials, encrypt_credentials
from app.services import executor


def active_account(db: Session, user_id: int | None = None) -> LinkedInAccount | None:
    stmt = select(LinkedInAccount)
    if user_id is not None:
        stmt = stmt.where(LinkedInAccount.user_id == user_id)
    return db.scalar(stmt.order_by(LinkedInAccount.id.desc()))


def credentials(account: LinkedInAccount | None) -> dict[str, str] | None:
    if account is None or not account.session_ciphertext:
        return None
    return decrypt_credentials(account.session_ciphertext)


def connect_with_password(
    db: Session,
    email: str,
    password: str,
    *,
    user_id: int | None = None,
    verification_code: str | None = None,
) -> dict:
    address = (email or "").strip()
    if not address or not password:
        return {"success": False, "code": "VALIDATION", "error": "email and password are required"}

    result = executor.run_script(
        "linkedin_login",
        {
            "email": address,
            "password": password,
            "verification_code": verification_code or "",
        },
        user_id=user_id,
        timeout=240,
    )
    if not result.get("success"):
        return {
            "success": False,
            "code": str(result.get("code") or "LOGIN_FAILED"),
            "error": str(result.get("error") or "LinkedIn did not sign in"),
        }

    data = result.get("data") or {}
    cookies = data.get("credentials") or {}
    if not cookies.get("li_at") or not cookies.get("JSESSIONID"):
        return {
            "success": False,
            "code": "LOGIN_FAILED",
            "error": "LinkedIn did not return a usable session",
        }

    account = db.scalar(select(LinkedInAccount).where(LinkedInAccount.email == address))
    if account is None:
        account = LinkedInAccount(email=address, user_id=user_id)
        db.add(account)
    elif user_id is not None and account.user_id is None:
        account.user_id = user_id

    account.display_name = str(data.get("name") or account.display_name or "")[:200]
    account.vanity_name = str(data.get("vanity") or account.vanity_name or "")[:120]
    account.session_ciphertext = encrypt_credentials(cookies)
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
            "vanity_name": account.vanity_name,
            "status": account.status,
        },
    }


def mark_status(db: Session, account: LinkedInAccount, status: str) -> None:
    if account.status != status:
        account.status = status
        db.commit()


def disconnect(db: Session, account: LinkedInAccount) -> None:
    db.delete(account)
    db.commit()
