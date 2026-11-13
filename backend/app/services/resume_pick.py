"""Pick the resume that fits a post best.

The human can keep several resumes (frontend, backend, AI, ...). For each post
the agent scores every resume against the post text and remembers the winner, so
the draft and the email attachment use the most relevant one.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import JobPost, Resume

_WORD_RE = re.compile(r"[a-z][a-z0-9+#.]{2,}")

_STOP = {
    "the", "and", "for", "with", "you", "your", "our", "are", "will", "have",
    "this", "that", "from", "they", "them", "who", "what", "when", "where",
    "hiring", "looking", "apply", "please", "role", "job", "team", "work",
    "more", "about", "into", "also", "been", "their", "would", "could", "need",
    "remote", "india", "years", "experience",
}


def _words(text: str) -> set[str]:
    return {word for word in _WORD_RE.findall((text or "").lower()) if word not in _STOP}


def pick_best(db: Session, job: JobPost) -> Resume | None:
    """Best resume for this post, or None when nothing is uploaded."""
    stmt = select(Resume)
    if job.user_id is not None:
        stmt = stmt.where(Resume.user_id == job.user_id)
    resumes = list(db.scalars(stmt).all())
    if not resumes:
        return None

    primary = next((resume for resume in resumes if resume.is_primary), resumes[0])
    job_words = _words(job.content)

    best = primary
    best_score = 0
    for resume in resumes:
        score = len(job_words & _words(resume.text))
        if resume.is_primary:
            score += 1  # tie-breaker
        if score > best_score:
            best, best_score = resume, score

    return best
