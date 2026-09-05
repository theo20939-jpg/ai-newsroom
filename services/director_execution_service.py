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
from services.business_context_snapshot_service import BusinessContextSnapshot, get_business_context_snapshot
from services.director_run_service import (
    compute_business_context_fingerprint,
    compute_input_fingerprint,
    create_director_run,
)
from services.instagram_content_opportunity import OpportunitySourceType, build_content_opportunity
from services.instagram_growth_strategist import InstagramGrowthStrategy, OpportunityContext, generate_growth_strategy
from services.telegram_feed_state import compute_feed_state
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
        "confidence": advisory.confidence,
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
    feed_state = await compute_feed_state(session, now=now)
    aggregate = await compute_telegram_performance_aggregate(session, now=now)
    advisory = derive_strategy_advisory(feed_state, patterns=aggregate.patterns)

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
        )
    return TelegramStrategyExecutionResult(advisory=advisory, aggregate_status=aggregate.status, run=run)


async def run_telegram_growth_director(
    session: AsyncSession, *, now: datetime | None = None,
) -> TelegramGrowthExecutionResult:
    """Real execution over the same TelegramPerformanceAggregator evidence `/performance` reads.
    `advisory` is None when the aggregate itself is not OK (nothing meaningful to advise on yet) -
    never a fabricated advisory over absent evidence."""
    now = now or datetime.now(timezone.utc)
    aggregate = await compute_telegram_performance_aggregate(session, now=now)
    if aggregate.status != "OK":
        return TelegramGrowthExecutionResult(advisory=None, aggregate_status=aggregate.status, run=None)

    advisory = derive_growth_director_advisory(aggregate.patterns)
    run: DirectorRun | None = None
    if settings.director_run_persistence_enabled:
        run = await create_director_run(
            session, director_type=DirectorType.TELEGRAM_GROWTH, platform="telegram", generated_at=now,
            input_fingerprint=compute_input_fingerprint(aggregate.total_posts_considered, aggregate.window),
            result_payload=_growth_advisory_payload(advisory),
            status=DirectorRunStatus.OK, decision=_first_or_none(advisory.signals) or "no actionable signal yet",
            confidence=advisory.confidence, evidence_stage=_best_evidence_stage(aggregate.patterns),
        )
    return TelegramGrowthExecutionResult(advisory=advisory, aggregate_status=aggregate.status, run=run)


async def run_instagram_growth_strategist(
    session: AsyncSession, *, now: datetime | None = None,
) -> InstagramGrowthExecutionResult:
    now = now or datetime.now(timezone.utc)
    snapshot = await get_business_context_snapshot(session, now=now)
    contexts = _product_opportunities_from_campaigns(snapshot)
    strategy = generate_growth_strategy(opportunity_contexts=contexts, directives=list(snapshot.active_directives))

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
