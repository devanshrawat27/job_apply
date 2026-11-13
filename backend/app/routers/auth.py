"""Single-user authentication: bootstrap register, login, refresh, logout."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth_utils import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_expiry,
    verify_password,
)
from app.config import settings
from app.database import get_db
from app.deps import CurrentUser
from app.models import (
    ActionLog,
    AgentSettings,
    DraftExample,
    JobPost,
    Profile,
    RefreshToken,
    Resume,
    Run,
    SearchQuery,
    User,
    XAccount,
)
from app.schemas import (
    AuthStatusOut,
    LoginIn,
    MessageOut,
    RefreshIn,
    RegisterIn,
    TokenPairOut,
    UserOut,
)
from app.services import ratelimit

router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_tokens(db: Session, user: User) -> TokenPairOut:
    refresh = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh),
            expires_at=refresh_expiry(),
        )
    )
    db.commit()
    return TokenPairOut(access_token=create_access_token(str(user.id)), refresh_token=refresh)


def _client_ip(request: Request) -> str:
    return (request.client.host if request.client else "") or "unknown"


def _login_limit(request: Request) -> None:
    if not ratelimit.allow(
        f"login:{_client_ip(request)}",
        limit=settings.login_rate_limit,
        window_seconds=300,
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again in a few minutes.",
        )


@router.get("/status", response_model=AuthStatusOut)
def auth_status(db: Session = Depends(get_db)) -> AuthStatusOut:
    has_user = bool(db.scalar(select(func.count(User.id))))
    return AuthStatusOut(auth_enabled=settings.auth_enabled, has_user=has_user)


@router.post("/register", response_model=TokenPairOut, status_code=201)
def register(payload: RegisterIn, request: Request, db: Session = Depends(get_db)) -> TokenPairOut:
    """Create an account. Each account gets its own isolated workspace."""
    _login_limit(request)

    email = payload.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="That email is already registered. Log in instead.")

    user = User(email=email, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    # First account on an existing install takes ownership of rows created
    # before multi-user support (user_id IS NULL), so nothing is lost.
    if db.scalar(select(func.count(User.id))) == 1:
        for model in (
            Profile,
            AgentSettings,
            XAccount,
            Resume,
            JobPost,
            Run,
            ActionLog,
            DraftExample,
            SearchQuery,
        ):
            db.execute(
                update(model).where(model.user_id.is_(None)).values(user_id=user.id)
            )
        db.commit()

    return _issue_tokens(db, user)


@router.post("/login", response_model=TokenPairOut)
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)) -> TokenPairOut:
    _login_limit(request)
    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Wrong email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account is disabled")
    return _issue_tokens(db, user)


@router.post("/refresh", response_model=TokenPairOut)
def refresh(payload: RefreshIn, db: Session = Depends(get_db)) -> TokenPairOut:
    token_hash = hash_refresh_token(payload.refresh_token)
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if row is None or row.revoked:
        raise HTTPException(status_code=401, detail="Refresh token is invalid")

    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Refresh token expired")

    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    row.revoked = True
    db.commit()
    return _issue_tokens(db, user)


@router.post("/logout", response_model=MessageOut)
def logout(
    payload: RefreshIn | None = None,
    user: CurrentUser = None,
    db: Session = Depends(get_db),
) -> MessageOut:
    if payload and payload.refresh_token:
        row = db.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_refresh_token(payload.refresh_token)
            )
        )
        if row is not None:
            row.revoked = True
            db.commit()
    return MessageOut(message="logged out")


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return UserOut.model_validate(user)
