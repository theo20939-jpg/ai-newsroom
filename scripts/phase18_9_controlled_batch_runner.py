"""Phase 18.9 M5 - bounded, explicit-allowlist controlled-run tooling (docs/
phase18_9_controlled_run_plan.md).

Reuses the exact same production primitives every worker cycle already uses -
`CapabilityExecutor`, `WorkflowRunner`, `assemble_ai_integration_layer()`,
`run_content_generation_for_event()` - never a parallel architecture, never a direct provider-
adapter call. The only new logic here is *selection* (an explicit ID allowlist, never a shared
eligibility query) and *budget gating* (reads the real `AIExecution` table before every single
task - chosen over the Redis cost ledger specifically because docs/phase18_9_paid_pipeline_audit.md
§4 found a real, disclosed write-reliability gap in that ledger).

Disabled by default: both entry points require `dry_run=False` to make any real call - the default
`dry_run=True` only ever previews what *would* run (existence/eligibility/budget checks), touches
no capability, no provider, no cost. Never imports `bot`/any Telegram module, any image-generation
module, or any meme module - Telegram sending, image generation, and meme workflows are
structurally unreachable from this file (enforced by `tests/test_phase18_9_controlled_batch.py`'s
own import-boundary check).

Hard ceilings (defense-in-depth on top of the caller passing a short list): at most
`MAX_ANALYSIS_BATCH_SIZE` (10) task IDs, at most `MAX_CONTENT_BATCH_SIZE` (5) event IDs - a longer
list is rejected outright, never silently truncated or partially honored.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capabilities.executor import CapabilityExecutor
from capabilities.registry import CapabilityRegistry
from core.config import settings
from database.models.ai_execution import AIExecution
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.session import async_session_factory
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.prompts.file_repository import FilePromptRepository
from schemas.controlled_batch import BoundedBatchResult, BoundedTaskOutcome, BoundedTaskStatus
from schemas.workflow import WorkflowType
from scripts.run_content_generation import run_content_generation_for_event
from services.cost_tracker import CostTracker
from services.pricing_catalog import ModelRegistryPricingCatalog, PricingCatalog
from workflows.runner import WorkflowRunner

logger = logging.getLogger(__name__)

MAX_ANALYSIS_BATCH_SIZE = 10
MAX_CONTENT_BATCH_SIZE = 5

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

# Conservative per-task worst-case estimates (docs/phase18_9_cost_estimate.md §4: sol-tier
# pricing, single pass, no retries - the *realistic* worst case, not the near-impossible
# max-retries-and-sol-pricing absolute ceiling) - used for the pre-flight "would this task alone
# blow the remaining budget" refusal, deliberately conservative (higher than the ~$0.003-0.008
# typical real cost) so the check is refuse-early, not refuse-only-after-the-fact.
#
# NEWS_ANALYSIS's own estimate is $0.0473, not the originally-lower $0.035 - revised upward after
# a real incident (docs/phase18_9_paid_pipeline_audit.md) established that the `engagement` step
# is a real, paid capability (previously miscategorized as free), which docs/
# phase18_9_cost_estimate.md §4 now accounts for.
_ANALYSIS_TASK_CONSERVATIVE_ESTIMATE_USD = Decimal("0.05")
_CONTENT_TASK_CONSERVATIVE_ESTIMATE_USD = Decimal("0.035")


async def _cost_spent_since(session: AsyncSession, run_started_at: datetime) -> Decimal:
    """Fails closed: if this query itself raises, the caller must treat the budget as unknown
    and stop, never assume $0 and proceed - unlike `RedisCostTracker.record()`'s own deliberate
    "swallow and continue" policy (a cost-recording write failure there is acceptable because it
    doesn't block a call from happening; here, a *read* failure would mean proceeding blind on a
    live-money decision, which must never happen).

    Deliberately a single, stateless `SUM(cost) WHERE created_at >= run_started_at` query - an
    earlier draft tracked a mutable "already-seen row ids" set and computed a delta between two
    calls, which had a real, confirmed bug: the very first call (empty seen-set) summed the
    *entire historical table* as its baseline, and every later call's delta was computed against
    that huge baseline, making the "spent so far this run" figure large and negative - permanently
    incapable of ever exceeding a budget, regardless of real spend. That bug was caught during this
    phase's own M6 testing (a real workflow execution was reached and ran to completion in a test
    that should have been refused for budget - see docs/phase18_9_paid_pipeline_audit.md's
    incident note) before any Section B authorization was sought - this rewrite removes the
    stateful class of bug entirely rather than patching the symptom."""
    result = await session.execute(
        select(func.coalesce(func.sum(AIExecution.cost), 0)).where(AIExecution.created_at >= run_started_at)
    )
    return Decimal(str(result.scalar_one()))


async def _known_model_ids() -> set[str]:
    return {m.model_id for m in build_model_registry().all_models()}


async def run_bounded_analysis_batch(
    task_ids: list[UUID],
    *,
    max_budget_usd: Decimal,
    dry_run: bool = True,
    capability_registry: CapabilityRegistry | None = None,
    cost_tracker: CostTracker | None = None,
    pricing_catalog: PricingCatalog | None = None,
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
) -> BoundedBatchResult:
    """Runs each explicit, pre-existing `NEWS_ANALYSIS` `EditorialTask` id in `task_ids`,
    sequentially (concurrency=1, matching production's own `run_analysis_cycle()` shape), never
    creating a new task, never touching any id outside this exact list.

    `capability_registry`/`cost_tracker`/`pricing_catalog`: injectable, mirroring `scripts.
    run_content_generation.run_content_generation_for_event()`'s own established DI seam - tests
    MUST inject a fake registry (never rely on `dry_run`/budget-check correctness alone to prevent
    a real call reaching a real provider - docs/phase18_9_paid_pipeline_audit.md's own incident
    note: an earlier version of this function always built the real, production
    `assemble_ai_integration_layer()` unconditionally, and a since-fixed budget-check bug let a
    real workflow execution run to completion in a test). The real layer is now only ever
    constructed lazily, immediately before the first actual (non-dry-run, budget-cleared)
    execution - never merely because the function was called."""
    if len(task_ids) > MAX_ANALYSIS_BATCH_SIZE:
        raise ValueError(f"task_ids exceeds MAX_ANALYSIS_BATCH_SIZE ({MAX_ANALYSIS_BATCH_SIZE})")

    result = BoundedBatchResult()
    run_started_at = datetime.now(timezone.utc)
    known_models = await _known_model_ids()

    consecutive_failures = 0
    for task_id in task_ids:
        async with session_factory() as session:
            try:
                spent_this_run = await _cost_spent_since(session, run_started_at)
            except Exception as exc:
                result.stopped_early = True
                result.stop_reason = f"budget_check_failed_closed: {exc}"
                break

            if spent_this_run + _ANALYSIS_TASK_CONSERVATIVE_ESTIMATE_USD > max_budget_usd:
                result.outcomes.append(BoundedTaskOutcome(task_id, BoundedTaskStatus.SKIPPED_BUDGET_EXCEEDED))
                result.stopped_early = True
                result.stop_reason = "budget_ceiling_would_be_exceeded"
                break

            task = await session.get(EditorialTask, task_id)
            if task is None or task.status != TaskStatus.CREATED:
                status = task.status.value if task else "not_found"
                result.outcomes.append(BoundedTaskOutcome(
                    task_id, BoundedTaskStatus.SKIPPED_NOT_ELIGIBLE, detail=f"status={status}",
                ))
                continue

            if dry_run:
                result.outcomes.append(BoundedTaskOutcome(task_id, BoundedTaskStatus.DRY_RUN_PREVIEW))
                continue

            if capability_registry is None:
                ai_layer = assemble_ai_integration_layer(settings, FilePromptRepository(_PROMPTS_ROOT))
                capability_registry = ai_layer.capability_registry
                if cost_tracker is None:
                    cost_tracker = ai_layer.cost_tracker
            if pricing_catalog is None:
                pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())

            executor = CapabilityExecutor(
                session, task_id, capability_registry,
                cost_tracker=cost_tracker, pricing_catalog=pricing_catalog,
            )
            try:
                run_result = await WorkflowRunner(executor).run(session, task_id)
            except Exception as exc:
                result.outcomes.append(BoundedTaskOutcome(
                    task_id, BoundedTaskStatus.STOPPED_UNEXPECTED_ERROR, detail=str(exc),
                ))
                consecutive_failures += 1
                if consecutive_failures >= 2:
                    result.stopped_early = True
                    result.stop_reason = "two_consecutive_unexpected_errors"
                    break
                continue

            consecutive_failures = 0
            models_used = (
                await session.execute(select(AIExecution.model).where(AIExecution.task_id == task_id))
            ).scalars().all()
            unexpected = [m for m in models_used if m not in known_models]
            if unexpected:
                result.outcomes.append(BoundedTaskOutcome(
                    task_id, BoundedTaskStatus.STOPPED_UNEXPECTED_MODEL, detail=f"models={unexpected}",
                ))
                result.stopped_early = True
                result.stop_reason = f"unexpected_model_encountered: {unexpected}"
                break

            status = BoundedTaskStatus.COMPLETED if run_result.status == "COMPLETED" else BoundedTaskStatus.FAILED
            result.outcomes.append(BoundedTaskOutcome(task_id, status))

    async with session_factory() as session:
        try:
            result.total_cost = await _cost_spent_since(session, run_started_at)
        except Exception:
            pass  # best-effort final tally only; the per-task fail-closed checks above already govern safety
    return result


async def run_bounded_content_batch(
    event_ids: list[UUID],
    *,
    max_budget_usd: Decimal,
    dry_run: bool = True,
    priority: TaskPriority = TaskPriority.B,
    capability_registry: CapabilityRegistry | None = None,
    cost_tracker: CostTracker | None = None,
    pricing_catalog: PricingCatalog | None = None,
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
) -> BoundedBatchResult:
    """Runs `scripts.run_content_generation.run_content_generation_for_event()` for each explicit
    `event_id` in `event_ids` - the same, unmodified, Telegram-free tool `content_worker` itself
    calls internally, never `content_worker`'s own cycle/eligibility path."""
    if len(event_ids) > MAX_CONTENT_BATCH_SIZE:
        raise ValueError(f"event_ids exceeds MAX_CONTENT_BATCH_SIZE ({MAX_CONTENT_BATCH_SIZE})")

    result = BoundedBatchResult()
    run_started_at = datetime.now(timezone.utc)
    registry = capability_registry

    consecutive_failures = 0
    for event_id in event_ids:
        async with session_factory() as session:
            try:
                spent_this_run = await _cost_spent_since(session, run_started_at)
            except Exception as exc:
                result.stopped_early = True
                result.stop_reason = f"budget_check_failed_closed: {exc}"
                break

            if spent_this_run + _CONTENT_TASK_CONSERVATIVE_ESTIMATE_USD > max_budget_usd:
                result.outcomes.append(BoundedTaskOutcome(event_id, BoundedTaskStatus.SKIPPED_BUDGET_EXCEEDED))
                result.stopped_early = True
                result.stop_reason = "budget_ceiling_would_be_exceeded"
                break

            has_analysis = (await session.execute(
                select(func.count()).select_from(EditorialTask).where(
                    EditorialTask.event_id == event_id,
                    EditorialTask.status == TaskStatus.COMPLETED,
                    EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value,
                )
            )).scalar_one()
            if not has_analysis:
                result.outcomes.append(BoundedTaskOutcome(
                    event_id, BoundedTaskStatus.SKIPPED_NOT_ELIGIBLE, detail="no_completed_analysis",
                ))
                continue

        if dry_run:
            result.outcomes.append(BoundedTaskOutcome(event_id, BoundedTaskStatus.DRY_RUN_PREVIEW))
            continue

        try:
            outcome = await run_content_generation_for_event(
                event_id, priority=priority, capability_registry=registry,
                session_factory=session_factory, cost_tracker=cost_tracker, pricing_catalog=pricing_catalog,
            )
        except Exception as exc:
            result.outcomes.append(BoundedTaskOutcome(
                event_id, BoundedTaskStatus.STOPPED_UNEXPECTED_ERROR, detail=str(exc),
            ))
            consecutive_failures += 1
            if consecutive_failures >= 2:
                result.stopped_early = True
                result.stop_reason = "two_consecutive_unexpected_errors"
                break
            continue

        consecutive_failures = 0
        status = (
            BoundedTaskStatus.COMPLETED if outcome.workflow_status == "COMPLETED" and outcome.content_draft
            else BoundedTaskStatus.FAILED
        )
        result.outcomes.append(BoundedTaskOutcome(event_id, status))

    async with session_factory() as session:
        try:
            result.total_cost = await _cost_spent_since(session, run_started_at)
        except Exception:
            pass
    return result
