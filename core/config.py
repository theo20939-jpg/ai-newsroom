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

    # Phase 19 M13: final-candidate vision review foundation (docs/phase19_m13_vision_review.md).
    # Two-state, no "enforce" value at all - reaching a real vision call always requires the
    # manually-invoked harness script (scripts/phase19_m13_vision_review_manual.py), never an
    # automatic/scheduled worker path, regardless of this setting's value. "off" (default): no
    # shadow persistence hook runs. "shadow": reserved for a future, narrowly-scoped deterministic
    # pre-check hook (e.g. persisting "this candidate is queued for vision review") - no such hook
    # exists yet in this milestone, so "shadow" is currently a no-op identical to "off"; the value
    # is defined now so a future milestone can add that hook without a new settings migration.
    media_vision_review_mode: Literal["off", "shadow"] = "off"

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
    copywriting_prompt_version: Literal["4", "5"] = "4"

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
    meme_opportunity_mode: Literal["off", "shadow"] = "off"

    # Phase 18 M3: Meme Safety & Originality Gate (docs/
    # phase18_m3_meme_safety_originality_report.md). "off" (default): zero processing. "shadow":
    # a deterministic (zero-LLM-call) MemeSafetyOriginalityGateResult is attached to the
    # "meme_concept" step's own structured output - never blocks, never mutates the concept
    # itself, never publishes anything.
    meme_safety_gate_mode: Literal["off", "shadow"] = "off"

    # Phase 18 M5: Meme Image Generation (docs/phase18_m5_meme_image_generation_report.md). "off"
    # (default): zero calls, zero cost. "dry_run": generates via whichever ImageGenerationGateway
    # was injected - in every call site this codebase wires up today, that is
    # `integrations.llm_gateway.providers.mock_image_adapter.MockImageAdapter`, a deterministic,
    # zero-network, zero-cost placeholder generator. There is deliberately no "live" value yet -
    # wiring a real, paid provider adapter is a separate, explicitly-authorized future step (per
    # the operating rule: no live/paid image-generation call without separate human
    # authorization) - the mode flag cannot even express "live" until that milestone adds it.
    meme_image_generation_mode: Literal["off", "dry_run"] = "off"
    meme_image_max_bytes: int = Field(default=10_000_000, gt=0)

    # Phase 18 M8: Telegram Meme Editorial Preview (docs/
    # phase18_m8_telegram_editorial_preview_report.md). "off" (default): the preview is never
    # built or sent. "dry_run": services.meme_preview_notifier.send_meme_preview() renders and
    # logs the exact payload, but never calls the Telegram API - mirrors content_generation_
    # dry_run's own established discipline. There is deliberately no "live" value yet - a real
    # Telegram send requires separate, explicit human authorization (operating rule) before that
    # value is even added.
    meme_telegram_preview_mode: Literal["off", "dry_run"] = "off"

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
