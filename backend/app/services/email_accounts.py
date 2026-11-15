"""Per-user email (SMTP) connection for application emails.

Each workspace can connect its own sending address. Credentials are encrypted
with the same Fernet key used for X sessions and are never returned by the API.
If no workspace account exists, the old global SMTP_* env values are used.
"""

from __future__ import annotations

import logging
import smtplib
import ssl

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import EmailAccount
from app.security import decrypt_credentials, encrypt_credentials

logger = logging.getLogger(__name__)


def get(db: Session, user_id: int | None) -> EmailAccount | None:
    stmt = select(EmailAccount)
    if user_id is None:
        stmt = stmt.where(EmailAccount.user_id.is_(None))
    else:
        stmt = stmt.where(EmailAccount.user_id == user_id)
    return db.scalar(stmt)


def config(db: Session, user_id: int | None) -> dict | None:
    """SMTP settings for this workspace, or None when not connected."""
    row = get(db, user_id)
    if row is None or not row.enabled:
        return None
    creds = decrypt_credentials(row.password_ciphertext) or {}
    password = str(creds.get("password") or "").replace(" ", "").strip()
    if not (row.host and row.username and password):
        return None
    return {
        "host": row.host,
        "port": int(row.port or 587),
        "username": row.username,
        "password": password,
        "from_address": row.from_address or row.username,
        "starttls": bool(row.starttls),
    }


def configured(db: Session, user_id: int | None) -> bool:
    return config(db, user_id) is not None or settings.email_configured


def save(
    db: Session,
    user_id: int | None,
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    from_address: str = "",
    starttls: bool = True,
) -> EmailAccount:
    row = get(db, user_id)
    if row is None:
        row = EmailAccount(user_id=user_id)
        db.add(row)
    row.host = host.strip()[:200]
    row.port = int(port or 587)
    row.username = username.strip()[:200]
    row.from_address = (from_address or username).strip()[:200]
    row.starttls = bool(starttls)
    row.enabled = True
    row.password_ciphertext = encrypt_credentials(
        {"password": password.replace(" ", "").strip()}
    )
    db.commit()
    db.refresh(row)
    return row


def delete(db: Session, user_id: int | None) -> bool:
    row = get(db, user_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def public(db: Session, user_id: int | None) -> dict:
    row = get(db, user_id)
    if row is None:
        return {
            "configured": settings.email_configured,
            "source": "env" if settings.email_configured else "none",
            "host": settings.smtp_host or "",
            "port": int(settings.smtp_port or 587),
            "username": settings.smtp_user or "",
            "from_address": settings.smtp_from or settings.smtp_user or "",
            "starttls": bool(settings.smtp_starttls),
        }
    return {
        "configured": True,
        "source": "workspace",
        "host": row.host,
        "port": int(row.port or 587),
        "username": row.username,
        "from_address": row.from_address or row.username,
        "starttls": bool(row.starttls),
    }


def test_connection(cfg: dict, timeout: int = 20) -> dict:
    """Log in and quit. Does not send an email."""
    host = cfg.get("host") or ""
    port = int(cfg.get("port") or 587)
    username = cfg.get("username") or ""
    password = (cfg.get("password") or "").replace(" ", "").strip()
    if not (host and username and password):
        return {"ok": False, "error": "email and app password are required"}

    def attempt(use_starttls: bool, use_port: int) -> None:
        if use_starttls:
            with smtplib.SMTP(host, use_port, timeout=timeout) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(username, password)
        else:
            with smtplib.SMTP_SSL(host, use_port, timeout=timeout) as server:
                server.login(username, password)

    try:
        attempt(bool(cfg.get("starttls", True)), port)
    except smtplib.SMTPAuthenticationError:
        return {
            "ok": False,
            "error": "Gmail rejected the login. Use the 16-character App Password, not your normal password.",
        }
    except (smtplib.SMTPServerDisconnected, ConnectionResetError, OSError) as exc:
        # Some networks close port 587. Gmail also accepts implicit SSL on 465.
        if port == 587 and cfg.get("starttls", True):
            try:
                attempt(False, 465)
                return {"ok": True, "error": ""}
            except smtplib.SMTPAuthenticationError:
                return {
                    "ok": False,
                    "error": "Gmail rejected the login. Use the 16-character App Password.",
                }
            except (smtplib.SMTPException, OSError) as retry_exc:
                return {"ok": False, "error": f"connection failed: {retry_exc}"}
        return {"ok": False, "error": f"connection failed: {exc}"}
    except smtplib.SMTPException as exc:
        return {"ok": False, "error": f"connection failed: {exc}"}
    return {"ok": True, "error": ""}
