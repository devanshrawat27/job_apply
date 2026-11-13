"""Pull a candidate's public GitHub data and keep it on the profile.

Onboarding already asks for a GitHub link. This module turns that link into
concrete evidence the agent can use: real projects, languages and stars. No
OAuth and no private data - only the public GitHub API.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Profile

logger = logging.getLogger(__name__)

API = "https://api.github.com"
TIMEOUT = 12
MAX_REPOS = 100
TOP_PROJECTS = 5

_USER_RE = re.compile(r"github\.com/([A-Za-z0-9-]{1,39})", re.IGNORECASE)


def username_from(value: str) -> str:
    raw = (value or "").strip().strip("/")
    if not raw:
        return ""
    match = _USER_RE.search(raw)
    if match:
        return match.group(1)
    # Accept a bare username too.
    if re.fullmatch(r"[A-Za-z0-9-]{1,39}", raw):
        return raw
    return ""


def _headers() -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "JobPilot/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return headers


def _relative_days(value: str | None) -> int | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, (datetime.now(timezone.utc) - moment).days)


def _build_summary(user: dict, repos: list[dict]) -> tuple[str, dict]:
    languages = Counter()
    projects = []
    stars = 0

    for repo in repos:
        if repo.get("fork"):
            continue
        if repo.get("language"):
            languages[repo["language"]] += 1
        stars += int(repo.get("stargazers_count") or 0)
        if len(projects) < TOP_PROJECTS:
            projects.append(
                {
                    "name": repo.get("name") or "",
                    "description": (repo.get("description") or "")[:180],
                    "language": repo.get("language") or "",
                    "stars": int(repo.get("stargazers_count") or 0),
                    "url": repo.get("html_url") or "",
                    "topics": (repo.get("topics") or [])[:6],
                }
            )

    top_projects = sorted(
        [repo for repo in repos if not repo.get("fork")],
        key=lambda repo: int(repo.get("stargazers_count") or 0),
        reverse=True,
    )[:TOP_PROJECTS]
    projects = [
        {
            "name": repo.get("name") or "",
            "description": (repo.get("description") or "")[:180],
            "language": repo.get("language") or "",
            "stars": int(repo.get("stargazers_count") or 0),
            "url": repo.get("html_url") or "",
            "topics": (repo.get("topics") or [])[:6],
        }
        for repo in top_projects
    ]

    active_days = _relative_days(user.get("updated_at"))
    data = {
        "login": user.get("login") or "",
        "name": user.get("name") or "",
        "bio": (user.get("bio") or "")[:500],
        "company": user.get("company") or "",
        "location": user.get("location") or "",
        "public_repos": int(user.get("public_repos") or 0),
        "followers": int(user.get("followers") or 0),
        "stars": stars,
        "languages": [name for name, _ in languages.most_common(8)],
        "projects": projects,
        "active_days_ago": active_days,
        "profile_url": user.get("html_url") or "",
    }

    lines = [
        f"GitHub @{data['login']}: {data['public_repos']} public repos, {stars} stars."
        + (f" Active {active_days} day(s) ago." if active_days is not None else "")
    ]
    if data["languages"]:
        lines.append("Main languages: " + ", ".join(data["languages"]))
    if data["bio"]:
        lines.append(f"Bio: {data['bio']}")
    for project in projects:
        detail = project["name"]
        if project["language"]:
            detail += f" ({project['language']}"
            detail += f", {project['stars']}★)" if project["stars"] else ")"
        if project["description"]:
            detail += f" - {project['description']}"
        lines.append(detail)
    return "\n".join(lines), data


def sync(db: Session, profile: Profile, *, force: bool = False) -> dict:
    """Fetch the public repos and summarise them on the profile."""
    link = (profile.links or {}).get("github", "")
    username = username_from(link)
    if not username:
        return {"ok": False, "error": "no GitHub link on the profile"}

    if (
        not force
        and profile.github_username == username
        and (profile.github_summary or "").strip()
    ):
        return {"ok": True, "cached": True, "username": username}

    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
            user_res = client.get(f"{API}/users/{username}", headers=_headers())
            if user_res.status_code == 404:
                return {"ok": False, "error": f"GitHub user @{username} not found"}
            if user_res.status_code == 403:
                return {"ok": False, "error": "GitHub API rate limit - add GITHUB_TOKEN"}
            user_res.raise_for_status()
            user = user_res.json()

            repos_res = client.get(
                f"{API}/users/{username}/repos",
                headers=_headers(),
                params={"per_page": MAX_REPOS, "sort": "pushed", "type": "owner"},
            )
            repos = repos_res.json() if repos_res.status_code < 400 else []
            if not isinstance(repos, list):
                repos = []
    except httpx.HTTPError as exc:
        logger.warning("GitHub sync failed for %s: %s", username, exc)
        return {"ok": False, "error": f"GitHub request failed: {type(exc).__name__}"}

    summary, data = _build_summary(user, repos)
    profile.github_username = username
    profile.github_summary = summary
    profile.github_data = data
    profile.github_synced_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "username": username, "summary": summary, "data": data}
