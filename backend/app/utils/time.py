"""Datetime helpers.

SQLite drops timezone info, so datetimes come back naive even though they were
written as UTC. Tagging them on the way out stops the UI from reading a UTC
value as local time (which made "just now" look like "5h ago").
"""

from __future__ import annotations

from datetime import datetime, timezone


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso_utc(value: datetime | None) -> str | None:
    fixed = ensure_utc(value)
    return fixed.isoformat() if fixed else None
