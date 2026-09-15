"""SOCIAL-INTELLIGENCE-OPS-1A, spec §2/§7: DirectorExecutionService - the ONLY place a Telegram
Strategy/Growth or Instagram Growth advisory is computed AND (flag-gated) persisted as a
DirectorRun. `services/director_console_service.py` (the read-only console) may only ever READ an
already-persisted run (`services/director_run_service.py::get_latest_run()`) - it never imports or
calls anything in this module, and never calls `create_director_run()` itself (spec §1's own
console read-purity invariant: opening `/plan`/`/performance`/`/directors` must never write to the
database).

Each `run_*` function here always computes its real, already-existing, deterministic advisory
(no Gateway call - spec §18's cost-safety rule is unaffected either way) and returns it as
structured output; PERSISTENCE is a separate, explicit, flag-gated step
(`settings.director_run_persistence_enabled`, default False) - the `run` field on each result is
`None` whenever persistence is disabled, never a fabricated row.

CRITICAL (spec §7): only real, already-existing, "runs over current global state" directors are
wrapped here. `services/telegram_channel_director_shadow.py::run_channel_director_shadow()`
(Telegram Channel Director) and `services/instagram_format_director_v2.py::evaluate_format_v2()`
(Instagram Format Director) are genuinely PER-SUBJECT evaluators already wired into their own real
call sites (worker/content_cycle.py's own per-Story shadow call; `director_console_service.py`'s
own per-opportunity-row builder) - they have no natural "run once over current global state" entry
point the way Growth/Strategy do, so wrapping them here would fabricate a symmetry that does not
exist. Deliberately not implemented; documented in this phase's own final report."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.director_run import DirectorRun, DirectorRunEvidenceStage, DirectorRunStatus, DirectorType
from database.models.social_launch_context import SocialLaunchPlatform
from services.business_context_snapshot_service import BusinessContextSnapshot, get_business_context_snapshot
from services.director_run_service import (
    compute_business_context_fingerprint,
    compute_input_fingerprint,
    create_director_run,
)
from services.instagram_connection_service import sync_instagram_feed_context
from services.instagram_content_opportunity import OpportunitySourceType, build_content_opportunity
from services.instagram_growth_strategist import InstagramGrowthStrategy, OpportunityContext, generate_growth_strategy
from services.social_launch_context_service import compute_launch_context_fingerprint, get_current_context
from services.telegram_feed_state import compute_feed_state
from services.telegram_feed_window import assemble_live_telegram_feed_window
from services.telegram_growth_director import GrowthDirectorAdvisory, derive_growth_director_advisory
from services.telegram_performance_aggregator import compute_telegram_performance_aggregate
from services.telegram_performance_memory import EvidenceStage, PerformancePattern
from services.telegram_strategy_director import StrategyDirectorAdvisory, derive_strategy_advisory

_AGGREGATE_STATUS_TO_RUN_STATUS: dict[str, DirectorRunStatus] = {
    "OK": DirectorRunStatus.OK,
    "WAITING_FOR_DATA": DirectorRunStatus.WAITING_FOR_DATA,
    "INSUFFICIENT_EVIDENCE": DirectorRunStatus.INSUFFICIENT_EVIDENCE,
    "PUBLIC_CHANNEL_NOT_CONFIGURED": DirectorRunStatus.BLOCKED,
}
_EVIDENCE_STAGE_ORDER = [
    EvidenceStage.ANOMALY, EvidenceStage.POSSIBLE_SIGNAL, EvidenceStage.REPEATED_PATTERN,
    EvidenceStage.STABLE_WORKING_RULE,
]
_EVIDENCE_STAGE_TO_RUN_STAGE: dict[EvidenceStage, DirectorRunEvidenceStage] = {
    EvidenceStage.ANOMALY: DirectorRunEvidenceStage.OBSERVATION,
    EvidenceStage.POSSIBLE_SIGNAL: DirectorRunEvidenceStage.POSSIBLE_SIGNAL,
    EvidenceStage.REPEATED_PATTERN: DirectorRunEvidenceStage.REPEATED_PATTERN,
    EvidenceStage.STABLE_WORKING_RULE: DirectorRunEvidenceStage.STABLE_WORKING_RULE,
}


def _best_evidence_stage(patterns: list[PerformancePattern]) -> DirectorRunEvidenceStage | None:
    """The most evidentially mature stage among the patterns a run actually consumed - a run fed
    zero patterns records no evidence stage at all, never a fabricated OBSERVATION."""
    if not patterns:
        return None
    best = max(patterns, key=lambda p: _EVIDENCE_STAGE_ORDER.index(p.stage))
    return _EVIDENCE_STAGE_TO_RUN_STAGE[best.stage]


def _first_or_none(values: list[str]) -> str | None:
    return values[0][:100] if values else None


def _strategy_advisory_payload(advisory: StrategyDirectorAdvisory) -> dict:
    """Explicit field selection, never `dataclasses.asdict()` - every key here matches a real
    `StrategyDirectorAdvisory` field name so `StrategyDirectorAdvisory(**payload)` round-trips
    exactly; all values are plain JSON-safe `list[str]`."""
    return {
        "priority_themes": advisory.priority_themes, "content_balance_notes": advisory.content_balance_notes,
        "campaign_support_notes": advisory.campaign_support_notes, "series_opportunities": advisory.series_opportunities,
        "avoidance_fatigue_notes": advisory.avoidance_fatigue_notes, "experiment_suggestions": advisory.experiment_suggestions,
        "content_gaps": advisory.content_gaps,
    }


def _growth_advisory_payload(advisory: GrowthDirectorAdvisory) -> dict:
    return {
        "signals": advisory.signals, "fatigue": advisory.fatigue,
        "amplification_candidates": advisory.amplification_candidates,
        "experiment_recommendations": advisory.experiment_recommendations, "warnings": advisory.warnings,
        "confidence": advisory.confidence, "first_party_baseline": advisory.first_party_baseline,
        "growth_hypotheses": advisory.growth_hypotheses,
    }


def _instagram_strategy_payload(strategy: InstagramGrowthStrategy) -> dict:
    """`priority_opportunities` (list[ContentOpportunity]) is deliberately OMITTED - it is not
    JSON-safe (nested dataclass carrying datetimes) and no console renderer ever reads it back;
    `InstagramGrowthStrategy(**payload)` still reconstructs correctly since that field's own
    `default_factory=list` fills it in as an empty list."""
    return {
        "objective_mix": strategy.objective_mix, "campaign_support": strategy.campaign_support,
        "content_gaps": strategy.content_gaps, "trend_opportunities": strategy.trend_opportunities,
        "series_recommendations": strategy.series_recommendations,
        "experiment_recommendations": strategy.experiment_recommendations,
        "avoidance_notes": strategy.avoidance_notes, "risks": strategy.risks, "confidence": strategy.confidence,
    }


def _product_opportunities_from_campaigns(snapshot: BusinessContextSnapshot) -> list[OpportunityContext]:
    contexts: list[OpportunityContext] = []
    product_by_id = {str(s.product.id): s.product for s in snapshot.products}
    for plan in snapshot.active_campaigns:
        product = product_by_id.get(plan.product_id)
        opportunity = build_content_opportunity(
            id=f"campaign:{plan.campaign_id}", source_type=OpportunitySourceType.PRODUCT,
            product_id=plan.product_id, campaign_id=plan.campaign_id, campaign_plan=plan,
            recommended_objectives=[], evidence=[f"active campaign phase={plan.phase}"], confidence=0.4,
        )
        real_restricted = [c.claim_text for c in snapshot.restricted_claims if str(c.product_id) == plan.product_id]
        if real_restricted:
            opportunity = replace(opportunity, restricted_claims=sorted(set(opportunity.restricted_claims) | set(real_restricted)))
        contexts.append(OpportunityContext(opportunity=opportunity, product_slug=product.slug if product else None))
    return contexts


def _product_opportunities_from_context(snapshot: BusinessContextSnapshot) -> list[OpportunityContext]:
    """INSTAGRAM-CONTENT-STRATEGY-V2 Phase 2 ("Founder Plan Review" constraint - "Campaign must
    NOT be mandatory" / addendum §8 point 8): `_product_opportunities_from_campaigns()` above ONLY
    iterates `snapshot.active_campaigns` - a real, confirmed gap, a `Product` with zero active
    `LaunchCampaign` rows produces ZERO opportunities today. This sibling function (never a
    replacement, never a second construction PATH - it calls the exact same
    `build_content_opportunity()` assembly function above, with `campaign_plan=None`, an
    already-supported optional parameter) covers every OTHER product with real, CONFIRMED ground
    truth to build content from.

    Never fabricates evidence: a product with zero `current_features` produces ZERO opportunities
    here - "we don't know anything confirmed about this product yet" is a real, disclosed gap for
    the Director to proactively ask about (services/business_context_proposal_service.py::
    scan_for_director_information_needs()), never something this function invents content from."""
    contexts: list[OpportunityContext] = []
    campaign_backed_product_ids = {ctx.opportunity.product_id for ctx in _product_opportunities_from_campaigns(snapshot)}
    for summary in snapshot.products:
        product = summary.product
        if str(product.id) in campaign_backed_product_ids:
            continue  # already covered above - never double-counted across both functions
        if not product.current_features:
            continue  # nothing CONFIRMED to build content from yet - a real gap, not invented
        opportunity = build_content_opportunity(
            id=f"product_context:{product.id}", source_type=OpportunitySourceType.PRODUCT,
            product_id=str(product.id), campaign_plan=None,
            evidence=[f"confirmed feature: {feature}" for feature in product.current_features],
            confidence=0.3,
        )
        contexts.append(OpportunityContext(opportunity=opportunity, product_slug=product.slug))
    return contexts


@dataclass(frozen=True)
class TelegramStrategyExecutionResult:
    advisory: StrategyDirectorAdvisory
    aggregate_status: str
    run: DirectorRun | None = None


@dataclass(frozen=True)
class TelegramGrowthExecutionResult:
    advisory: GrowthDirectorAdvisory | None
    aggregate_status: str
    run: DirectorRun | None = None


@dataclass(frozen=True)
class InstagramGrowthExecutionResult:
    strategy: InstagramGrowthStrategy
    run: DirectorRun | None = None


async def run_telegram_strategy_director(
    session: AsyncSession, *, now: datetime | None = None,
) -> TelegramStrategyExecutionResult:
    """Real execution: computes the same deterministic advisory `/plan` used to compute inline
    before this phase - now the ONLY place that happens. Persists a DirectorRun iff
    `settings.director_run_persistence_enabled`."""
    now = now or datetime.now(timezone.utc)
    snapshot = await get_business_context_snapshot(session, now=now)
    # SOCIAL-INTELLIGENCE-PRELAUNCH-1A §21/§25: the SAME launch context compute_feed_state()'s own
    # cold-start filtering already uses (services/telegram_feed_state.py) - a Strategy Director
    # reading a live, already-launched channel's feed_state is completely unaffected by this fetch
    # existing (launch_context=None -> unfiltered, exact prior behavior).
    launch_context = await get_current_context(session, SocialLaunchPlatform.TELEGRAM)
    feed_state = await compute_feed_state(session, now=now, launch_context=launch_context)
    aggregate = await compute_telegram_performance_aggregate(session, now=now)
    # DIRECTOR-CONTROL-PLANE-1B §5: real recent-feed window (bounded Telethon read of the
    # registered owned surface, else an honestly empty window). derive_strategy_advisory() uses it
    # only for a legacy-vs-eligible composition note - never to change the FeedState-derived
    # reasoning (spec §6: legacy VPN posts are transition context, never PULSE performance evidence).
    feed_window = await assemble_live_telegram_feed_window(session, launch_context=launch_context)
    advisory = derive_strategy_advisory(feed_state, patterns=aggregate.patterns, feed_window=feed_window)

    run: DirectorRun | None = None
    if settings.director_run_persistence_enabled:
        run = await create_director_run(
            session, director_type=DirectorType.TELEGRAM_STRATEGY, platform="telegram", generated_at=now,
            input_fingerprint=compute_input_fingerprint(
                feed_state.posts_24h, feed_state.topic_streak, aggregate.total_posts_considered,
            ),
            result_payload=_strategy_advisory_payload(advisory),
            status=_AGGREGATE_STATUS_TO_RUN_STATUS.get(aggregate.status, DirectorRunStatus.WAITING_FOR_DATA),
            decision=_first_or_none(advisory.priority_themes) or "no priority theme identified",
            evidence_stage=_best_evidence_stage(aggregate.patterns),
            business_context_fingerprint=compute_business_context_fingerprint(snapshot),
            launch_context_fingerprint=compute_launch_context_fingerprint(launch_context),
        )
    return TelegramStrategyExecutionResult(advisory=advisory, aggregate_status=aggregate.status, run=run)


async def run_telegram_growth_director(
    session: AsyncSession, *, now: datetime | None = None,
) -> TelegramGrowthExecutionResult:
    """Real execution over the same TelegramPerformanceAggregator evidence `/performance` reads.

    SOCIAL-INTELLIGENCE-PRELAUNCH-1A §5: `aggregate.status != "OK"` (zero eligible first-party
    posts, for any reason - no public channel, no posts yet, or too few) no longer returns
    `advisory=None` - it returns a real GrowthDirectorAdvisory with
    `first_party_baseline="NONE"` and clearly-labeled `growth_hypotheses` instead. This is NOT
    "a fabricated advisory over absent evidence" (this function's own prior docstring wording) -
    a hypothesis is explicitly never presented as an observed pattern, and
    services/telegram_growth_director.py never promotes one into a PerformancePattern on its own."""
    now = now or datetime.now(timezone.utc)
    aggregate = await compute_telegram_performance_aggregate(session, now=now)
    # DIRECTOR-CONTROL-PLANE-1B §6: Growth Director sees the recent-feed window ONLY to explain
    # WHY there is no PerformancePattern evidence yet (e.g. "all recent posts are pre-boundary
    # legacy/transition content"). derive_growth_director_advisory()'s own contract never lets the
    # window manufacture a signal/fatigue/amplification entry - PerformancePattern evidence stays
    # the sole trusted source for those, so legacy VPN engagement is never learned as PULSE
    # performance (spec §6). launch_context is the SAME one the aggregator already filtered through.
    growth_launch_context = await get_current_context(session, SocialLaunchPlatform.TELEGRAM)
    feed_window = await assemble_live_telegram_feed_window(session, launch_context=growth_launch_context)
    advisory = derive_growth_director_advisory(
        aggregate.patterns, is_cold_start=aggregate.status != "OK", feed_window=feed_window,
    )

    run: DirectorRun | None = None
    if settings.director_run_persistence_enabled:
        # SOCIAL-INTELLIGENCE-PRELAUNCH-1A §25: the aggregator's own patterns are already filtered
        # through the current launch context (services/telegram_performance_aggregator.py) - this
        # fingerprint lets a later staleness check (services/director_run_service.py::
        # is_run_context_stale()) detect a launch context change even though this run never reads
        # the context object directly itself.
        launch_context = growth_launch_context
        run = await create_director_run(
            session, director_type=DirectorType.TELEGRAM_GROWTH, platform="telegram", generated_at=now,
            input_fingerprint=compute_input_fingerprint(aggregate.total_posts_considered, aggregate.window),
            result_payload=_growth_advisory_payload(advisory),
            status=DirectorRunStatus.OK if aggregate.status == "OK" else DirectorRunStatus.WAITING_FOR_DATA,
            decision=_first_or_none(advisory.signals) or _first_or_none(advisory.growth_hypotheses) or "no actionable signal yet",
            confidence=advisory.confidence, evidence_stage=_best_evidence_stage(aggregate.patterns),
            launch_context_fingerprint=compute_launch_context_fingerprint(launch_context),
        )
    return TelegramGrowthExecutionResult(advisory=advisory, aggregate_status=aggregate.status, run=run)


async def run_instagram_growth_strategist(
    session: AsyncSession, *, now: datetime | None = None,
) -> InstagramGrowthExecutionResult:
    now = now or datetime.now(timezone.utc)
    snapshot = await get_business_context_snapshot(session, now=now)
    # Phase 2: campaign-backed AND campaign-free PRODUCT opportunities are merged before ranking -
    # an active LaunchCampaign is a real, distinguishing signal (campaign_relevance), never a
    # prerequisite for a Product to generate content (see _product_opportunities_from_context()'s
    # own docstring).
    contexts = _product_opportunities_from_campaigns(snapshot) + _product_opportunities_from_context(snapshot)
    # DIRECTOR-CONTROL-PLANE-1C §10/§11: the ONE bounded official read path. When Instagram is
    # configured, `sync_instagram_feed_context()` calls the real read-only reader
    # (services/instagram_account_reader.py) and normalizes the result through
    # build_instagram_feed_context(); when it is NOT configured (this environment - no credentials),
    # it returns raw_media=None -> an honestly empty prelaunch context, exactly as before. Any
    # fetch failure degrades to the same empty context (§15) - Director planning never crashes.
    sync = await sync_instagram_feed_context(session, now=now)
    strategy = generate_growth_strategy(
        opportunity_contexts=contexts, directives=list(snapshot.active_directives), feed_context=sync.feed_context,
    )

    run: DirectorRun | None = None
    if settings.director_run_persistence_enabled:
        run = await create_director_run(
            session, director_type=DirectorType.INSTAGRAM_GROWTH, platform="instagram", generated_at=now,
            input_fingerprint=compute_input_fingerprint(len(contexts), sorted(c.opportunity.id for c in contexts)),
            result_payload=_instagram_strategy_payload(strategy),
            status=DirectorRunStatus.OK if contexts else DirectorRunStatus.WAITING_FOR_DATA,
            confidence=strategy.confidence, business_context_fingerprint=compute_business_context_fingerprint(snapshot),
        )
    return InstagramGrowthExecutionResult(strategy=strategy, run=run)
