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


def email_configured() -> bool:
    return settings.email_configured


def send_application(
    to_email: str,
    subject: str,
    body: str,
    *,
    resume_path: str = "",
    reply_to: str = "",
    timeout: int = 30,
) -> dict:
    """Return {success, code, error}. Never raises for expected failures."""
    target = (to_email or "").strip().strip(".,;:()[]<>")
    if not EMAIL_RE.match(target):
        return {"success": False, "code": "INVALID_EMAIL", "error": f"not a valid address: {target}"}

    if not settings.email_configured:
        return {
            "success": False,
            "code": "EMAIL_NOT_CONFIGURED",
            "error": "SMTP is not configured. Add SMTP_* values to backend/.env to send email applications.",
        }

    message = EmailMessage()
    message["From"] = settings.smtp_from or settings.smtp_user or ""
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

    host = settings.smtp_host or ""
    port = int(settings.smtp_port or 587)

    try:
        if settings.smtp_starttls:
            with smtplib.SMTP(host, port, timeout=timeout) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(settings.smtp_user or "", settings.smtp_password or "")
                server.send_message(message)
        else:
            with smtplib.SMTP_SSL(host, port, timeout=timeout) as server:
                server.login(settings.smtp_user or "", settings.smtp_password or "")
                server.send_message(message)
    except smtplib.SMTPAuthenticationError:
        return {
            "success": False,
            "code": "EMAIL_AUTH",
            "error": "SMTP rejected the login. Check SMTP_USER / SMTP_PASSWORD (use an app password).",
        }
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning("email send failed: %s", exc)
        return {"success": False, "code": "ERROR", "error": f"email failed: {exc}"}

    return {"success": True, "code": "OK", "error": ""}
