"""ChatGPT through the browser - no API key needed.

The user logs into chatgpt.com once in their own Chromium profile (Settings ->
Connect ChatGPT). Every workspace has a separate profile, so two accounts never
share a ChatGPT session.

This is slower than an API (20-60s per answer) and depends on ChatGPT's page
markup, so it is used only for occasional analysis and as a draft fallback.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from app.services import executor

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


def ask_json(
    system: str,
    prompt: str,
    *,
    user_id: int | None = None,
    timeout: int = 220,
) -> dict:
    """Ask the logged-in ChatGPT page and return its parsed JSON."""
    if not connected(user_id):
        raise RuntimeError(
            "ChatGPT is not connected. Open Settings and press Connect ChatGPT."
        )

    result = executor.run_script(
        "chatgpt_ask",
        {"system": system[:9000], "prompt": prompt[:14000]},
        user_id=user_id,
        timeout=timeout,
    )
    if not result.get("success"):
        raise RuntimeError(result.get("error") or result.get("code") or "ChatGPT failed")

    data = (result.get("data") or {}).get("json")
    if not isinstance(data, dict):
        raise RuntimeError("ChatGPT did not return a JSON object")
    return data
