"""ChatGPT through the browser - no API key needed.

The user logs into chatgpt.com once in their own Chromium profile (Settings ->
Connect ChatGPT). Every workspace has a separate profile, so two accounts never
share a ChatGPT session.

All agent conversations live in one project (default: "JobPilot") and each task
has its own long-lived thread inside it, so ChatGPT keeps the context of what it
already checked or wrote.

This is slower than an API (20-60s per answer) and depends on ChatGPT's page
markup, so it is used only for occasional analysis and as a draft fallback.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models import AgentSettings
from app.services import chat_threads, executor

logger = logging.getLogger(__name__)


def _suffix(user_id: int | None) -> str:
    # The original workspace keeps the base profile so an existing login is not
    # lost; every other workspace gets its own.
    if user_id is None or user_id == 1:
        return ""
    return f"-u{user_id}"


def _profile_dir(user_id: int | None = None) -> Path:
    base = os.environ.get("AUTOMATION_DATA_DIR") or ""
    if base:
        root = Path(base)
    else:
        appdata = os.environ.get("APPDATA") or str(Path.home())
        root = Path(appdata) / "jobpilot"
    return root / f"chatgpt-profile{_suffix(user_id)}"


def marker_path(user_id: int | None = None) -> Path:
    return _profile_dir(user_id) / ".jobpilot-connected"


def connected(user_id: int | None = None) -> bool:
    return marker_path(user_id).exists()


def _forget(user_id: int | None) -> None:
    """The session is gone. Stop reporting a connection that does not exist."""
    try:
        marker_path(user_id).unlink(missing_ok=True)
    except OSError:
        pass


def login(user_id: int | None = None) -> dict:
    """Open chatgpt.com and wait for the human to finish logging in."""
    result = executor.run_script("chatgpt_login", {}, user_id=user_id, timeout=340)
    if result.get("success"):
        try:
            marker_path(user_id).parent.mkdir(parents=True, exist_ok=True)
            marker_path(user_id).write_text("connected", encoding="utf-8")
        except OSError:
            pass
    return result


def account(user_id: int | None = None) -> dict | None:
    """Read the signed-in ChatGPT account (read-only)."""
    if not connected(user_id):
        return None
    result = executor.run_script("chatgpt_whoami", {}, user_id=user_id, timeout=100)
    if not result.get("success"):
        if result.get("code") == "NOT_LOGGED_IN":
            _forget(user_id)
        return None
    data = result.get("data") or {}
    email = str(data.get("email") or "")
    if not email:
        return None
    return {
        "email": email,
        "name": str(data.get("name") or ""),
        "plan": str(data.get("plan") or ""),
    }


def _settings_row(user_id: int | None) -> AgentSettings | None:
    db = SessionLocal()
    try:
        stmt = select(AgentSettings)
        if user_id is None:
            stmt = stmt.where(AgentSettings.user_id.is_(None))
        else:
            stmt = stmt.where(AgentSettings.user_id == user_id)
        return db.scalar(stmt.order_by(AgentSettings.id).limit(1))
    finally:
        db.close()


def project_url(user_id: int | None = None) -> str:
    row = _settings_row(user_id)
    return (row.chatgpt_project_url or "") if row is not None else ""


def save_project_url(user_id: int | None, url: str, name: str = "") -> None:
    db = SessionLocal()
    try:
        stmt = select(AgentSettings)
        if user_id is None:
            stmt = stmt.where(AgentSettings.user_id.is_(None))
        else:
            stmt = stmt.where(AgentSettings.user_id == user_id)
        row = db.scalar(stmt.order_by(AgentSettings.id).limit(1))
        if row is None:
            row = AgentSettings(user_id=user_id)
            db.add(row)
        row.chatgpt_project_url = (url or "")[:500]
        if name:
            row.chatgpt_project_name = name[:120]
        db.commit()
    finally:
        db.close()


def ensure_project(user_id: int | None = None, name: str = "") -> dict:
    """Create (or find) the ChatGPT project that holds the agent's chats."""
    wanted = (name or "").strip() or chat_threads.PROJECT_NAME
    result = executor.run_script(
        "chatgpt_project", {"name": wanted}, user_id=user_id, timeout=200
    )
    if not result.get("success"):
        code = str(result.get("code") or "ERROR")
        if code == "CHATGPT_LOGIN_REQUIRED":
            _forget(user_id)
        return {
            "ok": False,
            "code": code,
            "error": str(result.get("error") or code)[:300],
            "url": "",
        }

    data = result.get("data") or {}
    url = str(data.get("project_url") or "")
    if url:
        save_project_url(user_id, url, wanted)
    return {
        "ok": bool(url),
        "code": "OK" if url else "NO_PROJECT_URL",
        "error": "" if url else "ChatGPT did not return a project link",
        "url": url,
        "created": bool(data.get("created")),
        "name": wanted,
    }


def _ask(
    system: str,
    prompt: str,
    *,
    user_id: int | None,
    thread_url: str,
    thread_title: str,
    project: str,
    timeout: int,
) -> dict:
    args = {
        "system": system[:9000],
        "prompt": prompt[:14000],
        "thread_url": thread_url,
        "thread_title": thread_title,
        "project_url": project,
    }
    return executor.run_script("chatgpt_ask", args, user_id=user_id, timeout=timeout)


def ask_json(
    system: str,
    prompt: str,
    *,
    user_id: int | None = None,
    purpose: str = "",
    timeout: int = 240,
) -> dict:
    """Ask the logged-in ChatGPT page and return its parsed JSON.

    With a ``purpose`` the same conversation is resumed every time, so the model
    already knows what it decided for earlier posts.
    """
    if not connected(user_id):
        raise RuntimeError(
            "ChatGPT is not connected. Open Settings and press Connect ChatGPT."
        )

    project = project_url(user_id)
    thread_url = ""
    thread_title = chat_threads.title_for(purpose) if purpose else ""
    thread_id: int | None = None

    if purpose:
        db = SessionLocal()
        try:
            thread = chat_threads.ensure(db, user_id, purpose)
            thread_url = thread.url
            thread_title = thread.title or thread_title
            thread_id = thread.id
        finally:
            db.close()

    result = _ask(
        system,
        prompt,
        user_id=user_id,
        thread_url=thread_url,
        thread_title=thread_title,
        project=project,
        timeout=timeout,
    )

    # The conversation was deleted in ChatGPT (or the link is stale): open a new
    # one instead of failing the task.
    if not result.get("success") and thread_url and result.get("code") == "THREAD_MISSING":
        result = _ask(
            system,
            prompt,
            user_id=user_id,
            thread_url="",
            thread_title=thread_title,
            project=project,
            timeout=timeout,
        )

    if not result.get("success"):
        code = str(result.get("code") or "ERROR")
        if code == "CHATGPT_LOGIN_REQUIRED":
            _forget(user_id)
        raise RuntimeError(str(result.get("error") or code))

    payload = result.get("data") or {}
    data = payload.get("json")
    if not isinstance(data, dict):
        raise RuntimeError("ChatGPT did not return a JSON object")

    if purpose and thread_id is not None:
        url = str(payload.get("thread_url") or "")
        db = SessionLocal()
        try:
            chat_threads.record(
                db, user_id, purpose, url=url, project_url=project
            )
        finally:
            db.close()

    return data
