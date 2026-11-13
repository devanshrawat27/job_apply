"""At-rest encryption for X session cookies.

The connect flow ends with `auth_token` / `ct0` / `twid` cookies. They are
stored encrypted on the account row and are never returned by the API.
"""

from __future__ import annotations

import json

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _fernet() -> Fernet:
    key = (settings.credentials_encryption_key or "").strip()
    if not key:
        raise RuntimeError(
            "CREDENTIALS_ENCRYPTION_KEY is not set. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_credentials(creds: dict) -> str:
    payload = json.dumps(creds, separators=(",", ":")).encode("utf-8")
    return _fernet().encrypt(payload).decode("utf-8")


def decrypt_credentials(token: str) -> dict | None:
    if not token:
        return None
    try:
        return json.loads(_fernet().decrypt(token.encode("utf-8")).decode("utf-8"))
    except (InvalidToken, ValueError, TypeError):
        return None
