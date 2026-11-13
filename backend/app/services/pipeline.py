"""The single flow: scan X -> rank -> draft -> decide -> send -> log.

Everything the product does lives in this module. There is no workflow builder
and no second pipeline, on purpose.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.agents import composer, discovery, query_lab, spam as spam_guard
from app.agents.resume import format_experience
from app.models import (
    ActionLog,
    AgentSettings,
    DraftExample,
    Insight,
    JobPost,
    LLMApiKey,
    Profile,
    Resume,
    Run,
    XAccount,
)
from app.security import decrypt_credentials
from app.services import accounts, browser_chatgpt, executor, limits, mailer, resume_pick

logger = logging.getLogger(__name__)


class PipelineError(RuntimeError):
    pass


# --------------------------------------------------------------------- setup

def get_profile(db: Session, user_id: int | None = None) -> Profile | None:
    if user_id is None:
        return db.get(Profile, 1)
    return db.scalar(select(Profile).where(Profile.user_id == user_id))


def get_settings_row(db: Session, user_id: int | None = None) -> AgentSettings:
    if user_id is None:
        row = db.get(AgentSettings, 1)
    else:
        row = db.scalar(select(AgentSettings).where(AgentSettings.user_id == user_id))
    if row is None:
        row = AgentSettings(id=None if user_id else 1, user_id=user_id)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Drafting is the slow part of a scan. Once this is spent, the rest of the
# matches get the deterministic template instead of stalling the whole run.
DRAFT_BUDGET_S = 90

# Search is the other slow part: a stuck browser must not hold the whole scan.
SEARCH_BUDGET_S = 420


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def llm_providers(db: Session, user_id: int | None) -> list[dict]:
    """The user's own LLM keys (ChatGPT/OpenAI etc.), decrypted for one call."""
    stmt = select(LLMApiKey).where(LLMApiKey.enabled.is_(True))
    if user_id is None:
        stmt = stmt.where(LLMApiKey.user_id.is_(None))
    else:
        stmt = stmt.where(LLMApiKey.user_id == user_id)

    providers: list[dict] = []
    for row in db.scalars(stmt.order_by(LLMApiKey.id)).all():
        creds = decrypt_credentials(row.key_ciphertext) or {}
        key = str(creds.get("api_key") or "")
        if not key:
            continue
        providers.append(
            {
                "id": row.id,
                "label": row.label or row.provider,
                "provider": row.provider,
                "base_url": row.base_url,
                "api_key": key,
                "models": [row.model],
            }
        )
    return providers


def _log(job: JobPost, message: str) -> None:
    stamp = _now().strftime("%H:%M:%S")
    job.logs = [*(job.logs or []), f"{stamp} {message}"][-60:]


# ---------------------------------------------------------------------- scan

def _search(query: str, count: int, creds: dict | None) -> dict:
    return executor.run_script("search", {"query": query, "count": count}, creds=creds)


def _feed(count: int, creds: dict | None, scrolls: int = 8) -> dict:
    return executor.run_script(
        "feed", {"count": count, "scrolls": scrolls}, creds=creds
    )


def scan(
    db: Session,
    *,
    manual: bool = False,
    run: Run | None = None,
    user_id: int | None = None,
    feed_only: bool = False,
    feed_count: int = 40,
    feed_scrolls: int = 8,
) -> Run:
    """Discover fresh job posts and prepare drafts for one user.

    ``feed_only`` is the idle pass: the agent has nothing queued, so it scrolls
    the home feed deeper instead of repeating the keyword searches. More feed
    pages means more chances to catch a founder's fresh hiring post.
    """
    if run is None:
        run = Run(kind="scan", status="running", user_id=user_id)
        db.add(run)
        db.commit()
        db.refresh(run)

    stats = {
        "queries": 0,
        "posts_seen": 0,
        "posts_new": 0,
        "duplicates": 0,
        "relevant": 0,
        "queued": 0,
        "pending_approval": 0,
        "rejected": 0,
        "errors": [],
        "feed_posts": 0,
    }

    try:
        profile = get_profile(db, user_id)
        if profile is None:
            raise PipelineError("Set up your profile first (upload a resume or fill the form).")

        settings_row = get_settings_row(db, user_id)
        if not manual and not settings_row.enabled:
            run.status = "skipped"
            run.stats = {**stats, "errors": ["agent is paused"]}
            run.finished_at = _now()
            db.commit()
            return run

        account = accounts.active_account(db, user_id)
        if account is None:
            raise PipelineError("Connect your X account first.")
        creds = accounts.account_credentials(account)
        if not creds:
            raise PipelineError("The stored X session could not be read. Reconnect the account.")

        keywords = [] if feed_only else query_lab.select_keywords(db, profile, user_id)
        stats["queries"] = len(keywords)
        stats["keywords"] = [row.keyword for row in keywords]
        stats["mode"] = "feed-only" if feed_only else "search+feed"

        raw_posts: list[dict] = []
        seen_by_keyword: dict[str, int] = {}
        search_deadline = _now() + timedelta(seconds=SEARCH_BUDGET_S)

        def budget_left() -> bool:
            return _now() < search_deadline

        # The home feed covers accounts the user follows - often founders who
        # post a role directly instead of using a job board.
        feed_result = _feed(
            max(1, min(feed_count, 100)),
            creds,
            scrolls=max(1, min(feed_scrolls, 20)),
        )
        if feed_result.get("success"):
            feed_posts = (feed_result.get("data") or {}).get("posts") or []
            for post in feed_posts:
                post["_keyword"] = "home feed"
            raw_posts.extend(feed_posts)
            stats["feed_posts"] = len(feed_posts)
        else:
            stats["errors"].append(
                f"feed skipped: {feed_result.get('error') or feed_result.get('code')}"
            )

        for row in keywords:
            if not budget_left():
                stats["errors"].append("search budget exhausted - remaining keywords skipped")
                break
            result = _search(
                query_lab.wrap_query(row.keyword, settings_row, profile=profile),
                settings_row.max_posts_per_scan,
                creds,
            )
            data = result.get("data") or {}
            posts = data.get("posts") or []

            if not result.get("success"):
                stats["errors"].append(f"search failed: {result.get('error') or result.get('code')}")
                if result.get("code") == "SESSION_EXPIRED":
                    account.status = "expired"
                    db.commit()
                    break
                continue

            for post in posts:
                post["_keyword"] = row.keyword
            raw_posts.extend(posts)

        stats["posts_seen"] = len(raw_posts)

        existing_stmt = select(JobPost.post_id)
        hashes_stmt = select(JobPost.content_hash)
        if user_id is not None:
            existing_stmt = existing_stmt.where(JobPost.user_id == user_id)
            hashes_stmt = hashes_stmt.where(JobPost.user_id == user_id)

        existing = set(db.scalars(existing_stmt).all())
        existing_hashes = {value for value in db.scalars(hashes_stmt).all() if value}
        fresh_rows: list[JobPost] = []
        now = _now()

        for raw in raw_posts:
            post_id = str(raw.get("post_id") or "").strip()
            if not post_id or post_id in existing:
                continue
            text = str(raw.get("post_content") or "").strip()
            handle = str(raw.get("author_handle") or "").lstrip("@")
            if discovery.is_own_post(handle, account.username):
                continue
            if not discovery.looks_like_job_post(text):
                continue

            posted_at = _parse_time(raw.get("posted_at"))
            if not discovery.is_fresh(posted_at, settings_row.lookback_hours, now):
                continue

            fingerprint = discovery.content_fingerprint(text)
            if fingerprint and fingerprint in existing_hashes:
                # Same job reposted by a different account.
                stats["duplicates"] += 1
                continue

            row = JobPost(
                user_id=user_id,
                post_id=post_id,
                post_url=str(raw.get("post_url") or f"https://x.com/i/web/status/{post_id}"),
                author_handle=handle,
                author_name=str(raw.get("author_name") or ""),
                content=text,
                content_hash=fingerprint,
                posted_at=posted_at,
                query_text=str(raw.get("_keyword") or ""),
                status="new",
            )
            db.add(row)
            fresh_rows.append(row)
            existing.add(post_id)
            if fingerprint:
                existing_hashes.add(fingerprint)
            # Only fresh posts count as "seen" for keyword quality; duplicates
            # would otherwise make every good keyword look useless.
            keyword = str(raw.get("_keyword") or "")
            if keyword:
                seen_by_keyword[keyword] = seen_by_keyword.get(keyword, 0) + 1

        stats["posts_new"] = len(fresh_rows)
        if not fresh_rows:
            _record_keywords(db, keywords, seen_by_keyword, [])
            db.commit()
            run.status = "completed"
            run.stats = stats
            run.finished_at = _now()
            db.commit()
            db.refresh(run)
            return run

        db.flush()

        scored = discovery.score_posts(profile, fresh_rows)
        examples_stmt = select(DraftExample).order_by(DraftExample.id.desc()).limit(3)
        if user_id is not None:
            examples_stmt = examples_stmt.where(DraftExample.user_id == user_id)
        examples = list(db.scalars(examples_stmt).all())
        draft_deadline = _now() + timedelta(seconds=DRAFT_BUDGET_S)
        providers = llm_providers(db, user_id)
        browser_draft = bool(settings_row.chatgpt_browser_enabled) and browser_chatgpt.connected()
        for job in fresh_rows:
            row = scored.get(job.post_id, {})
            job.relevance = int(row.get("relevance") or 0)
            job.company = str(row.get("company") or "")[:200]
            job.role = str(row.get("role") or "")[:200]
            job.job_location = str(row.get("job_location") or "")[:200]
            job.apply_method = str(row.get("apply_method") or "unknown")[:80]
            job.contact = str(row.get("contact") or "")[:200]
            job.required_experience_months = int(row.get("required_experience_months") or 0)
            job.reason = str(row.get("reason") or "")

            email = discovery.extract_contact_email(job.content)
            url = discovery.extract_apply_url(job.content)
            job.contact_email = email or str(row.get("contact_email") or "")[:200]
            job.apply_url = url or str(row.get("apply_url") or "")[:500]
            detected = discovery.detect_apply_method(
                job.content, email=job.contact_email, url=job.apply_url
            )
            method = detected if detected != "unknown" else str(row.get("apply_method") or "dm")
            job.outreach_method = "dm" if method in ("reply", "") else method

            job.author_type = str(
                row.get("author_type") or discovery.classify_author(job.author_handle, job.author_name)
            )
            # Job boards / community pages rarely read DMs, so only reply there.
            if job.author_type == "job_board":
                job.outreach_method = "reply"

            spam = spam_guard.assess(job.content, job.author_handle)
            job.spam_score = spam["score"]
            job.spam_reasons = spam["reasons"]

            reported = {str(handle).lstrip("@").lower() for handle in (settings_row.reported_handles or [])}
            if job.author_handle.lstrip("@").lower() in reported:
                job.status = "rejected"
                stats["rejected"] += 1
                _log(job, "you reported this account as fake - skipped")
                continue

            if job.spam_score >= spam_guard.REJECT_THRESHOLD:
                job.status = "rejected"
                stats["rejected"] += 1
                _log(job, f"fake-post score {job.spam_score}/100: " + "; ".join(job.spam_reasons[:3]))
                continue

            avoid = discovery.matches_avoid(profile, job.content)
            if avoid:
                job.status = "rejected"
                stats["rejected"] += 1
                _log(job, f"you marked '{avoid}' as not a fit - skipped")
                continue

            mismatch = discovery.domain_mismatch(profile, job.content)
            if mismatch:
                job.status = "rejected"
                stats["rejected"] += 1
                _log(job, f"{mismatch} (your resume is {(profile.domain or 'tech')}) - skipped")
                continue

            gap = _experience_gap(profile, job)
            if gap:
                job.status = "rejected"
                stats["rejected"] += 1
                _log(job, gap)
                continue

            if job.relevance < settings_row.relevance_threshold:
                job.status = "rejected"
                stats["rejected"] += 1
                _log(job, f"relevance {job.relevance} < {settings_row.relevance_threshold} - skipped")
                continue

            stats["relevant"] += 1

            # External apply link (or a post that says "Apply Link:" but kept
            # the URL in X's link card) is applied to manually. Never send a
            # public reply or DM for it.
            if (job.apply_url or "").strip() or discovery.mentions_apply_link(job.content):
                job.outreach_method = "link"
                job.reply_text = ""
                job.dm_text = ""
                job.confidence = 0.0
                if (job.apply_url or "").strip():
                    job.status = "new"
                    job.decision_reason = (
                        "external apply link found - apply on the company site; no reply or DM sent"
                    )
                    _log(job, "external apply link - added to Apply links, nothing sent")
                else:
                    # The URL is hidden in X's link card. Keep the job in the
                    # Apply links tab by pointing at the post itself.
                    job.apply_url = job.post_url
                    job.status = "new"
                    job.decision_reason = (
                        "application link is inside the post - open the post to apply; "
                        "no reply or DM sent"
                    )
                    _log(job, "apply link is inside the post - added to Apply links, nothing sent")
                continue

            resume = resume_pick.pick_best(db, job)
            if resume is not None:
                job.resume_id = resume.id
                job.resume_label = (resume.label or resume.filename)[:120]
            earlier_dms, _last_dm = dm_stats(db, job)
            draft = composer.compose(
                profile,
                job,
                examples,
                budget_s=max(0.0, (draft_deadline - _now()).total_seconds()),
                follow_up=earlier_dms,
                providers=providers,
                browser_fallback=browser_draft,
            )
            job.reply_text = draft["reply_text"]
            job.dm_text = draft["dm_text"]
            job.confidence = float(draft["confidence"])
            job.uncertainties = draft["uncertainties"]
            job.generic_draft = bool(draft.get("generic"))

            blockers = composer.blockers_for(job, draft)
            allowed, dm_count, dm_reason = dm_followup_allowed(db, job)
            if not allowed:
                # Too many DMs already, or a follow-up would be too soon: this
                # post gets a public reply instead of another DM.
                job.dm_text = ""
                draft["dm_text"] = ""
                job.outreach_method = "reply"
                blockers = [b for b in blockers if b != "no DM draft"]
                _log(job, dm_reason)
            elif dm_count > 0:
                _log(job, f"follow-up DM #{dm_count + 1} to @{job.author_handle} (no reply yet)")
            job.status, why = _decide(job, settings_row, blockers)
            job.decision_reason = why
            _log(job, why)
            if job.status == "queued":
                stats["queued"] += 1
            else:
                stats["pending_approval"] += 1

        _record_keywords(db, keywords, seen_by_keyword, fresh_rows)
        db.commit()
        run.status = "completed"
        run.stats = stats
        run.finished_at = _now()
        db.commit()
        db.refresh(run)
        return run

    except Exception as exc:  # noqa: BLE001 - surfaced to the UI
        db.rollback()
        logger.exception("scan failed")
        run.status = "failed"
        run.error = str(exc)
        run.stats = stats
        run.finished_at = _now()
        db.commit()
        db.refresh(run)
        return run


def _record_keywords(
    db: Session,
    keywords: list,
    seen_by_keyword: dict[str, int],
    jobs: list[JobPost],
) -> None:
    """Feed the keyword lab: how many posts each keyword produced vs. useful."""
    per_keyword = {keyword: {"seen": seen, "relevant": 0} for keyword, seen in seen_by_keyword.items()}
    for job in jobs:
        if job.status == "rejected":
            continue
        entry = per_keyword.get(job.query_text)
        if entry is not None:
            entry["relevant"] += 1
    query_lab.record_results(db, keywords, per_keyword)


def _experience_gap(profile: Profile, job: JobPost) -> str:
    """Empty string when the candidate can apply, otherwise the reason."""
    required = job.required_experience_months or 0
    if required <= 0:
        return ""
    # Small grace so a 6-month candidate still sees "1 year" roles.
    if required <= profile.experience_months + 3:
        return ""
    return (
        f"needs {format_experience(required)} experience, "
        f"you have {format_experience(profile.experience_months)} - skipped"
    )


def _parse_time(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return _as_utc(value)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return _as_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


STRONG_MATCH_RELEVANCE = 90
STRONG_MATCH_CONFIDENCE = 0.55


def _decide(job: JobPost, settings_row: AgentSettings, blockers: list[str]) -> tuple[str, str]:
    """Auto-send only when the agent is genuinely sure.

    A very strong role match is allowed to go out slightly below the confidence
    bar as long as the draft is clean - that is the "skills matched, just apply"
    case.
    """
    if job.outreach_method == "email" and not mailer.email_configured():
        return (
            "pending_approval",
            f"apply by email to {job.contact_email or 'the address in the post'} (email is not configured)",
        )

    if not settings_row.auto_send_enabled:
        return "pending_approval", "auto-send is off - waiting for approval"

    if job.spam_score >= spam_guard.REVIEW_THRESHOLD:
        return (
            "pending_approval",
            f"possible fake post ({job.spam_score}/100): " + "; ".join(job.spam_reasons[:3]),
        )

    if blockers:
        return "pending_approval", "needs review: " + "; ".join(blockers)

    if job.apply_method in ("email", "link") and job.contact and job.contact != job.author_handle:
        return "pending_approval", f"application goes to {job.contact}, not a DM"

    if job.confidence >= settings_row.auto_send_confidence:
        return (
            "queued",
            f"confident match (relevance {job.relevance}, confidence {job.confidence:.2f}) - queued to send",
        )

    if job.relevance >= STRONG_MATCH_RELEVANCE and job.confidence >= STRONG_MATCH_CONFIDENCE:
        return (
            "queued",
            f"strong match (relevance {job.relevance}, confidence {job.confidence:.2f}) - queued to send",
        )

    return (
        "pending_approval",
        f"confidence {job.confidence:.2f} < {settings_row.auto_send_confidence:.2f} - waiting for approval",
    )


# ---------------------------------------------------------------------- send

# One send pass at a time. The scheduler and a manual "Approve & send" can fire
# together; without this they both pick the same queued job and DM it twice.
_send_lock = threading.Lock()


def send_batch(
    db: Session,
    *,
    job_ids: list[int] | None = None,
    limit: int | None = None,
    run: Run | None = None,
    user_id: int | None = None,
) -> Run:
    with _send_lock:
        return _send_batch(db, job_ids=job_ids, limit=limit, run=run, user_id=user_id)


def _send_batch(
    db: Session,
    *,
    job_ids: list[int] | None = None,
    limit: int | None = None,
    run: Run | None = None,
    user_id: int | None = None,
) -> Run:
    if run is None:
        run = Run(kind="send", status="running", user_id=user_id)
        db.add(run)
        db.commit()
        db.refresh(run)

    stats = {"attempted": 0, "replied": 0, "dm_sent": 0, "failed": 0, "deferred": "", "stopped": ""}

    try:
        settings_row = get_settings_row(db, user_id)
        account = accounts.active_account(db, user_id)
        if account is None:
            raise PipelineError("Connect your X account first.")
        creds = accounts.account_credentials(account)
        if not creds:
            raise PipelineError("The stored X session could not be read. Reconnect the account.")

        query = (
            select(JobPost)
            .where(JobPost.status == "queued")
            .order_by(
                # Individuals and founders first, then the strongest match.
                case((JobPost.author_type == "person", 0), else_=1),
                JobPost.relevance.desc(),
                JobPost.id.asc(),
            )
        )
        if user_id is not None:
            query = query.where(JobPost.user_id == user_id)
        if job_ids:
            query = (
                select(JobPost)
                .where(JobPost.id.in_(job_ids), JobPost.status == "queued")
                .order_by(JobPost.id.asc())
            )

        jobs = list(db.scalars(query).all())
        if limit:
            jobs = jobs[:limit]

        for job in jobs:
            job.status = "sending"
            db.commit()

            outcome = _send_one(db, job, account, settings_row, creds)
            stats["attempted"] += 1

            if outcome.get("stop"):
                stats["stopped"] = outcome["stop"]
                job.status = outcome.get("job_status", "queued")
                db.commit()
                break

            if outcome.get("deferred"):
                stats["deferred"] = outcome["deferred"]
                job.status = "queued"
                _log(job, f"deferred: {outcome['deferred']}")
                db.commit()
                break

            if job.reply_status == "sent":
                stats["replied"] += 1
            if job.dm_status == "sent":
                stats["dm_sent"] += 1
            if job.status == "failed":
                stats["failed"] += 1
            db.commit()

        run.status = "completed"
        run.stats = stats
        run.finished_at = _now()
        db.commit()
        db.refresh(run)
        return run

    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("send batch failed")
        run.status = "failed"
        run.error = str(exc)
        run.stats = stats
        run.finished_at = _now()
        db.commit()
        db.refresh(run)
        return run


def _email_body(profile: Profile, job: JobPost) -> tuple[str, str]:
    """Return (subject, body) for an application email."""
    role = job.role or "the role"
    company = job.company or "your team"
    name = profile.full_name or "the candidate"

    links = profile.links or {}
    link_line = " Â· ".join(
        value for value in (links.get("portfolio"), links.get("github"), links.get("linkedin")) if value
    )

    body_lines = [
        f"Hi {company} team,",
        "",
        job.dm_text or "I would like to apply for this role.",
        "",
        "My resume is attached.",
    ]
    if link_line:
        body_lines.append(f"Portfolio / GitHub: {link_line}")
    body_lines.extend(["", "Best,", name])
    if profile.phone:
        body_lines.append(profile.phone)

    subject = f"Application: {role}" f"{f' at {job.company}' if job.company else ''} â€” {name}"
    return subject, "\n".join(body_lines)


DM_MAX_PER_PERSON = 4
DM_FOLLOWUP_GAP = timedelta(hours=6)


def dm_stats(db: Session, job: JobPost) -> tuple[int, datetime | None]:
    """How many DMs this person already got, and when the last one went.

    One DM is not enough: a polite follow-up is fine when they have not
    answered. But after DM_MAX_PER_PERSON unanswered DMs we stop DMing and use
    public replies only, so the account is never seen as spam.
    """
    handle = (job.author_handle or "").strip().lstrip("@").lower()
    if not handle:
        return 0, None

    user_clause = (
        ActionLog.user_id == job.user_id
        if job.user_id is not None
        else ActionLog.user_id.is_(None)
    )
    times = [
        _as_utc(value)
        for value in db.scalars(
            select(ActionLog.created_at)
            .where(
                user_clause,
                ActionLog.action == "dm",
                ActionLog.status.in_(("sent", "unknown")),
                func.lower(ActionLog.target) == f"@{handle}",
            )
            .order_by(ActionLog.created_at.desc())
        ).all()
    ]

    job_user_clause = (
        JobPost.user_id == job.user_id
        if job.user_id is not None
        else JobPost.user_id.is_(None)
    )
    legacy = [
        _as_utc(value)
        for value in db.scalars(
            select(JobPost.sent_at)
            .where(
                job_user_clause,
                JobPost.id != (job.id or -1),
                JobPost.dm_status.in_(("sent", "unknown")),
                func.lower(JobPost.author_handle) == handle,
            )
            .order_by(JobPost.sent_at.desc())
        ).all()
        if value
    ]

    # ActionLog and JobPost describe the same sends; take the larger count
    # instead of adding them together.
    count = max(len(times), len(legacy))
    latest = [value for value in (*times, *legacy) if value is not None]
    return count, (max(latest) if latest else None)


def dm_followup_allowed(db: Session, job: JobPost) -> tuple[bool, int, str]:
    """Can this post get a DM? Returns (allowed, follow_up_number, reason)."""
    count, last = dm_stats(db, job)
    if count >= DM_MAX_PER_PERSON:
        return (
            False,
            count,
            f"already sent {count} DMs to @{job.author_handle} - public reply only now",
        )
    if count > 0 and last is not None and (_now() - last) < DM_FOLLOWUP_GAP:
        wait = DM_FOLLOWUP_GAP - (_now() - last)
        return (
            False,
            count,
            f"DM'd @{job.author_handle} recently - follow-up in about {int(wait.total_seconds() // 3600) + 1}h, reply only for now",
        )
    return True, count, ""


def _send_one(
    db: Session,
    job: JobPost,
    account: XAccount,
    settings_row: AgentSettings,
    creds: dict,
) -> dict:
    """Apply to one post using the method the post actually asks for."""
    method = job.outreach_method or "dm"

    # External apply link: never send a reply or DM. The human applies through
    # the link (Apply links tab); a queued row may still reach this guard.
    if (job.apply_url or "").strip() or method == "link":
        job.outreach_method = "link"
        if (job.apply_url or "").strip():
            job.status = "new"
            job.decision_reason = (
                "external apply link found - apply on the company site; no reply or DM sent"
            )
            _log(job, "external apply link - nothing sent")
        else:
            job.apply_url = job.post_url
            job.status = "new"
            job.decision_reason = (
                "application link is inside the post - open the post to apply; "
                "no reply or DM sent"
            )
            _log(job, "apply link is inside the post - nothing sent")
        job.reply_text = ""
        job.dm_text = ""
        return {}

    # Defensive: a legacy queued row whose text mentions an apply link.
    if discovery.mentions_apply_link(job.content):
        job.outreach_method = "link"
        if not (job.apply_url or "").strip():
            job.apply_url = job.post_url
        job.status = "new"
        job.reply_text = ""
        job.dm_text = ""
        job.decision_reason = (
            "application link is inside the post - open the post to apply; no reply or DM sent"
        )
        _log(job, "apply link is inside the post - nothing sent")
        return {}

    # Defensive: never message a job seeker (someone asking for a job/referral),
    # even if an old row is still queued.
    seeker = discovery.job_seeker_reason(job.content)
    if seeker:
        job.status = "rejected"
        job.reply_text = ""
        job.dm_text = ""
        job.decision_reason = f"job seeker post ({seeker}) - not a hiring post"
        _log(job, f"job seeker post ({seeker}) - nothing sent")
        return {}

    profile = get_profile(db, job.user_id)

    # ---- email application -------------------------------------------
    if method == "email":
        if not job.contact_email:
            return {"deferred": "post mentions email but no address was found"}
        if not mailer.email_configured():
            return {"deferred": "email is not configured - add SMTP_* to backend/.env"}
        if job.email_status not in ("none", "pending"):
            return {}

        state = limits.check(db, settings_row, "email")
        if not state.allowed:
            return {"deferred": state.reason}

        subject, body = _email_body(profile, job) if profile else (
            f"Application: {job.role or 'role'}",
            job.dm_text,
        )

        attachment = profile.resume_path if profile else ""
        if job.resume_id:
            chosen = db.get(Resume, job.resume_id)
            if chosen is not None and chosen.path:
                attachment = chosen.path

        result = mailer.send_application(
            job.contact_email,
            subject,
            body,
            resume_path=attachment,
        )
        stop = ""
        job.email_status, stop = _apply_write_result(
            db,
            job,
            "email",
            result,
            target=job.contact_email,
            content=body,
        )
        if stop:
            job.status = "queued"
            return {"stop": stop, "job_status": "queued"}
        if job.email_status in ("failed", "unknown"):
            job.status = "failed"
            job.last_error = result.get("error") or result.get("code", "ERROR")
            return {}

        job.status = "sent" if job.email_status in ("sent", "skipped") else "failed"
        if job.status == "sent":
            job.sent_at = _now()
        return {}

    # ---- public reply (DM flow only) ----------------------------------
    if (
        settings_row.use_public_reply
        and job.reply_text
        and job.reply_status in ("none", "pending")
    ):
        state = limits.check(db, settings_row, "reply")
        if not state.allowed:
            return {"deferred": state.reason}

        result = executor.run_script(
            "reply",
            {"post_url": job.post_url, "reply_text": job.reply_text},
            creds=creds,
        )
        code = result.get("code", "ERROR")
        job.reply_status, stop = _apply_write_result(
            db,
            job,
            "reply",
            result,
            target=f"@{job.author_handle}",
            content=job.reply_text,
        )
        if stop:
            job.status = "queued"
            return {"stop": stop, "job_status": "queued"}
        if job.reply_status in ("failed", "unknown"):
            job.status = "failed"
            job.last_error = result.get("error") or code
            return {}

    # ---- DM -----------------------------------------------------------
    # People with a closed X inbox can never receive a DM. The executor reports
    # DM_CLOSED once; from then on they are skipped before any browser work.
    closed_handles = {
        str(handle).strip().lstrip("@").lower()
        for handle in (settings_row.closed_inbox_handles or [])
    }
    if (
        method != "reply"
        and settings_row.send_dms
        and job.dm_text
        and job.dm_status in ("none", "pending")
        and job.author_handle.strip().lstrip("@").lower() in closed_handles
    ):
        job.dm_status = "skipped"
        _log(job, f"@{job.author_handle} has a closed inbox - no DM sent")
        db.add(
            ActionLog(
                user_id=job.user_id,
                job_id=job.id,
                action="dm",
                status="skipped",
                target=f"@{job.author_handle}",
                content=job.dm_text,
                detail="X says this inbox is closed - removed from the DM queue",
            )
        )
        db.commit()

    # Follow-ups are allowed, but there is a hard cap per person: after
    # DM_MAX_PER_PERSON unanswered DMs (or too soon after the last one) the post
    # gets a public reply only.
    if (
        method != "reply"
        and settings_row.send_dms
        and job.dm_text
        and job.dm_status in ("none", "pending")
    ):
        allowed, dm_count, dm_reason = dm_followup_allowed(db, job)
        if not allowed:
            job.dm_status = "skipped"
            _log(job, dm_reason)
            db.add(
                ActionLog(
                    user_id=job.user_id,
                    job_id=job.id,
                    action="dm",
                    status="skipped",
                    target=f"@{job.author_handle}",
                    content=job.dm_text,
                    detail=dm_reason,
                )
            )
            db.commit()

            # No reply from them yet: following is the polite nudge instead of
            # another DM. Only for real people, never job-board accounts.
            if not job.followed and (job.author_type or "person") in ("person", "founder"):
                follow = executor.run_script("follow", {"username": job.author_handle}, creds=creds)
                follow_code = follow.get("code", "ERROR")
                if follow.get("success") or follow_code == "ALREADY_FOLLOWING":
                    job.followed = True
                    db.add(
                        ActionLog(
                            user_id=job.user_id,
                            job_id=job.id,
                            action="follow",
                            status="sent",
                            target=f"@{job.author_handle}",
                            content="",
                            detail="no reply to earlier DMs - followed instead of DMing again",
                        )
                    )
                    db.commit()
                    _log(job, f"followed @{job.author_handle} instead of another DM")
                else:
                    _log(job, f"follow instead of DM failed ({follow_code})")

    if (
        method != "reply"
        and settings_row.send_dms
        and job.dm_text
        and job.dm_status in ("none", "pending")
    ):
        if job.reply_status == "unknown":
            return {"deferred": "reply outcome unknown - not sending a DM on top"}

        state = limits.check(db, settings_row, "dm")
        if not state.allowed:
            return {"deferred": state.reason}

        # Follow-up DM: follow the person first so a non-answer does not hide
        # the message in their requests/unknown inbox.
        if dm_count > 0 and not job.followed:
            follow = executor.run_script("follow", {"username": job.author_handle}, creds=creds)
            follow_code = follow.get("code", "ERROR")
            if follow.get("success") or follow_code == "ALREADY_FOLLOWING":
                job.followed = True
                db.add(
                    ActionLog(
                        user_id=job.user_id,
                        job_id=job.id,
                        action="follow",
                        status="sent",
                        target=f"@{job.author_handle}",
                        content="",
                        detail="followed before the follow-up DM",
                    )
                )
                db.commit()
                _log(job, f"followed @{job.author_handle} before the follow-up DM")
            else:
                _log(job, f"follow before follow-up failed ({follow_code}) - sending DM anyway")

        job.dm_attempts = int(job.dm_attempts or 0) + 1
        result = executor.run_script(
            "dm",
            {"username": job.author_handle, "message": job.dm_text},
            creds=creds,
            dm_passcode=accounts.dm_passcode(account),
        )

        # X sometimes only allows a DM once you follow. Follow *only* then, and
        # retry the DM once - never follow when the DM already works.
        if result.get("code") == "DM_LOCKED" and settings_row.follow_when_needed:
            follow = executor.run_script("follow", {"username": job.author_handle}, creds=creds)
            follow_code = follow.get("code", "ERROR")
            if follow.get("success") or follow_code == "ALREADY_FOLLOWING":
                job.followed = True
                _log(job, f"followed @{job.author_handle} - X blocked the DM until follow")
                db.add(
                    ActionLog(
                        user_id=job.user_id,
                        job_id=job.id,
                        action="follow",
                        status="sent",
                        target=f"@{job.author_handle}",
                        content="",
                        detail="followed because X blocked the DM",
                    )
                )
                db.commit()
                job.dm_attempts = int(job.dm_attempts or 0) + 1
                result = executor.run_script(
                    "dm",
                    {"username": job.author_handle, "message": job.dm_text},
                    creds=creds,
                    dm_passcode=accounts.dm_passcode(account),
                )
                if result.get("code") == "DM_LOCKED":
                    result["error"] = (
                        f"followed @{job.author_handle}, but X still blocks DMs - "
                        "this account does not accept DMs from you"
                    )
            else:
                _log(job, f"follow failed ({follow_code}) - DM not retried")
                result["error"] = (
                    f"could not follow @{job.author_handle} ({follow_code}), and DMs are "
                    "blocked until you follow"
                )

        code = result.get("code", "ERROR")
        job.dm_status, stop = _apply_write_result(
            db,
            job,
            "dm",
            result,
            target=f"@{job.author_handle}",
            content=job.dm_text,
        )
        if stop:
            job.status = "queued"
            return {"stop": stop, "job_status": "queued"}

        # Closed inbox: remember the handle so future posts never DM them again.
        if code == "DM_CLOSED":
            handle = job.author_handle.strip().lstrip("@").lower()
            handles = [str(item).strip().lstrip("@").lower() for item in (settings_row.closed_inbox_handles or [])]
            if handle and handle not in handles:
                settings_row.closed_inbox_handles = [*handles, handle]
                _log(job, f"@{job.author_handle} has a closed inbox - no future DMs")
                db.commit()

        # "Chat did not finish loading" is a transient browser problem: nothing
        # was sent, so retry it later instead of losing the lead.
        if (
            code in ("CHAT_NOT_READY", "CHAT_UNAVAILABLE")
            and int(job.dm_attempts or 0) < 2
        ):
            job.status = "retry_wait"
            job.dm_status = "pending"
            job.next_retry_at = _now() + timedelta(minutes=30)
            job.last_error = "waiting to retry: X chat did not load"
            _log(
                job,
                f"DM chat did not load - auto-retry {int(job.dm_attempts or 0) + 1}/3 in 30 min",
            )
            db.commit()
            return {}

        if job.dm_status in ("failed", "unknown", "skipped"):
            job.status = "skipped" if job.dm_status == "skipped" else "failed"
            job.last_error = result.get("error") or code
            return {}

    # ---- final status --------------------------------------------------
    unknown = "unknown" in (job.reply_status, job.dm_status, job.email_status)
    failed = "failed" in (job.reply_status, job.dm_status, job.email_status)

    if unknown:
        job.status = "failed"
        job.last_error = "outcome unknown - open X and verify manually"
    elif failed:
        job.status = "failed"
    elif method == "email":
        job.status = "sent" if job.email_status in ("sent", "skipped") else "failed"
    elif method == "reply":
        # Job-board accounts: reply only, no DM.
        job.status = "sent" if job.reply_status in ("sent", "skipped") else "failed"
    elif settings_row.send_dms:
        job.status = "sent" if job.dm_status in ("sent", "skipped") else "failed"
    else:
        job.status = "sent" if job.reply_status in ("sent", "skipped") else "failed"

    if job.status == "sent":
        job.sent_at = _now()
    _log(job, f"reply={job.reply_status} dm={job.dm_status} email={job.email_status}")
    return {}


def _apply_write_result(
    db: Session,
    job: JobPost,
    action: str,
    result: dict,
    *,
    target: str = "",
    content: str = "",
) -> tuple[str, str]:
    """Map RESULT_JSON onto a status. Returns (status, stop_reason)."""
    code = result.get("code", "ERROR")
    success = bool(result.get("success"))
    error = str(result.get("error") or "")

    if success:
        status = "sent"
    elif code in ("CHAT_NOT_READY", "CHAT_UNAVAILABLE"):
        # X's chat pane did not render. Nothing was sent, and retrying on its
        # own just burns time - mark it skipped with the reason.
        status = "skipped"
    elif code == "PASSCODE_INVALID":
        status = "skipped"
    elif code == "DELIVERY_UNVERIFIED":
        # X showed it optimistically but it never landed.
        status = "skipped"
    elif code == "DM_LOCKED":
        # This account does not accept DMs from us. Not our failure to retry.
        status = "skipped"
    elif code == "DM_CLOSED":
        # Their X inbox is closed; no DM can ever land. Never retry.
        status = "skipped"
    elif code == "DUPLICATE":
        status = "skipped"
    elif code == "UNKNOWN":
        status = "unknown"
    elif code == "PASSCODE_REQUIRED":
        # Nothing was sent, so this is a safe, retryable failure.
        status = "failed"
    else:
        status = "failed"

    field = {
        "reply": "reply_status",
        "dm": "dm_status",
        "email": "email_status",
    }.get(action, "dm_status")
    setattr(job, field, status)

    db.add(
        ActionLog(
            user_id=job.user_id,
            job_id=job.id,
            action=action,
            status=status,
            target=(target or "")[:300],
            content=(content or "")[:4000],
            detail=error[:900],
        )
    )
    _log(job, f"{action}: {status}" + (f" - {error}" if error else ""))

    stop = ""
    if code == "SESSION_EXPIRED":
        stop = "X session expired - reconnect the account"
    elif code == "RATE_LIMITED":
        stop = "X rate-limited this session - paused"
    return status, stop


# ------------------------------------------------------------------ decision

def approve(db: Session, job: JobPost, *, approved: bool, reply_text: str | None = None, dm_text: str | None = None) -> JobPost:
    job.decided_at = _now()
    if reply_text is not None:
        job.reply_text = reply_text
    if dm_text is not None:
        job.dm_text = dm_text
    if approved:
        job.status = "queued"
        job.decision_reason = "approved by you - queued to send"
        _log(job, "approved by you - queued to send")
        # Learn from what the human actually approved (often after editing).
        if job.reply_text or job.dm_text:
            db.add(
                DraftExample(
                    user_id=job.user_id,
                    role=job.role or "",
                    reply_text=job.reply_text or "",
                    dm_text=job.dm_text or "",
                )
            )
            _prune_examples(db, user_id=job.user_id)
    else:
        job.status = "rejected"
        job.decision_reason = "rejected by you"
        _log(job, "rejected by you")
    db.commit()
    db.refresh(job)
    return job


def _prune_examples(db: Session, keep: int = 20, user_id: int | None = None) -> None:
    stmt = select(DraftExample)
    if user_id is not None:
        stmt = stmt.where(DraftExample.user_id == user_id)
    rows = list(db.scalars(stmt.order_by(DraftExample.id.desc())))
    for old in rows[keep:]:
        db.delete(old)


def pending_count(db: Session, user_id: int | None = None) -> int:
    stmt = select(JobPost.id).where(JobPost.status == "pending_approval")
    if user_id is not None:
        stmt = stmt.where(JobPost.user_id == user_id)
    return len(db.scalars(stmt).all())


# Statuses where a post with an application link is still actionable by hand.
# Rejected posts stay out: the agent already decided they are not a fit.
OPEN_LINK_STATUSES = ("new", "pending_approval", "queued", "failed", "skipped")


def apply_link_count(db: Session, user_id: int | None = None) -> int:
    """Posts that carry a direct application link and are not applied yet."""
    stmt = select(func.count(JobPost.id)).where(
        JobPost.apply_url.isnot(None),
        JobPost.apply_url != "",
        JobPost.status.in_(OPEN_LINK_STATUSES),
    )
    if user_id is not None:
        stmt = stmt.where(JobPost.user_id == user_id)
    return int(db.scalar(stmt) or 0)

