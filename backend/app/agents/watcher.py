"""Background watcher: keeps an eye on the agent and reports to ChatGPT.

The agent does the work; this module watches what actually happened and asks
the analyst model to grade it in plain language: is the outreach healthy, what
broke, and what should the agent do next.

It never sends anything. It stores an :class:`Insight` of kind
``activity_report`` which the dashboard shows, and it only runs when there was
new activity since the previous report.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.llm import LLMUnavailable, complete_json
from app.models import ActionLog, Insight, JobPost, Run

logger = logging.getLogger(__name__)

REPORT_AFTER = timedelta(minutes=90)
SYSTEM = """You supervise an automated job-outreach agent on X (Twitter) for one
candidate. You get the agent's activity since your last check: scans, posts
found/filtered, replies, DMs, failures with reasons, queue and approvals.

Your job is to answer, briefly and bluntly:
1. Is the agent healthy, or is something broken?
2. What exactly went wrong (specific reasons, not general advice)?
3. What should the agent or the human do next?

Never invent numbers that are not in the report. Return strict JSON only."""

PROMPT = """ACTIVITY SINCE {since}

SCANS
{scans}

OUTREACH
{outreach}

FAILURES / SKIPS
{failures}

CURRENT STATE
{state}

Return JSON:
{{
  "health": "good|warning|bad",
  "summary": "2 lines: what happened and is it healthy",
  "problems": ["specific problem with the exact reason"],
  "next_actions": ["concrete next step for the agent or the human"],
  "note_for_user": "one short line the candidate should read"
}}
"""


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def latest(db: Session, user_id: int | None) -> Insight | None:
    stmt = select(Insight).where(Insight.kind == "activity_report")
    if user_id is None:
        stmt = stmt.where(Insight.user_id.is_(None))
    else:
        stmt = stmt.where(Insight.user_id == user_id)
    return db.scalar(stmt.order_by(Insight.id.desc()).limit(1))


def since(db: Session, user_id: int | None) -> datetime:
    row = latest(db, user_id)
    if row is not None:
        return _as_utc(row.created_at) or (datetime.now(timezone.utc) - REPORT_AFTER)
    return datetime.now(timezone.utc) - REPORT_AFTER


def due(db: Session, user_id: int | None) -> bool:
    row = latest(db, user_id)
    if row is None:
        return True
    created = _as_utc(row.created_at)
    return created is None or datetime.now(timezone.utc) - created >= REPORT_AFTER


def _had_activity(db: Session, user_id: int | None, since_at: datetime) -> bool:
    naive = since_at.replace(tzinfo=None)
    stmt = select(func.count(Run.id)).where(Run.started_at >= naive)
    if user_id is not None:
        stmt = stmt.where(Run.user_id == user_id)
    return bool(db.scalar(stmt))


def collect(db: Session, user_id: int | None, since_at: datetime) -> dict:
    naive = since_at.replace(tzinfo=None)

    run_stmt = select(Run).where(Run.started_at >= naive)
    if user_id is not None:
        run_stmt = run_stmt.where(Run.user_id == user_id)
    runs = list(db.scalars(run_stmt.order_by(Run.id)).all())

    scan_lines = []
    totals = {"seen": 0, "new": 0, "relevant": 0, "rejected": 0, "feed": 0, "queries": 0}
    for run in runs:
        if run.kind != "scan":
            continue
        stats = run.stats or {}
        totals["seen"] += int(stats.get("posts_seen") or 0)
        totals["new"] += int(stats.get("posts_new") or 0)
        totals["relevant"] += int(stats.get("relevant") or 0)
        totals["rejected"] += int(stats.get("rejected") or 0)
        totals["feed"] += int(stats.get("feed_posts") or 0)
        totals["queries"] += int(stats.get("queries") or 0)
        scan_lines.append(
            f"{run.status}: {stats.get('mode') or 'search+feed'} "
            f"seen={stats.get('posts_seen')} new={stats.get('posts_new')} "
            f"relevant={stats.get('relevant')} rejected={stats.get('rejected')} "
            f"keywords={stats.get('keywords')}"
        )
    if not scan_lines:
        scan_lines.append("no scans in this window")

    log_stmt = select(ActionLog).where(ActionLog.created_at >= naive)
    if user_id is not None:
        log_stmt = log_stmt.where(ActionLog.user_id == user_id)
    logs = list(db.scalars(log_stmt.order_by(ActionLog.id)).all())

    counts: dict[str, int] = {}
    for log in logs:
        counts[f"{log.action}:{log.status}"] = counts.get(f"{log.action}:{log.status}", 0) + 1
    outreach = ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "no writes"

    failures = [
        f"{log.action} job {log.job_id} {log.status}: {(log.detail or '')[:110]}"
        for log in logs
        if log.status in ("failed", "skipped", "unknown")
    ][-8:]

    def job_count(statuses: tuple[str, ...]) -> int:
        stmt = select(func.count(JobPost.id)).where(JobPost.status.in_(statuses))
        if user_id is not None:
            stmt = stmt.where(JobPost.user_id == user_id)
        return int(db.scalar(stmt) or 0)

    state = (
        f"queued={job_count(('queued',))} "
        f"pending_approval={job_count(('pending_approval',))} "
        f"sent={job_count(('sent',))} failed={job_count(('failed',))} "
        f"apply_links={job_count(('new',))}"
    )

    return {
        "since": since_at.astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d %H:%M IST"),
        "totals": totals,
        "scans": scan_lines[-6:],
        "outreach": outreach,
        "failures": failures or ["none"],
        "state": state,
    }


def review(
    db: Session,
    user_id: int | None,
    *,
    providers: list[dict] | None = None,
    browser: bool = False,
) -> dict:
    since_at = since(db, user_id)
    data_in = collect(db, user_id, since_at)

    prompt = PROMPT.format(
        since=data_in["since"],
        scans="\n".join(data_in["scans"]),
        outreach=data_in["outreach"],
        failures="\n".join(data_in["failures"]),
        state=data_in["state"],
    )

    data: dict | None = None
    if browser:
        from app.services import browser_chatgpt

        try:
            data = browser_chatgpt.ask_json(SYSTEM, prompt)
        except Exception as exc:  # noqa: BLE001 - fall back to the API
            logger.warning("browser watcher report failed: %s", exc)

    if data is None:
        data = complete_json(
            SYSTEM,
            prompt,
            temperature=0.3,
            max_tokens=900,
            budget_s=60,
            providers=providers,
        )
    if not isinstance(data, dict):
        raise LLMUnavailable("watcher returned non-object JSON")

    payload = {
        "health": str(data.get("health") or "warning").lower()[:10],
        "summary": str(data.get("summary") or "")[:900],
        "problems": [str(item)[:300] for item in (data.get("problems") or [])][:6],
        "next_actions": [str(item)[:300] for item in (data.get("next_actions") or [])][:6],
        "note_for_user": str(data.get("note_for_user") or "")[:300],
        "activity": data_in,
    }

    row = Insight(
        user_id=user_id,
        kind="activity_report",
        summary=payload["summary"],
        payload=payload,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, **payload}


def needs_report(db: Session, user_id: int | None) -> bool:
    """Only spend a model call when the agent actually did something."""
    if not due(db, user_id):
        return False
    return _had_activity(db, user_id, since(db, user_id))
