"""Centralized application configuration loaded from environment variables."""
from datetime import datetime
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
    # Phase 23.1L (docs/phase23_1l_runtime_isolation_final_canary_report.md): a physically
    # separate database, same Postgres server, dedicated to pytest - the fix for a proven
    # incident (two live NEWS posts generated from a leaked test-fixture row) where integration
    # tests committed real rows into this same `postgres_db` and hand-maintained per-table
    # teardown DELETEs fell behind a newly-added FK-referencing table, silently orphaning them.
    # Deliberately a distinct database name, not a naming convention within `postgres_db` - two
    # different Postgres databases share nothing (no cross-database FK/query is even possible),
    # so this is a structural guarantee, not a discipline someone has to remember to uphold.
    postgres_test_db: str = "ai_newsroom_test"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # Reserved for future phases (Telegram Bot / AI Layer).
    # Optional and unused in Phase 1 - no functionality depends on them yet.
    telegram_bot_token: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    # Phase V2.1 (docs/nnj_source_faithful_editorial_visual_recomposition_v1.md): the Gemini image
    # adapter's own credential, consumed by `services/editorial_recomposition.py` (live NEWS photo
    # recomposition, gated by `editorial_recomposition_mode`) and, as of the REAL IMAGE PROVIDER
    # FINALIZATION phase, also by `services/meme_generation_orchestrator.py` (gated by
    # `meme_image_generation_mode == "enforce"`) - the same credential, two independent gated
    # consumers, never a provider-specific key duplicated per feature.
    gemini_api_key: SecretStr | None = None
    max_daily_ai_cost: float | None = None
    max_monthly_ai_cost: float | None = None

    # API cost optimization (docs/api_cost_optimization_report.md §10): the real, enforceable
    # application-level daily cost cap, superseding the never-wired-up `max_daily_ai_cost`
    # above (kept, unused, for backward compatibility - nothing reads it going forward).
    # Three-state pattern matching this codebase's own established fact_safety_mode/
    # editorial_scoring_version convention: "off" (RedisBudgetGuard always allows, no
    # logging), "shadow" (the safe initial default - computes and logs the projected
    # allow/deny decision, never blocks), "enforce" (actually raises BudgetExceededError once
    # the daily budget is exhausted).
    llm_budget_mode: Literal["off", "shadow", "enforce"] = "shadow"
    llm_daily_warning_usd: float = 0.50
    llm_daily_budget_usd: float = 1.00

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
    # Phase 15 runtime reliability fix (docs/phase15_runtime_reliability_report.md): bounded
    # cooldown for a regional/account-scoped provider permission failure (403), which - unlike a
    # genuinely permanent invalid-model/invalid-request config error - has been directly observed
    # to self-resolve within the same day. Threaded into FallbackPolicy at boot
    # (integrations/llm_gateway/boot.py); a model latched for this reason automatically becomes
    # routable again once this many seconds elapse, with no manual Redis intervention required.
    provider_regional_unavailable_cooldown_seconds: int = 3600

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

    # Phase I.2.1A.4: a real, reproduced hang - services/collector.py::_fetch_with_retry() awaited
    # SourceAdapter.fetch() with no timeout at all, so one broken/hung source (a Telegram user
    # session that had silently expired, causing Telethon to fall back to an interactive login
    # prompt no detached container can ever answer) blocked the entire collection cycle
    # indefinitely - no subsequent RSS/NEWS_API/Telegram source was ever attempted. Every
    # HTTP-based adapter already bounds itself internally (rss_source.py/github_source.py/
    # arxiv_source.py/hacker_news_source.py all set their own httpx `FETCH_TIMEOUT_SECONDS =
    # 15.0`), but nothing previously bounded a non-HTTP adapter (Telegram, via Telethon) or acted
    # as a defense-in-depth ceiling for any adapter regardless of its own internal timeout. This
    # single collector-level setting wraps every `adapter.fetch()` call
    # (`asyncio.wait_for`, this codebase's own established timeout idiom - workflows/runner.py,
    # services/image_intelligence.py, integrations/http/safe_fetch.py all use the same primitive)
    # so NO SourceAdapter of any kind can ever hang the cycle again. 30s (double every existing
    # per-adapter HTTP ceiling) is a reasoned starting default - generous headroom for Telegram's
    # own uncapped `iter_messages()` fetch of up to MESSAGE_FETCH_LIMIT=50 messages under normal
    # conditions, while still being a real, finite bound - not fit to production timing data yet.
    news_source_fetch_timeout_seconds: float = Field(default=30.0, gt=0)

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

    # Phase 22: Telegram Editorial Routing Foundation (docs/phase22_telegram_editorial_routing_
    # report.md). All `None` by default - byte-identical to pre-Phase-22 behavior (nothing calls
    # services/telegram_routing.py from any live/automated path yet, matching this phase's own
    # "routing capability only, not automatic decision making" scope). `newsroom_telegram_chat_id`
    # is deliberately separate from `editorial_chat_id` above (a different, single-topic delivery
    # path already in production use since Phase 14 - left completely untouched, per acceptance
    # criterion E) - the NINJA NEWSROOM supergroup this phase targets is a distinct destination.
    # Each `*_topic_id` is optional independently of the chat id itself: a destination whose topic
    # id is unset routes to the chat's own root (no `message_thread_id`), never an error - see
    # services/telegram_routing.py::resolve_route()'s own docstring for the exact contract.
    newsroom_telegram_chat_id: int | None = None
    news_topic_id: int | None = None
    meme_topic_id: int | None = None
    telegraph_topic_id: int | None = None
    instagram_topic_id: int | None = None
    reels_topic_id: int | None = None

    # Phase 23.1A: canary delivery adapter (docs/phase23_1a_canary_delivery_adapter_report.md).
    # Two-state, not the usual off/shadow/enforce shape - this selects which of two already-built
    # delivery mechanisms `worker/content_cycle.py` uses, it does not gate a new capability on/off.
    # "legacy" (default - byte-identical to every pre-Phase-23.1A behavior): the existing
    # `editorial_chat_id` + `services/telegram_notifier.py::send_editorial_card()`/`services/
    # image_preview_notifier.py::send_news_with_image_preview()` path, completely untouched.
    # "router": `worker/content_cycle.py` sends via Phase 22's `services/telegram_routing.py::
    # send_to_editorial_destination()` instead, hardcoded to `EditorialDestination.NEWS` only -
    # there is no path from this setting to any other destination. Intended only for the local
    # canary; never set in the real `.env` this phase.
    editorial_delivery_mode: Literal["legacy", "router"] = "legacy"

    # Default editorial target output language (docs/
    # content_generation_language_final_implementation_plan.md). Injected explicitly by
    # capabilities.executor.CapabilityExecutor._build_context() into every
    # BusinessContext.language - never left to that schema field's own implicit default.
    # This is the language Capabilities are instructed to WRITE their output in, not the
    # source NewsEvent's own language (unrelated, tracked separately and unwired -
    # schemas/source_definition.py's SourceDefinition.language).
    default_content_language: str = "ru"

    # Phase 15 M4: Editorial Scoring V2 (docs/phase15_m4_editorial_scoring_v2_report.md).
    # Explicit default "v1" - matches every other Phase 9-14 automation flag's own established
    # "opt-in, safe default" convention (news_collection_enabled, news_analysis_enabled,
    # content_generation_enabled, verify_capabilities_at_boot). Switching to "v2" requires no
    # database migration - the breakdown lives in the existing EditorialTask.workflow
    # step_results JSON (services.editorial_scoring). Switching back to "v1" (no code change,
    # no DB change) is the rollback path.
    editorial_scoring_version: Literal["v1", "v2"] = "v1"
    # Weights for services.editorial_scoring.compute_editorial_score_v2()'s five components -
    # must sum to 1.0 (tests/test_editorial_scoring.py enforces this against these exact
    # defaults, mirroring content_generation_scan_limit's own established
    # tested-not-validated convention - this Settings class has no cross-field-validator
    # precedent). Reasoned, not fit to historical outcome data (none exists yet - see
    # docs/phase15_editorial_intelligence_discovery_report.md §9) - kept here, not hardcoded,
    # so they are tunable without a code change once M4's backtest/live-validation evidence
    # supports a different distribution.
    editorial_scoring_weight_semantic: float = Field(default=0.40, ge=0.0, le=1.0)
    editorial_scoring_weight_freshness: float = Field(default=0.20, ge=0.0, le=1.0)
    editorial_scoring_weight_engagement: float = Field(default=0.20, ge=0.0, le=1.0)
    editorial_scoring_weight_source_reliability: float = Field(default=0.10, ge=0.0, le=1.0)
    editorial_scoring_weight_novelty: float = Field(default=0.10, ge=0.0, le=1.0)

    # Phase 15 M5: Fact Safety (docs/phase15_m5_fact_safety_report.md). Three-state, not the
    # usual two-state opt-in flag: "off" (zero processing, byte-identical to pre-M5 behavior -
    # the rollback path), "shadow" (compute and record findings on the existing "quality" step's
    # result, but never change delivery behavior - safe to default to, since it is purely
    # additive/observational), "enforce" (uses shadow's own findings to withhold live Telegram
    # delivery for a REVIEW/BLOCK-classified draft - see services/fact_safety.py's own docstring
    # for the exact mechanism). Default is "shadow", not "off": explicitly required by M5's own
    # task brief ("Preferred initial/default state for M5 validation: shadow") and safe to ship
    # as the code default without an .env change, because shadow mode is provably delivery-
    # neutral (tests/test_fact_safety.py's own "shadow mode records but does not block" case).
    # "enforce" is implemented but never selected by this default - a future milestone's
    # cutover decision, exactly mirroring editorial_scoring_version's own v1-default,
    # rollback-without-migration precedent.
    fact_safety_mode: Literal["off", "shadow", "enforce"] = "shadow"

    # Phase 16 M1: Image Intelligence (docs/phase16_m1_native_media_ingestion_report.md). Two-state
    # for M1 - "editorial" (the state that would actually change Telegram output) does not exist
    # yet and is reserved for M6 (docs/phase16_image_intelligence_discovery_report.md §19's own
    # recommendation to eventually match fact_safety_mode's off/shadow/enforce convention).
    # "off" (default): zero processing, byte-identical to pre-Phase-16 behavior - the rollback
    # path. "shadow": native candidates are discovered/recorded (Collector-time audit log,
    # CONTENT_GENERATION step_results) - never downloads an image, never changes Telegram output,
    # never changes ContentDraft text. Matches fact_safety_mode's own "off is the true no-op,
    # shadow is safe-by-construction" precedent, except M1 defaults to "off" (not "shadow") since,
    # unlike Fact Safety, this is a brand-new capability with zero live validation yet - M7's own
    # live-validation milestone is the gate for even a shadow-by-default posture.
    image_intelligence_mode: Literal["off", "shadow"] = "off"

    # Phase 18.10 M1/M2: Story Memory (docs/phase18_10_editorial_intelligence_report.md).
    # Three-state, matching fact_safety_mode's own convention exactly. "off" (default): zero
    # processing, byte-identical to pre-18.10 behavior - the rollback path. "shadow": every
    # NewsEvent is matched against recent same-category stories (services/story_memory.py) and
    # the result (story_id/story_match_type/story_match_score) is persisted for observability -
    # never suppresses NEWS_ANALYSIS task creation, so publication behavior is completely
    # unchanged. "enforce" (skip task creation for a semantic_duplicate match) is NOT implemented
    # in this phase - selecting it currently has no additional effect beyond "shadow" behavior
    # until a future milestone adds the suppression path; do not rely on it to change behavior
    # yet. Defaults to "off", not "shadow" - mirrors image_intelligence_mode's own reasoning: a
    # brand-new signal with zero live validation yet, not something safe to default to shadow
    # before this phase's own shadow-mode bake period produces real calibration data.
    story_memory_mode: Literal["off", "shadow", "enforce"] = "off"

    # STORY-CONTINUITY-P0-CONSTRAINED-ENFORCEMENT-1 (2026-09): the FIRST, deliberately very
    # narrow Story Continuity enforcement. When True (production may enable it only during the
    # authorized rollout - default stays False everywhere in code/config templates), a
    # continuity decision may have its editorial-task creation suppressed, but ONLY when it is a
    # near-certain DUPLICATE_NO_DELTA that passes every gate in services/story_continuity.py::
    # evaluate_constrained_enforcement() (score >= 0.99, stable-identity or exact-normalized-
    # title match, no material delta, not guard-forced, not polluted, not an identity conflict).
    # Everything else still fails open and creates the normal task. "Suppress" means ONLY: skip
    # create_task() for that event - the NewsEvent, Story link and audit evidence stay
    # persisted. No effect at all unless story_memory_mode != "off" (the pipeline that produces
    # the decision). Independent of story_memory_mode's own "enforce" value, which is a
    # different, broader Story Memory concept and is NOT wired to any suppression.
    story_continuity_p0_constrained_enforcement_enabled: bool = False

    # Phase 20 M3: candidate-retrieval time window for services/story_memory.py::match_story() -
    # previously a module-level constant (STORY_MATCH_LOOKBACK_DAYS = 14), now tunable without a
    # code deploy, matching services/editorial_scoring.py's own established "reasoned default,
    # refine from real shadow-mode data" convention. Value unchanged from the original constant -
    # this is a mechanism change (settings vs. hardcoded), not a recalibration.
    story_match_lookback_days: int = Field(default=14, gt=0)

    # TELEGRAPH Checkpoint 1 (deterministic topic-candidate formation, services/
    # telegraph_topic_candidates.py) - dormant until a caller invokes build_telegraph_topic_
    # candidates(); no scheduler, worker, or bot command reaches this module yet. TELEGRAPH
    # articles can legitimately be based on a Story older than a normal NEWS post (a still-current
    # topic worth explaining in depth), so this is a deliberately separate, larger window from
    # content_generation_freshness_cutoff_hours/news_analysis_freshness_cutoff_hours above - never
    # reused from either. Reasoned starting default (3 days - long enough for a developing story to
    # accumulate real depth, short enough to stay "current"), not fit to any real data yet, matching
    # this codebase's own established "reasoned default, refine later" convention.
    telegraph_candidate_recency_hours: float = Field(default=72.0, gt=0)

    # TELEGRAPH Checkpoint 2 (durable shortlist + human approval, services/telegraph_shortlist_
    # service.py::get_recently_proposed_story_ids()) - dormant until a caller invokes
    # create_telegraph_shortlist(); no scheduler/worker reaches this yet. Deliberately its own
    # setting, never reused from story_match_lookback_days (a Story-MATCHING window, an unrelated
    # concern) or telegraph_candidate_recency_hours above (candidate FRESHNESS, not reproposal
    # SPACING). Reasoned starting default (24h - one full day, so a Story is never re-proposed
    # twice within the same day across multiple future shortlist windows, but can be reconsidered
    # the next day if still developing), not fit to any real data yet.
    telegraph_reproposal_cooldown_hours: float = Field(default=24.0, gt=0)

    # TELEGRAPH Checkpoint 2 security correction: the explicit, minimal per-user approver
    # boundary for the shortlist callback (bot/handlers/telegraph_shortlist.py). A forensic
    # sweep of this codebase found no existing reusable admin/owner/operator allowlist or
    # authorization middleware anywhere (grepped for admin_user/owner_id/operator_id/allowlist/
    # is_admin - the only precedent is `enabled_providers` above, a provider-id allowlist, not a
    # person allowlist) - this is a new, narrowly-scoped setting, not a reuse of an existing one.
    # Mirrors `enabled_providers`'s own list-of-primitives shape/JSON-array env parsing exactly
    # (`TELEGRAPH_APPROVER_USER_IDS=[123456789]`). Deliberately FAIL CLOSED: the empty default
    # means NO Telegram user id is authorized to approve/reject - never "every member of
    # newsroom_telegram_chat_id", which was the exact gap this setting closes (chat membership
    # alone is necessary but no longer sufficient once APPROVED will gate paid Deep Research/
    # article generation). Populating this list is a deliberate, separate operator action (adding
    # real Telegram numeric user ids to `.env`), not made as part of this checkpoint.
    telegraph_approver_user_ids: list[int] = Field(default_factory=list)

    # Phase 19 M7 (docs/phase19 plan, Correction 1): a real, previously-undisclosed shadow-mode
    # gap was found in the block above's own downstream consumer (worker/content_cycle.py) - it
    # unconditionally computed and applied a Telegram reply_to_message_id, and could skip a send
    # entirely, the moment story_memory_mode != "off". This setting is the fix: Telegram
    # delivery behavior is now independently gated, never coupled to story_memory_mode or
    # story_context_mode alone. "off" (default): no reply computation at all for delivery
    # purposes, byte-identical to pre-Phase-18.10 behavior. "shadow": the reply decision is
    # computed and persisted (database.models.content_draft_reply_routing_proposal) for review,
    # but the real send always proceeds as a standalone post - reply_to_message_id stays None and
    # a fail-closed case is never skipped. "enforce": applies the decision to the real send,
    # preserving the original fail-closed skip-and-route-to-review guarantee - reaching enforce
    # requires both a separate human authorization and the Phase 19 M6 Story Memory calibration
    # gate being passed (a documented precondition, not a code-level check, since the calibration
    # report is a human-reviewed artifact).
    telegram_story_reply_mode: Literal["off", "shadow", "enforce"] = "off"

    # Phase 19 M7: Story Timeline + Editorial Memory (docs/phase19_m7_story_timeline_and_reply_
    # routing.md). Two-state, matching image_intelligence_mode's own convention - no "enforce"
    # value exists at all, since this milestone never proposes to change Copywriting output.
    # "off" (default): the "intelligence" step's own shadow hook never runs, zero processing.
    # "shadow": services/story_context.py::build_story_timeline() (a deterministic, evidence-only
    # reconstruction - no LLM call, no embeddings) is computed and persisted (database.models.
    # story_context_snapshot) for review whenever this event's underlying NewsEvent is
    # story-linked (requires story_memory_mode != "off" too) - Copywriting never reads it,
    # ContentDraft output is unchanged. Independent of telegram_story_reply_mode - a snapshot can
    # be computed even if reply-threading itself stays off.
    story_context_mode: Literal["off", "shadow"] = "off"

    # Phase 19 M8: Source Intelligence (docs/phase19_m8_source_intelligence.md). Two-state, no
    # "enforce" value - services/source_intelligence.py only ever produces hedged
    # POSSIBLE_ORIGINAL/POSSIBLE_CONFIRMATION/POSSIBLE_AGGREGATION/POSSIBLE_ANALYSIS/UNKNOWN
    # labels for human review, never a definitive attribution claim, and is never wired into
    # Copywriting's prompt/output at any mode. "off" (default): zero processing. "shadow": a
    # label is computed and persisted (database.models.news_event_source_intelligence) whenever
    # this event is story-linked (requires story_memory_mode != "off" too) - Copywriting never
    # reads it, ContentDraft output is unchanged.
    source_intelligence_mode: Literal["off", "shadow"] = "off"

    # Phase 19 M1: post-selection full-article acquisition (docs/phase19_m0_audit.md). Three-state,
    # matching story_memory_mode's own convention. "off" (default): zero network calls, zero
    # processing - byte-identical to pre-Phase-19 behavior. "shadow": for an event that has
    # already passed the existing selection pipeline (scripts/run_content_generation.py::
    # run_content_generation_for_event(), between task creation and WorkflowRunner.run() - never
    # for the mass NEWS_ANALYSIS population), the canonical article is fetched once and its
    # cleaned text persisted (database.models.news_event_article_acquisition), but Research/
    # Copywriting still read news_event.content unchanged - byte-identical delivery. "enforce":
    # Research/quote-verification read the persisted evidence via services.evidence_package
    # instead. Never blocks or fails the calling function - every failure mode is a persisted
    # status string, never a raised exception.
    article_acquisition_mode: Literal["off", "shadow", "enforce"] = "off"
    # Second, later-selected event resolving to the same canonical_url within this window reuses
    # the first event's already-fetched text (reused_from_news_event_id) instead of fetching
    # again - a fresh fetch happens automatically once the window has elapsed (staleness
    # protection), never an unbounded cache.
    article_acquisition_reuse_window_hours: int = Field(default=48, gt=0)
    article_acquisition_connect_timeout_seconds: float = Field(default=3.0, gt=0)
    article_acquisition_read_timeout_seconds: float = Field(default=7.0, gt=0)
    article_acquisition_total_timeout_seconds: float = Field(default=12.0, gt=0)
    article_acquisition_max_redirects: int = Field(default=3, gt=0)
    article_acquisition_max_html_bytes: int = Field(default=2_000_000, gt=0)
    article_acquisition_max_extracted_chars: int = Field(default=20_000, gt=0)

    # Phase 19 M10: bounded, source-local video discovery (docs/phase19_m10_video_discovery.md).
    # Three-state, matching article_acquisition_mode's own convention. "off" (default): zero
    # processing. "shadow": video hints already present in RSS/article HTML (never an open web
    # search, never a YouTube/Vimeo API call) are extracted and, for direct-hosted candidates
    # only, bounded-validated via safe_fetch() + magic-byte sniffing; results are persisted
    # (database.models.content_draft_media_item) for review only - Copywriting/Telegram delivery
    # are unaffected. "enforce": discovered/validated video candidates become eligible for M11
    # ranking and M12 delivery.
    video_discovery_mode: Literal["off", "shadow", "enforce"] = "off"
    video_discovery_connect_timeout_seconds: float = Field(default=3.0, gt=0)
    video_discovery_read_timeout_seconds: float = Field(default=8.0, gt=0)
    video_discovery_total_timeout_seconds: float = Field(default=15.0, gt=0)
    video_discovery_max_redirects: int = Field(default=3, gt=0)
    # A direct-hosted video file is legitimately much larger than an image - bounded well below
    # an unlimited download, but large enough that only the leading bytes needed for magic-byte
    # sniffing plus a reasonable short-clip cap are ever pulled over the wire.
    video_discovery_max_bytes: int = Field(default=20_000_000, gt=0)

    # Phase 19 M12: multi-photo/mixed-media Telegram delivery (docs/phase19_m12_rich_media_
    # delivery.md). "off" (default): services.image_preview_notifier.send_news_with_rich_media()
    # is never called - byte-identical to today's single-photo/text-only delivery. "shadow":
    # renders and logs what a media-group send would contain (item count/order/caption), never
    # calls bot.send_media_group(). "enforce": sends the real media group. Built and tested this
    # milestone but deliberately NOT wired into worker/content_cycle.py's live loop yet - doing
    # so safely requires M11's ranking to actually run and persist a specific draft's ranked
    # candidates first, which M11 deliberately does not do (see docs/phase19_m11_media_ranking.md
    # §1's own "no new persistence table" scope decision) - live wiring is left for a future,
    # separately-reviewed milestone.
    rich_media_mode: Literal["off", "shadow", "enforce"] = "off"

    # MEDIA-PROD-1: deterministic (no LLM) advertisement-keyword text scan over the NewsEvent's own
    # title/content, applied to whichever video hint rich_media_mode="enforce" would otherwise
    # attach (services/video_quality_gate.py::assess_video_text_signals()). "off" (default):
    # byte-identical to before this gate existed. "shadow": computes and logs the classification,
    # never drops the video hint. "enforce": a flagged ADVERTISEMENT classification drops the video
    # hint entirely (worker/content_cycle.py falls back to its existing image-only/text-only send,
    # exactly as it already does whenever no video hint resolves for any other reason - no new
    # fallback mechanism). Independent of rich_media_mode - rich_media_mode="enforce" remains the
    # precondition for a video hint to be looked up/attached at all.
    video_quality_gate_mode: Literal["off", "shadow", "enforce"] = "off"

    # Phase V2.27: native Telegram video upload for YouTube/Vimeo hosted-platform hints - before
    # this, a YouTube/Vimeo NativeVideoHint (services/video_discovery_persistence.py) always
    # became a plain caption link (services/image_preview_notifier.py::_hosted_platform_link_
    # line()), never an uploaded video. Two-state, no "shadow" - unlike video_discovery_mode's own
    # review-only shadow persistence, a download+transcode+discard-without-sending action has real
    # CPU/bandwidth/disk cost with no product benefit at review time, so there is nothing useful
    # for a shadow mode to do here. "off" (default): byte-identical to pre-V2.27 behavior -
    # YouTube/Vimeo hints still become a caption link. "enforce": worker/content_cycle.py attempts
    # services/hosted_video_download.py::download_hosted_video() for a YouTube/Vimeo hint instead;
    # on ANY failure (see that module's own docstring for the full list) the video is dropped
    # entirely for that send - no caption-link fallback in this mode (Phase V2.27 §4's own explicit
    # instruction). Independent of rich_media_mode - rich_media_mode="enforce" remains the
    # precondition for a video hint to be looked up/attached at all; this flag only controls
    # whether a YouTube/Vimeo hint specifically gets downloaded, so it can be turned off without
    # also disabling DIRECT_HOSTED video attachment (which never needs this flag - Telegram fetches
    # a direct-hosted URL itself, no local download ever happens for that platform).
    hosted_video_download_mode: Literal["off", "enforce"] = "off"
    # Overall wall-clock bound on one yt-dlp invocation (download + mux) - the process is killed
    # and the attempt treated as HOSTED_VIDEO_DOWNLOAD_FAILED if this elapses.
    hosted_video_download_timeout_seconds: float = Field(default=45.0, gt=0)
    # Telegram Bot API's own real, documented upload limit for a bot-uploaded (non-local-server)
    # file is 50MB - this is not an arbitrary product choice, it is the hard ceiling a larger
    # upload would fail against regardless of anything this codebase does. Enforced twice: as a
    # yt-dlp `--max-filesize` pre-check (aborts before finishing an oversized download) and again
    # as a real on-disk byte-count check after download (the pre-check is a best-effort estimate,
    # not always accurate for every source format).
    hosted_video_max_bytes: int = Field(default=50_000_000, gt=0)
    # A NEWS video attachment is a short illustrative clip, not the article itself - bounded well
    # under a typical full-length YouTube video. Enforced via yt-dlp's own `--match-filter`
    # (skips/aborts before downloading anything once declared duration is known), never a
    # post-download-only check.
    hosted_video_max_duration_seconds: int = Field(default=180, gt=0)
    # Separate, tighter bound for the optional compatibility-transcode fallback (services/
    # hosted_video_download.py) - only ever invoked for the rare case yt-dlp's own format
    # selection could not produce an already-Telegram-compatible H.264/AAC MP4 directly.
    hosted_video_ffmpeg_timeout_seconds: float = Field(default=30.0, gt=0)

    # Phase 19 M13: final-candidate vision review foundation (docs/phase19_m13_vision_review.md).
    # Two-state, no "enforce" value at all - reaching a real vision call always requires the
    # manually-invoked harness script (scripts/phase19_m13_vision_review_manual.py), never an
    # automatic/scheduled worker path, regardless of this setting's value. "off" (default): no
    # shadow persistence hook runs. "shadow": reserved for a future, narrowly-scoped deterministic
    # pre-check hook (e.g. persisting "this candidate is queued for vision review") - no such hook
    # exists yet in this milestone, so "shadow" is currently a no-op identical to "off"; the value
    # is defined now so a future milestone can add that hook without a new settings migration.
    media_vision_review_mode: Literal["off", "shadow"] = "off"

    # CROSS-PLATFORM-MEDIA-RESEARCH-SELECTION-1: mirrors media_vision_review_mode's own exact
    # two-state convention, for the sibling media_subject_match Capability. "off" (default): no
    # live path reaches it (there is none yet regardless). "shadow": reserved the same way
    # media_vision_review_mode's "shadow" is - no automatic hook exists yet; only the manually-
    # invoked harness (scripts/_cross_platform_media_research_canary_1.py) ever makes a real call,
    # independent of this setting's value.
    media_subject_match_mode: Literal["off", "shadow"] = "off"
    # A brand-new capability this phase adds: real, external web-based image discovery (section 5
    # Tiers 2-4 of the phase's own spec) - confirmed by direct code audit to not exist anywhere
    # else in this codebase (services/image_intelligence.py only ever fetches the NewsEvent's own
    # article URL). "off" (default, and the only state with a real backend today): services.
    # media_web_discovery.NullWebDiscoveryClient - zero network calls, zero results, a true no-op.
    # "shadow" is defined now, matching this codebase's own off/shadow staging convention, for a
    # FUTURE milestone that wires a real search-API-backed WebDiscoveryClient behind it; no such
    # backend exists yet, and selecting "shadow" today has no effect (no code branches on this
    # setting's value yet - a future integration is the one that would).
    media_web_discovery_mode: Literal["off", "shadow"] = "off"

    # Phase 19 M14: capability-level routing-objective overrides (docs/phase19_m14_cost_quality_
    # analysis.md). Empty by default - every real capability in this codebase relies on the
    # RoutingCriteria default (LOWEST_COST, see integrations/llm_gateway/routing/criteria.py's own
    # comment confirming no capability currently overrides it). A per-capability entry here
    # (capability_name -> one of RoutingObjective's values: "best_quality"/"lowest_cost"/
    # "fastest"/"reasoning") is injected into that capability's own GenerateRequest.metadata
    # ("objective") by capabilities/gateway_call.py::call_generate() - the gateway itself already
    # knows how to honor this via its own established request.metadata["objective"] convention;
    # no change to RoutingEngine/RoutingCriteria/the gateway was needed. Must stay empty in this
    # phase - populating it is a live routing-behavior change requiring its own, separate,
    # explicit authorization, never made as part of this implementation.
    capability_routing_objective_overrides: dict[str, str] = Field(default_factory=dict)

    # Phase 19 M3: Editorial Planning foundation (docs/phase19_m0_audit.md). NOT the usual
    # off/shadow/enforce triplet - "comparison" replaces "enforce" deliberately, matching this
    # codebase's own established adaptive_length_mode/beginner_copywriting_mode precedent for a
    # milestone that wants A/B-style side-by-side generation without ever mutating the live
    # artifact. "off" (default): the "intelligence" step's own hook never runs, zero processing.
    # "shadow": a zero-cost, zero-LLM-call deterministic scaffold (services/editorial_planning_
    # deterministic.py) is built and persisted (database.models.content_draft_editorial_plan) for
    # review - Copywriting never reads it, ContentDraft output is unchanged. "comparison": enables
    # the separately-invoked, never-auto-run scripts/phase19_m3_editorial_plan_comparison.py to
    # make a real, LLM-backed editorial_planning call (capabilities/editorial_planning_capability.py)
    # producing a baseline-vs-candidate pair for human review - never mutates a real ContentDraft,
    # requires its own separate, explicit paid-call authorization to actually run. There is no
    # "enforce"/live-production-use value in this type at all - Correction 3's own explicit
    # requirement that Editorial Planning may not influence production Copywriting without a
    # controlled human comparison first.
    editorial_planning_mode: Literal["off", "shadow", "comparison"] = "off"

    # Phase 19 M4: Editorial Writer V5 (docs/phase19_m0_audit.md). A version cutover, not an
    # off/shadow/enforce risk tier - v4 (prompts/copywriting/v4.yaml) stays the default and
    # remains frozen/unmodified/fully selectable; v5 (prompts/copywriting/v5.yaml) is a genuinely
    # editorial long-form structure, opt-in only. capabilities/copywriting_capability.py reads
    # this at call time (never a fixed constant), so switching versions needs no code deploy.
    # "6" (prompts/copywriting/v6.yaml, overnight A/B/C validation seam): the next immutable
    # version, per the same prompt-immutability rule - v5 is never edited to add this, since it
    # has its own established identity. Reachable only via the manual comparison harness, which
    # overrides this setting in-process for the duration of a single call and restores it
    # afterward (mirrors tests/test_content_generation_integration.py's own established
    # temporarily-override-then-restore convention) - never set in .env, never the default.
    # "7" (prompts/copywriting/v7.yaml, Phase 23.1I live editorial hardening): same structural
    # shape as v6, plain-language + importance-does-not-imply-length rule set added - v6 stays
    # frozen. Reachable the same in-process-override-only way, never set in .env, never the
    # default.
    # "8" (prompts/copywriting/v8.yaml, Phase 23.1J): a deliberately SMALLER output shape
    # (title/main_body/ending/expandable_details/quote, not v6/v7's seven/eight sections) - v6/v7
    # stay frozen. Reachable the same in-process-override-only way, never set in .env, never the
    # default this phase.
    # "8.1" (prompts/copywriting/v8.1.yaml, Phase 23.1J.1): a further simplification - main_body
    # is exactly one paragraph, no expandable_details field at all. v6/v7/v8 stay frozen. Same
    # in-process-override-only reachability, never set in .env, never the default this phase.
    # "8.2" (prompts/copywriting/v8.2.yaml, Phase 23.1K): a pure editorial-style refinement of
    # v8.1 (stronger "delete before explaining" + vendor/supplier rule) - the output SCHEMA is
    # identical to v8.1, only the prompt wording differs. v6/v7/v8/v8.1 stay frozen. Reachable the
    # same in-process-override-only way; this is the first version this session wires into a real
    # live canary (Phase 23.1K), but it is still never the settings default.
    # "8.6" (prompts/copywriting/v8.6.yaml, Phase 23.1Q): a single, narrow rule fix - rewrites the
    # UNCERTAINTY rule to remove the "данные неизвестны"/"подробности не раскрыты" worked examples
    # that licensed generic missing-detail-enumeration filler endings (confirmed live, e.g. the
    # real Craft Ventures post), replacing them with an explicit materiality standard. Output
    # SCHEMA is identical to v8.5 (still title/main_body/ending/quote/story_led/viral_potential/
    # meme_potential) - v6 through v8.5 stay frozen. Still never the settings default.
    copywriting_prompt_version: Literal["4", "5", "6", "7", "8", "8.1", "8.2", "8.3", "8.4", "8.5", "8.6"] = "4"

    # Phase I.1.2 (Final Post Authoring editorial calibration): mirrors copywriting_prompt_version's
    # own established pattern exactly - v1 (prompts/final_post_authoring/v1.yaml) is Phase I.1's
    # original, real-validated (Pixel, task f38bee1a-6ccb-4c0e-bbed-b0e3334c29ad) version; v2
    # (prompts/final_post_authoring/v2.yaml) rewrites the editorial contract to produce a genuinely
    # composed public post rather than a literal recap repackaging. Both files are immutable once
    # published; capabilities/final_post_authoring_capability.py reads this setting at call time,
    # never a fixed constant, so the active version can change without a code deploy.
    #
    # Phase I.1.4: promoted to "2" as the production default, after a real, live-validated V2 run
    # (Silver Lake/Workday, task 748b6456-56d9-4a1c-b8c0-eddcbab8976b, ContentDraft
    # 603cfbab-38ea-48f6-a8e1-d9b9335ffed6) confirmed technical PASS + fact-safety PASS +
    # editorial approval to promote (Phase I.1.3's own report, §32/user decision). "1" remains a
    # fully supported, explicit-selectable, immutable value - never deleted from the Literal, never
    # made unreachable - for rollback or comparison.
    final_post_authoring_prompt_version: Literal["1", "2"] = "2"

    # Phase 19 M5: quote delivery wiring and length safety (docs/phase19_m0_audit.md). Three-
    # state, matching article_acquisition_mode's own convention. "off" (default): worker/
    # content_cycle.py's two Telegram send call sites pass no quote at all - byte-identical to
    # today's actual (if unintended) behavior, where a persisted ContentDraftQuote never reaches
    # Telegram. "shadow": the quote is looked up and logged (what would be sent) but still not
    # passed to either send call. "enforce": the verified quote is threaded through to
    # bot.formatting.render_editorial_card() via services.telegram_notifier/
    # services.image_preview_notifier - length-budget-safe (services/quote_budget.py): rendered
    # whole or omitted entirely, never partially truncated.
    quote_telegram_rendering_mode: Literal["off", "shadow", "enforce"] = "off"

    # Phase 16 M2: secure fetch / technical validation limits (docs/phase16_m2_secure_fetch_and_
    # validation_report.md §9). All positive-bounded, no unlimited fallback - every external fetch
    # Image Intelligence makes (article HTML, candidate image bytes) is bounded by exactly these
    # settings via integrations/http/safe_fetch.py::SafeFetchPolicy. Only consulted when
    # image_intelligence_mode == "shadow" - "off" makes zero network calls regardless.
    image_intelligence_connect_timeout_seconds: float = Field(default=3.0, gt=0)
    image_intelligence_read_timeout_seconds: float = Field(default=7.0, gt=0)
    image_intelligence_total_timeout_seconds: float = Field(default=12.0, gt=0)
    image_intelligence_max_redirects: int = Field(default=3, gt=0)
    image_intelligence_max_html_bytes: int = Field(default=2_000_000, gt=0)
    image_intelligence_max_image_bytes: int = Field(default=10_000_000, gt=0)
    image_intelligence_max_decoded_pixels: int = Field(default=40_000_000, gt=0)
    # Technical safety/cost boundaries, not editorial judgment (mirrors content_generation_
    # scan_limit's own established "cheap ops cap, not a quality decision" convention).
    image_intelligence_max_articles_per_event: int = Field(default=1, gt=0)
    image_intelligence_max_candidate_urls_per_event: int = Field(default=10, gt=0)
    image_intelligence_max_image_downloads_per_event: int = Field(default=5, gt=0)
    image_intelligence_global_concurrency: int = Field(default=4, gt=0)
    image_intelligence_per_host_concurrency: int = Field(default=2, gt=0)

    # Phase 16 M4: deterministic relevance ranking (docs/phase16_m4_relevance_ranking_report.md
    # §17). Bounded positive integer - a safe maximum (20) prevents an accidental config typo from
    # producing an unbounded/unreviewable top-candidate list; the default (5) matches the M4 task
    # brief. Purely a result-shaping cap - never affects how many candidates are fetched/analyzed
    # (that remains image_intelligence_max_image_downloads_per_event, unchanged).
    image_intelligence_top_candidates: int = Field(default=5, gt=0, le=20)

    # Phase 16 M5: candidate persistence and finalist storage (docs/phase16_m5_persistence_and_
    # retention_report.md §13). Three-state, matching image_intelligence_mode's own off/shadow
    # precedent: "off" (default) performs zero database writes and zero file writes - byte-
    # identical to pre-M5 behavior, the rollback path. "metadata" persists bounded audit rows only
    # (no image bytes). "finalists" additionally stores bytes for up to image_max_stored_per_event
    # top-ranked candidates. Only consulted when image_intelligence_mode == "shadow" - M5 has
    # nothing to persist when M1-M4 never ran.
    image_candidate_persistence_mode: Literal["off", "metadata", "finalists"] = "off"
    # Container-internal path only - the actual persistent location is the Docker named volume
    # mounted at this path (docker-compose.yml), never a repo-relative bind mount.
    image_storage_root: str = Field(default="/data/image_storage")
    image_max_stored_per_event: int = Field(default=5, gt=0, le=20)
    image_max_total_stored_bytes_per_event: int = Field(default=50_000_000, gt=0)
    # Stored finalist bytes are reclaimed sooner than their own metadata row (§14) - an unselected
    # finalist's bytes are speculative disk usage, while the audit trail (SHA-256, provenance,
    # scores) is cheap to keep and useful long after the bytes are gone.
    image_bytes_retention_days: int = Field(default=7, gt=0)
    # Two-tier metadata retention: rejected/non-finalist rows (the overwhelming majority - M4's own
    # backtest measured ~1 finalist per ~2-6 discovered candidates) are pruned sooner than finalist
    # rows, which remain a materially more valuable audit record.
    image_metadata_retention_days: int = Field(default=30, gt=0)
    image_finalist_metadata_retention_days: int = Field(default=90, gt=0)
    image_cleanup_batch_size: int = Field(default=200, gt=0, le=2000)
    # Cleanup runs inline inside content_worker's existing poll loop (docs §15 - "least coupled
    # existing owner", no new worker/scheduler) every N cycles rather than on its own timer.
    image_cleanup_every_n_cycles: int = Field(default=20, gt=0)

    # Phase 16 M6: Telegram Editorial Preview (docs/phase16_m6_telegram_editorial_preview_
    # report.md §9). Default False - zero Telegram sends beyond the existing, unchanged
    # send_editorial_card() notification until an operator explicitly enables it. Only ever
    # consulted when image_candidate_persistence_mode != "off" (nothing to preview otherwise) -
    # M6 has no independent "off" no-op path of its own beyond this single flag.
    image_editorial_preview_enabled: bool = False

    # Phase 17 M1: Editorial Brief (docs/phase17_m1_editorial_brief_shadow_report.md). Two-state,
    # matching image_intelligence_mode's own convention: "off" (default) performs zero processing,
    # byte-identical to pre-M1 behavior - the rollback path. "shadow": a deterministic
    # (zero-new-LLM-call) EditorialBrief is built from already-available NewsEvent/Research/
    # Intelligence data and persisted into EditorialTask.workflow's existing
    # step_results["intelligence"]["editorial_brief"] JSON - never read by CopywritingCapability,
    # never changes ContentDraft. "enforce"/"editorial" (an eventual mode that would actually feed
    # Copywriting) does not exist yet - reserved for a future milestone once M1's shadow data is
    # validated, mirroring image_intelligence_mode's own M1-to-M6 staging precedent.
    editorial_brief_mode: Literal["off", "shadow"] = "off"

    # Phase 17 M2: Channel/Topic Relevance (docs/
    # phase17_m2_channel_topic_relevance_shadow_report.md). Two-state, matching editorial_
    # brief_mode's/image_intelligence_mode's own convention: "off" (default) performs zero
    # processing, byte-identical to pre-M2 behavior - the rollback path. "shadow": a
    # deterministic (zero-new-LLM-call) ArticleTopicAssessment/ChannelFitAssessment/
    # ShadowEditorialDecision is built and persisted into EditorialTask.workflow's existing
    # step_results["intelligence"]["channel_relevance"] JSON - never read by
    # CopywritingCapability, never changes ContentDraft, never blocks a task. A future
    # enforcement mode does not exist yet - reserved for a milestone after this shadow data is
    # validated, mirroring image_intelligence_mode's own M1-to-M6 staging precedent.
    channel_relevance_mode: Literal["off", "shadow"] = "off"

    # Phase 17 M3: Adaptive Length (docs/
    # phase17_m3_adaptive_length_shadow_comparison_report.md). Three-state, not the usual
    # off/shadow pair: "off" (default) performs zero processing, byte-identical to pre-M3
    # behavior - the rollback path. "shadow": a deterministic (zero-new-LLM-call)
    # AdaptiveLengthPlan is built and persisted into EditorialTask.workflow's existing
    # step_results["copywriting"]["adaptive_length_plan"] JSON - never read by
    # CopywritingCapability, never changes ContentDraft, never blocks a task. "comparison": same
    # shadow computation inside the worker/executor path (no different from "shadow" there - it
    # never triggers an LLM call by itself), but ALSO the precondition
    # scripts/phase17_m3_adaptive_length_comparison.py requires, on top of its own separate
    # --confirm-paid-calls CLI flag and --dry-run defaulting on, before it will make any real
    # paid candidate-generation call - two independent, deliberate confirmations required for any
    # real API spend, never triggered automatically by a worker or by this setting alone.
    adaptive_length_mode: Literal["off", "shadow", "comparison"] = "off"

    # Phase 17 M4: Beginner-Friendly Copywriting (docs/
    # phase17_m4_beginner_friendly_copywriting_report.md). Same three-state convention as
    # adaptive_length_mode: "off" (default) zero processing. "shadow": a deterministic
    # (zero-new-LLM-call) BeginnerFriendlyPlan is built and persisted into EditorialTask.
    # workflow's existing step_results["copywriting"]["beginner_friendly_plan"] JSON - never read
    # by CopywritingCapability, never changes ContentDraft. "comparison": same shadow computation
    # inside the worker/executor path, but ALSO the required precondition
    # scripts/phase17_m4_beginner_copywriting_comparison.py checks, on top of its own separate
    # --confirm-paid-calls flag and --dry-run defaulting on, before any real paid call.
    beginner_copywriting_mode: Literal["off", "shadow", "comparison"] = "off"

    # Phase 17 M5: Editorial Completeness Gate (docs/
    # phase17_m5_editorial_completeness_gate_shadow_report.md). Two-state only - unlike M3/M4
    # there is no "comparison" state: M5 never generates a candidate and never makes an LLM call
    # of any kind, so there is nothing for a paid comparison mode to gate. "off" (default): zero
    # processing. "shadow": a deterministic (zero-new-LLM-call) EditorialCompletenessAssessment +
    # CalibratedFactSafetyAssessment are built and persisted into EditorialTask.workflow's
    # existing step_results["quality"] JSON - never read by any Capability, never changes
    # ContentDraft, never blocks a task or changes Telegram delivery.
    editorial_completeness_mode: Literal["off", "shadow"] = "off"

    # Phase 18 M1: Meme Opportunity Detection (docs/phase18_m1_meme_opportunity_report.md). "off"
    # (default): zero processing. "shadow": a deterministic (zero-LLM-call) MemeOpportunity
    # Assessment is built and persisted into EditorialTask.workflow's existing step_results
    # ["quality"] JSON - never read by any Capability, never changes ContentDraft, never blocks a
    # task, never creates a MEME_GENERATION task on its own (that remains a separate, explicit
    # step - this flag governs only whether the shadow assessment itself is computed).
    #
    # MEME PRODUCTION PIPELINE (overnight phase): "enforce" is new - real gating for the
    # AUTOMATIC path only, applied by services/meme_generation_orchestrator.py::
    # trigger_meme_generation() (never inside capabilities/executor.py's own shadow-annotation
    # hook above, which stays byte-for-byte unchanged) - a NewsEvent scoring below MEME_READY is
    # never given a MEME_GENERATION task at all when this is "enforce". The MANUAL path
    # (an editor pressing "😂 Сгенерировать мем") always bypasses this gate entirely, regardless
    # of this setting's value - an explicit human request is never second-guessed by the same
    # heuristic that exists to avoid pestering an editor with LOW-signal automatic candidates.
    # Still defaults to "off" - this phase does not activate anything; see docs/
    # meme_production_pipeline_report.md for the exact morning .env change required to go live.
    meme_opportunity_mode: Literal["off", "shadow", "enforce"] = "off"

    # Phase 18 M3: Meme Safety & Originality Gate (docs/
    # phase18_m3_meme_safety_originality_report.md). "off" (default): zero processing. "shadow":
    # a deterministic (zero-LLM-call) MemeSafetyOriginalityGateResult is attached to the
    # "meme_concept" step's own structured output - never blocks, never mutates the concept
    # itself, never publishes anything.
    #
    # MEME PRODUCTION PIPELINE: "enforce" is new - applied by services/
    # meme_generation_orchestrator.py AFTER concept generation, for BOTH automatic and manual
    # triggers alike (a human explicitly requesting a meme still never bypasses the safety gate -
    # only the opportunity/worthiness gate above is bypassable by an explicit request). A
    # BLOCK decision stops the pipeline before any image is generated; the MemeCandidate row is
    # still persisted (status=SAFETY_BLOCKED) for durable diagnosis, never silently dropped. Still
    # defaults to "off".
    meme_safety_gate_mode: Literal["off", "shadow", "enforce"] = "off"

    # Phase 18 M5: Meme Image Generation (docs/phase18_m5_meme_image_generation_report.md). "off"
    # (default): zero calls, zero cost. "dry_run": generates via whichever ImageGenerationGateway
    # was injected - in every call site this codebase wires up today, that is
    # `integrations.llm_gateway.providers.mock_image_adapter.MockImageAdapter`, a deterministic,
    # zero-network, zero-cost placeholder generator.
    #
    # MEME PRODUCTION PIPELINE: "enforce" is functionally identical to "dry_run" INSIDE
    # `services/meme_image_generation.py::generate_meme_image()` itself (that function has no
    # opinion about which real value is configured; it simply calls whichever gateway its caller
    # injected - untouched by this phase). The distinction is ENTIRELY at the caller
    # (`services/meme_generation_orchestrator.py::_resolve_default_image_gateway()`): "off"/
    # "dry_run" default to `MockImageAdapter` (zero network, zero cost); "enforce" constructs the
    # real `OpenAIImageAdapter` (`gpt-image-2`, `n=1`, `quality="medium"`), keyed off the existing
    # `openai_api_key` below - MEME-PROD-2 (real production diagnostics found `gemini-3.1-flash-
    # image` returns HTTP 400 "blocked for unspecified reasons" for real editorial meme prompts;
    # rather than a growing Gemini-specific prompt-rewrite/policy-recovery subsystem, the provider
    # was replaced). If `openai_api_key` is unset while this is "enforce", the orchestrator FAILS
    # CLOSED (`MemeGenerationOutcome.status == "provider_not_configured"`) rather than silently
    # falling back to Mock. `GeminiImageAdapter` remains the live provider for NEWS photo
    # recomposition (`services/editorial_recomposition.py`) - completely unaffected by this
    # setting. Still defaults to "off" - flipping this to "enforce" is the explicit morning
    # activation decision, not made by this phase.
    meme_image_generation_mode: Literal["off", "dry_run", "enforce"] = "off"
    meme_image_max_bytes: int = Field(default=10_000_000, gt=0)

    # Phase 18 M8: Telegram Meme Editorial Preview (docs/
    # phase18_m8_telegram_editorial_preview_report.md). "off" (default): the preview is never
    # built or sent. "dry_run": services.meme_preview_notifier.send_meme_preview() renders and
    # logs the exact payload, but never calls the Telegram API - mirrors content_generation_
    # dry_run's own established discipline.
    #
    # MEME PRODUCTION PIPELINE: "enforce" is new - the real live-send value: `send_meme_preview()`
    # actually calls `bot.send_photo()`/`bot.send_message()`, routed exclusively through
    # `EditorialDestination.MEME` (services/telegram_routing.py), never any other destination.
    # Still defaults to "off" - flipping this (plus `meme_opportunity_mode`/
    # `meme_image_generation_mode` as appropriate) is the explicit morning activation decision,
    # not made by this phase.
    meme_telegram_preview_mode: Literal["off", "dry_run", "enforce"] = "off"

    # MEME PRODUCTION PIPELINE (overnight phase): the manual "😂 Сгенерировать мем" NEWS-button
    # authorization allowlist - byte-for-byte the same fail-closed shape as
    # `telegraph_approver_user_ids` (core/config.py's own established precedent for a per-feature
    # editorial-action allowlist), deliberately a SEPARATE setting rather than reusing that one -
    # the two buttons gate two independent editorial actions in two different parts of the product
    # (Telegraph article approval vs. meme generation), and this codebase's own convention is one
    # allowlist per distinct authorized action, never a single shared "is this person an editor at
    # all" list conflating unrelated permissions. Empty by default: NO Telegram user id is
    # authorized to press the button until an operator explicitly populates this list.
    meme_manual_approver_user_ids: list[int] = Field(default_factory=list)

    # MEME PRODUCTION PIPELINE: bounded cap on how many NewsEvent candidates one automatic
    # meme-worthiness cycle may advance to MEME_GENERATION - mirrors this codebase's own
    # established "every automatic batch has a bounded cap" convention (news_analysis_batch_size,
    # content_generation_batch_size). Reasoned starting default, not fit to any real operating
    # data yet (no automatic cycle has ever run in production).
    meme_auto_max_candidates_per_cycle: int = Field(default=3, gt=0)

    # MEME PRODUCTION PIPELINE: bounded recent-history lookback for concept-diversity context
    # (services/meme_diversity.py) - the N most recently created MemeCandidate rows (any status,
    # across all NewsEvents), never unbounded history, never a new vector-DB/embedding
    # architecture (none exists in this codebase and none is justified for this feature alone).
    # Reasoned starting default; not fit to any real repetition data yet.
    meme_recent_diversity_lookback: int = Field(default=10, gt=0)

    # Phase 18.7: Meme Intelligence Calibration Update (docs/phase18_7_calibration_results.md).
    # "v1" (default): the original Phase 18 M1/M3 classifiers run unmodified, exactly as accepted.
    # "v2": `services.meme_calibration_rules` wraps them with additive score/context calibration
    # (research-paper penalty, missing positive-signal scoring, safety context exceptions) -
    # `services.meme_opportunity.assess_meme_opportunity()`/`detect_sensitive_categories()`
    # themselves are never modified. Not consumed by `CapabilityExecutor` or any live call site in
    # this phase - the flag exists so a future phase can wire v2 in without adding a new setting,
    # not to activate anything now (Phase 18.7 is calibration/replay tooling only).
    meme_opportunity_calibration_version: Literal["v1", "v2"] = "v1"
    meme_safety_calibration_version: Literal["v1", "v2"] = "v1"

    # TELEGRAPH Checkpoint 7 (docs/telegraph_checkpoint_7_dormant_production_prep_report.md):
    # dormant scheduler/worker config, declared ahead of the feature that would read it - mirrors
    # verify_capabilities_at_boot's own established "the setting is added now so its default is
    # already the safe, documented value" precedent (Phase 7 §17.3). Nothing in this codebase
    # reads any of the three fields below yet - no scheduler, cron, or automatic-execution path
    # exists for TELEGRAPH (scripts/telegraph_pipeline_worker.py is a manually-invoked harness
    # only, exactly like scripts/run_content_generation.py/scripts/phase19_m13_vision_review_
    # manual.py's own established "human invokes this, nothing else does" convention). Enabling
    # automatic TELEGRAPH generation/approval/publishing is explicitly out of this checkpoint's
    # scope and requires a future, separately-authorized milestone - these three fields exist
    # only so that future milestone does not also need a settings migration.
    telegraph_pipeline_enabled: bool = False

    # NINJA PULSE RECAP Phase R2 integration, Phase E.0: the identical double-confirmation flag,
    # for the identical reason, one level later in a different pipeline - mirrors
    # telegraph_pipeline_enabled's own docstring exactly. Nothing in this codebase reads this
    # field yet except scripts/event_recap_pipeline_worker.py's own `--live` guard (a manually-
    # invoked harness only, exactly like scripts/telegraph_pipeline_worker.py's own established
    # "human invokes this, nothing else does" convention) - no scheduler, cron, or automatic-
    # execution path exists for EVENT_RECAP.
    event_recap_pipeline_enabled: bool = False

    # Phase I.2: the identical double-confirmation flag, for the identical reason, one stage later
    # in the same pipeline - mirrors event_recap_pipeline_enabled's own docstring exactly. Nothing
    # in this codebase reads this field yet except scripts/final_post_review_worker.py's own
    # `--live` guard (a manually-invoked harness only, exactly like scripts/
    # event_recap_pipeline_worker.py's own established "human invokes this, nothing else does"
    # convention) - no scheduler, cron, or automatic-execution path exists for Final Post Preview.
    final_post_review_enabled: bool = False

    # PRESENTATION RECOVERY (2026-09-02), Phase I.3: the identical double-confirmation flag, for
    # the identical reason, gating ONLY the real Telegram publish call in services/
    # final_post_publication.py - does NOT alter event_recap_pipeline_enabled's or
    # final_post_review_enabled's own semantics, which still gate only their own review-stage
    # sends. Nothing in this codebase reads this field yet except scripts/
    # final_post_publication_worker.py's own `--live` guard (a manually-invoked harness only,
    # mirroring the identical "human invokes this, nothing else does" convention every other stage
    # of this pipeline already established) - no scheduler, cron, or automatic-execution path
    # exists for real RECAP publication.
    final_post_publication_enabled: bool = False

    # Reasoned starting point mirroring news_collection_interval_seconds's own cadence exactly -
    # how often a future scheduler would form a new shortlist batch. Not fit to any real
    # operating data yet.
    telegraph_shortlist_schedule_interval_seconds: int = Field(default=3600, gt=0)
    # Reasoned starting point mirroring news_analysis_poll_interval_seconds's own cadence - how
    # often a future worker would poll for APPROVED-and-unconsumed proposals /
    # COMPLETED-and-unreviewed articles to advance. Not fit to any real operating data yet.
    telegraph_pipeline_poll_interval_seconds: int = Field(default=300, gt=0)

    # NINJA PULSE Visual System v1 (services/presentation_director.py, services/brand_renderer.py)
    # - "off" (default): byte-identical to pre-Visual-System delivery, no presentation decision is
    # even computed. "shadow": decision computed and logged, never rendered/sent. "enforce": the
    # real router-mode send path uses the rendered/branded output. Mirrors this file's own
    # established off/shadow/enforce convention (e.g. article_acquisition_mode) exactly.
    presentation_director_mode: Literal["off", "shadow", "enforce"] = "off"
    pulse_brand_enabled: bool = False
    # Phase V2.3 (docs/nnj_source_faithful_editorial_visual_recomposition_v1.md §15-17,
    # services/editorial_recomposition.py) - a separate mode from presentation_director_mode
    # (that one gates whether the deterministic NNJ brand layer renders at all; this one gates
    # whether the source photo is optionally recomposed BEFORE that layer runs - two distinct
    # product behaviors, deliberately not conflated into one flag). Also distinct from
    # meme_image_generation_mode (a completely different consumer/product, its own independent
    # "off"/"dry_run"/"enforce" values). "off" (default): zero
    # ImageGenerationGateway calls, byte-identical to pre-V2.3 behavior. "dry_run": eligibility is
    # evaluated and the request that WOULD be sent is built, but no network call is made. "live":
    # a real gemini-3.1-flash-image call is made when eligible; any failure fails open to the
    # original source bytes (services/editorial_recomposition.py::maybe_recompose(), never a
    # fallback to gemini-3-pro-image or gpt-image-2). "live" exists in this type after V2.3 but is
    # NOT exercised by any live call in that phase - a separate, explicitly-authorized canary
    # phase is required before this is ever set to "live" outside a test.
    editorial_recomposition_mode: Literal["off", "dry_run", "live"] = "off"
    brand_asset_path: str = "assets/brand/nnj_logo.svg"
    brand_red_asset_path: str = "assets/brand/nnj_logo_red.svg"
    brand_raster_fallback_path: str = "assets/brand/nnj_logo.png"
    brand_template_version: str = "v1"
    # Unset by default - see services/brand_renderer.py's own module docstring for the OS-font
    # resolution fallback chain this drives (no font file is ever downloaded or shipped).
    brand_font_path: str | None = None
    # FOUNDER-VISUAL-OVERLAY-RECOVERY-4 §12: optional pin for the BOLD face used by the DATA
    # hero-metric hierarchy. Unset -> the OS-provided bold companion of `brand_font_path`'s family
    # (see services/brand_renderer.py::_resolve_bold_font_path); never downloaded.
    brand_font_bold_path: str | None = None
    # FOUNDER-VISUAL-BREAKING-DATA-RECONSTRUCTION-5 §13: optional pin for the black-weight face used
    # by the DATA hero number. Unset -> Arial Black on Windows / the bold face on the Linux VPS
    # (see services/brand_renderer.py::_resolve_heavy_font_path); never downloaded.
    brand_font_heavy_path: str | None = None
    watermark_enabled: bool = True
    watermark_opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    pulse_line_enabled: bool = True
    editorial_code_enabled: bool = True
    # No persistent 24h delivery history query backs this (a disclosed, deliberate follow-up
    # limitation - report §"known limitations") - only a per-cycle in-memory counter the caller
    # (worker/content_cycle.py) threads through itself; resets every run_content_cycle() call.
    presentation_breaking_max_per_cycle: int = Field(default=1, ge=0)
    # Pre-commit correction ("BREAKING first-canary safety"): a narrow kill switch for BREAKING
    # specifically, independent of presentation_director_mode - lets a first "enforce" canary run
    # with NEWS/DATA/QUOTE presentation active while BREAKING (the strongest visual treatment)
    # stays off. Defaults to True (no behavior change) because presentation_director_mode itself
    # (default "off") is still the overall master switch - this only matters once that is already
    # "enforce". No new scoring system, no persistence - see services/presentation_director.py::
    # decide_presentation()'s own docstring.
    presentation_breaking_enabled: bool = True

    # NINJA PULSE RECAP Phase R1 (offline/shadow foundation only - services/recap_event.py,
    # services/weekly_recap_selection.py). ALL inactive by default - no scheduler, worker, or
    # command reaches any of this code yet; flipping these to True alone still does nothing
    # (nothing calls the recap services from a running loop in R1 - see those modules' own
    # docstrings). pulse_recap_enabled is the overall master switch (mirrors presentation_
    # director_mode's own "off" default / master-switch role); the two mode-specific flags below
    # let a future canary enable EVENT_RECAP and WEEKLY_RECAP independently of each other, the
    # same independent-kill-switch pattern presentation_breaking_enabled already established
    # relative to presentation_director_mode.
    pulse_recap_enabled: bool = False
    pulse_event_recap_enabled: bool = False
    pulse_weekly_recap_enabled: bool = False

    # services/recap_event.py::evaluate_recap_readiness() thresholds - reasoned starting points
    # (this codebase's own established "reasoned default, refine from real data later" convention
    # - see story_match_lookback_days/telegraph_candidate_recency_hours above for the same
    # disclosed-as-such pattern), NOT calibrated against any real recap replay dataset yet (none
    # exists - Phase R1 is the first checkpoint to define this metric at all).
    recap_min_event_count: int = Field(default=3, ge=1)
    # Phase R1.1 quality-floor correction: raised from 2 to 4 - two distinct announcements is
    # insufficient maturity for a genuinely useful recap (spec's own "EVENT_RECAP is intended to
    # summarize a genuinely developed event and normally produce approximately 5-8 useful items").
    # Still config-driven, never hardcoded in the evaluator - tests may override it explicitly.
    recap_min_announcement_count: int = Field(default=4, ge=1)
    recap_min_unique_sources: int = Field(default=2, ge=1)
    # Minutes since the story's most recent linked event before it is considered "cooled" enough
    # to be recap-eligible - deliberately independent of story_match_lookback_days (a Story-
    # MATCHING window, an unrelated concern) or telegraph_candidate_recency_hours (candidate
    # freshness, the opposite direction). 90 minutes: long enough that a still-actively-developing
    # launch (new announcements arriving every few minutes) is not prematurely recapped mid-event,
    # short enough that a genuinely concluded event does not sit un-recapped for hours.
    recap_cooling_window_minutes: int = Field(default=90, ge=0)

    # services/recap_event.py::cluster_announcements() - the minimum combined entity/title
    # similarity score (see that module's own _announcement_similarity() docstring for the
    # inverted 0.4/0.6 entity/title weighting reasoning) for two events within ONE story to be
    # folded into the same AnnouncementCluster. Deliberately higher than services/story_memory.
    # py's own _HIGH_THRESHOLD (0.65, a cross-story "is this the same story at all" bar) - within
    # one already-confirmed story, over-merging two genuinely distinct announcements (e.g. a
    # product launch vs. its own later pricing announcement) is the more costly failure mode, so
    # this bar is set higher.
    recap_announcement_cluster_threshold: float = Field(default=0.75, ge=0.0, le=1.0)

    # Phase R1.3 (services/recap_event.py::evaluate_recap_story_integrity()) - the temporal-
    # compactness informational signal only (§5.E's own "should be suspicious," not a hard gate -
    # see that function's own docstring for why this is not itself disqualifying). 168h = 7 days,
    # a reasoned starting point (long enough for a genuinely multi-day developing story - a
    # security incident, a legal case - to stay unflagged), not calibrated against real data yet.
    recap_integrity_max_time_span_hours: float = Field(default=168.0, gt=0)

    # R2.10G3-E1 (services/recap_eventness_shadow.py) - master switch for the SHADOW-ONLY
    # deterministic eventness rejector signal (RULE_A/RULE_C, validated read-only across
    # R2.10G3-A through G3-D; RULE_D was disqualified and does not exist in production code at
    # all). Default False in every environment - no environment currently sets this. When True,
    # `services.event_recap.build_event_recap_candidate()` additionally computes and attaches a
    # diagnostic `EventnessShadowEvaluation` to its own `EventRecapCandidate.eventness_shadow`
    # field (corrected reference - an earlier draft of this comment named
    # `build_recap_event_snapshot()`/`RecapEventSnapshot`, services/recap_event.py's own R1
    # function; G3-E1's actual wiring is in services/event_recap.py, the function the real
    # processor/scheduler call chain uses) - this NEVER changes `readiness_state`/
    # `readiness_reason`/`story_integrity_eligible`/anything else on that candidate, and there is
    # no code path anywhere that reads this field to reject, publish, or otherwise act on a Story
    # (R2.10G3-E1's own explicit "no production execution path capable of rejecting a Story from
    # eventness in this phase" requirement).
    recap_eventness_shadow_enabled: bool = False

    # R2.10-RUNTIME-2 (services/event_recap_scheduler.py) - two INDEPENDENT flags, deliberately
    # never combined into one (R2.10-RUNTIME-1's own design-correction: a single flag cannot
    # support "observe real readiness naturally, without ever creating a Story-generation task").
    #
    # event_recap_scheduler_enabled gates ONLY whether worker/cycle.py::run_automation_cycle()
    # calls the scheduler at all, every cycle, after Triage. When True alone (generation False),
    # the scheduler runs in READ-ONLY shadow/readiness-observation mode: it calls
    # `services.event_recap.build_event_recap_candidate(force_shadow=False, ...)` directly (the
    # real, unmodified readiness decision - never a second, divergent readiness implementation)
    # and creates NO EditorialTask, performs NO synthesis, NO Tier-2B network acquisition, and NO
    # DB write of any kind - see services/event_recap_scheduler.py's own module docstring for the
    # full read-only contract and its own test suite for the empirical proof.
    #
    # event_recap_generation_enabled gates whether the scheduler additionally calls the existing,
    # unmodified `services.event_recap_processor.generate_recap_for_story()` once per candidate
    # Story - this is the only thing that can create a real EVENT_RECAP EditorialTask and run its
    # one real LLM synthesis call. Fails closed (a structured warning, generation simply does not
    # run) if this is True while `event_recap_scheduler_enabled` is False, since generation with
    # no scheduler loop would mean nothing ever calls it - documented invariant: generation
    # requires scheduler, never the reverse.
    #
    # Both default False in every environment; no environment currently sets either. Deliberately
    # independent of `recap_eventness_shadow_enabled` above (and of
    # `recap_canonical_source_resolution_enabled`/`recap_article_acquisition_enabled`/
    # `final_post_publication_enabled`) - no combined master flag anywhere in this system.
    event_recap_scheduler_enabled: bool = False
    event_recap_generation_enabled: bool = False

    # Bounded candidate-scan cap for services/event_recap_scheduler.py, mirroring content_
    # generation_scan_limit's own established precedent/magnitude exactly (same reasoning: a
    # periodic worker cycle must never issue an unbounded table scan). No cadence setting is
    # added alongside it - the scheduler reuses automation_worker's own existing
    # news_collection_interval_seconds cycle interval unchanged, per R2.10-RUNTIME-1's own
    # finding that this cadence already comfortably subdivides recap_cooling_window_minutes.
    event_recap_scan_limit: int = Field(default=50, ge=1)

    # NINJA Social Intelligence Foundation, Part II (General topic / Business Context Command
    # Center) - reuses the SAME `newsroom_telegram_chat_id` this codebase already established
    # (Phase 22), never a second, competing chat setting - and follows that same phase's own flat
    # `<feature>_topic_id` naming exactly (news_topic_id/meme_topic_id/telegraph_topic_id/etc.),
    # never a `_general_` qualifier. Deliberately `None` by default: Telegram's own "General" topic
    # in a forum-enabled supergroup carries NO `message_thread_id` at all (confirmed via bot/
    # handlers/whereami.py's own diagnostic contract) - `None` is itself the correct, permanent
    # value for "the General topic", not a placeholder awaiting configuration. This setting exists
    # only as an explicit override escape hatch, never required for normal operation.
    business_context_topic_id: int | None = None
    # Explicit, hand-curated Telegram user_id -> role mapping (Business Context §31). No general
    # role/permission system exists anywhere in this codebase to reuse - the established pattern
    # (`telegraph_approver_user_ids`, `meme_manual_approver_user_ids`) is a single flat per-feature
    # `list[int]` allowlist (binary authorized/not), never graded roles. This phase's own spec
    # explicitly requires graded roles (FOUNDER/PRODUCT_OWNER/MARKETING/EDITOR/VIEWER with
    # different command sets), so a dict is used here instead of a third flat list - same
    # fail-closed default (`{}`) as every existing allowlist: a user_id absent from this mapping
    # receives no role at all (services/business_context_roles.py treats an unmapped user as
    # having zero permitted commands, never a default role).
    business_context_role_map: dict[int, str] = Field(default_factory=dict)

    # NINJA Social Intelligence Foundation, Part IV §96: Instagram Growth Engine flags. All
    # default False - no Meta/Instagram credentials exist anywhere in this codebase (forensic
    # sweep: zero references to a Graph API client or Instagram credential setting), so even the
    # concept of "enabling" one of these today changes nothing observable - each flag exists only
    # for the future phase that actually implements the capability it names. No publication flag
    # exists at all in this phase (spec §92/§96's own "no ad spend, no Meta Ads API" instruction) -
    # there is nothing here that could ever be flipped to make this codebase publish to Instagram.
    instagram_growth_engine_enabled: bool = False
    instagram_story_opportunity_shadow_enabled: bool = False
    instagram_trend_intelligence_enabled: bool = False
    instagram_performance_memory_enabled: bool = False
    instagram_format_director_shadow_enabled: bool = False
    # INSTAGRAM GROWTH ENGINE v2 (spec §61) - same discipline as the five flags above: real
    # persistence/service code exists behind each of these (competitor intelligence tables, the
    # growth strategy advisory layer, the dynamic calendar), but every flag still defaults False
    # and nothing in this phase reads any of them to gate a live/production code path yet.
    instagram_competitor_intelligence_enabled: bool = False
    instagram_growth_strategy_shadow_enabled: bool = False
    instagram_calendar_enabled: bool = False

    # INSTAGRAM-CONTENT-STRATEGY-V2 Phase 2/3 CONTROLLED ROLLOUT: two narrow, independent runtime
    # gates - neither is a new pipeline/scheduler/agent, both default False. Deploying the Phase
    # 2/3 code is safe with both left False: `_run_instagram_product_lane()` (worker/content_
    # cycle.py) becomes a real no-op (logs "instagram_product_lane_disabled", never falls through
    # to another lane) instead of running automatic PRODUCT generation every cycle; a REEL format
    # decision reaching `evaluate_and_submit_instagram_opportunity()` (services/instagram_
    # automatic_trigger.py) is deferred (never silently downgraded to SINGLE) instead of reaching
    # the Reel Creative Director. Neither flag affects Phase 1 (Active Director/Product Truth
    # ingestion), existing NEWS Instagram delivery, or a manual bounded canary invocation - a
    # canary may pass its own local override without ever touching this persistent config.
    instagram_product_lane_enabled: bool = False
    instagram_reel_execution_enabled: bool = False
    # INSTAGRAM-GROWTH-3 - same discipline again: real semantic-matching/Creative-Director code
    # exists (services/instagram_semantic_matching.py, services/instagram_creative_director.py),
    # both defaulting False and unread by any live/production code path. Still no publication flag
    # anywhere - there is nothing here that could ever be flipped to make this codebase publish to
    # Instagram.
    instagram_semantic_matching_enabled: bool = False
    instagram_creative_director_shadow_enabled: bool = False

    # NINJA Social Intelligence Foundation, Part III §57: Telegram Director shadow flags. All
    # default False - no enforcement, no automatic delay/deprioritization/rework tonight (spec
    # §111's own "no production wiring" instruction). Each gates only whether its OWN advisory
    # evaluation function is ever called from a live cycle - none of these functions exist in any
    # automatic call path yet in this phase, so even "enabling" one today changes nothing; the
    # flag exists for the future phase that actually wires one in.
    telegram_channel_director_shadow_enabled: bool = False
    telegram_art_director_shadow_enabled: bool = False
    telegram_growth_memory_enabled: bool = False
    telegram_strategy_director_enabled: bool = False
    telegram_revision_router_enabled: bool = False
    telegram_art_director_enforcement_enabled: bool = False

    # Telegram Directors Phase 2 §4: explicit OWN-CHANNEL identity - never hardcoded, never
    # confused with services/collector.py's externally-monitored Source rows (each external
    # channel is configured per-row in the sources table, not a global setting). Deliberately
    # optional: real publication already resolves to `newsroom_telegram_chat_id` (Phase 22) - these
    # settings exist only for a future distinct outward-facing channel separate from the internal
    # supergroup; until set, services/telegram_own_channel.py::owned_chat_id() falls back to
    # `newsroom_telegram_chat_id`.
    telegram_owned_channel_id: int | None = None
    telegram_owned_channel_username: str | None = None

    # Telegram Directors Phase 2 §6: passive-only first-party performance collection. Default
    # False - no automatic Telethon call anywhere until explicitly enabled. Even when True,
    # services/telegram_performance_collection.py only ever reads (iter_messages/get_messages) -
    # never edits/deletes/sends/reacts/comments (spec §6's own hard constraint).
    telegram_performance_collection_enabled: bool = False

    # SOCIAL-INTELLIGENCE-INTEGRATION-1 §28: the Director Console itself (read-only /directors,
    # /plan, /opportunities, /calendar, /performance). Default False - no console handler runs
    # until this is explicitly turned on; individual director flags above are unaffected either
    # way. No enforcement flag, no publication flag exists anywhere alongside this one.
    director_console_enabled: bool = False

    # SOCIAL-INTELLIGENCE-OPS-1 §29-34: gates ONLY the DirectorRun audit-log write that
    # /plan and /performance perform as a byproduct of their already-free, already-happening
    # advisory computation - never gates the advisory computation or display itself, and never
    # triggers any LLM call either way. Default False - no DirectorRun row is persisted until a
    # founder explicitly opts in.
    director_run_persistence_enabled: bool = False

    # VISUAL-DESIGN-AUTONOMY-1 §61: everything runtime-impacting defaults False - this phase is
    # development-only (no production wiring, spec §62). visual_design_director_enabled gates the
    # Visual Design Director's LLM creative-direction call being reachable from ANY orchestration
    # path (real or test-invoked outside pytest); visual_design_autonomy_enabled additionally
    # gates the full attempt/revision loop actually running end to end; visual_design_auto_
    # revision_enabled gates whether a REWORK verdict is allowed to trigger a next attempt
    # automatically (vs. always stopping at HUMAN_REVIEW); visual_brief_auto_adaptation_enabled
    # gates whether repeated-pattern evidence may create a CANDIDATE Designer Brief at all;
    # visual_brief_auto_promotion_enabled additionally gates whether a validated candidate may be
    # promoted to ACTIVE without a human action; visual_regression_validation_enabled gates
    # whether a candidate brief is run against the regression set at all.
    visual_design_director_enabled: bool = False
    visual_design_autonomy_enabled: bool = False
    visual_design_auto_revision_enabled: bool = False
    visual_brief_auto_adaptation_enabled: bool = False
    visual_brief_auto_promotion_enabled: bool = False
    visual_regression_validation_enabled: bool = False

    # SOCIAL-INTELLIGENCE-PRELAUNCH-1 §47: cold-start social launch strategy flags. All default
    # False - the /launch command and SocialLaunchContext model are always importable/testable,
    # but social_launch_context_enabled gates whether bot/handlers/launch.py's router is even
    # registered (mirrors settings.director_console_enabled's own "no console handler runs until
    # this is explicitly turned on" precedent). social_advisory_execution_enabled separately gates
    # ONLY `/directors refresh` (spec §25's own explicit "NOT a read operation" mutation path) -
    # console reads (/plan /directors /performance /calendar /opportunities) never check this flag
    # at all, since they only ever display already-persisted DirectorRun state (spec §24's own
    # "console reads remain PURE" invariant, unaffected by whether refresh is enabled).
    # social_advisory_daily_enabled gates a future automatic daily scheduling hook that this phase
    # explicitly does NOT wire into worker/cycle.py (spec §29's own "do not enable in this
    # development phase" instruction) - the setting exists so a later phase can turn it on without
    # a migration, not because anything reads it yet.
    social_launch_context_enabled: bool = False
    social_advisory_execution_enabled: bool = False
    social_advisory_daily_enabled: bool = False

    # SOCIAL-INTELLIGENCE-PRELAUNCH-1 §28: SocialAdvisoryBudgetService's hard limits - mirrors
    # the Visual Design Autonomy budget settings immediately below in shape and intent.
    social_advisory_max_runs_per_day: int = 3
    social_advisory_max_cost_per_day: float = 5.0
    # Structural, not a runtime counter: services/social_prelaunch_advisory.py::
    # build_prelaunch_advisory() makes exactly one call_generate() call per invocation, no internal
    # retry loop beyond capabilities/gateway_call.py's own already-established Gateway retry
    # behavior (spec §28's own "reuse existing Gateway retry behavior only" instruction) - this
    # setting documents that invariant as an explicit, checkable number rather than leaving "one
    # bounded call" as an unverified claim in a docstring alone.
    social_advisory_max_calls_per_refresh: int = 1

    # VISUAL-DESIGN-AUTONOMY-1 §27/§28: attempt/cost budgets - the hard limits the Visual Design
    # Director operates inside of. `visual_max_attempts_default` applies unless a presentation-type
    # override below is set; one initial render counts as attempt 1 (spec §27). All costs are USD.
    visual_max_attempts_default: int = 2
    visual_max_attempts_data: int = 3
    visual_max_attempts_campaign: int = 3
    visual_max_cost_per_post: float = 0.50
    visual_max_cost_per_day: float = 20.0

    # services/weekly_recap_selection.py::select_weekly_recap_stories() - target Story count
    # (spec's own "Target 5-8 Stories max"), lookback window, and the per-company diversity cap
    # (spec's own "recommended default 2").
    weekly_recap_target_min: int = Field(default=5, ge=1)
    weekly_recap_target_max: int = Field(default=8, ge=1)
    weekly_recap_window_days: int = Field(default=7, gt=0)
    weekly_recap_max_per_company: int = Field(default=2, ge=1)

    # Phase R1.1 quality floor (services/weekly_recap_selection.py::_is_eligible()) - "quality >
    # count": a Story must clear this deterministic floor BEFORE ranking/diversity even runs, so
    # weak stories are never used as padding to reach weekly_recap_target_min. CORE is always
    # eligible; ADJACENT needs one of these two signals to clear its own threshold; PERIPHERAL is
    # eligible only via the existing major_impact_override signal (never these thresholds).
    # weekly_recap_adjacent_min_score reuses content_generation_min_score's own 0-100 magnitude
    # (70) - same scale, a separate setting since this is a different decision (recap
    # inclusion, not draft generation) and must be tunable independently.
    # weekly_recap_adjacent_min_significance reuses services/editorial_treatment.py's own
    # _LOW_SIGNIFICANCE_MAX=5.0 boundary (0-10 scale) - "at least medium significance", the same
    # reasoned tier boundary already established there, not a new number invented for this
    # checkpoint. Neither signal present (both None) means "not verifiably sufficient" - fails
    # closed, mirroring editorial_treatment.py's own "no significance available - conservative
    # default" precedent.
    weekly_recap_adjacent_min_score: int = Field(default=70, ge=0, le=100)
    weekly_recap_adjacent_min_significance: float = Field(default=5.0, ge=0.0, le=10.0)

    # DIRECTOR-CONTROL-PLANE-1 §6 / 1C §7: Instagram API with Instagram Login (Business Login for
    # Instagram) config - the OFFICIAL direct-Instagram OAuth route that replaced the deprecated
    # Instagram Basic Display API. Mirrors telegram_bot_token's own SecretStr pattern exactly.
    #   instagram_access_token          - the long-lived Instagram User access token (SecretStr;
    #                                     the ONLY secret here). Scopes: instagram_business_basic
    #                                     (profile+media) and, optionally, instagram_business_
    #                                     manage_insights. NO write scopes are requested or used.
    #   instagram_business_account_id   - the numeric IG user id the token authorizes (`/me` id).
    # Both None by default (1C §7 "do not hardcode tokens") - services/instagram_account_reader.py
    # ::is_configured() is False whenever either is unset, and every caller reports NOT_CONFIGURED
    # rather than fabricating a connected state. 1C adds NO app-id/app-secret: the interactive
    # OAuth token exchange / refresh is an operational flow documented in
    # design/instagram_official_api.md, never automated with secrets in this phase (1C §16).
    instagram_access_token: SecretStr | None = None
    instagram_business_account_id: str | None = None
    # DIRECTOR-CONTROL-PLANE-1C §9: the configured expected handle for identity verification. A
    # connection whose returned username does not match this (when set) is ERROR / IDENTITY_MISMATCH,
    # never silently accepted. Non-secret. Leading '@' tolerated.
    instagram_expected_username: str | None = None
    # DIRECTOR-CONTROL-PLANE-1C §28: pinned Graph API host + version - a version bump is a one-line
    # config change, never an inline literal in the adapter ("do not freeze obsolete assumptions").
    instagram_graph_base_url: str = "https://graph.instagram.com"
    instagram_api_version: str = "v23.0"
    # DIRECTOR-CONTROL-PLANE-1C §16: operator-supplied long-lived-token expiry, surfaced by
    # /accounts as TOKEN_EXPIRY_AT / TOKEN_STATUS. Non-secret (a timestamp, never the token). The
    # adapter never performs autonomous token refresh - see design/instagram_official_api.md.
    instagram_access_token_expires_at: datetime | None = None

    # INSTAGRAM-EXECUTION-FOUNDATION-1 section 18: the ONE hard publication safety flag for
    # services/instagram_publish_adapter.py. Default False (fail CLOSED) - a real (non-shadow)
    # publish attempt raises InstagramPublishErrorCode.PUBLICATION_DISABLED immediately, before any
    # client call is made, whenever this is False. Shadow/fake publish execution (no network write,
    # no real credential) is unaffected by this flag either way - it is always available for
    # testing. Independent of any Telegram publication concept; flipping it changes nothing about
    # Telegram. Turning this True in production is a separate, explicitly-authorized future step
    # (this phase never sets it True anywhere, never reads a real access token for a write call).
    instagram_publication_enabled: bool = False
    # INSTAGRAM-PRODUCTION-ROLLOUT-1 §6: a SEPARATE, narrower control from `instagram_publication_
    # enabled` above. That flag gates whether a LIVE (non-shadow) publish call is permitted to run
    # at all for one explicit, controlled, individually-approved package (`editor_approved=True`
    # still required per-call - see `services/instagram_publish_adapter.py::publish_instagram_
    # content()`). THIS flag would gate a future scheduler/worker loop autonomously selecting and
    # publishing READY packages with no per-call human approval - no such loop exists anywhere in
    # this codebase today (confirmed by direct audit; nothing calls `publish_instagram_content()`
    # from any worker/scheduler path). Default False and left False for the entire duration of this
    # phase - turning this True is a distinct, separately-authorized future decision, never implied
    # by `instagram_publication_enabled=True` alone.
    instagram_autonomous_publication_enabled: bool = False
    # The official write scope this flag conceptually gates, kept separate from the READ scopes
    # services/instagram_account_reader.py already uses (instagram_business_basic /
    # ..._manage_insights) - section 17's own "separate READ_SCOPES and WRITE_SCOPES" instruction.
    # Documented here, never silently requested/added to any live OAuth flow by this phase.
    instagram_write_scopes: tuple[str, ...] = ("instagram_business_content_publish",)

    # INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1 §6: the real media-hosting mechanism's own config -
    # see services/instagram_media_hosting.py's own module docstring for the full rationale.
    # `instagram_media_public_base_url` is `None` in every environment this phase touches (no TLS/
    # domain/reverse-proxy exists in front of `backend` today - a genuine, disclosed infrastructure
    # decision, not a code default this phase should invent a value for). Until an operator
    # configures a real `https://` base url that resolves to a public address,
    # `services.instagram_media_hosting.build_public_media_url()` always returns `None` and
    # `MEDIA_HOSTING_READY` stays `False` - by construction, never by convention alone.
    instagram_media_public_base_url: str | None = None
    instagram_media_storage_root: str = "/data/instagram_media_public"
    instagram_media_asset_ttl_seconds: int = 3600

    # DIRECTOR-CONTROL-PLANE-1 §8/§12: the ONE new enforcement flag this phase introduces - gates
    # only whether services/director_editorial_gate.py's decision actually withholds DROP/HOLD
    # candidates from the real Founder NEWS queue. Default False: every gate evaluation still runs
    # and persists a DirectorEditorialDecision (shadow), but worker/content_cycle.py's own routing
    # is completely unaffected until this is explicitly turned on - deliberately separate from
    # every PUBLICATION-facing flag (final_post_publication_enabled, telegram_channel_director_
    # shadow_enabled, telegram_art_director_enforcement_enabled), none of which this flag touches.
    telegram_editorial_gate_enabled: bool = False

    # UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1: gates whether worker/content_cycle.py's router-mode
    # dispatch delegates to the new shared services/editorial_pipeline/ orchestrator instead of its
    # own inline media/presentation/render/fallback logic. Default False for the entire duration of
    # this phase - the new pipeline exists, is tested, and can run in shadow (dual-run) mode, but
    # the legacy path remains the only one actually reachable in production until a Founder-
    # approved future phase flips this on. Never set True by this phase's own code.
    unified_editorial_pipeline_enabled: bool = False
    # UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 §27: when true (and unified_editorial_pipeline_
    # enabled is True), run the new pipeline ALONGSIDE the legacy path for comparison only - never
    # a second real Telegram/Instagram send. Meaningless while unified_editorial_pipeline_enabled
    # is False. Default False.
    unified_editorial_pipeline_shadow_mode: bool = False
    # DIRECTOR-CONTROL-PLANE-1A §29 / 1B §3: the daily bound on Stage 2 (real Director LLM)
    # editorial-gate reviews - services/director_editorial_gate_budget.py's own real, tested guard.
    # As of 1B, Stage 2 IS wired into the live pre-generation path (worker/content_main.py ->
    # run_content_cycle -> run_pre_generation_gate), so this bound is load-bearing: an
    # escalation-worthy candidate gets a real Gateway call only while check_gate_llm_budget()
    # reports budget remaining; once the day's count of v1-llm DirectorEditorialDecision rows hits
    # this value the gate falls back to the Stage 1 deterministic outcome. See §28's cost model.
    director_editorial_gate_max_llm_reviews_per_day: int = Field(default=100, ge=0)

    @property
    def database_url(self) -> str:
        """Build the async PostgreSQL connection URL for SQLAlchemy."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def test_database_url(self) -> str:
        """Phase 23.1L: the dedicated pytest database - same host/user/password as `database_url`,
        different database name (`postgres_test_db`). Every pytest fixture that opens a real
        Postgres connection must use this, never `database_url`."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_test_db}"
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
