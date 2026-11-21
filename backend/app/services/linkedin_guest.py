"""Read LinkedIn job listings through the public (logged-out) guest endpoints.

Two endpoints are used, both of which LinkedIn serves to anonymous visitors:

    GET /jobs-guest/jobs/api/seeMoreJobPostings/search   -> HTML job cards
    GET /jobs-guest/jobs/api/jobPosting/<job id>          -> HTML job detail

No cookies, no login, no password. Volume stays deliberately low: LinkedIn
throttles an IP after roughly ten result pages and answers 429/999. When that
happens the caller gets ``LinkedInBlocked`` and must pause instead of retrying.
"""

from __future__ import annotations

import html
import logging
import random
import re
import time
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

BASE = "https://www.linkedin.com"
SEARCH_PATH = "/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_PATH = "/jobs-guest/jobs/api/jobPosting/{job_id}"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)

# Throttle windows. A blocked IP can take an hour or more to recover.
BLOCK_MINUTES = 90
# LinkedIn's 999 is an anti-bot answer; back off longer than a plain 429.
HARD_BLOCK_MINUTES = 60

_cooldown_until: datetime | None = None
_last_reason = ""

# Behave like a slow human. Consecutive requests from the same IP with no gap
# get a 429 in only a few calls, which costs the whole pass.
MIN_GAP_SECONDS = 2.0
_last_request_at = 0.0

# A hard daily ceiling protects the IP from a rotation bug or repeated manual
# scans. LinkedIn throttles an IP long before this, so the cooldown usually
# fires first.
DAILY_REQUEST_LIMIT = 100
_daily_day = ""
_daily_requests = 0

# One persistent client keeps LinkedIn's own session cookies (JSESSIONID,
# bcookie, ...) between requests. A brand-new anonymous client for every call
# looks like a bot and gets a 429 after a couple of pages.
_client: httpx.Client | None = None


def _http() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "x-li-lang": "en_US",
            },
            timeout=35,
            follow_redirects=True,
        )
    return _client


def _wait_for_gap() -> None:
    global _last_request_at
    now = time.monotonic()
    gap = MIN_GAP_SECONDS + random.uniform(0.2, 1.0)
    wait = gap - (now - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


class LinkedInBlocked(Exception):
    """LinkedIn is throttling this IP. Nothing was read; wait and retry later."""

    def __init__(self, reason: str, retry_in_minutes: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_in_minutes = retry_in_minutes


class LinkedInError(Exception):
    """A request failed for a reason other than throttling."""


def cooldown_until() -> datetime | None:
    return _cooldown_until


def cooldown_reason() -> str:
    return _last_reason


def _set_cooldown(minutes: int, reason: str) -> None:
    global _cooldown_until, _last_reason
    _cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    _last_reason = reason
    logger.warning("LinkedIn cooldown for %s min: %s", minutes, reason)


def reset_cooldown() -> None:
    """Tests only."""
    global _cooldown_until, _last_reason, _daily_day, _daily_requests, _last_request_at, _client
    _cooldown_until = None
    _last_reason = ""
    _daily_day = ""
    _daily_requests = 0
    _last_request_at = 0.0
    if _client is not None:
        _client.close()
        _client = None


def _headers(path: str) -> dict[str, str]:
    referer = (
        f"{BASE}{path.split('?')[0]}"
        if "jobPosting" in path
        else f"{BASE}/jobs/search/"
    )
    return {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "x-li-lang": "en_US",
        "Referer": referer,
    }


def _note_request() -> None:
    global _daily_day, _daily_requests
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if day != _daily_day:
        _daily_day = day
        _daily_requests = 0
    _daily_requests += 1
    if _daily_requests > DAILY_REQUEST_LIMIT:
        _set_cooldown(360, "daily request limit")
        raise LinkedInBlocked(
            "daily LinkedIn request limit reached - resuming tomorrow", 360
        )


def _get(path: str, params: dict | None = None) -> str:
    if _cooldown_until is not None and datetime.now(timezone.utc) < _cooldown_until:
        raise LinkedInBlocked(
            f"paused after {_last_reason or 'a LinkedIn block'}",
            max(1, int((_cooldown_until - datetime.now(timezone.utc)).total_seconds() // 60)),
        )
    _note_request()
    _wait_for_gap()
    try:
        response = _http().get(
            f"{BASE}{path}",
            params=params,
            headers=_headers(path),
        )
    except httpx.HTTPError as exc:
        raise LinkedInError(f"could not reach LinkedIn: {exc}") from exc

    if response.status_code in (429, 999):
        _set_cooldown(BLOCK_MINUTES, f"HTTP {response.status_code}")
        raise LinkedInBlocked(f"LinkedIn rate limit (HTTP {response.status_code})", BLOCK_MINUTES)
    if response.status_code in (403, 401):
        _set_cooldown(HARD_BLOCK_MINUTES, f"HTTP {response.status_code}")
        raise LinkedInBlocked(f"LinkedIn refused the request (HTTP {response.status_code})", HARD_BLOCK_MINUTES)
    if "/authwall" in str(response.url) or "checkpoint" in str(response.url):
        _set_cooldown(HARD_BLOCK_MINUTES, "auth wall")
        raise LinkedInBlocked("LinkedIn asked for a login (auth wall)", HARD_BLOCK_MINUTES)
    if response.status_code != 200:
        raise LinkedInError(f"LinkedIn returned HTTP {response.status_code}")

    body = response.text or ""
    if "authwall" in body[:4000] or "checkpoint/challenge" in body[:4000]:
        _set_cooldown(HARD_BLOCK_MINUTES, "auth wall")
        raise LinkedInBlocked("LinkedIn asked for a login (auth wall)", HARD_BLOCK_MINUTES)
    return body


# --------------------------------------------------------------------- parsing


def _text(fragment: str) -> str:
    """Strip tags, unescape, collapse whitespace."""
    clean = re.sub(r"<[^>]+>", " ", fragment or "")
    return " ".join(html.unescape(clean).split())


def _first(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.S | re.I)
    return _text(match.group(1)) if match else ""


def _attr(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.S | re.I)
    return html.unescape(match.group(1)).strip() if match else ""


def normalize_job_url(url: str, job_id: str) -> str:
    if job_id:
        return f"{BASE}/jobs/view/{job_id}/"
    clean = (url or "").split("?")[0]
    return clean if clean.startswith("http") else ""


def clean_title(value: str) -> str:
    """Drop the duplicated prefix some LinkedIn cards put in the same heading.

    Example: "AI-Assisted Full Stack DevelopeAI-Assisted Full Stack Developer
    Intern — Remote" -> "AI-Assisted Full Stack Developer Intern — Remote".
    """
    text = " ".join((value or "").split())
    if len(text) < 80:
        return text
    lowered = text.lower()
    head = lowered[:25]
    if len(head) >= 10:
        index = lowered.find(head, 10)
        if 0 < index <= len(text) // 2:
            return text[index:].strip()
    half = len(text) // 2
    left, right = text[:half].strip().lower(), text[half:].strip().lower()
    if left and left == right:
        return text[half:].strip()
    return text


def parse_search_cards(body: str) -> list[dict]:
    """One dict per job card in the guest search HTML."""
    cards: list[dict] = []
    seen: set[str] = set()
    for match in re.finditer(r"<li>(.*?)</li>", body or "", re.S | re.I):
        block = match.group(1)
        job_id = _attr(r'data-entity-urn="urn:li:jobPosting:(\d+)"', block)
        if not job_id or job_id in seen:
            continue
        seen.add(job_id)
        title = _first(r'class="[^"]*base-search-card__title[^"]*"[^>]*>(.*?)</h3>', block)
        if not title:
            title = _first(r'class="[^"]*sr-only[^"]*"[^>]*>(.*?)</span>', block)
        title = clean_title(title)
        company = _first(
            r'class="[^"]*base-search-card__subtitle[^"]*"[^>]*>(.*?)</h4>', block
        )
        location = _first(
            r'class="[^"]*job-search-card__location[^"]*"[^>]*>(.*?)</span>', block
        )
        posted_text = _first(
            r'class="[^"]*job-search-card__listdate[^"]*"[^>]*>(.*?)</time>', block
        )
        posted = _attr(r"<time[^>]*datetime=\"([^\"]+)\"", block)
        if not posted:
            posted = posted_text
        href = _attr(r'class="[^"]*base-card__full-link[^"]*"[^>]*href="([^"]+)"', block)
        company_url = _attr(
            r'class="[^"]*base-search-card__subtitle[^"]*"[\s\S]*?<a[^>]*href="([^"]+)"',
            block,
        )
        cards.append(
            {
                "job_id": job_id,
                "title": title,
                "company": company,
                "location": location,
                "posted_at": posted,
                "posted_text": posted_text or posted,
                "url": normalize_job_url(href, job_id),
                "company_url": company_url.split("?")[0] if company_url else "",
            }
        )
    return cards


def parse_detail(body: str, job_id: str = "") -> dict:
    """Structured fields out of a guest job posting page."""
    title = _first(r'class="[^"]*top-card-layout__title[^"]*"[^>]*>(.*?)</h[12]>', body)
    if not title:
        title = _first(r'class="[^"]*topcard__title[^"]*"[^>]*>(.*?)</h[12]>', body)
    if not title:
        page_title = _first(r"<title>(.*?)</title>", body)
        if page_title:
            title = re.split(r"\s*\|\s*LinkedIn|\s+at\s+", page_title)[0].strip()
    title = clean_title(title)
    company = _first(r'class="[^"]*topcard__org-name-link[^"]*"[^>]*>(.*?)</a>', body)
    if not company:
        company = _first(r'class="[^"]*topcard__flavor[^"]*"[^>]*>(.*?)</span>', body)
    location = _first(r'class="[^"]*topcard__flavor--bullet[^"]*"[^>]*>(.*?)</span>', body)
    description = _first(
        r'class="[^"]*show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>', body
    )
    if not description:
        description = _first(r'class="[^"]*description__text[^"]*"[^>]*>(.*?)</div>', body)
    company_url = _attr(r'class="[^"]*topcard__org-name-link[^"]*"[^>]*href="([^"]+)"', body)
    applicants = _first(r'class="[^"]*num-applicants__caption[^"]*"[^>]*>(.*?)</span>', body)
    posted = _attr(r'class="[^"]*posted-time-ago__text[^"]*"[^>]*datetime="([^"]+)"', body)
    if not posted:
        posted = _first(
            r'class="[^"]*posted-time-ago__text[^"]*"[^>]*>(.*?)</span>', body
        )

    criteria: dict[str, str] = {}
    for item in re.finditer(
        r'class="[^"]*job-criteria__item[^"]*"[^>]*>(.*?)</li>', body, re.S | re.I
    ):
        block = item.group(1)
        name = _first(r'class="[^"]*job-criteria__subheader[^"]*"[^>]*>(.*?)</h3>', block)
        value = _first(r'class="[^"]*job-criteria__text[^"]*"[^>]*>(.*?)</span>', block)
        if name and value:
            criteria[name.lower()] = value

    salary = ""
    salary_match = re.search(
        r'class="[^"]*(?:compensation__salary|salary)[^"]*"[^>]*>(.*?)</span>', body, re.S
    )
    if salary_match:
        salary = _text(salary_match.group(1))

    return {
        "job_id": job_id,
        "title": title,
        "company": company,
        "location": location,
        "description": description,
        "company_url": company_url.split("?")[0] if company_url else "",
        "applicants": applicants,
        "posted_at": posted,
        "posted_text": posted,
        "seniority": criteria.get("seniority level", ""),
        "employment_type": criteria.get("employment type", ""),
        "job_function": criteria.get("job function", ""),
        "industries": criteria.get("industries", ""),
        "salary": salary,
        "easy_apply": "easy apply" in body.lower(),
    }


# --------------------------------------------------------------------- public


def search_jobs(
    keyword: str,
    *,
    location: str = "India",
    since_hours: int = 24,
    experience: tuple[int, ...] = (1, 2, 3),
    job_types: str = "F,I",
    start: int = 0,
) -> list[dict]:
    """Up to ten job cards for one keyword. Raises LinkedInBlocked/Error."""
    params: dict[str, object] = {
        "keywords": keyword,
        "location": location,
        "start": max(0, start),
        "f_TPR": f"r{max(1, since_hours) * 3600}",
        "sortBy": "DD",
    }
    if experience:
        params["f_E"] = ",".join(str(level) for level in experience)
    if job_types:
        params["f_JT"] = job_types
    body = _get(SEARCH_PATH, params)
    return parse_search_cards(body)


def job_detail(job_id: str) -> dict:
    if not str(job_id).isdigit():
        raise LinkedInError("invalid job id")
    body = _get(DETAIL_PATH.format(job_id=job_id))
    return parse_detail(body, job_id=str(job_id))


def posted_age_minutes(value) -> int | None:
    """Age in minutes from a LinkedIn relative time ("2 hours ago", "30 minutes")."""
    text = str(value or "").strip().lower()
    if not text:
        return None
    if "just" in text or text in ("now", "today"):
        return 0
    match = re.search(r"(\d+)\s*(minute|hour|day|week|month)", text)
    if match:
        count = int(match.group(1))
        unit = match.group(2)
        if unit == "minute":
            return count
        if unit == "hour":
            return count * 60
        if unit == "day":
            return count * 60 * 24
        if unit == "week":
            return count * 60 * 24 * 7
        return count * 60 * 24 * 30
    parsed = posted_datetime(text)
    if parsed is None:
        return None
    return max(0, int((datetime.now(timezone.utc) - parsed).total_seconds() // 60))


def posted_datetime(value) -> datetime | None:
    """Best-effort date from a card/detail value ("2026-11-20", "2 days ago")."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        pass
    lowered = text.lower()
    minutes = 0
    number = re.search(r"(\d+)", lowered)
    count = int(number.group(1)) if number else 0
    if "minute" in lowered:
        minutes = count
    elif "hour" in lowered:
        minutes = count * 60
    elif "day" in lowered:
        minutes = count * 60 * 24
    elif "week" in lowered:
        minutes = count * 60 * 24 * 7
    elif "month" in lowered:
        minutes = count * 60 * 24 * 30
    else:
        return None
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)
