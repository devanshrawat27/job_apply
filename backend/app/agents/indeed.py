"""Turn Indeed search cards into reviewable jobs.

Indeed's search cards are structured by the browser script. The assessment rules
are shared with Naukri because the same profile, role and freshness checks apply.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.agents import naukri
from app.models import Profile


def search_terms(profile: Profile, limit: int = 3) -> list[str]:
    return naukri.search_terms(profile, limit=limit)


def assess(profile: Profile, card: dict) -> dict:
    # Indeed cards rarely carry an experience line; treat a missing value as a
    # fresher-friendly listing and let the title/snippet checks do the work.
    prepared = {
        **card,
        "experience": str(card.get("experience") or "fresher"),
        "skills": card.get("skills") or [],
    }
    return naukri.assess(profile, prepared)


def posted_datetime(value: str, *, now: datetime | None = None) -> datetime | None:
    text = str(value or "").strip().lower()
    if "just posted" in text or "posted today" in text or text.startswith("today"):
        return now or datetime.now(timezone.utc)
    return naukri.posted_datetime(value, now=now)
