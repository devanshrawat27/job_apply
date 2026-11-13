"""Seed the UI with clearly-labelled demo posts, or clear them.

    python -m scripts.seed_demo          # add demo posts
    python -m scripts.seed_demo --ui     # also complete onboarding with a demo account
    python -m scripts.seed_demo --clear  # remove demo posts

Demo rows use post ids that start with "demo-" so they can never collide with a
real X status id (which is always numeric).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import JobPost, Profile, XAccount
from app.security import encrypt_credentials


def _ensure_demo_account(db) -> None:
    """Make the workspace reachable without a real X login."""
    profile = db.get(Profile, 1)
    if profile is None:
        profile = Profile(id=1)
        db.add(profile)

    profile.full_name = profile.full_name or "Demo User"
    profile.job_title = profile.job_title or "Full Stack Developer"
    profile.seniority = profile.seniority or "junior"
    profile.experience_months = profile.experience_months or 18
    profile.current_role = profile.current_role or "Full Stack Developer"
    profile.current_company = profile.current_company or "Freelance"
    profile.skills = profile.skills or ["React", "Python", "FastAPI", "Node.js"]
    profile.locations = profile.locations or ["Remote"]
    profile.remote_ok = True
    profile.pitch = profile.pitch or "I build production web apps with React and FastAPI."
    profile.onboarding_completed = True

    account = db.scalar(select(XAccount).where(XAccount.username == "demo"))
    if account is None:
        account = XAccount(username="demo", display_name="Demo account")
        db.add(account)
    account.session_ciphertext = encrypt_credentials(
        {"auth_token": "demo", "ct0": "demo", "twid": "u=demo"}
    )
    account.status = "connected"
    db.commit()


def _demo_rows() -> list[JobPost]:
    now = datetime.now(timezone.utc)
    return [
        JobPost(
            post_id="demo-001",
            post_url="https://x.com/example/status/1",
            author_handle="acmehiring",
            author_name="Acme Hiring",
            content=(
                "[DEMO] We're hiring a backend engineer (Python + FastAPI) to build "
                "our agent platform. Fully remote, 2-5 yrs. DM me if interested."
            ),
            posted_at=now - timedelta(hours=1),
            relevance=88,
            company="Acme",
            role="Backend Engineer",
            job_location="remote",
            apply_method="dm",
            contact="acmehiring",
            reason="Clear role match; the post asks to DM.",
            confidence=0.63,
            uncertainties=["salary not stated"],
            reply_text=(
                "This is right in my lane — I build FastAPI backends and agent "
                "systems. Sending you a DM with my work."
            ),
            dm_text=(
                "Hi Acme team — saw your backend engineer post.\n"
                "I've shipped FastAPI services and agent pipelines in production.\n"
                "Happy to share my GitHub if the role is still open."
            ),
            status="pending_approval",
            logs=["[DEMO] drafted, waiting for approval"],
        ),
        JobPost(
            post_id="demo-002",
            post_url="https://x.com/example/status/2",
            author_handle="founderxyz",
            author_name="Founder XYZ",
            content=(
                "[DEMO] Looking for a React developer for a 6-week contract. "
                "React, TypeScript, Tailwind. Remote. DM for details."
            ),
            posted_at=now - timedelta(hours=3),
            relevance=74,
            company="XYZ Labs",
            role="React Developer",
            job_location="remote",
            apply_method="dm",
            contact="founderxyz",
            reason="Good stack match, contract length unclear.",
            confidence=0.91,
            uncertainties=[],
            reply_text="Sent you a DM — React + TypeScript is my daily stack.",
            dm_text=(
                "Hey — saw the 6-week React contract.\n"
                "I ship React/TS/Tailwind products and can start quickly.\n"
                "Want me to send over two relevant projects?"
            ),
            status="sent",
            reply_status="sent",
            dm_status="sent",
            sent_at=now - timedelta(minutes=20),
            logs=["[DEMO] sent reply + DM"],
        ),
        JobPost(
            post_id="demo-003",
            post_url="https://x.com/example/status/3",
            author_handle="cheapwork",
            author_name="Cheap Work",
            content="[DEMO] Unpaid internship, commission only. React dev needed. DM for details only.",
            posted_at=now - timedelta(hours=5),
            relevance=66,
            status="rejected",
            reason="Red flags: unpaid, commission only.",
            confidence=0.2,
            uncertainties=["post contains a red flag: unpaid"],
            logs=["[DEMO] skipped"],
        ),
    ]


def main() -> None:
    db = SessionLocal()
    try:
        db.execute(delete(JobPost).where(JobPost.post_id.like("demo-%")))
        db.commit()

        if "--clear" not in sys.argv:
            if "--ui" in sys.argv:
                _ensure_demo_account(db)
            db.add_all(_demo_rows())
            db.commit()
            print("seeded 3 demo posts")
        else:
            print("demo posts cleared")
    finally:
        db.close()


if __name__ == "__main__":
    main()
