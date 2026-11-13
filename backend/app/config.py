"""Application settings loaded from the environment / .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "JobPilot - X job outreach agent"
    environment: str = "development"
    database_url: str = "sqlite:///./jobpilot.db"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # LLM (any OpenAI-compatible provider)
    llm_api_key: str | None = None
    # Comma separated fallback keys. When one runs out of quota the next is used.
    llm_api_keys: str | None = None
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "openai/gpt-4o-mini"
    llm_timeout_s: int = 90

    # Playwright executor
    automation_enabled: bool = True
    automation_timeout_s: int = 180
    automation_headless: bool = False

    # Auth. Set JWT_SECRET_KEY in production; AUTH_ENABLED=false is only for
    # local single-user development and automated tests.
    auth_enabled: bool = True
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 120
    refresh_token_expire_days: int = 30
    login_rate_limit: int = 10

    # X sign-in
    x_login_timeout_s: int = 210

    # Optional GitHub token. Public data works without it (60 requests/hour).
    github_token: str | None = None

    # At-rest encryption for the X session cookies
    credentials_encryption_key: str | None = None

    # Background scanner
    scheduler_enabled: bool = True
    scheduler_poll_seconds: int = 30

    # Email applications (optional). When the post says "mail us at ...".
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_starttls: bool = True

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_password)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_key_list)

    @property
    def llm_key_list(self) -> list[str]:
        raw = self.llm_api_keys or self.llm_api_key or ""
        return [key.strip() for key in raw.split(",") if key.strip()]

    @property
    def llm_model_list(self) -> list[str]:
        return [model.strip() for model in (self.llm_model or "").split(",") if model.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
