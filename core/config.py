"""Centralized application configuration loaded from environment variables."""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
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

    # Phase 9 Triage Orchestrator (docs/phase9_research_intelligence_architecture_contract.md
    # §7.6/§22). A PROCESSING NewsEvent with no active task becomes a stale-recovery
    # candidate once its claim age exceeds this many seconds. The Contract freezes this
    # guard's *existence and positivity* as architecture, not configuration (§7.6 rule 5,
    # §22) - Field(gt=0) enforces that at Settings construction (process startup), so an
    # invalid value (0 or negative) fails loudly rather than silently disabling
    # stale-recovery protection. Only the exact duration (the default below) is product
    # configuration.
    stale_processing_threshold_seconds: int = Field(default=900, gt=0)

    # GitHub REST API - used only by integrations/sources/github_source.py.
    # Optional: the GitHub API works unauthenticated too, just at a much lower
    # rate limit (60 req/hr vs 5000 req/hr). Required for the pack's
    # github_api sources to be imported at all (see services/adapter_keys.py).
    github_token: SecretStr | None = None

    # Phase 12 Fresh News Automation (docs/phase12_fresh_news_automation_architecture_contract.md
    # §11/§16). Opt-in by default, matching enabled_providers/verify_capabilities_at_boot's own
    # established convention: automation does not run until explicitly enabled. Global, not
    # per-source cadence - schemas.source_definition.SourceDefinition.fetch_interval is
    # deliberately never imported into NewsSource (see services/source_pack_importer.py).
    news_collection_enabled: bool = False
    news_collection_interval_seconds: int = Field(default=1800, gt=0)

    # Phase 13 M4: automatic NEWS_ANALYSIS execution worker. Disabled by default, matching
    # news_collection_enabled's own established convention. No max_daily_ai_cost - cost exposure
    # is bounded entirely by news_analysis_freshness_cutoff_hours/news_analysis_batch_size/no
    # automatic FAILED retry (docs/phase13_automatic_news_analysis_implementation_plan.md §21).
    news_analysis_enabled: bool = False
    news_analysis_poll_interval_seconds: int = Field(default=300, gt=0)
    news_analysis_batch_size: int = Field(default=5, gt=0)
    news_analysis_freshness_cutoff_hours: float = Field(default=48.0, gt=0)

    # Phase 14: automatic CONTENT_GENERATION trigger + Telegram editorial notification (docs/
    # phase14_autonomous_newsroom_implementation_plan.md §6). Disabled by default, matching
    # news_analysis_enabled's own established convention.
    content_generation_enabled: bool = False
    content_generation_poll_interval_seconds: int = Field(default=300, gt=0)
    content_generation_batch_size: int = Field(default=5, gt=0)
    # SQL-side candidate scan cap, evaluated before Python-side score filtering - must be >=
    # content_generation_batch_size (enforced by tests/test_settings_phase7.py against the
    # defaults, not by a new cross-field validator - this codebase's Settings class has no
    # existing cross-field-validator precedent to extend).
    content_generation_scan_limit: int = Field(default=50, gt=0)
    content_generation_min_score: int = Field(default=70, ge=0, le=100)
    # Technical safety boundary only (bounds initial-enablement backlog cost, gives tests a safe
    # isolation lever) - NOT an editorial "is this still newsworthy" control. That judgment, to
    # the extent Phase 14 makes one at all, lives entirely in content_generation_min_score above.
    content_generation_freshness_cutoff_hours: float = Field(default=24.0, gt=0)
    # Safe default: dry-run only. Live sending requires a deliberate, explicit flip to False,
    # plus editorial_chat_id already configured (services/telegram_notifier.py fails loud
    # otherwise) - never a silent path to sending a real Telegram message.
    content_generation_dry_run: bool = True
    editorial_chat_id: int | None = None

    # Default editorial target output language (docs/
    # content_generation_language_final_implementation_plan.md). Injected explicitly by
    # capabilities.executor.CapabilityExecutor._build_context() into every
    # BusinessContext.language - never left to that schema field's own implicit default.
    # This is the language Capabilities are instructed to WRITE their output in, not the
    # source NewsEvent's own language (unrelated, tracked separately and unwired -
    # schemas/source_definition.py's SourceDefinition.language).
    default_content_language: str = "ru"

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
