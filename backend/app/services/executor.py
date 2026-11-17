"""Bridge to the Node + Playwright executor.

Contract (same as the reference projects):

    node scripts/<name>.js --agent-mode
    SCRIPT_ARG_<NAME> environment variables
    one final line on stdout:  RESULT_JSON:{"success":true,"code":"OK","data":{...}}

Every browser action is serialised: X silently drops concurrent actions from the
same account, and two Playwright browsers fighting over one profile is worse.
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from app.config import settings

EXECUTOR_DIR = Path(__file__).resolve().parents[2] / "executor"
RESULT_MARKER = "RESULT_JSON:"

SCRIPTS: dict[str, str] = {
    "search": "scripts/searchJobs.js",
    "feed": "scripts/feedJobs.js",
    "train_feed": "scripts/trainFeed.js",
    "reply": "scripts/replyToPost.js",
    "dm": "scripts/sendDm.js",
    "follow": "scripts/followUser.js",
    "login": "scripts/loginWithPassword.js",
    "chatgpt_ask": "scripts/chatgptAsk.js",
    "chatgpt_login": "scripts/chatgptLogin.js",
    "chatgpt_whoami": "scripts/chatgptWhoami.js",
    "chatgpt_project": "scripts/chatgptProject.js",
    "check_inbox": "scripts/checkInbox.js",
}

TIMEOUTS: dict[str, int] = {
    "search": 100,
    "feed": 120,
    "train_feed": 130,
    "reply": 90,
    "dm": 240,
    "follow": 90,
    "login": 210,
    "chatgpt_ask": 220,
    "chatgpt_login": 340,
    "chatgpt_whoami": 100,
    "chatgpt_project": 200,
    "check_inbox": 130,
}

SCRIPT_LOCK = threading.Lock()

# One warm browser for every action. X's encrypted chat only renders in a page
# that is already logged in and hydrated, so we keep a persistent host alive
# and let each script attach over CDP (same approach as the reference project).
_HOST: dict[str, Any] = {"proc": None, "endpoint": "", "key": ""}
_HOST_LOCK = threading.Lock()


def _port_open(port: int, timeout: float = 0.6) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill a script and every browser it spawned."""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=20,
            )
        else:
            proc.kill()
    except Exception:  # noqa: BLE001 - best effort
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def stop_host() -> None:
    proc = _HOST.get("proc")
    if proc is not None and proc.poll() is None:
        try:
            if proc.stdin:
                proc.stdin.write("close\n")
                proc.stdin.flush()
            proc.wait(timeout=6)
        except Exception:  # noqa: BLE001
            proc.kill()
    _HOST.update({"proc": None, "endpoint": "", "key": ""})


atexit.register(stop_host)


def profile_suffix(user_id: int | None) -> str:
    """Workspace-specific browser profile suffix.

    The original workspace (user 1 / legacy rows) keeps the base profile so its
    existing X login keeps working. Every other user gets an isolated profile.
    """
    if user_id is None or user_id == 1:
        return ""
    return f"-u{user_id}"


def ensure_host(creds: dict[str, str], suffix: str = "") -> str:
    """No CDP host: every script launches the persistent profile itself.

    The old host never exposed a debugging port, so each call waited 60s for a
    port that never opened and then launched a browser anyway. ``run_script``
    already serialises scripts, so one browser at a time is guaranteed and the
    profile (cookies, IndexedDB) is still shared.
    """
    return ""


class ExecutorUnavailable(RuntimeError):
    pass


def executor_health() -> dict[str, Any]:
    node = shutil.which("node")
    missing = [k for k, rel in SCRIPTS.items() if not (EXECUTOR_DIR / rel).exists()]
    deps = (EXECUTOR_DIR / "node_modules" / "playwright").exists()
    return {
        "available": bool(node) and not missing and deps,
        "node": node,
        "dir": str(EXECUTOR_DIR),
        "missing_scripts": missing,
        "dependencies_installed": deps,
    }


def _parse_result(stdout: str) -> dict[str, Any] | None:
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if not line.startswith(RESULT_MARKER):
            continue
        try:
            payload = json.loads(line[len(RESULT_MARKER):])
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None
    return None


def _tail(stdout: str, limit: int = 40) -> list[str]:
    return [ln for ln in (stdout or "").strip().splitlines()[-limit:]]


def run_script(
    name: str,
    args: dict[str, Any] | None = None,
    *,
    creds: dict[str, str] | None = None,
    dm_passcode: str | None = None,
    user_id: int | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    """Run one executor script and return its parsed RESULT_JSON payload."""
    if name not in SCRIPTS:
        raise ValueError(f"unknown script: {name}")
    if not settings.automation_enabled:
        raise ExecutorUnavailable("automation is disabled (AUTOMATION_ENABLED=false)")

    script = EXECUTOR_DIR / SCRIPTS[name]
    if not script.exists():
        raise ExecutorUnavailable(f"missing executor script: {script}")

    suffix = profile_suffix(user_id)
    env = os.environ.copy()
    env["STEALTH_BACKEND"] = "chromium-stealth"
    env["JOBPILOT_PROFILE_SUFFIX"] = suffix
    # Everything runs headless in the background. The only exceptions are the
    # interactive sign-ins, which the human explicitly starts from the UI.
    if settings.automation_headless and name not in ("login", "chatgpt_login"):
        env["STEALTH_HEADLESS"] = "1"

    for key, value in (args or {}).items():
        if value is None:
            continue
        env[f"SCRIPT_ARG_{key.upper()}"] = str(value)

    if creds:
        env["TWITTER_AUTH_TOKEN"] = creds.get("auth_token", "")
        env["TWITTER_CT0"] = creds.get("ct0", "")
        env["TWITTER_TWID"] = creds.get("twid", "")
    if dm_passcode:
        env["DM_PASSCODE"] = dm_passcode

    # Every action except login reuses the persistent browser.
    if name != "login" and creds:
        endpoint = ensure_host(creds, suffix)
        if endpoint:
            env["BROWSER_CDP_ENDPOINT"] = endpoint

    limit = timeout or TIMEOUTS.get(name, settings.automation_timeout_s)

    with SCRIPT_LOCK:
        try:
            proc = subprocess.Popen(
                ["node", str(script), "--agent-mode"],
                cwd=str(EXECUTOR_DIR),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            return {
                "success": False,
                "code": "ERROR",
                "error": f"could not start {name}: {exc}",
                "data": {"logs": []},
            }

        try:
            stdout, stderr = proc.communicate(timeout=limit)
        except subprocess.TimeoutExpired:
            # Kill the whole tree. A killed node process can leave a Chromium
            # child holding the pipes, which would block communicate() forever
            # and keep SCRIPT_LOCK locked for every later action.
            _kill_tree(proc)
            try:
                proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                for stream in (proc.stdout, proc.stderr):
                    try:
                        stream.close()
                    except Exception:  # noqa: BLE001
                        pass
            return {
                "success": False,
                "code": "TIMEOUT",
                "error": f"{name} exceeded {limit}s",
                "data": {"logs": []},
            }

    payload = _parse_result(stdout)
    if payload is None:
        # Surface the real reason (missing module, missing browser, crash)
        # instead of a useless "no RESULT_JSON" message.
        tail = _tail(stderr, 12) or _tail(stdout, 12)
        reason = " | ".join(line.strip() for line in tail[-6:] if line.strip())
        payload = {
            "success": False,
            "code": "ERROR",
            "error": (
                f"{name} produced no RESULT_JSON line"
                + (f": {reason}" if reason else f" (exit code {proc.returncode})")
            ),
            "data": {"logs": tail},
        }
    logs = (payload.get("data") or {}).get("logs") or _tail(stdout)
    payload.setdefault("data", {})
    payload["data"]["logs"] = logs
    if proc.returncode != 0 and payload.get("success"):
        payload["success"] = False
        payload["code"] = "ERROR"
        payload["error"] = f"script exited with code {proc.returncode}"
    return payload

