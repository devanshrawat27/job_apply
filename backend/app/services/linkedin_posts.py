"""Read LinkedIn search posts with the member's own session cookies.

LinkedIn has no public post search: the page is rendered from an RSC stream
behind a login. This module sends the same request the web app sends and reads
the stream defensively. It is read-only, and volume stays deliberately low.

Everything here is best-effort: if LinkedIn changes the stream shape, the
parser returns fewer posts instead of inventing them.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

BASE = "https://www.linkedin.com"
CONTENT_SEARCH = "/flagship-web/search/results/content/"
ME = "/voyager/api/me"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)

BLOCK_MINUTES = 90
_cooldown_until: datetime | None = None
_last_reason = ""


class PostsUnavailable(Exception):
    """The saved session cannot be used (missing cookies, wrong shape)."""


class PostsAuthRequired(Exception):
    """LinkedIn rejected the session; the member must reconnect."""


class PostsBlocked(Exception):
    """LinkedIn is throttling; stop and retry later."""

    def __init__(self, reason: str, retry_in_minutes: int = BLOCK_MINUTES) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_in_minutes = retry_in_minutes


def cooldown_until() -> datetime | None:
    return _cooldown_until


def cooldown_reason() -> str:
    return _last_reason


def reset_cooldown() -> None:
    global _cooldown_until, _last_reason
    _cooldown_until = None
    _last_reason = ""


def _block(reason: str) -> None:
    global _cooldown_until, _last_reason
    _cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=BLOCK_MINUTES)
    _last_reason = reason
    logger.warning("LinkedIn posts cooldown for %s min: %s", BLOCK_MINUTES, reason)


def _headers(credentials: dict[str, str], *, referer: str, rsc: bool = False) -> dict[str, str]:
    session = credentials.get("JSESSIONID", "")
    csrf = session.strip('"')
    cookie_parts = []
    for name in ("li_at", "JSESSIONID", "bcookie", "lidc", "liap"):
        value = credentials.get(name)
        if value:
            cookie_parts.append(f"{name}={value}")
    headers = {
        "cookie": "; ".join(cookie_parts),
        "csrf-token": csrf,
        "accept": "application/vnd.linkedin.normalized+json+2.1",
        "accept-language": "en-US,en;q=0.9",
        "origin": BASE,
        "referer": referer,
        "user-agent": USER_AGENT,
        "x-li-lang": "en_US",
        "x-li-page-instance": f"urn:li:page:d_flagship3_search_srp_content;{uuid.uuid4()}",
        "x-restli-protocol-version": "2.0.0",
        "x-li-track": json.dumps(
            {
                "clientVersion": "1.13.47316",
                "mpVersion": "1.13.47316",
                "osName": "web",
                "timezoneOffset": 5.5,
                "timezone": "Asia/Kolkata",
                "deviceFormFactor": "DESKTOP",
                "mpName": "voyager-web",
                "displayDensity": 1,
                "displayWidth": 1920,
                "displayHeight": 1080,
            }
        ),
    }
    if rsc:
        headers.update(
            {
                "accept": "*/*",
                "content-type": "application/json",
                "x-li-rsc-stream": "true",
                "x-li-anchor-page-key": "d_flagship3_search_srp_content",
            }
        )
    return headers


def check_session(credentials: dict[str, str]) -> tuple[bool, str]:
    """Only a 401/sign-in redirect is proof that the saved cookies are dead."""
    if not credentials.get("li_at") or not credentials.get("JSESSIONID"):
        return False, "missing LinkedIn session cookies"
    try:
        with httpx.Client(
            headers=_headers(credentials, referer=f"{BASE}/feed/"),
            timeout=25,
            follow_redirects=False,
        ) as client:
            response = client.get(f"{BASE}{ME}")
    except httpx.HTTPError:
        return True, ""
    if response.status_code == 401:
        return False, "LinkedIn rejected the session"
    if response.status_code == 403:
        # A permission/bot check is ambiguous; do not force a reconnect.
        return True, ""
    if 300 <= response.status_code < 400:
        location = response.headers.get("location", "")
        if "/login" in location or "/authwall" in location or "/checkpoint" in location:
            return False, "LinkedIn asked for a sign-in"
    return True, ""


def _query_body(keyword: str) -> dict:
    return {
        "$type": "proto.sdui.actions.core.NavigateToScreen",
        "screenId": "com.linkedin.sdui.flagshipnav.search.SearchResultsContent",
        "pageKey": "search_srp_content",
        "presentationStyle": "PresentationStyle_FULL_PAGE",
        "presentation": {"$type": "proto.sdui.actions.core.presentation.FullPagePresentation"},
        "title": "Search",
        "newHierarchy": {
            "$type": "proto.sdui.navigation.ScreenHierarchy",
            "screenHash": "com.linkedin.sdui.flagshipnav.home.Home#0",
            "screenId": "com.linkedin.sdui.flagshipnav.home.Home",
            "pageKey": "",
            "isAnchorPage": False,
            "childHierarchy": {
                "$type": "proto.sdui.navigation.ScreenHierarchy",
                "screenHash": "com.linkedin.sdui.flagshipnav.search.SearchResults#0",
                "screenId": "com.linkedin.sdui.flagshipnav.search.SearchResults",
                "pageKey": "",
                "isAnchorPage": False,
                "childHierarchy": {
                    "$type": "proto.sdui.navigation.ScreenHierarchy",
                    "screenHash": "com.linkedin.sdui.flagshipnav.search.SearchResultsContent#0",
                    "screenId": "com.linkedin.sdui.flagshipnav.search.SearchResultsContent",
                    "pageKey": "",
                    "isAnchorPage": False,
                    "url": "",
                },
                "url": "",
            },
            "url": "",
        },
        "url": f"/search/results/content/?keywords={keyword}&origin=FACETED_SEARCH",
        "inheritActor": False,
        "colorScheme": "ColorScheme_UNKNOWN",
        "disableScreenGutters": False,
        "shouldHideMobileTopNavBar": True,
        "shouldHideLoadingSpinner": False,
        "screenTitle": ["Search"],
        "replaceCurrentScreen": False,
        "shouldHideMobileTopNavBarDivider": False,
        "requestedArguments": {
            "payload": {"keywords": keyword, "origin": "FACETED_SEARCH", "sortBy": ["date_posted"]},
            "states": [],
            "requestMetadata": {"$type": "proto.sdui.common.RequestMetadata"},
            "screenId": "",
        },
    }


def search_posts(
    credentials: dict[str, str],
    keyword: str,
    *,
    limit: int = 20,
    date_posted: str = "past-24h",
) -> list[dict]:
    """Return recent posts for one keyword. Read-only."""
    if _cooldown_until is not None and datetime.now(timezone.utc) < _cooldown_until:
        raise PostsBlocked(f"paused after {_last_reason or 'a LinkedIn block'}")
    if not credentials.get("li_at") or not credentials.get("JSESSIONID"):
        raise PostsUnavailable("no LinkedIn session")

    params = {"keywords": keyword, "origin": "FACETED_SEARCH"}
    params["sortBy"] = '["date_posted"]'
    params["datePosted"] = f'["{date_posted}"]'
    referer = f"{BASE}/search/results/content/?keywords={keyword}&origin=FACETED_SEARCH"
    try:
        with httpx.Client(
            headers=_headers(credentials, referer=referer, rsc=True),
            timeout=45,
            follow_redirects=False,
        ) as client:
            response = client.post(
                f"{BASE}{CONTENT_SEARCH}",
                params=params,
                content=json.dumps(_query_body(keyword)),
            )
    except httpx.HTTPError as exc:
        raise PostsUnavailable(f"could not reach LinkedIn: {exc}") from exc

    if response.status_code == 401:
        raise PostsAuthRequired("LinkedIn rejected the session")
    if response.status_code == 403:
        _block("HTTP 403")
        raise PostsBlocked("LinkedIn refused the post search (HTTP 403)")
    if response.status_code in (429, 999):
        _block(f"HTTP {response.status_code}")
        raise PostsBlocked(f"LinkedIn rate limit (HTTP {response.status_code})")
    if 300 <= response.status_code < 400:
        location = response.headers.get("location", "")
        if "/login" in location or "/checkpoint" in location or "/authwall" in location:
            raise PostsAuthRequired("LinkedIn asked for a sign-in")
    if response.status_code != 200:
        raise PostsUnavailable(f"LinkedIn returned HTTP {response.status_code}")

    posts = parse_rsc_posts(response.text)
    return posts[:limit]


# --------------------------------------------------------------------- parser

_SKIP_KEYS = {
    "className",
    "fontFamily",
    "fontSize",
    "fontStyle",
    "fontWeight",
    "lineHeight",
    "textAlign",
    "color",
    "style",
    "legacyControlName",
    "viewTrackingSpecs",
    "href",
    "url",
    "trackingId",
    "referenceId",
    "id",
    "componentKey",
    "text-attr-0",
}
_ID_LIKE = re.compile(r"^(\$L?[0-9a-f]+|text-attr-\d+|auto-component-\d+|[\$0-9a-f]{1,4})$", re.I)


def _collect_text(node, out: list[str], depth: int = 0) -> None:
    if depth > 14:
        return
    if isinstance(node, str):
        text = node.strip()
        if not text or text in ("$",) or _ID_LIKE.match(text):
            return
        out.append(text)
        return
    if isinstance(node, list):
        for value in node:
            _collect_text(value, out, depth + 1)
        return
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _SKIP_KEYS:
                continue
            if key in ("children", "textProps", "text", "content", "commentary", "textComponent"):
                _collect_text(value, out, depth + 1)
        return


def _walk_find(node, key: str, depth: int = 0):
    if depth > 15:
        return None
    if isinstance(node, dict):
        if key in node and not isinstance(node[key], (dict, list)):
            return node[key]
        for value in node.values():
            found = _walk_find(value, key, depth + 1)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _walk_find(value, key, depth + 1)
            if found is not None:
                return found
    return None


def _rsc_lines(text: str) -> list[tuple[int, object]]:
    """(position, parsed JSON) for every ``id:{...}`` line in the RSC stream."""
    out: list[tuple[int, object]] = []
    position = 0
    for raw in (text or "").splitlines():
        start = text.find(raw, position) if raw else position
        position = max(position, start + len(raw))
        match = re.match(r"^([0-9a-f]+):(.+)$", raw.strip())
        if not match:
            continue
        try:
            value = json.loads(match.group(2))
        except (ValueError, TypeError):
            continue
        out.append((start, value))
    return out


def _posted_at(value, depth: int = 0) -> datetime | None:
    if depth > 10:
        return None
    if isinstance(value, dict):
        for key in ("postedAt", "createdAt", "publishedAt", "timestamp"):
            found = value.get(key)
            if isinstance(found, (int, float)) and found > 10**11:
                return datetime.fromtimestamp(found / 1000, tz=timezone.utc)
            if isinstance(found, str) and found.isdigit() and len(found) >= 13:
                return datetime.fromtimestamp(int(found) / 1000, tz=timezone.utc)
        for child in value.values():
            result = _posted_at(child, depth + 1)
            if result:
                return result
    elif isinstance(value, list):
        for child in value:
            result = _posted_at(child, depth + 1)
            if result:
                return result
    return None


def _author_url(slug_url: str, author: str) -> str:
    match = re.match(r"https://www\.linkedin\.com/posts/([^_/?#]+)", slug_url or "")
    if match:
        return f"{BASE}/in/{match.group(1)}/"
    return ""


def parse_rsc_posts(text: str) -> list[dict]:
    """Best-effort parse of the content-search stream.

    Each result keeps the author, the profile URL (when derivable), the text and
    the post URL. Missing pieces stay missing; nothing is invented.
    """
    if not text:
        return []

    regions: list[tuple[int, str]] = []
    anchors: list[tuple[int, dict]] = []
    legacy: list[tuple[int, dict]] = []

    for position, value in _rsc_lines(text):
        raw = json.dumps(value)
        if "commentary_text" in raw:
            collected: list[str] = []
            _collect_text(value, collected)
            content = " ".join(" ".join(collected).split())
            if content:
                regions.append((position, content))
        if "actorName" in raw and ("postSlugUrl" in raw or "activityId" in raw):
            activity = _walk_find(value, "activityId")
            slug_url = _walk_find(value, "postSlugUrl") or ""
            author = _walk_find(value, "actorName") or ""
            if activity or slug_url:
                anchors.append(
                    (
                        position,
                        {
                            "activity_id": str(activity or ""),
                            "author": str(author),
                            "slug_url": str(slug_url),
                            "posted_at": _posted_at(value),
                        },
                    )
                )
        elif "postUrl" in raw or "urn:li:ugcPost:" in raw or "urn:li:activity:" in raw:
            post_url = _walk_find(value, "postUrl") or ""
            urn = _walk_find(value, "urn") or ""
            if post_url or urn:
                legacy.append((position, {"post_url": str(post_url), "urn": str(urn)}))

    posts: list[dict] = []
    if anchors:
        anchors.sort(key=lambda item: item[0])
        regions.sort(key=lambda item: item[0])
        pending: list[str] = []
        region_index = 0
        for position, anchor in anchors:
            while region_index < len(regions) and regions[region_index][0] < position:
                pending.append(regions[region_index][1])
                region_index += 1
            content = pending.pop(0) if pending else ""
            activity = anchor["activity_id"]
            slug_url = anchor["slug_url"]
            urn = f"urn:li:activity:{activity}" if activity else ""
            post_url = slug_url or (f"{BASE}/feed/update/{urn}/" if urn else "")
            if not post_url:
                continue
            posts.append(
                {
                    "post_id": activity or post_url,
                    "post_url": post_url,
                    "urn": urn,
                    "author_name": anchor["author"],
                    "author_profile_url": _author_url(slug_url, anchor["author"]),
                    "content": content,
                    "posted_at": anchor["posted_at"],
                }
            )
        return [post for post in posts if post["content"].strip()]

    # Older RSC shape: commentary regions + a bare post/update urn.
    legacy.sort(key=lambda item: item[0])
    regions.sort(key=lambda item: item[0])
    for index, (_position, item) in enumerate(legacy):
        content = regions[index][1] if index < len(regions) else ""
        urn = item["urn"]
        post_url = item["post_url"] or (f"{BASE}/feed/update/{urn}/" if urn else "")
        if not post_url or not content:
            continue
        activity = re.search(r"(?:activity|ugcPost):(\d+)", urn or post_url)
        posts.append(
            {
                "post_id": activity.group(1) if activity else post_url,
                "post_url": post_url,
                "urn": urn,
                "author_name": "",
                "author_profile_url": "",
                "content": content,
                "posted_at": None,
            }
        )
    return posts
