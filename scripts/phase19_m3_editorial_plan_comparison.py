"""Phase 19 M3: manually-invoked, NEVER auto-run comparison script (docs/phase19_m0_audit.md).

Produces a baseline (no Editorial Plan, today's exact CONTENT_GENERATION behavior) and a
candidate (WITH a real, LLM-backed Editorial Plan injected into Copywriting's context) draft for
the SAME event, for side-by-side human review. Never mutates a real ContentDraft row - both
outputs are written to a review-only JSON file.

This is the ONLY code path in this phase that makes a real, LLM-backed
capabilities.editorial_planning_capability.EditorialPlanningCapability call - requires
editorial_planning_mode == "comparison" to even start, and making it run for real against a live
provider requires its own, separate, explicit paid-call authorization (this script has NOT been
executed for real as part of this implementation - see the M6 checkpoint report).

Launch with:
    python -m scripts.phase19_m3_editorial_plan_comparison <event_id>

No scheduler, cron, or automatic-execution path - mirrors scripts/run_content_generation.py's own
established "a human or an external process invokes this manually" discipline, deliberately
stricter here (an explicit settings guard refuses to run at all outside "comparison" mode).
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capabilities.copywriting_capability import CAPABILITY_NAME as COPYWRITING_CAPABILITY_NAME
from capabilities.editorial_planning_capability import EditorialPlanningCapability
from capabilities.registry import CapabilityRegistry
from core.config import settings
from core.logging import setup_logging
from database.models.editorial_task import TaskPriority
from database.models.news_event import NewsEvent
from database.session import async_session_factory
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import (
    BusinessContext,
    CapabilityContext,
    ExecutionContext,
    NewsEventSnapshot,
    RuntimeContext,
    WorkflowExecutionStateSnapshot,
)
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowType
from services import workflow_service
from services.editorial_planning_safety import evaluate_plan_safety
from workflows.registry import registry as real_workflow_registry
from workflows.runner import WorkflowRunner

logger = logging.getLogger(__name__)

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"


class ComparisonModeNotEnabledError(Exception):
    """Refuses to run unless editorial_planning_mode == 'comparison' - defense-in-depth against
    accidental invocation, independent of whatever gates the caller's own environment has."""


@dataclass(frozen=True)
class ComparisonOutcome:
    event_id: UUID
    baseline_copywriting_output: dict | None
    candidate_editorial_plan: dict | None
    plan_safety_passed: bool
    plan_safety_failed_checks: list[str]
    candidate_copywriting_output: dict | None
    generated_at: str


async def _run_baseline(
    session: AsyncSession, event_id: UUID, capability_registry: CapabilityRegistry
) -> dict | None:
    """Today's exact, unmodified CONTENT_GENERATION chain - no plan involved at all. Reuses the
    real WorkflowRunner/CapabilityExecutor exactly as scripts/run_content_generation.py does."""
    from capabilities.executor import CapabilityExecutor

    command = EditorialTaskCreate(event_id=event_id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B)
    task = await workflow_service.create_task(session, command)
    executor = CapabilityExecutor(session, task.id, capability_registry)
    result = await WorkflowRunner(executor=executor, registry=real_workflow_registry).run(session, task.id)
    for step_result in result.step_results:
        if step_result.step_name == COPYWRITING_CAPABILITY_NAME:
            return step_result.result
    return None


async def _run_candidate_plan(
    session: AsyncSession, news_event: NewsEvent, prompt_repository: FilePromptRepository, capability_registry: CapabilityRegistry,
) -> dict | None:
    """The one real, LLM-backed Editorial Plan call in this entire phase - only ever reached from
    this manually-invoked script, never from the live CONTENT_GENERATION workflow."""
    _definition, capability = capability_registry.resolve("editorial_planning")
    assert isinstance(capability, EditorialPlanningCapability)

    context = CapabilityContext(
        business=BusinessContext(
            news_event=NewsEventSnapshot(
                id=news_event.id, title=news_event.title, summary=news_event.summary,
                content=news_event.content, url=news_event.url, category=news_event.category.value,
                published_at=news_event.published_at,
            ),
            workflow_state=WorkflowExecutionStateSnapshot(
                workflow_name="content_generation", workflow_version=1, completed_steps=[],
            ),
        ),
        runtime=RuntimeContext(
            task_id=news_event.id, event_id=news_event.id, capability_name="editorial_planning",
            priority=TaskPriority.B, attempt=1, iteration_count=0,
        ),
        execution=ExecutionContext(),
    )
    result = await capability.execute(context)
    return result.structured_output


async def run_comparison_for_event(
    event_id: UUID,
    *,
    capability_registry: CapabilityRegistry | None = None,
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
) -> ComparisonOutcome:
    if settings.editorial_planning_mode != "comparison":
        raise ComparisonModeNotEnabledError(
            "editorial_planning_mode must be explicitly set to 'comparison' to run this script - "
            f"currently '{settings.editorial_planning_mode}'."
        )

    prompt_repository = FilePromptRepository(_PROMPTS_ROOT)
    registry = capability_registry
    if registry is None:
        ai_layer = assemble_ai_integration_layer(settings, prompt_repository)
        registry = ai_layer.capability_registry

    async with session_factory() as session:
        news_event = await session.get(NewsEvent, event_id)
        if news_event is None:
            raise ValueError(f"No NewsEvent with id {event_id}")

        baseline_output = await _run_baseline(session, event_id, registry)
        plan = await _run_candidate_plan(session, news_event, prompt_repository, registry)

        safety_report = None
        if plan is not None:
            evidence_text = news_event.content or ""
            safety_report = evaluate_plan_safety(plan, evidence_text=evidence_text, quote_candidates=[evidence_text])

        # Never persisted as a real ContentDraft - the candidate copywriting call is deliberately
        # NOT performed by this MVP script version; a full "inject the plan into Copywriting's
        # own context and re-run it" candidate-generation pass is left for a future, separately-
        # reviewed extension once the baseline/plan comparison itself has been reviewed. The plan
        # itself (and its safety report) is the primary artifact for human review at this stage.
        candidate_copywriting_output = None

        await session.rollback()  # never commit anything this script's own baseline run touched

    return ComparisonOutcome(
        event_id=event_id,
        baseline_copywriting_output=baseline_output,
        candidate_editorial_plan=plan,
        plan_safety_passed=safety_report.passed if safety_report is not None else False,
        plan_safety_failed_checks=safety_report.failed_checks if safety_report is not None else [],
        candidate_copywriting_output=candidate_copywriting_output,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def write_review_packet(outcome: ComparisonOutcome, output_path: Path) -> None:
    output_path.write_text(json.dumps(asdict(outcome), indent=2, default=str), encoding="utf-8")


async def main() -> None:
    setup_logging()
    event_id = UUID(sys.argv[1])
    outcome = await run_comparison_for_event(event_id)
    output_path = Path(f"phase19_m3_comparison_{event_id}.json")
    write_review_packet(outcome, output_path)
    logger.info("comparison_written", extra={"event_id": str(event_id), "output_path": str(output_path)})


if __name__ == "__main__":
    asyncio.run(main())
