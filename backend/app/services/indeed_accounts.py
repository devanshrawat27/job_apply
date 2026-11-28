"""Connect an Indeed account and keep its session cookies encrypted.

Indeed's public search works without a login, but its Quick Apply flow needs a
signed-in session. The user signs in once in JobPilot's own Chrome window; only
the resulting cookies are stored.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IndeedAccount
from app.security import decrypt_credentials, encrypt_credentials
from app.services import executor

CDP_PORT = 9225


def active_account(db: Session, user_id: int | None = None) -> IndeedAccount | None:
    stmt = select(IndeedAccount)
    if user_id is not None:
        stmt = stmt.where(IndeedAccount.user_id == user_id)
    return db.scalar(stmt.order_by(IndeedAccount.id.desc()))


def cookies(account: IndeedAccount | None) -> dict[str, str]:
    if account is None or not account.session_ciphertext:
        return {}
    return decrypt_credentials(account.session_ciphertext) or {}


def connect_manual(db: Session, *, email: str = "", user_id: int | None = None) -> dict:
    """Open Indeed in Chrome and wait for the human to finish signing in."""
    result = executor.run_script(
        "indeed_login",
        {"email": (email or "").strip()},
        user_id=user_id,
        timeout=360,
    )
    if not result.get("success"):
        return {
            "success": False,
            "code": str(result.get("code") or "LOGIN_FAILED"),
            "error": str(result.get("error") or "Indeed did not sign in"),
        }

    data = result.get("data") or {}
    stored = data.get("credentials") or {}
    if not stored:
        return {
            "success": False,
            "code": "LOGIN_FAILED",
            "error": "Indeed did not return a usable session",
        }

    address = (email or "").strip() or str(data.get("email") or "").strip()
    account = None
    if address:
        account = db.scalar(select(IndeedAccount).where(IndeedAccount.email == address))
    if account is None and user_id is not None:
        account = active_account(db, user_id)
    if account is None:
        account = IndeedAccount(email=address, user_id=user_id)
        db.add(account)
    elif user_id is not None and account.user_id is None:
        account.user_id = user_id

    account.email = address or account.email or ""
    account.display_name = str(data.get("name") or account.display_name or "")[:200]
    account.session_ciphertext = encrypt_credentials(stored)
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
            "status": account.status,
        },
    }


def mark_status(db: Session, account: IndeedAccount, status: str) -> None:
    if account.status != status:
        account.status = status
        db.commit()


def disconnect(db: Session, account: IndeedAccount) -> None:
    db.delete(account)
    db.commit()


def _profile_dir() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "jobpilot" / "browser-profile-indeed"


def _focus_existing_window() -> bool:
    if os.name != "nt":
        return False
    script = r'''
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class JPFocusIndeed {
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
}
'@
$procs = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | Where-Object { $_.CommandLine -like '*browser-profile-indeed*' }
foreach ($p in $procs) {
  $gp = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue
  if ($gp -and $gp.MainWindowHandle -ne 0) {
    [JPFocusIndeed]::ShowWindow($gp.MainWindowHandle, 9) | Out-Null
    [JPFocusIndeed]::SetForegroundWindow($gp.MainWindowHandle) | Out-Null
    exit 0
  }
}
exit 1
'''
    try:
        result = subprocess.run(
            ["powershell", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=15,
        )
        return result.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _close_profile_chrome() -> None:
    if os.name != "nt":
        return
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        "Where-Object { $_.CommandLine -like '*browser-profile-indeed*' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; "
        "for ($i = 0; $i -lt 40; $i++) { "
        "Start-Sleep -Milliseconds 200; "
        "if (-not (Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        "Where-Object { $_.CommandLine -like '*browser-profile-indeed*' })) { break } }"
    )
    try:
        subprocess.run(
            ["powershell", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=20,
        )
    except Exception:  # noqa: BLE001
        pass


def _prepare_profile() -> None:
    default = _profile_dir() / "Default"
    prefs = default / "Preferences"
    if prefs.exists():
        try:
            data = json.loads(prefs.read_text(encoding="utf-8"))
            session = data.setdefault("session", {})
            session["restore_on_startup"] = 5
            session["startup_urls"] = []
            profile = data.setdefault("profile", {})
            profile["exit_type"] = "Normal"
            profile["exited_cleanly"] = True
            prefs.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    sessions = default / "Sessions"
    if sessions.exists():
        for item in sessions.iterdir():
            try:
                item.unlink()
            except OSError:
                pass
    for name in ("Current Session", "Current Tabs", "Last Session", "Last Tabs"):
        try:
            (default / name).unlink()
        except OSError:
            pass


def _port_open(port: int = CDP_PORT) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.6):
            return True
    except OSError:
        return False


def cdp_endpoint() -> str | None:
    return f"http://127.0.0.1:{CDP_PORT}" if _port_open() else None


def _close_blank_targets() -> None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=3) as response:
            targets = json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return
    pages = [target for target in targets if target.get("type") == "page"]
    if not any(str(target.get("url") or "") != "about:blank" for target in pages):
        return
    for target in pages:
        if target.get("url") == "about:blank":
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{CDP_PORT}/json/close/{target.get('id')}", timeout=3
                ).read()
            except Exception:  # noqa: BLE001
                pass


def _settle_window(seconds: float = 2.0) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        _close_blank_targets()
        time.sleep(0.35)


def _launch(url: str) -> dict:
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome.exists():
        found = shutil.which("chrome")
        if not found:
            return {"ok": False, "error": "Chrome was not found on this machine"}
        chrome = Path(found)

    profile = _profile_dir()
    if not profile.exists():
        return {
            "ok": False,
            "error": "The Indeed Chrome profile does not exist yet - connect Indeed first",
        }
    _prepare_profile()

    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    try:
        subprocess.Popen(
            [
                str(chrome),
                f"--user-data-dir={profile}",
                "--new-window",
                url,
                f"--remote-debugging-port={CDP_PORT}",
                "--remote-allow-origins=*",
                "--window-position=120,60",
                "--window-size=1280,900",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-session-crashed-bubble",
            ],
            creationflags=flags,
            close_fds=True,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}

    for _ in range(40):
        if _port_open():
            time.sleep(0.8)
            _settle_window(2.2)
            return {"ok": True}
        time.sleep(0.25)
    return {"ok": True, "slow": True}


def _navigate(url: str) -> None:
    endpoint = cdp_endpoint()
    if not endpoint or not url:
        return
    try:
        executor.run_script(
            "indeed_open",
            {"url": url},
            timeout=60,
            browser_cdp_endpoint=endpoint,
        )
    except Exception:  # noqa: BLE001
        pass


def open_window(url: str = "https://in.indeed.com/", *, replace: bool = False) -> dict:
    if replace:
        _close_profile_chrome()
    elif _port_open():
        if _focus_existing_window():
            _settle_window(1.0)
            _navigate(url)
            return {"ok": True, "reused": True}
    else:
        _close_profile_chrome()
    return _launch(url)


def ensure_window(url: str) -> str | None:
    if _port_open():
        _focus_existing_window()
        _settle_window(1.2)
        endpoint = cdp_endpoint()
        if endpoint:
            return endpoint
    _close_profile_chrome()
    result = _launch(url)
    if not result.get("ok"):
        return None
    return cdp_endpoint()
