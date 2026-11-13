"""Multiple resumes, and picking the best one for a post."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.database import SessionLocal
from app.main import app
from app.models import JobPost, Resume
from app.services import resume_pick

FRONTEND = b"""Dev Rawat
Frontend engineer. React, TypeScript, Next.js, Tailwind, Redux.
Built dashboards and design systems.
"""

BACKEND = b"""Dev Rawat
Backend engineer. Python, FastAPI, PostgreSQL, Redis, Docker, Celery.
Built APIs and data pipelines.
"""


def _client() -> TestClient:
    db = SessionLocal()
    db.execute(delete(Resume))
    db.execute(delete(JobPost))
    db.commit()
    db.close()
    return TestClient(app)


def test_add_two_resumes_and_pick_best():
    client = _client()

    first = client.post(
        "/api/profile/resumes",
        files={"file": ("frontend.txt", io.BytesIO(FRONTEND), "text/plain")},
        data={"label": "Frontend", "make_primary": "true"},
    )
    assert first.status_code == 200, first.text

    second = client.post(
        "/api/profile/resumes",
        files={"file": ("backend.txt", io.BytesIO(BACKEND), "text/plain")},
        data={"label": "Backend", "make_primary": "false"},
    )
    assert second.status_code == 200, second.text

    listing = client.get("/api/profile/resumes").json()
    assert len(listing) == 2
    assert sum(1 for row in listing if row["is_primary"]) == 1

    db = SessionLocal()
    try:
        backend_job = JobPost(
            post_id="r1",
            post_url="",
            author_handle="someone",
            content="Hiring a backend engineer. Python, FastAPI, PostgreSQL and Redis. DM me.",
        )
        frontend_job = JobPost(
            post_id="r2",
            post_url="",
            author_handle="someone",
            content="Hiring a frontend engineer. React, TypeScript, Next.js, Tailwind. DM me.",
        )

        assert resume_pick.pick_best(db, backend_job).label == "Backend"
        assert resume_pick.pick_best(db, frontend_job).label == "Frontend"
    finally:
        db.close()


def test_make_primary_and_delete():
    client = _client()

    client.post(
        "/api/profile/resumes",
        files={"file": ("a.txt", io.BytesIO(FRONTEND), "text/plain")},
        data={"label": "A", "make_primary": "true"},
    )
    row = client.post(
        "/api/profile/resumes",
        files={"file": ("b.txt", io.BytesIO(BACKEND), "text/plain")},
        data={"label": "B", "make_primary": "false"},
    ).json()

    promoted = client.post(f"/api/profile/resumes/{row['id']}/primary").json()
    assert promoted["is_primary"] is True
    assert client.get("/api/profile").json()["resume_filename"] == "b.txt"

    client.delete(f"/api/profile/resumes/{row['id']}")
    remaining = client.get("/api/profile/resumes").json()
    assert len(remaining) == 1
    assert remaining[0]["is_primary"] is True
