from fastapi import APIRouter
from sqlalchemy import text

from app.config import settings
from app.database import engine
from app.services import executor
from app import llm

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database = "connected"
    except Exception:  # noqa: BLE001 - health must never raise
        database = "unavailable"

    return {
        "status": "ok" if database == "connected" else "degraded",
        "app": settings.app_name,
        "database": database,
        "auth_enabled": settings.auth_enabled,
        "llm_configured": settings.llm_enabled,
        "llm_model": settings.llm_model if settings.llm_enabled else None,
        "llm_usage": llm.stats() if settings.llm_enabled else None,
        "email_configured": settings.email_configured,
        "executor": executor.executor_health(),
    }
