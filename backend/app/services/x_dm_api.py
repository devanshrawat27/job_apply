"""Send X direct messages through X's private web API.

XChat's browser UI asks for a per-browser passcode and often renders blank in
the automation browser, which made ``send_dm`` fail even when the account can
DM normally. X's legacy DM endpoints still work with the account's session
cookies and need no passcode, so this module is tried first. When the API is
unavailable the caller falls back to the Playwright script.

Treat cookies and message text as sensitive: never log either.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BEARER = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
    "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)


class DMUnavailable(Exception):
    """The API route cannot be used; fall back to the browser script."""


class DMError(Exception):
    """A definitive failure (unknown user, message rejected)."""


class DMUnknown(Exception):
    """The request may have reached X, so the outcome cannot be verified.

    X sometimes drops the connection after accepting a message. Retrying the
    write — in the API or the browser — could send the DM twice, so callers
    must report this as unverified instead of falling back.
    """


def _headers(cookies: dict[str, str]) -> dict[str, str]:
    return {
        "authorization": f"Bearer {_BEARER}",
        "x-csrf-token": cookies.get("ct0", ""),
        "x-twitter-active-user": "yes",
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-client-language": "en",
        "accept": "application/json",
        "content-type": "application/json",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "referer": "https://x.com/messages",
        # X closes idle keep-alive sockets, and reusing one of those makes the
        # next request fail with RemoteProtocolError before X reads it. A fresh
        # connection per call removes that failure mode.
        "connection": "close",
    }


def _client(credentials: dict[str, str], timeout: int = 40) -> httpx.Client:
    cookies = {
        "auth_token": credentials.get("auth_token", ""),
        "ct0": credentials.get("ct0", ""),
    }
    if credentials.get("twid"):
        cookies["twid"] = credentials["twid"]
    if not cookies["auth_token"] or not cookies["ct0"]:
        raise DMUnavailable("no stored session cookies")
    return httpx.Client(timeout=timeout, cookies=cookies, headers=_headers(cookies))


def resolve_user_id(client: httpx.Client, handle: str) -> str:
    """Return the numeric user id for ``handle`` using X's typeahead endpoint."""
    wanted = handle.strip().lstrip("@")
    if not wanted:
        raise DMError("Send a DM needs a recipient handle.")
    try:
        response = client.get(
            "https://x.com/i/api/1.1/search/typeahead.json",
            params={"q": wanted, "src": "search_box"},
        )
    except httpx.HTTPError as exc:
        raise DMUnavailable(f"typeahead request failed: {type(exc).__name__}") from exc

    if response.status_code in {401, 403, 429}:
        raise DMUnavailable(f"typeahead rejected with {response.status_code}")
    if response.status_code >= 500:
        raise DMUnavailable(f"typeahead unavailable with {response.status_code}")
    if response.status_code != 200:
        raise DMError(f"Could not look up @{wanted} on X.")

    try:
        users = response.json().get("users") or []
    except ValueError as exc:
        raise DMUnavailable("typeahead returned non-JSON") from exc

    match = next(
        (
            user
            for user in users
            if str(user.get("screen_name") or "").casefold() == wanted.casefold()
        ),
        None,
    )
    if match is None:
        # X returns similar handles; accept the first only when it is the
        # requested one, otherwise treat it as not found.
        raise DMError(f"X could not find the user @{wanted}.")
    user_id = str(match.get("id_str") or match.get("id") or "").strip()
    if not user_id:
        raise DMError(f"X returned no user id for @{wanted}.")
    return user_id


def send_dm(handle: str, message: str, credentials: dict[str, str]) -> dict[str, Any]:
    """Send ``message`` to ``handle``.

    Raises ``DMError`` (definitive refusal), ``DMUnavailable`` (the API cannot
    be used, safe to fall back) or ``DMUnknown`` (delivery unverified, do not
    retry).
    """
    text = str(message or "").strip()
    if not text:
        raise DMError("Send a DM needs message text.")
    if len(text) > 900:
        text = text[:900]

    username = handle.strip().lstrip("@")
    with _client(credentials) as client:
        user_id = resolve_user_id(client, username)
        payload = {
            "recipient_ids": user_id,
            "text": text,
            "cards_platform": "Web-12",
            "include_cards": 1,
            "include_quote_count": True,
            "dm_users": False,
        }
        try:
            response = client.post(
                "https://x.com/i/api/1.1/dm/new2.json", json=payload
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # The connection never opened, so nothing reached X.
            raise DMUnavailable(f"dm request failed: {type(exc).__name__}") from exc
        except httpx.HTTPError as exc:
            # The request may have been written before the socket failed.
            raise DMUnknown(
                f"X did not confirm the DM to @{username}, and the request may "
                f"have reached X ({type(exc).__name__}). Check the conversation "
                "before retrying so it is not sent twice."
            ) from exc

    if response.status_code == 401:
        raise DMError(
            "X rejected the DM because the saved session is no longer valid. "
            "Reconnect the account from Accounts, then retry."
        )

    if response.status_code == 429:
        raise DMError(
            f"X rate-limited this account, so the DM to @{username} was not "
            "sent. Wait a while and run it again."
        )

    if response.status_code >= 500:
        # A 5xx can arrive after X accepted the message; never retry blindly.
        raise DMUnknown(
            f"X returned an error (HTTP {response.status_code}) for the DM to "
            f"@{username}, so delivery is unverified. Check the conversation "
            "before retrying so it is not sent twice."
        )

    try:
        body = response.json()
    except ValueError:
        body = {}
    errors = body.get("errors") if isinstance(body, dict) else None

    # A recipient who does not accept messages returns 403 code 349. That is a
    # definitive answer, not a reason to retry in the browser (the browser then
    # fails on the chat passcode screen and hides the real reason).
    if response.status_code == 403 and isinstance(errors, list) and errors:
        first = errors[0] or {}
        if first.get("code") == 349:
            raise DMError(
                f"X won't let this account message @{username}: "
                f"{first.get('message') or 'the recipient does not accept messages'} "
                "(code 349)."
            )
        # X answered the write, so the browser fallback would only replace this
        # reason with a passcode error. Report what X actually said.
        raise DMError(
            f"X refused the DM to @{username}: "
            f"{first.get('message') or 'no detail'}"
            f" (code {first.get('code') or 'unknown'})."
        )

    if response.status_code != 200 or errors:
        detail = ""
        if isinstance(errors, list) and errors:
            detail = str((errors[0] or {}).get("message") or "")
        raise DMError(detail or f"X rejected the message (HTTP {response.status_code}).")

    entries = body.get("entries") or []
    sent = entries[0].get("message") if entries and isinstance(entries[0], dict) else {}
    message_data = (sent or {}).get("message_data") or {}
    return {
        "username": username,
        "message_id": str(message_data.get("id") or (sent or {}).get("id") or ""),
        "conversation_id": str((sent or {}).get("conversation_id") or ""),
        "text": str(message_data.get("text") or text),
    }

def follow_user(handle: str, credentials: dict[str, str]) -> dict[str, Any]:
    """Follow a user through X's own endpoint (no Chromium window)."""
    username = handle.strip().lstrip("@")
    if not username:
        raise DMError("A follow needs a username.")
    with _client(credentials) as client:
        user_id = resolve_user_id(client, username)
        try:
            response = client.post(
                "https://x.com/i/api/1.1/friendships/create.json",
                data={"user_id": user_id},
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            raise DMUnavailable(f"follow request failed: {type(exc).__name__}") from exc

    if response.status_code in {401, 403, 429}:
        body = response.text[:400]
        lowered = body.lower()
        if "already" in lowered or '"code":160' in body or "code\":160" in body:
            return {"username": username, "user_id": user_id, "already": True}
        if response.status_code == 429:
            raise DMUnavailable("X rate-limited the follow")
        raise DMError(f"X refused the follow (HTTP {response.status_code}): {body[:160]}")
    if response.status_code >= 500:
        raise DMUnavailable(f"follow unavailable with {response.status_code}")
    if response.status_code != 200:
        raise DMError(f"X returned HTTP {response.status_code} for the follow")

    return {"username": username, "user_id": user_id, "already": False}


def read_inbox(
    credentials: dict[str, str], *, limit: int = 25
) -> dict[str, Any]:
    """Return recent DM conversations via X's private inbox endpoint."""
    capped = max(1, min(int(limit or 25), 100))
    with _client(credentials) as client:
        try:
            response = client.get(
                "https://x.com/i/api/1.1/dm/inbox_initial_state.json",
                params={"filter": "all"},
            )
        except httpx.HTTPError as exc:
            raise DMUnavailable(f"inbox request failed: {type(exc).__name__}") from exc

    if response.status_code in {401, 403, 429}:
        raise DMUnavailable(f"inbox rejected with {response.status_code}")
    if response.status_code >= 500:
        raise DMUnavailable(f"inbox unavailable with {response.status_code}")
    if response.status_code != 200:
        raise DMError(f"X rejected the inbox request (HTTP {response.status_code}).")

    try:
        inbox = (response.json() or {}).get("inbox_initial_state") or {}
    except ValueError as exc:
        raise DMUnavailable("inbox returned non-JSON") from exc

    users = inbox.get("users") or {}
    conversations = inbox.get("conversations") or {}
    entries = inbox.get("entries") or []

    messages: dict[str, list[dict[str, str]]] = {}
    for entry in entries:
        message = (entry or {}).get("message") or {}
        conversation_id = str(message.get("conversation_id") or "")
        if not conversation_id:
            continue
        data = message.get("message_data") or {}
        sender_id = str(data.get("sender_id") or "")
        sender = str((users.get(sender_id) or {}).get("screen_name") or "")
        messages.setdefault(conversation_id, []).append(
            {
                "sender": sender,
                "text": str(data.get("text") or ""),
                "time": str(data.get("time") or message.get("time") or ""),
            }
        )

    rows: list[dict[str, Any]] = []
    for conversation_id, conversation in conversations.items():
        participants = [
            str(participant.get("user_id") or "")
            for participant in conversation.get("participants") or []
        ]
        other_id = next((uid for uid in participants if uid in users), None)
        if other_id is None and participants:
            other_id = participants[0]
        user = users.get(other_id or "", {})
        rows.append(
            {
                "username": str(user.get("screen_name") or ""),
                "name": str(user.get("name") or user.get("screen_name") or ""),
                "messages": messages.get(str(conversation_id), [])[:20],
                "sort": str(conversation.get("sort_timestamp") or ""),
            }
        )

    rows.sort(key=lambda row: row.get("sort") or "", reverse=True)
    for row in rows:
        row.pop("sort", None)
    trimmed = rows[:capped]
    return {"count": len(trimmed), "conversations": trimmed}


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _message_time_ms(message: dict[str, Any] | None) -> int | None:
    raw = str((message or {}).get("time") or "").strip()
    if not raw.isdigit():
        return None
    value = int(raw)
    # X normally sends milliseconds; tolerate seconds.
    return value * 1000 if value < 10**12 else value


def find_sent_message(
    credentials: dict[str, str],
    username: str,
    text: str,
    *,
    since_ms: int | None = None,
    attempts: int = 3,
    delay: float = 2.0,
    limit: int = 50,
) -> dict[str, Any] | None:
    """Return the stored message when X already has ``text`` in that thread.

    A dropped connection leaves the send unverified: the POST may have been
    accepted without a response. Re-reading the conversation is the only way to
    know, and it never risks sending the message twice.

    ``since_ms`` rejects an older message with the same text (test messages are
    often identical between runs), which would otherwise look like a delivery.
    """
    wanted_handle = str(username or "").strip().lstrip("@").casefold()
    wanted_text = _normalize_text(text)
    if not wanted_handle or not wanted_text:
        return None

    for attempt in range(max(1, attempts)):
        inbox: dict[str, Any] | None = None
        try:
            inbox = read_inbox(credentials, limit=limit)
        except (DMUnavailable, DMError) as exc:
            logger.warning("dm_verify_unavailable: %s", exc)
        for conversation in (inbox or {}).get("conversations") or []:
            if str(conversation.get("username") or "").casefold() != wanted_handle:
                continue
            for message in conversation.get("messages") or []:
                if _normalize_text(message.get("text")) != wanted_text:
                    continue
                stamp = _message_time_ms(message)
                if stamp is None:
                    continue
                if since_ms is not None and stamp < since_ms:
                    continue
                return message
        if attempt + 1 < attempts:
            time.sleep(max(0.0, delay))
    return None


def check_session(credentials: dict[str, str]) -> tuple[bool, str]:
    """Cheap session probe: returns (ok, reason).

    Only a 401 is treated as proof that the saved cookies are dead. Network
    errors and 403/429 are ambiguous and must not mark the account expired.
    """
    try:
        with _client(credentials, timeout=20) as client:
            response = client.get("https://x.com/i/api/1.1/account/settings.json")
    except httpx.HTTPError:
        return True, ""
    if response.status_code == 401:
        return False, "session expired"
    return True, ""
