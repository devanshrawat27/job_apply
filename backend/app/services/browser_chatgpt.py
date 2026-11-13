"""ChatGPT through the browser - no API key needed.

The user logs into chatgpt.com once in the dedicated Chromium profile (Settings
-> Connect ChatGPT). After that the analyst can ask it questions the same way a
person would: type the prompt, wait for the answer, read the JSON.

This is slower than an API (20-60s per answer) and depends on ChatGPT's page
markup, so it is used only for the occasional analysis - never for the scan
loop. If it fails, the normal LLM path is still tried.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from app.config import settings
from app.services import executor

logger = logging.getLogger(__name__)


def _profile_dir() -> Path:
    base = os.environ.get("AUTOMATION_DATA_DIR") or ""
    if base:
        return Path(base) / "chatgpt-profile"
    # Same default as executor/utils/paths.js on Windows.
    appdata = os.environ.get("APPDATA") or str(Path.home())
    return Path(appdata) / "jobpilot" / "chatgpt-profile"


def marker_path() -> Path:
    return _profile_dir() / ".jobpilot-connected"


def connected() -> bool:
    return marker_path().exists()


def account() -> dict | None:
    """Read the signed-in ChatGPT account (read-only)."""
    if not connected():
        return None
    result = executor.run_script("chatgpt_whoami", {}, timeout=100)
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


def login() -> dict:
    """Open chatgpt.com and wait for the human to finish logging in."""
    result = executor.run_script("chatgpt_login", {}, timeout=340)
    if result.get("success"):
        try:
            marker_path().parent.mkdir(parents=True, exist_ok=True)
            marker_path().write_text("connected", encoding="utf-8")
        except OSError:
            pass
    return result


def ask_json(system: str, prompt: str, *, timeout: int = 220) -> dict:
    """Ask the logged-in ChatGPT page and return its parsed JSON."""
    if not connected():
        raise RuntimeError(
            "ChatGPT is not connected. Open Settings and press Connect ChatGPT."
        )

    result = executor.run_script(
        "chatgpt_ask",
        {"system": system[:9000], "prompt": prompt[:14000]},
        timeout=timeout,
    )
    if not result.get("success"):
        raise RuntimeError(result.get("error") or result.get("code") or "ChatGPT failed")

    data = (result.get("data") or {}).get("json")
    if not isinstance(data, dict):
        raise RuntimeError("ChatGPT did not return a JSON object")
    return data
