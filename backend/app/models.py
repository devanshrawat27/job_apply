"""Data model for the single outreach flow.

Tables
------
profile          the human's resume + targeting preferences (single row, id=1)
x_account        connected X account and its encrypted session cookies
agent_settings   thresholds, caps, quiet hours (single row, id=1)
job_post         every post the agent discovered, plus its draft and outcome
run              one scan or one send batch
action_log       append-only audit trail for every write attempt
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Profile(Base):
    __tablename__ = "profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )

    full_name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(60), default="")
    location: Mapped[str] = mapped_column(String(120), default="")
    links: Mapped[dict] = mapped_column(JSON, default=dict)

    resume_text: Mapped[str] = mapped_column(Text, default="")
    resume_filename: Mapped[str] = mapped_column(String(255), default="")
    resume_path: Mapped[str] = mapped_column(String(500), default="")

    # The roles the agent searches for. The first entry is the primary title.
    job_title: Mapped[str] = mapped_column(String(160), default="")
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    # "tech" | "non-tech" - inferred from the resume so a developer never gets
    # sales/marketing posts and vice versa.
    domain: Mapped[str] = mapped_column(String(20), default="tech")

    skills: Mapped[list] = mapped_column(JSON, default=list)
    target_roles: Mapped[list] = mapped_column(JSON, default=list)
    extra_keywords: Mapped[list] = mapped_column(JSON, default=list)
    locations: Mapped[list] = mapped_column(JSON, default=list)
    avoid: Mapped[list] = mapped_column(JSON, default=list)

    seniority: Mapped[str] = mapped_column(String(60), default="fresher")
    # Total professional experience in months. 4 months is valid, so a plain
    # "years" integer loses information.
    experience_months: Mapped[int] = mapped_column(Integer, default=0)
    current_company: Mapped[str] = mapped_column(String(200), default="")
    current_role: Mapped[str] = mapped_column(String(200), default="")
    min_salary: Mapped[str] = mapped_column(String(80), default="")
    remote_ok: Mapped[bool] = mapped_column(Boolean, default=True)

    tone: Mapped[str] = mapped_column(String(60), default="friendly-professional")
    pitch: Mapped[str] = mapped_column(Text, default="")

    # GitHub profile pulled from the public API (no OAuth needed). Used to make
    # messages and job matching concrete: real projects, languages and stars.
    github_username: Mapped[str] = mapped_column(String(120), default="")
    github_summary: Mapped[str] = mapped_column(Text, default="")
    github_data: Mapped[dict] = mapped_column(JSON, default=dict)
    github_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class XAccount(Base):
    __tablename__ = "x_account"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    session_ciphertext: Mapped[str] = mapped_column(Text, default="")
    dm_passcode: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="connected")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Resume(Base):
    """One uploaded resume. The agent picks the most relevant one per post."""

    __tablename__ = "resume"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    label: Mapped[str] = mapped_column(String(120), default="")
    filename: Mapped[str] = mapped_column(String(255), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    path: Mapped[str] = mapped_column(String(500), default="")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentSettings(Base):
    __tablename__ = "agent_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )

    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    scan_interval_minutes: Mapped[int] = mapped_column(Integer, default=30)

    max_posts_per_scan: Mapped[int] = mapped_column(Integer, default=40)
    lookback_hours: Mapped[int] = mapped_column(Integer, default=36)

    relevance_threshold: Mapped[int] = mapped_column(Integer, default=65)
    auto_send_confidence: Mapped[float] = mapped_column(Float, default=0.70)
    auto_send_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    daily_reply_cap: Mapped[int] = mapped_column(Integer, default=8)
    daily_dm_cap: Mapped[int] = mapped_column(Integer, default=8)
    min_minutes_between_writes: Mapped[int] = mapped_column(Integer, default=12)
    quiet_hours: Mapped[str] = mapped_column(String(40), default="23-7")

    use_public_reply: Mapped[bool] = mapped_column(Boolean, default=True)
    send_dms: Mapped[bool] = mapped_column(Boolean, default=True)
    # Only follow when X blocks the DM until the recipient is followed.
    follow_when_needed: Mapped[bool] = mapped_column(Boolean, default=True)
    # Handles you reported as fake; their posts are skipped.
    reported_handles: Mapped[list] = mapped_column(JSON, default=list)
    extra_queries: Mapped[list] = mapped_column(JSON, default=list)
    # Use the logged-in chatgpt.com browser session for the analyst when no API
    # key exists. Off by default; the human connects ChatGPT in Settings.
    chatgpt_browser_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # People whose X inbox is closed. The agent never DMs them again; posts from
    # them still get a public reply when one is possible.
    closed_inbox_handles: Mapped[list] = mapped_column(JSON, default=list)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class JobPost(Base):
    __tablename__ = "job_post"
    __table_args__ = (UniqueConstraint("user_id", "post_id", name="uq_job_post_user_post"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )

    post_id: Mapped[str] = mapped_column(String(40), index=True)
    post_url: Mapped[str] = mapped_column(String(400), default="")
    author_handle: Mapped[str] = mapped_column(String(120), default="")
    author_name: Mapped[str] = mapped_column(String(200), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    # Fingerprint of the post text. Catches the same job reposted by a
    # different account, which post_id dedupe alone would miss.
    content_hash: Mapped[str] = mapped_column(String(40), default="", index=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    # LLM extraction
    relevance: Mapped[int] = mapped_column(Integer, default=0)
    company: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(200), default="")
    job_location: Mapped[str] = mapped_column(String(200), default="")
    apply_method: Mapped[str] = mapped_column(String(80), default="")
    contact: Mapped[str] = mapped_column(String(200), default="")
    apply_url: Mapped[str] = mapped_column(String(500), default="")
    contact_email: Mapped[str] = mapped_column(String(200), default="")
    # dm | email | link  - how this post should actually be applied to
    outreach_method: Mapped[str] = mapped_column(String(20), default="dm")
    # Plain-language reason shown to the human when the agent stops.
    decision_reason: Mapped[str] = mapped_column(Text, default="")
    # person | company | job_board
    author_type: Mapped[str] = mapped_column(String(20), default="person")
    required_experience_months: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(Text, default="")
    # Which search keyword surfaced this post (used to learn good keywords).
    query_text: Mapped[str] = mapped_column(String(200), default="", index=True)
    # Which resume the agent chose for this post.
    resume_id: Mapped[int] = mapped_column(Integer, default=0)
    resume_label: Mapped[str] = mapped_column(String(120), default="")

    # Fake / scam post detection.
    spam_score: Mapped[int] = mapped_column(Integer, default=0)
    spam_reasons: Mapped[list] = mapped_column(JSON, default=list)
    followed: Mapped[bool] = mapped_column(Boolean, default=False)

    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    uncertainties: Mapped[list] = mapped_column(JSON, default=list)
    generic_draft: Mapped[bool] = mapped_column(Boolean, default=False)
    # ChatGPT job-fit screen: reviewed once, then never sent to the model again.
    ai_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_fit: Mapped[int] = mapped_column(Integer, default=-1)
    ai_note: Mapped[str] = mapped_column(Text, default="")
    # Incoming reply tracking (DM inbox / public reply to our post).
    incoming_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    incoming_reply_text: Mapped[str] = mapped_column(Text, default="")
    # DM retry bookkeeping for "X chat did not finish loading" failures.
    dm_attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reply_text: Mapped[str] = mapped_column(Text, default="")
    dm_text: Mapped[str] = mapped_column(Text, default="")

    # new | rejected | pending_approval | approved | sending | sent | failed | skipped
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)
    reply_status: Mapped[str] = mapped_column(String(30), default="none")
    dm_status: Mapped[str] = mapped_column(String(30), default="none")
    email_status: Mapped[str] = mapped_column(String(30), default="none")
    last_error: Mapped[str] = mapped_column(Text, default="")

    # Set once a human approves/rejects; None while untouched.
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    logs: Mapped[list] = mapped_column(JSON, default=list)

    actions: Mapped[list["ActionLog"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="ActionLog.id"
    )


class Run(Base):
    __tablename__ = "run"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(30), default="scan")  # scan | send | manual_send
    status: Mapped[str] = mapped_column(String(30), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")


class ActionLog(Base):
    __tablename__ = "action_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    job_id: Mapped[int] = mapped_column(ForeignKey("job_post.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(30))  # reply | dm | email | follow
    status: Mapped[str] = mapped_column(String(30))
    target: Mapped[str] = mapped_column(String(300), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    job: Mapped[JobPost] = relationship(back_populates="actions")


class DraftExample(Base):
    """Messages the human approved (often after editing).

    They are fed back to the composer as style examples, so the agent keeps
    sounding like the person instead of like a template.
    """

    __tablename__ = "draft_example"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    role: Mapped[str] = mapped_column(String(200), default="")
    reply_text: Mapped[str] = mapped_column(Text, default="")
    dm_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SearchQuery(Base):
    """A keyword the agent has tried, with how well it performed.

    Only keywords that produce relevant posts become `active` and keep being
    used. Weak ones are dropped, so the table never becomes a dumping ground.
    """

    __tablename__ = "search_query"
    __table_args__ = (UniqueConstraint("user_id", "keyword", name="uq_search_query_user_keyword"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    keyword: Mapped[str] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(20), default="candidate")  # candidate | active
    # Pinned keywords are always scheduled (rotated fairly), regardless of score.
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    # Where the keyword came from: seed | curated | analyst (ChatGPT suggestion)
    source: Mapped[str] = mapped_column(String(20), default="seed")

    uses: Mapped[int] = mapped_column(Integer, default=0)
    posts_seen: Mapped[int] = mapped_column(Integer, default=0)
    posts_relevant: Mapped[int] = mapped_column(Integer, default=0)
    # Replies/DMs received from posts found by this keyword. Real outcome, not
    # just "looks relevant".
    replies: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[float] = mapped_column(Float, default=0.0)

    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class LLMApiKey(Base):
    """A per-user LLM credential (e.g. the ChatGPT / OpenAI API key).

    The key is stored encrypted, exactly like the X session cookies, and is
    never returned by the API. ``provider`` is only a label for the UI; every
    provider that speaks the OpenAI chat-completions format works here.
    """

    __tablename__ = "llm_api_key"
    __table_args__ = (UniqueConstraint("user_id", "label", name="uq_llm_key_user_label"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(40), default="openai")
    label: Mapped[str] = mapped_column(String(80), default="ChatGPT")
    key_ciphertext: Mapped[str] = mapped_column(Text, default="")
    base_url: Mapped[str] = mapped_column(String(300), default="https://api.openai.com/v1")
    model: Mapped[str] = mapped_column(String(120), default="gpt-4o-mini")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Insight(Base):
    """Analyst output: which keywords work, what to write better.

    Produced by the LLM from the agent's own keyword/job data. The agent uses it
    as advice only - it never sends anything on its own.
    """

    __tablename__ = "insight"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(40), default="keyword_review")
    summary: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
