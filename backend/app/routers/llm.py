"""Per-user LLM credentials (ChatGPT/OpenAI etc.) and the analyst's insights."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import analyst
from app.database import get_db
from app.deps import CurrentUser
from app.llm import LLMUnavailable, complete_json
from app.models import LLMApiKey
from app.security import decrypt_credentials, encrypt_credentials
from app.services import pipeline

router = APIRouter(prefix="/llm", tags=["llm"])

OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


def _uid(user: CurrentUser) -> int | None:
    return user.id if user is not None else None


class LLMKeyIn(BaseModel):
    label: str = Field(default="ChatGPT", max_length=80)
    provider: str = Field(default="openai", max_length=40)
    api_key: str = Field(min_length=8, max_length=400)
    base_url: str = Field(default=OPENAI_BASE_URL, max_length=300)
    model: str = Field(default=DEFAULT_MODEL, max_length=120)
    enabled: bool = True


class LLMKeyOut(BaseModel):
    id: int
    label: str
    provider: str
    masked: str
    base_url: str
    model: str
    enabled: bool


def _masked(row: LLMApiKey) -> str:
    creds = decrypt_credentials(row.key_ciphertext) or {}
    key = str(creds.get("api_key") or "")
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


def _out(row: LLMApiKey) -> LLMKeyOut:
    return LLMKeyOut(
        id=row.id,
        label=row.label,
        provider=row.provider,
        masked=_masked(row),
        base_url=row.base_url,
        model=row.model,
        enabled=bool(row.enabled),
    )


def _scoped(db: Session, user_id: int | None):
    stmt = select(LLMApiKey)
    if user_id is None:
        stmt = stmt.where(LLMApiKey.user_id.is_(None))
    else:
        stmt = stmt.where(LLMApiKey.user_id == user_id)
    return stmt


@router.get("/keys", response_model=list[LLMKeyOut])
def list_keys(user: CurrentUser = None, db: Session = Depends(get_db)):
    rows = db.scalars(_scoped(db, _uid(user)).order_by(LLMApiKey.id)).all()
    return [_out(row) for row in rows]


@router.post("/keys", response_model=LLMKeyOut)
def save_key(payload: LLMKeyIn, user: CurrentUser = None, db: Session = Depends(get_db)):
    user_id = _uid(user)
    row = db.scalar(
        _scoped(db, user_id).where(LLMApiKey.label == payload.label).limit(1)
    )
    if row is None:
        row = LLMApiKey(user_id=user_id, label=payload.label)
        db.add(row)

    row.provider = payload.provider.strip() or "openai"
    row.base_url = (payload.base_url or OPENAI_BASE_URL).rstrip("/")
    row.model = payload.model.strip() or DEFAULT_MODEL
    row.enabled = bool(payload.enabled)
    row.key_ciphertext = encrypt_credentials({"api_key": payload.api_key.strip()})
    db.commit()
    db.refresh(row)
    return _out(row)


@router.delete("/keys/{key_id}")
def delete_key(key_id: int, user: CurrentUser = None, db: Session = Depends(get_db)):
    row = db.scalar(_scoped(db, _uid(user)).where(LLMApiKey.id == key_id).limit(1))
    if row is None:
        raise HTTPException(status_code=404, detail="Key not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.post("/keys/{key_id}/test")
def test_key(key_id: int, user: CurrentUser = None, db: Session = Depends(get_db)):
    row = db.scalar(_scoped(db, _uid(user)).where(LLMApiKey.id == key_id).limit(1))
    if row is None:
        raise HTTPException(status_code=404, detail="Key not found")

    providers = pipeline.llm_providers(db, _uid(user))
    try:
        data = complete_json(
            "You are a health check. Reply with JSON only.",
            'Return exactly {"ok": true} and nothing else.',
            temperature=0.0,
            max_tokens=30,
            budget_s=30,
            providers=providers,
        )
    except LLMUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:300])
    return {"ok": bool(data.get("ok", True)), "model": row.model}


@router.get("/chatgpt/status")
def chatgpt_status(user: CurrentUser = None, db: Session = Depends(get_db)):
    from app.services import browser_chatgpt

    row = pipeline.get_settings_row(db, _uid(user))
    return {
        "connected": browser_chatgpt.connected(),
        "enabled": bool(row.chatgpt_browser_enabled),
        "profile": str(browser_chatgpt.marker_path().parent),
    }


@router.get("/chatgpt/account")
def chatgpt_account(user: CurrentUser = None):
    from app.services import browser_chatgpt

    info = browser_chatgpt.account()
    if info is None:
        raise HTTPException(
            status_code=404,
            detail="No ChatGPT account found - reconnect ChatGPT in Settings",
        )
    return info


@router.post("/chatgpt/connect")
def chatgpt_connect(user: CurrentUser = None, db: Session = Depends(get_db)):
    """Open chatgpt.com and wait for the human to log in (up to ~5 minutes)."""
    from app.services import browser_chatgpt

    result = browser_chatgpt.login()
    if not result.get("success"):
        raise HTTPException(
            status_code=400,
            detail=str(result.get("error") or result.get("code") or "ChatGPT login failed")[:300],
        )
    row = pipeline.get_settings_row(db, _uid(user))
    row.chatgpt_browser_enabled = True
    db.commit()
    return {"connected": True, "enabled": True}


@router.post("/chatgpt/disconnect")
def chatgpt_disconnect(user: CurrentUser = None, db: Session = Depends(get_db)):
    from app.services import browser_chatgpt

    marker = browser_chatgpt.marker_path()
    try:
        marker.unlink(missing_ok=True)
    except OSError:
        pass
    row = pipeline.get_settings_row(db, _uid(user))
    row.chatgpt_browser_enabled = False
    db.commit()
    return {"connected": False, "enabled": False}


@router.get("/watcher/latest")
def latest_watcher(user: CurrentUser = None, db: Session = Depends(get_db)):
    from app.agents import watcher

    row = watcher.latest(db, _uid(user))
    if row is None:
        return {"report": None}
    return {
        "report": {
            "id": row.id,
            "summary": row.summary,
            "payload": row.payload or {},
            "created_at": row.created_at,
        }
    }


@router.post("/watcher/check")
def watcher_check(user: CurrentUser = None, db: Session = Depends(get_db)):
    from app.agents import watcher
    from app.services import browser_chatgpt

    user_id = _uid(user)
    settings_row = pipeline.get_settings_row(db, user_id)
    providers = pipeline.llm_providers(db, user_id)
    use_browser = bool(settings_row.chatgpt_browser_enabled) and browser_chatgpt.connected()
    try:
        payload = watcher.review(db, user_id, providers=providers, browser=use_browser)
    except LLMUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:300])
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:300])
    return {"report": payload}


@router.get("/insights/latest")
def latest_insight(user: CurrentUser = None, db: Session = Depends(get_db)):
    row = analyst.latest(db, _uid(user))
    if row is None:
        return {"insight": None}
    return {
        "insight": {
            "id": row.id,
            "kind": row.kind,
            "summary": row.summary,
            "payload": row.payload or {},
            "created_at": row.created_at,
        }
    }


@router.post("/insights/refresh")
def refresh_insight(user: CurrentUser = None, db: Session = Depends(get_db)):
    from app.services import browser_chatgpt

    user_id = _uid(user)
    row = pipeline.get_settings_row(db, user_id)
    providers = pipeline.llm_providers(db, user_id)
    use_browser = bool(row.chatgpt_browser_enabled) and browser_chatgpt.connected()
    try:
        payload = analyst.review_keywords(
            db, user_id, providers=providers, browser=use_browser
        )
    except LLMUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:300])
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:300])
    return {"insight": payload}
