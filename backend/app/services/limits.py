"""Rate limits, caps and quiet hours.

X punishes bursty automation. These guards are checked immediately before every
write, not just at scan time, so a long queue can never blow past the caps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ActionLog, AgentSettings


@dataclass
class LimitState:
    allowed: bool
    reason: str = ""
    replies_today: int = 0
    dms_today: int = 0


def _day_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _parse_quiet_hours(raw: str) -> tuple[int, int] | None:
    text = (raw or "").strip()
    if not text or "-" not in text:
        return None
    try:
        start, end = text.split("-", 1)
        start_h, end_h = int(start.strip()), int(end.strip())
    except ValueError:
        return None
    if not (0 <= start_h <= 23 and 0 <= end_h <= 23):
        return None
    return start_h, end_h


def in_quiet_hours(raw: str, now: datetime | None = None) -> bool:
    window = _parse_quiet_hours(raw)
    if window is None:
        return False
    now = now or datetime.now(timezone.utc)
    start_h, end_h = window
    hour = now.hour
    if start_h == end_h:
        return False
    if start_h < end_h:
        return start_h <= hour < end_h
    return hour >= start_h or hour < end_h


def _count_today(
    db: Session, actions: tuple[str, ...], now: datetime, user_id: int | None = None
) -> int:
    stmt = select(func.count(ActionLog.id)).where(
        ActionLog.action.in_(actions),
        ActionLog.status == "sent",
        ActionLog.created_at >= _day_start(now),
    )
    if user_id is not None:
        stmt = stmt.where(ActionLog.user_id == user_id)
    return int(db.scalar(stmt) or 0)


def _last_write_at(db: Session, user_id: int | None = None) -> datetime | None:
    # Only real outreach counts. "apply" is a local marker for a manual apply.
    stmt = select(func.max(ActionLog.created_at)).where(
        ActionLog.status == "sent",
        ActionLog.action.in_(("reply", "dm", "email")),
    )
    if user_id is not None:
        stmt = stmt.where(ActionLog.user_id == user_id)
    return db.scalar(stmt)


def check(db: Session, settings: AgentSettings, action: str, now: datetime | None = None) -> LimitState:
    now = now or datetime.now(timezone.utc)
    user_id = settings.user_id
    replies = _count_today(db, ("reply",), now, user_id)
    dms = _count_today(db, ("dm", "email"), now, user_id)

    if in_quiet_hours(settings.quiet_hours, now):
        return LimitState(False, f"quiet hours ({settings.quiet_hours} UTC)", replies, dms)

    if action == "reply" and replies >= settings.daily_reply_cap:
        return LimitState(False, f"daily reply cap reached ({settings.daily_reply_cap})", replies, dms)
    if action in ("dm", "email") and dms >= settings.daily_dm_cap:
        return LimitState(False, f"daily outreach cap reached ({settings.daily_dm_cap})", replies, dms)

    last = _last_write_at(db, user_id)
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        gap = timedelta(minutes=max(0, settings.min_minutes_between_writes))
        if now - last < gap:
            remaining = int((gap - (now - last)).total_seconds() // 60) + 1
            return LimitState(False, f"cooling down, next write in ~{remaining} min", replies, dms)

    return LimitState(True, "", replies, dms)


def stats(db: Session, settings: AgentSettings, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return {
        "replies_today": _count_today(db, ("reply",), now, settings.user_id),
        "dms_today": _count_today(db, ("dm", "email"), now, settings.user_id),
        "daily_reply_cap": settings.daily_reply_cap,
        "daily_dm_cap": settings.daily_dm_cap,
        "quiet_hours": settings.quiet_hours,
        "in_quiet_hours": in_quiet_hours(settings.quiet_hours, now),
    }
