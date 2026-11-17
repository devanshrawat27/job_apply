"""Background agent loop.

One daemon thread runs the whole cycle:

    find posts -> reply/DM them -> when the queue is empty, scan again

It never needs a button. Every write still respects the caps, the cool-down and
quiet hours, and it only creates a run when it actually does something.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from filelock import FileLock, Timeout
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import JobPost, User
from app.agents import analyst, inbox, watcher
from app.config import settings
from app.services import accounts, browser_chatgpt, limits, pipeline

logger = logging.getLogger(__name__)

POLL_SECONDS = 30

# When nothing is queued the agent keeps scrolling the home feed instead of
# sitting still. A deeper feed pass every few minutes finds fresh posts.
IDLE_FEED_MINUTES = 12
IDLE_FEED_COUNT = 70
IDLE_FEED_SCROLLS = 14

# Check the X inbox for answers this often. Read-only.
INBOX_MINUTES = 20

# Run the AI fit screen for unreviewed Approvals at most this often.
FIT_SCREEN_MINUTES = 10

# Scanning pauses when the queue is this deep; sending cannot keep up with it.
MAX_QUEUE_BEFORE_PAUSE = 40

# A scan that finds nothing relevant is followed by another one with the next
# keyword rotation after this many minutes, up to this many times in a row.
EMPTY_RETRY_MINUTES = 1
MAX_EMPTY_SCAN_RETRIES = 4

# Barren keywords trigger an analyst review this often (instead of every 6h).
BARREN_REVIEW_MINUTES = 20

# Only one process may run the agent loop. With uvicorn --workers N every
# worker runs lifespan startup; without this lock they would all scan and send.
SCHEDULER_LOCK = Path(__file__).resolve().parents[2] / ".scheduler.lock"
_lock_handle: FileLock | None = None


class AgentLoop(threading.Thread):
    daemon = True

    def __init__(self) -> None:
        super().__init__(name="agent-loop")
        self._stop_event = threading.Event()
        self._last_scan: dict[int | None, datetime] = {}
        self._last_idle_feed: dict[int | None, datetime] = {}
        self._last_inbox: dict[int | None, datetime] = {}
        self._last_fit: dict[int | None, datetime] = {}
        # Consecutive scans that found nothing, per user. Used to retry with the
        # next keywords instead of sitting idle for the whole interval.
        self._empty_scans: dict[int | None, int] = {}
        self._running = False

    def stop(self) -> None:
        self._stop_event.set()

    @property
    def last_scan(self) -> datetime | None:
        return max(self._last_scan.values()) if self._last_scan else None

    @property
    def busy(self) -> bool:
        return self._running

    def run(self) -> None:
        logger.info("agent loop started")
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the loop must survive
                logger.exception("agent loop tick failed")
            self._stop_event.wait(POLL_SECONDS)
        logger.info("agent loop stopped")

    def tick(self) -> None:
        if self._running:
            return

        db = SessionLocal()
        try:
            self._running = True
            user_ids = list(db.scalars(select(User.id).where(User.is_active.is_(True))).all())
            # No users yet (legacy/dev install): operate on the unscoped rows.
            if not user_ids:
                user_ids = [None]

            for user_id in user_ids:
                try:
                    self._tick_user(db, user_id, datetime.now(timezone.utc))
                except Exception:  # noqa: BLE001 - one user must not break others
                    logger.exception("agent tick failed for user %s", user_id)
                    db.rollback()
        finally:
            self._running = False
            db.close()

    def _tick_user(self, db, user_id: int | None, now: datetime) -> None:
        settings_row = pipeline.get_settings_row(db, user_id)
        if not settings_row.enabled:
            return

        # 0. Promote DM retries whose 30-minute wait is over.
        retry_stmt = select(JobPost).where(JobPost.status == "retry_wait")
        if user_id is not None:
            retry_stmt = retry_stmt.where(JobPost.user_id == user_id)
        now_naive = now.replace(tzinfo=None)
        for job in db.scalars(retry_stmt).all():
            if job.next_retry_at is not None and job.next_retry_at > now_naive:
                continue
            job.status = "queued"
            job.dm_status = "pending"
            job.next_retry_at = None
            job.last_error = ""
            job.logs = [*(job.logs or []), "retry window reached - queued again"][-60:]
        db.commit()

        # 0b. Read the X inbox for answers (read-only, every ~20 min).
        last_inbox = self._last_inbox.get(user_id)
        inbox_due = last_inbox is None or now - last_inbox >= timedelta(minutes=INBOX_MINUTES)
        if inbox_due:
            account = accounts.active_account(db, user_id)
            creds = accounts.account_credentials(account) if account else None
            if creds:
                self._last_inbox[user_id] = now
                try:
                    result = inbox.sync(db, user_id, creds)
                    logger.info("user %s inbox: %s", user_id, result)
                except Exception:  # noqa: BLE001 - never break the loop
                    logger.warning("inbox check failed for user %s", user_id, exc_info=True)
                    db.rollback()

        write_action = "reply" if settings_row.use_public_reply else "dm"

        # 1. Send at most one queued post (the cool-down owns the pace).
        queued_stmt = select(func.count(JobPost.id)).where(JobPost.status == "queued")
        if user_id is not None:
            queued_stmt = queued_stmt.where(JobPost.user_id == user_id)
        queued = int(db.scalar(queued_stmt) or 0)

        sent_this_tick = False
        if queued:
            state = limits.check(db, settings_row, write_action)
            if not state.allowed:
                logger.info("user %s queue waiting: %s", user_id, state.reason)
            else:
                run = pipeline.send_batch(db, limit=1, user_id=user_id)
                sent_this_tick = True
                logger.info("user %s send pass: %s %s", user_id, run.status, run.stats)

        # 2. Idle pass. Nothing queued means nothing left to apply to, so use
        # the time to scroll deeper into the home feed - that is where the
        # newest hiring posts from followed founders show up.
        queued_now_stmt = select(func.count(JobPost.id)).where(JobPost.status == "queued")
        if user_id is not None:
            queued_now_stmt = queued_now_stmt.where(JobPost.user_id == user_id)
        queued_now = int(db.scalar(queued_now_stmt) or 0)
        last_idle = self._last_idle_feed.get(user_id)
        idle_due = last_idle is not None and now - last_idle >= timedelta(minutes=IDLE_FEED_MINUTES)
        if queued_now == 0 and idle_due:
            self._last_idle_feed[user_id] = now
            feed_run = pipeline.scan(
                db,
                user_id=user_id,
                feed_only=True,
                feed_count=IDLE_FEED_COUNT,
                feed_scrolls=IDLE_FEED_SCROLLS,
            )
            logger.info("user %s idle feed: %s %s", user_id, feed_run.status, feed_run.stats)
            if feed_run.status == "completed":
                state = limits.check(db, settings_row, write_action)
                if state.allowed:
                    send_run = pipeline.send_batch(db, limit=1, user_id=user_id)
                    logger.info("user %s idle send: %s %s", user_id, send_run.status, send_run.stats)

        # 2b. Keep Approvals clean. Run the AI fit screen for unreviewed pending
        # jobs on a short timer, so jobs found by the idle feed are covered too.
        last_fit = self._last_fit.get(user_id)
        fit_due = last_fit is None or now - last_fit >= timedelta(minutes=FIT_SCREEN_MINUTES)
        if fit_due:
            try:
                from app.agents import job_filter

                if job_filter.remaining(db, user_id, "pending") > 0:
                    providers = pipeline.llm_providers(db, user_id)
                    use_browser = bool(settings_row.chatgpt_browser_enabled) and browser_chatgpt.connected(user_id)
                    if providers or settings.llm_enabled or use_browser:
                        self._last_fit[user_id] = now
                        fit_result = job_filter.review_batch(
                            db, user_id, "pending", limit=10, providers=providers, browser=use_browser
                        )
                        logger.info("user %s auto fit screen: %s", user_id, fit_result)
            except Exception:  # noqa: BLE001 - never break the loop
                logger.warning("fit screen failed for user %s", user_id, exc_info=True)
                db.rollback()

        # 3. Scanning runs on its own schedule and is never starved by the queue.
        interval = max(1, settings_row.scan_interval_minutes)
        last = self._last_scan.get(user_id)
        due = last is None or now - last >= timedelta(minutes=interval)
        if not due:
            return

        if queued > MAX_QUEUE_BEFORE_PAUSE:
            self._last_scan[user_id] = now
            self._last_idle_feed[user_id] = now
            logger.info("user %s scan skipped: %s posts already queued", user_id, queued)
            return

        self._last_scan[user_id] = now
        self._last_idle_feed[user_id] = now
        scan_run = pipeline.scan(db, user_id=user_id)
        logger.info("user %s scan pass: %s %s", user_id, scan_run.status, scan_run.stats)

        # An empty scan means the agent would sit idle for the whole interval.
        # Try the next keywords right away instead, a limited number of times.
        stats = scan_run.stats or {}
        found = int(stats.get("relevant") or 0)
        if scan_run.status == "completed" and found == 0:
            empties = self._empty_scans.get(user_id, 0) + 1
            self._empty_scans[user_id] = empties
            if empties <= MAX_EMPTY_SCAN_RETRIES:
                retry_at = datetime.now(timezone.utc) - timedelta(
                    minutes=max(0, interval - EMPTY_RETRY_MINUTES)
                )
                self._last_scan[user_id] = retry_at
                logger.info(
                    "user %s scan found nothing (retry %s/%s) - next keywords in %s min",
                    user_id,
                    empties,
                    MAX_EMPTY_SCAN_RETRIES,
                    EMPTY_RETRY_MINUTES,
                )
        else:
            self._empty_scans[user_id] = 0

        # 4. Immediately start applying to whatever the scan found.
        if scan_run.status == "completed" and not sent_this_tick:
            state = limits.check(db, settings_row, write_action)
            if state.allowed:
                send_run = pipeline.send_batch(db, limit=1, user_id=user_id)
                logger.info("user %s send pass: %s %s", user_id, send_run.status, send_run.stats)

        # 4. Every few hours let the analyst (ChatGPT when configured) grade the
        # keywords and suggest better junior-friendly ones. It only stores
        # advice; sending stays with the agent.
        try:
            from app.services import browser_chatgpt

            # Barren keywords (plenty of posts, zero relevant) get reviewed
            # right away instead of waiting for the 6-hour cycle.
            try:
                from app.agents import query_lab

                barren = query_lab.barren_keywords(db, user_id)
                stale = True
                last_insight = analyst.latest(db, user_id)
                if last_insight is not None and last_insight.created_at is not None:
                    created = last_insight.created_at
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    stale = (datetime.now(timezone.utc) - created) >= timedelta(
                        minutes=BARREN_REVIEW_MINUTES
                    )
                if barren and stale:
                    providers = pipeline.llm_providers(db, user_id)
                    use_browser = bool(settings_row.chatgpt_browser_enabled) and browser_chatgpt.connected(
                        user_id
                    )
                    if providers or settings.llm_enabled or use_browser:
                        analyst.review_keywords(
                            db, user_id, providers=providers, browser=use_browser
                        )
                        logger.info(
                            "user %s barren keyword review: %s keywords",
                            user_id,
                            len(barren),
                        )
            except Exception:  # noqa: BLE001 - never break the loop
                logger.warning("barren keyword review failed for user %s", user_id, exc_info=True)
                db.rollback()

            providers = pipeline.llm_providers(db, user_id)
            use_browser = bool(settings_row.chatgpt_browser_enabled) and browser_chatgpt.connected(user_id)
            if (providers or settings.llm_enabled or use_browser) and analyst.due(db, user_id):
                analyst.review_keywords(
                    db, user_id, providers=providers, browser=use_browser
                )
                logger.info("user %s analyst: keyword review stored", user_id)
        except Exception:  # noqa: BLE001 - analysis must never break the loop
            logger.warning("analyst review failed for user %s", user_id, exc_info=True)
            db.rollback()

        # 5. Watcher: every ~90 min, hand the agent's recent activity to ChatGPT
        # so it can say whether the outreach is healthy and what broke.
        try:
            from app.services import browser_chatgpt

            providers = pipeline.llm_providers(db, user_id)
            use_browser = bool(settings_row.chatgpt_browser_enabled) and browser_chatgpt.connected(user_id)
            if (providers or settings.llm_enabled or use_browser) and watcher.needs_report(
                db, user_id
            ):
                watcher.review(db, user_id, providers=providers, browser=use_browser)
                logger.info("user %s watcher: activity report stored", user_id)
        except Exception:  # noqa: BLE001 - the watcher must never break the loop
            logger.warning("watcher failed for user %s", user_id, exc_info=True)
            db.rollback()


_loop: AgentLoop | None = None
_lock = threading.Lock()


def start() -> AgentLoop | None:
    global _loop, _lock_handle
    with _lock:
        if _loop is not None and _loop.is_alive():
            return _loop

        handle = FileLock(str(SCHEDULER_LOCK))
        try:
            handle.acquire(timeout=0)
        except Timeout:
            logger.warning(
                "agent loop already owned by another process (%s) - not starting here",
                SCHEDULER_LOCK,
            )
            return None
        _lock_handle = handle

        _loop = AgentLoop()
        _loop.start()
        return _loop


def stop() -> None:
    global _loop, _lock_handle
    with _lock:
        if _loop is not None:
            _loop.stop()
            _loop = None
        if _lock_handle is not None:
            try:
                _lock_handle.release()
            except Exception:  # noqa: BLE001 - already released
                pass
            _lock_handle = None


def status() -> dict:
    loop = _loop
    return {
        "running": bool(loop and loop.is_alive()),
        "busy": bool(loop and loop.busy),
        "last_scan": loop.last_scan.isoformat() if loop and loop.last_scan else None,
    }


def trigger_now() -> None:
    """Reset the timers so the next tick scans immediately."""
    if _loop is not None:
        _loop._last_scan.clear()  # noqa: SLF001 - internal timer reset
        _loop._last_idle_feed.clear()  # noqa: SLF001
        _loop._last_fit.clear()  # noqa: SLF001
