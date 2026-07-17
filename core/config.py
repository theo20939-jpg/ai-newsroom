"""Centralized application configuration loaded from environment variables."""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root (core/ is a direct child of it) - used to anchor .env to an
# absolute path. A relative "env_file=\".env\"" is resolved by pydantic-settings
# against the process's current working directory, not this file's location,
# so launching a script from anywhere other than the repo root would silently
# fail to load .env (optional fields would just stay at their defaults).
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    """Application settings sourced from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI Newsroom"
    app_env: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "postgres"
    postgres_password: SecretStr = SecretStr("postgres")
    postgres_db: str = "ai_newsroom"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # Reserved for future phases (Telegram Bot / AI Layer).
    # Optional and unused in Phase 1 - no functionality depends on them yet.
    telegram_bot_token: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    max_daily_ai_cost: float | None = None
    max_monthly_ai_cost: float | None = None

    # Phase 7 AI Integration Layer (docs/phase7_architecture_contract.md).
    # `enabled_providers` gates which providers build_provider_registry() actually
    # constructs (§2 rule 2) - a provider_id absent here is never registered, even if
    # its credential is present. Empty by default: no provider goes live until a restart
    # explicitly opts it in (§17.1, §20.1 step 5/7).
    enabled_providers: list[str] = []
    # Gated, boot-time-only, opt-in CapabilityNegotiator pass (§17.3) - deferred past this
    # delivery (CapabilityNegotiator is not implemented yet), but the setting is added now
    # so its default ("off") is already the safe, documented value.
    verify_capabilities_at_boot: bool = False
    # §28 Q1 (Pending Ratification): deliberately no default. RateLimiter and the real
    # CostTracker ledger MUST raise a boot-time configuration error if this is left unset,
    # rather than silently choosing fail-open or fail-closed - the contract's own binding
    # provisional rule for this one still-open question.
    redis_unavailable_policy: Literal["fail_open", "fail_closed"] | None = None

    # Telegram Client API (Telethon) - used only by the Source Collector.
    # Fully separate from telegram_bot_token, which is Bot API and belongs to bot/.
    telegram_api_id: int | None = None
    telegram_api_hash: SecretStr | None = None
    telegram_session_string: SecretStr | None = None

    # GitHub REST API - used only by integrations/sources/github_source.py.
    # Optional: the GitHub API works unauthenticated too, just at a much lower
    # rate limit (60 req/hr vs 5000 req/hr). Required for the pack's
    # github_api sources to be imported at all (see services/adapter_keys.py).
    github_token: SecretStr | None = None

    @property
    def database_url(self) -> str:
        """Build the async PostgreSQL connection URL for SQLAlchemy."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        """Build the Redis connection URL."""
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance shared across the application."""
    return Settings()


settings = get_settings()
