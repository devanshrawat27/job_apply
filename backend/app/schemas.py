"""Pydantic schemas for the API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_serializer

from app.utils.time import iso_utc


# --------------------------------------------------------------------- profile

class ProfileIn(BaseModel):
    full_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: dict = Field(default_factory=dict)

    resume_text: str = ""
    job_title: str = ""
    onboarding_completed: bool = False
    domain: str = "tech"
    skills: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)
    extra_keywords: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)

    seniority: str = "fresher"
    experience_months: int = 0
    current_company: str = ""
    current_role: str = ""
    min_salary: str = ""
    remote_ok: bool = True
    tone: str = "friendly-professional"
    pitch: str = ""


class ProfileOut(ProfileIn):
    id: int = 1
    resume_filename: str = ""
    resume_path: str = ""
    github_username: str = ""
    github_summary: str = ""
    github_data: dict = {}
    github_synced_at: datetime | None = None
    updated_at: datetime | None = None

    @field_serializer("updated_at", "github_synced_at")
    def _serialize_utc(self, value: datetime | None, _info):
        return iso_utc(value)

    model_config = {"from_attributes": True}


class ResumeParseOut(BaseModel):
    filename: str
    chars: int
    extracted: dict


class ResumeOut(BaseModel):
    id: int
    label: str
    filename: str
    is_primary: bool
    chars: int = 0
    created_at: datetime | None = None

    @field_serializer("created_at")
    def _serialize_utc(self, value: datetime | None, _info):
        return iso_utc(value)


# -------------------------------------------------------------------- accounts

class ConnectIn(BaseModel):
    username: str
    password: str
    verification_code: str | None = None
    dm_passcode: str | None = None


class DmPasscodeIn(BaseModel):
    passcode: str | None = None


class AccountOut(BaseModel):
    id: int
    username: str
    display_name: str
    status: str
    has_session: bool = True
    has_dm_passcode: bool = False
    last_checked_at: datetime | None = None

    @field_serializer("last_checked_at")
    def _serialize_utc(self, value: datetime | None, _info):
        return iso_utc(value)


# -------------------------------------------------------------------- settings

class SettingsIn(BaseModel):
    enabled: bool | None = None
    scan_interval_minutes: int | None = None
    max_posts_per_scan: int | None = None
    lookback_hours: int | None = None
    relevance_threshold: int | None = None
    auto_send_confidence: float | None = None
    auto_send_enabled: bool | None = None
    daily_reply_cap: int | None = None
    daily_dm_cap: int | None = None
    min_minutes_between_writes: int | None = None
    quiet_hours: str | None = None
    use_public_reply: bool | None = None
    send_dms: bool | None = None
    follow_when_needed: bool | None = None
    reported_handles: list[str] | None = None
    extra_queries: list[str] | None = None
    chatgpt_browser_enabled: bool | None = None
    closed_inbox_handles: list[str] | None = None


class SettingsOut(BaseModel):
    enabled: bool
    scan_interval_minutes: int
    max_posts_per_scan: int
    lookback_hours: int
    relevance_threshold: int
    auto_send_confidence: float
    auto_send_enabled: bool
    daily_reply_cap: int
    daily_dm_cap: int
    min_minutes_between_writes: int
    quiet_hours: str
    use_public_reply: bool
    send_dms: bool
    follow_when_needed: bool
    reported_handles: list[str]
    extra_queries: list[str]
    chatgpt_browser_enabled: bool
    closed_inbox_handles: list[str] = []

    model_config = {"from_attributes": True}


# ------------------------------------------------------------------------ jobs

class JobOut(BaseModel):
    id: int
    post_id: str
    post_url: str
    author_handle: str
    author_name: str
    content: str
    posted_at: datetime | None
    discovered_at: datetime

    relevance: int
    company: str
    role: str
    job_location: str
    apply_method: str
    contact: str
    apply_url: str
    contact_email: str
    outreach_method: str
    decision_reason: str
    author_type: str
    required_experience_months: int
    reason: str
    query_text: str
    resume_id: int = 0
    resume_label: str = ""
    spam_score: int
    spam_reasons: list[str]
    followed: bool
    generic_draft: bool
    email_status: str

    confidence: float
    uncertainties: list[str]
    reply_text: str
    dm_text: str

    status: str
    reply_status: str
    dm_status: str
    last_error: str
    decided_at: datetime | None
    sent_at: datetime | None
    # ChatGPT job-fit screen + incoming reply tracking
    ai_fit: int = -1
    ai_note: str = ""
    incoming_reply_at: datetime | None = None
    incoming_reply_text: str = ""
    logs: list[str]

    @field_serializer("posted_at", "discovered_at", "decided_at", "sent_at", "incoming_reply_at")
    def _serialize_utc(self, value: datetime | None, _info):
        return iso_utc(value)

    model_config = {"from_attributes": True}


class ApproveIn(BaseModel):
    approved: bool = True
    reply_text: str | None = None
    dm_text: str | None = None


# ------------------------------------------------------------------------ runs

class RunOut(BaseModel):
    id: int
    kind: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    stats: dict
    error: str

    @field_serializer("started_at", "finished_at")
    def _serialize_utc(self, value: datetime | None, _info):
        return iso_utc(value)

    model_config = {"from_attributes": True}


# ----------------------------------------------------------------------- auth

class AuthStatusOut(BaseModel):
    auth_enabled: bool
    has_user: bool


class RegisterIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=8, max_length=200)


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=300)


class TokenPairOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: str
    is_active: bool

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    message: str
