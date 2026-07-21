"""Entry point for running one CONTENT_GENERATION cycle for a given event (Phase 10 M4,
docs/phase10_production_content_pipeline_architecture_contract.md §9).

Launch with:
    python -m scripts.run_content_generation <event_id>

Unlike scripts/run_triage.py (a ~20-line wrapper around services.triage_orchestrator.
run_triage_cycle(), which has "no LLMGateway, no Capability layer, no provider SDK"), this
script is this repository's first production caller of assemble_ai_integration_layer() - it
assembles the real AI integration layer (LLMGateway, CapabilityRegistry) itself, mirroring the
pattern already proven in tests/test_capability_boot_wiring_e2e.py and
tests/test_phase9_research_intelligence_integration.py (docs/phase10_implementation_plan.md §6).

No scheduler, cron, or automatic-execution path - a human or an external process invokes this
manually (Contract §9). Orchestration only: never duplicates WorkflowRunner's step loop, never
invokes a Capability directly, never writes a ContentDraft row itself - it composes the existing,
unmodified WorkflowRunner/CapabilityExecutor/CapabilityRegistry/ContentDraftService exactly as
Milestones 1-3 already built them.
"""
import asyncio
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capabilities.executor import CapabilityExecutor
from capabilities.registry import CapabilityRegistry
from core.config import settings
from core.logging import setup_logging
from database.models.editorial_task import TaskPriority
from database.session import async_session_factory
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.prompts.file_repository import FilePromptRepository
from schemas.content_draft import ContentDraftRead
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import RunStatus, WorkflowType
from services import workflow_service
from services.content_draft_service import ContentDraftService
from workflows.runner import WorkflowRunner

logger = logging.getLogger(__name__)

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"


@dataclass(frozen=True)
class ContentGenerationOutcome:
    """Returned by run_content_generation_for_event() - the three-outcome distinction Contract
    §9 requires, made directly inspectable by both the CLI and tests, not merely logged.

    `workflow_status == "FAILED"` -> outcome 2 (no ContentDraft was ever attempted).
    `workflow_status == "COMPLETED" and content_draft is None` -> outcome 3 (the disclosed,
    accepted gap: ContentDraftService raised after the task had already committed COMPLETED).
    `workflow_status == "COMPLETED" and content_draft is not None` -> outcome 1 (full success).
    """

    task_id: UUID
    workflow_status: RunStatus
    content_draft: ContentDraftRead | None


async def run_content_generation_for_event(
    event_id: UUID,
    *,
    priority: TaskPriority = TaskPriority.B,
    capability_registry: CapabilityRegistry | None = None,
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
) -> ContentGenerationOutcome:
    """Orchestrate one NewsEvent through research -> intelligence -> copywriting -> quality ->
    ContentDraft persistence, using only the already-implemented production abstractions.

    `capability_registry`: injectable dependency seam (docs/phase10_implementation_advisory.md) -
    if omitted (the production default), the real AI integration layer is assembled via
    assemble_ai_integration_layer(), exactly as production requires. Tests inject a fake/test
    CapabilityRegistry instead (built the same way tests/test_phase10_workflow_integration.py's
    already does, via capabilities.registry.build_registry() against a FakeLLMGateway), which
    entirely avoids constructing a real LLMGateway, provider stack, or Redis connection.

    `session_factory`: mirrors services.triage_orchestrator.run_triage_cycle()'s own
    `session_factory: async_sessionmaker[AsyncSession] = async_session_factory` default-parameter
    shape exactly - the same, already-established DI precedent in this codebase, not a new one.
    Production default is the real, pooled `database.session.async_session_factory`; tests inject
    a fresh, event-loop-scoped factory (tests.test_triage_orchestrator_claims.
    independent_session_factory()), avoiding the documented cross-event-loop connection-reuse
    hazard the shared engine singleton carries across separate test functions.

    NewsEvent existence is validated by workflow_service.create_task() itself (raises
    NewsEventNotFoundError) - not re-checked here, to avoid a second, redundant lookup query.
    """
    registry = capability_registry
    if registry is None:
        prompt_repository = FilePromptRepository(_PROMPTS_ROOT)
        ai_layer = assemble_ai_integration_layer(settings, prompt_repository)
        registry = ai_layer.capability_registry

    async with session_factory() as session:
        task = await workflow_service.create_task(
            session,
            EditorialTaskCreate(event_id=event_id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=priority),
        )
        executor = CapabilityExecutor(session, task.id, registry)
        runner = WorkflowRunner(executor)
        result = await runner.run(session, task.id)

        if result.status != "COMPLETED":
            logger.error("content_generation_task_failed", extra={"task_id": str(task.id)})
            return ContentGenerationOutcome(task_id=task.id, workflow_status=result.status, content_draft=None)

        try:
            draft = await ContentDraftService(session).create_from_result(task.id, result)
        except Exception:
            logger.exception(
                "content_generation_completed_but_draft_persistence_failed",
                extra={"task_id": str(task.id)},
            )
            return ContentGenerationOutcome(task_id=task.id, workflow_status=result.status, content_draft=None)

        logger.info(
            "content_generation_succeeded", extra={"task_id": str(task.id), "draft_id": str(draft.id)}
        )
        return ContentGenerationOutcome(task_id=task.id, workflow_status=result.status, content_draft=draft)


async def main() -> None:
    setup_logging()
    event_id = UUID(sys.argv[1])
    await run_content_generation_for_event(event_id)


if __name__ == "__main__":
    asyncio.run(main())
