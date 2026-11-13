"""Shared test environment. Everything here is offline: no X, no LLM provider."""

from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_jobpilot.db"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_API_KEYS"] = ""
os.environ["CREDENTIALS_ENCRYPTION_KEY"] = "5xQ0kK7o4m2r8y1p6s9t3v5w7z0a2b4c6d8e0f1g2h4="
os.environ["AUTH_ENABLED"] = "false"
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-for-offline-tests"

import pytest  # noqa: E402

from app.database import Base, engine  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _fresh_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
