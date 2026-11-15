"""Send an application email when a post says "mail your resume to ...".

Uses plain SMTP (Gmail app password, Resend, Brevo, ...). Nothing happens when
SMTP is not configured - the pipeline routes those posts to approvals instead.
"""

from __future__ import annotations

import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from app.config import settings
from app.services import resume_store

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

_MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


def email_configured(config: dict | None = None) -> bool:
    if config:
        return bool(config.get("host") and config.get("username") and config.get("password"))
    return settings.email_configured


def send_application(
    to_email: str,
    subject: str,
    body: str,
    *,
    resume_path: str = "",
    reply_to: str = "",
    config: dict | None = None,
    timeout: int = 30,
) -> dict:
    """Return {success, code, error}. Never raises for expected failures."""
    target = (to_email or "").strip().strip(".,;:()[]<>")
    if not EMAIL_RE.match(target):
        return {"success": False, "code": "INVALID_EMAIL", "error": f"not a valid address: {target}"}

    cfg = config or (
        {
            "host": settings.smtp_host,
            "port": settings.smtp_port,
            "username": settings.smtp_user,
            "password": settings.smtp_password,
            "from_address": settings.smtp_from or settings.smtp_user,
            "starttls": settings.smtp_starttls,
        }
        if settings.email_configured
        else None
    )
    if not cfg:
        return {
            "success": False,
            "code": "EMAIL_NOT_CONFIGURED",
            "error": "Email is not connected. Connect it in Settings -> Email applications.",
        }

    message = EmailMessage()
    message["From"] = cfg.get("from_address") or cfg.get("username") or ""
    message["To"] = target
    message["Subject"] = subject[:200]
    if reply_to:
        message["Reply-To"] = reply_to
    message.set_content(body)

    attachment = resume_store.read(resume_path)
    if attachment:
        raw, filename = attachment
        suffix = Path(filename).suffix.lower()
        maintype, subtype = _MIME.get(suffix, "application/octet-stream").split("/", 1)
        message.add_attachment(raw, maintype=maintype, subtype=subtype, filename=filename)

    host = cfg.get("host") or ""
    port = int(cfg.get("port") or 587)
    user = cfg.get("username") or ""
    password = (cfg.get("password") or "").replace(" ", "").strip()

    def deliver(use_starttls: bool, use_port: int) -> None:
        if use_starttls:
            with smtplib.SMTP(host, use_port, timeout=timeout) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(user, password)
                server.send_message(message)
        else:
            with smtplib.SMTP_SSL(host, use_port, timeout=timeout) as server:
                server.login(user, password)
                server.send_message(message)

    try:
        deliver(bool(cfg.get("starttls", True)), port)
    except smtplib.SMTPAuthenticationError:
        return {
            "success": False,
            "code": "EMAIL_AUTH",
            "error": "Gmail rejected the login. Re-enter the 16-character App Password in Settings.",
        }
    except (smtplib.SMTPServerDisconnected, ConnectionResetError, OSError) as exc:
        # Port 587 is blocked on some networks; Gmail also accepts SSL on 465.
        if port == 587 and cfg.get("starttls", True):
            try:
                deliver(False, 465)
                return {"success": True, "code": "OK", "error": ""}
            except smtplib.SMTPAuthenticationError:
                return {
                    "success": False,
                    "code": "EMAIL_AUTH",
                    "error": "Gmail rejected the login. Re-enter the App Password in Settings.",
                }
            except (smtplib.SMTPException, OSError) as retry_exc:
                logger.warning("email send failed: %s", retry_exc)
                return {"success": False, "code": "ERROR", "error": f"email failed: {retry_exc}"}
        logger.warning("email send failed: %s", exc)
        return {"success": False, "code": "ERROR", "error": f"email failed: {exc}"}
    except smtplib.SMTPException as exc:
        logger.warning("email send failed: %s", exc)
        return {"success": False, "code": "ERROR", "error": f"email failed: {exc}"}

    return {"success": True, "code": "OK", "error": ""}
