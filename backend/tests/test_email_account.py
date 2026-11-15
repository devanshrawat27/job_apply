"""Per-user email connection: encrypted storage and config shape."""

from __future__ import annotations

from sqlalchemy import delete

from app.database import SessionLocal
from app.models import EmailAccount
from app.services import email_accounts, mailer


def _reset():
    db = SessionLocal()
    db.execute(delete(EmailAccount))
    db.commit()
    return db


def test_save_and_read_email_config():
    db = _reset()
    email_accounts.save(
        db,
        None,
        host="smtp.gmail.com",
        port=587,
        username="candidate@example.com",
        password="app-password-123",
        from_address="candidate@example.com",
        starttls=True,
    )

    cfg = email_accounts.config(db, None)
    assert cfg is not None
    assert cfg["host"] == "smtp.gmail.com"
    assert cfg["username"] == "candidate@example.com"
    assert cfg["password"] == "app-password-123"

    public = email_accounts.public(db, None)
    assert public["configured"] is True
    assert public["source"] == "workspace"
    assert "password" not in public

    assert mailer.email_configured(cfg) is True
    db.close()


def test_delete_email_account():
    db = _reset()
    email_accounts.save(
        db,
        None,
        host="smtp.example.com",
        port=465,
        username="a@example.com",
        password="secret",
        starttls=False,
    )
    assert email_accounts.config(db, None) is not None
    assert email_accounts.delete(db, None) is True
    assert email_accounts.config(db, None) is None
    db.close()
