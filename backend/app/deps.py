"""FastAPI dependencies: DB session and the authenticated user."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.auth_utils import decode_access_token, token_blocklist
from app.config import settings
from app.database import get_db
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

DbDep = Annotated[Session, Depends(get_db)]
TokenDep = Annotated[str | None, Depends(oauth2_scheme)]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(token: TokenDep, db: DbDep) -> User | None:
    """Return the logged-in user, or None when auth is disabled.

    With AUTH_ENABLED=false (local dev / tests) every request is allowed, which
    keeps the pre-auth developer workflow working.
    """
    if not settings.auth_enabled:
        return None

    if not token:
        raise _unauthorized("Not authenticated")
    if token in token_blocklist:
        raise _unauthorized("Session ended, please log in again")

    payload = decode_access_token(token)
    if payload is None or not payload.get("sub"):
        raise _unauthorized("Invalid or expired token")

    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        raise _unauthorized("Invalid token subject")

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized("User not found or inactive")
    return user


CurrentUser = Annotated[User | None, Depends(get_current_user)]
