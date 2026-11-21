"""Check that an application link actually opens a real, open job.

A post can say "apply here" and carry a link that is dead (404), a redirect back
to the post, an empty page, or a job that asks for far more experience than the
candidate has. The human should never waste a click on those.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Status codes that mean the page exists but blocks bots/logins. Not dead.
# 999 is LinkedIn's own "we do not serve this to you" answer.
AMBIGUOUS = {401, 403, 429, 999}
DEAD = {404, 410}

_SCRIPT_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# Text that means the job is gone even when the HTTP status is 200.
_GONE_MARKERS = (
    "job not found",
    "job no longer",
    "no longer available",
    "this job has expired",
    "job has expired",
    "position has been filled",
    "this position is closed",
    "applications are closed",
    "this posting is closed",
    "page not found",
    "page you requested",
    "vacancy is no longer",
)

_EXP_RE = re.compile(r"(\d{1,2})\s*(?:\+|plus)?\s*(?:-|–|to)?\s*(\d{1,2})?\s*years?", re.I)

# Pages that are never a job application.
_NOT_JOB_HOSTS = (
    "youtube.com",
    "youtu.be",
    "instagram.com",
    "facebook.com",
    "x.com",
    "twitter.com",
    "t.me",
    "discord.gg",
    "medium.com",
)
# A careers homepage is not a specific job.
_GENERIC_PATHS = {"", "/", "/careers", "/jobs", "/job", "/home", "/en", "/about"}
# Applicant tracking systems render with JavaScript, so short HTML text does not
# mean the job is missing.
_ATS_HOSTS = (
    "myworkdayjobs.com",
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "workable.com",
    "smartrecruiters.com",
    "icims.com",
    "taleo.net",
    "bamboohr.com",
    "jobvite.com",
    "breezy.hr",
    "recruitee.com",
    "zohorecruit.com",
    "successfactors.com",
)
_JOB_PATH_RE = re.compile(
    r"/(job|jobs|career|careers|position|positions|internship|internships|opening|openings)/",
    re.I,
)
_JOB_TEXT_MARKERS = (
    "apply",
    "responsibilit",
    "qualification",
    "job description",
    "we are hiring",
    "what you'll do",
    "requirements",
    "about the role",
    "job summary",
    "full-time",
    "salary",
    "experience",
)


def visible_text(html: str) -> str:
    text = _SCRIPT_RE.sub(" ", html or "")
    text = _TAG_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def page_experience_months(text: str) -> int:
    """Lowest stated experience requirement on the page, in months."""
    lowered = (text or "").lower()
    if re.search(r"\b(no experience|fresher|entry level|0-1 year|0\+? years?)\b", lowered):
        return 0
    lows: list[int] = []
    for match in _EXP_RE.finditer(lowered):
        try:
            lows.append(int(match.group(1)))
        except (TypeError, ValueError):
            continue
    lows = [value for value in lows if 0 <= value <= 20]
    return min(lows) * 12 if lows else 0


def dead_reason(html: str, text: str, final_url: str = "") -> str:
    parsed = urlparse(final_url or "")
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower().rstrip("/")

    if host and any(host.endswith(bad) for bad in _NOT_JOB_HOSTS):
        return "not a job page (video or social post)"
    if final_url and path in _GENERIC_PATHS:
        return "generic careers page, not a specific job"

    known_job_page = any(host.endswith(ats) for ats in _ATS_HOSTS) or bool(
        _JOB_PATH_RE.search(path)
    )

    lowered = (text or "").lower()
    for marker in _GONE_MARKERS:
        if marker in lowered[:4000]:
            return marker

    if len(lowered) < 120 and "jobposting" not in (html or "").lower():
        if not known_job_page:
            return "empty page"

    # A page with no job words at all is a homepage or a broken listing.
    if (
        not known_job_page
        and len(lowered) < 800
        and not any(marker in lowered for marker in _JOB_TEXT_MARKERS)
    ):
        return "no job details on the page"
    return ""


def check(
    url: str,
    timeout: float = 8.0,
    *,
    max_experience_months: int | None = None,
) -> tuple[bool, str]:
    """Return (ok, reason). ``ok`` is False only when the link is clearly bad."""
    target = (url or "").strip()
    if not target:
        return False, "empty link"
    if not target.lower().startswith(("http://", "https://")):
        target = f"https://{target}"

    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"},
        ) as client:
            response = client.get(target)
    except Exception as exc:  # noqa: BLE001 - DNS, TLS, timeouts, bad host
        return False, f"unreachable ({type(exc).__name__})"

    final = str(response.url)
    status = response.status_code

    if status in DEAD:
        return False, f"HTTP {status}"
    if status >= 500:
        return False, f"HTTP {status}"
    if "x.com/" in final and "/status/" in final:
        return False, "redirects back to the post"
    if status in AMBIGUOUS:
        # Login walls and bot protection are not proof of a dead job page.
        return True, ""

    html = response.text
    text = visible_text(html)
    reason = dead_reason(html, text, final)
    if reason:
        return False, reason

    if max_experience_months is not None:
        required = page_experience_months(text)
        if required and required > max_experience_months + 3:
            return False, f"page asks {required // 12}+ years experience"

    return True, ""
