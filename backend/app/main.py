"""FastAPI entry point for the JobPilot X outreach agent."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import update

from app.config import settings
from app.database import Base, SessionLocal, engine, ensure_schema
from app.deps import get_current_user
from app.models import JobPost, Run
from app.routers import (
    accounts,
    auth,
    health,
    jobs,
    keywords,
    llm,
    outreach,
    profile,
    runs,
    settings as settings_router,
)
from app.services import pipeline, scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("jobpilot")


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema()

    db = SessionLocal()
    try:
        pipeline.get_settings_row(db)
        # A restart can leave a run marked "running"; close it out.
        db.execute(
            update(Run)
            .where(Run.status == "running")
            .values(status="failed", error="interrupted by a restart")
        )
        # A crash mid-send leaves jobs stuck in "sending"; put them back in line.
        db.execute(update(JobPost).where(JobPost.status == "sending").values(status="queued"))
        db.commit()
    finally:
        db.close()

    if settings.scheduler_enabled:
        loop = scheduler.start()
        if loop is not None:
            logger.info("agent loop started")
        else:
            logger.warning("agent loop not started in this worker (lock held or disabled)")
    else:
        logger.info("agent loop disabled (SCHEDULER_ENABLED=false)")

    yield

    scheduler.stop()


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Never echo submitted values back.

    The X connect flow submits a password; FastAPI's default 422 payload
    includes the offending input, which would leak it into logs/clients.
    """
    errors = [
        {key: value for key, value in error.items() if key in {"type", "loc", "msg"}}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_prefix = "/api"
app.include_router(health.router, prefix=api_prefix)
app.include_router(auth.router, prefix=api_prefix)

# Everything below requires a valid access token when AUTH_ENABLED=true.
protected = APIRouter(dependencies=[Depends(get_current_user)])
protected.include_router(profile.router)
protected.include_router(accounts.router)
protected.include_router(settings_router.router)
protected.include_router(jobs.router)
protected.include_router(keywords.router)
protected.include_router(llm.router)
protected.include_router(outreach.router)
protected.include_router(runs.router)
app.include_router(protected, prefix=api_prefix)


@app.get("/")
def root() -> dict:
    return {"app": settings.app_name, "docs": "/docs", "health": "/api/health"}
