"""Auto-reconnect: the agent signs in again with the saved encrypted password."""

from __future__ import annotations

from datetime import datetime, timezone

from app.database import SessionLocal
from app.models import XAccount
from app.security import decrypt_credentials, encrypt_credentials
from app.services import accounts, pipeline


def _account(db, username: str, password: str | None) -> XAccount:
    account = XAccount(
        username=username,
        session_ciphertext=encrypt_credentials({"auth_token": "old", "ct0": "old"}),
        password_ciphertext=encrypt_credentials({"password": password}) if password else "",
        status="expired",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def test_reconnect_signs_in_and_replaces_the_session(monkeypatch):
    db = SessionLocal()
    account = _account(db, "reconnect_ok", "hunter2")
    monkeypatch.setattr(
        accounts.executor,
        "run_script",
        lambda *a, **k: {
            "success": True,
            "code": "OK",
            "data": {"credentials": {"auth_token": "new", "ct0": "newct0"}},
        },
    )

    result = accounts.auto_reconnect(db, account)

    assert result["ok"] is True
    db.refresh(account)
    assert account.status == "connected"
    assert decrypt_credentials(account.session_ciphertext)["auth_token"] == "new"
    assert account.reconnect_attempts == 0
    db.delete(account)
    db.commit()
    db.close()


def test_without_a_saved_password_it_asks_the_human(monkeypatch):
    db = SessionLocal()
    account = _account(db, "reconnect_nopass", None)
    called = {"n": 0}
    monkeypatch.setattr(
        accounts.executor, "run_script", lambda *a, **k: called.__setitem__("n", called["n"] + 1)
    )

    result = accounts.auto_reconnect(db, account)

    assert result["ok"] is False
    assert result["code"] == "NO_PASSWORD"
    assert called["n"] == 0
    db.delete(account)
    db.commit()
    db.close()


def test_a_verification_challenge_counts_as_a_failed_attempt(monkeypatch):
    db = SessionLocal()
    account = _account(db, "reconnect_challenge", "hunter2")
    monkeypatch.setattr(
        accounts.executor,
        "run_script",
        lambda *a, **k: {"success": False, "code": "LOGIN_CHALLENGE", "error": "code needed"},
    )

    result = accounts.auto_reconnect(db, account)

    assert result["ok"] is False
    assert result["code"] == "LOGIN_CHALLENGE"
    db.refresh(account)
    assert account.reconnect_attempts == 1
    assert account.status == "expired"
    db.delete(account)
    db.commit()
    db.close()


def test_attempts_are_capped_so_x_does_not_lock_the_account(monkeypatch):
    db = SessionLocal()
    account = _account(db, "reconnect_limit", "hunter2")
    account.reconnect_attempts = accounts.MAX_RECONNECT_ATTEMPTS
    account.last_reconnect_at = datetime.now(timezone.utc)
    db.commit()
    called = {"n": 0}
    monkeypatch.setattr(
        accounts.executor, "run_script", lambda *a, **k: called.__setitem__("n", called["n"] + 1)
    )

    result = accounts.auto_reconnect(db, account)

    assert result["code"] == "LIMIT"
    assert called["n"] == 0
    db.delete(account)
    db.commit()
    db.close()


def test_email_send_does_not_need_an_x_session():
    db = SessionLocal()
    run = pipeline.send_batch(db, user_id=99999, only_email=True)
    assert run.status == "completed"
    db.close()
