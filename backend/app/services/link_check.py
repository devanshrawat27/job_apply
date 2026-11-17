"""Check that an application link actually opens something.

A post can say "apply here" and carry a link that is dead (404), a typo, or a
redirect back to the post itself. The human should never waste a click on those.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Status codes that mean the page exists but blocks bots/logins. Not dead.
AMBIGUOUS = {401, 403, 429}
DEAD = {404, 410}


def check(url: str, timeout: float = 8.0) -> tuple[bool, str]:
    """Return (ok, reason). ``ok`` is False only when the link is clearly dead."""
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
    return True, ""
