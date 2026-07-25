"""CapabilityExecutor: implements workflows.runner.StepExecutor, bridging the
Workflow Engine (Phase 5) to the Capability Framework (Phase 6).

Constructed fresh per (session, task_id, registry), immediately before the
matching WorkflowRunner.run() call, using the same session and task_id -
constructor injection, zero changes to workflows/runner.py, workflows/
registry.py, or schemas/workflow.py (docs/phase6_architecture_contract.md
§5, rule 1).

Per Amendment B (§16): CapabilityExecutor MUST NOT persist any AIExecution
row in Phase 6. It holds a live database session only to re-fetch the
EditorialTask/NewsEvent (read-only) - it never calls CostTracker, BudgetGuard,
or LLMGateway, and never writes to `ai_executions`.
"""
import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.editorial_task import EditorialTask
from database.models.news_event import NewsEvent
from schemas.capability import (
    BusinessContext,
    CapabilityContext,
    ExecutionContext,
    NewsEventSnapshot,
    RuntimeContext,
    WorkflowExecutionStateSnapshot,
)
from schemas.workflow import WorkflowExecutionState, WorkflowStepDefinition
from capabilities.capability_mapping import resolve_ai_capability
from capabilities.errors import (
    CapabilityConfigurationError,
    CapabilityTimeoutError,
    PermanentCapabilityError,
    RetryableCapabilityError,
    UnknownCapabilityError,
    ValidationCapabilityError,
)
from capabilities.registry import CapabilityRegistry
from services.editorial_scoring import apply_editorial_scoring_v2
from services.fact_safety import apply_fact_safety
from workflows.errors import PermanentStepFailureError, StepExecutionError, TaskNotFoundError

logger = logging.getLogger(__name__)


class CapabilityExecutor:
    """Implements workflows.runner.StepExecutor by dispatching to a registered
    Capability. The only bridge between StepExecutor and the Capability
    Framework - never called directly by a Capability, never calling one
    Capability from another (P4)."""

    def __init__(self, session: AsyncSession, task_id: UUID, registry: CapabilityRegistry) -> None:
        self._session = session
        self._task_id = task_id
        self._registry = registry
        self._attempts: dict[str, int] = {}

    async def execute(self, step: WorkflowStepDefinition) -> dict[str, Any]:
        """Run one Workflow step's capability once and return its structured output.

        Raises StepExecutionError for a retryable failure, PermanentStepFailureError
        for one that must not be retried - never a bare CapabilityError, and
        never persists an AIExecution row (Amendment B, §16).
        """
        attempt = self._attempts.get(step.name, 0) + 1
        self._attempts[step.name] = attempt

        task = await self._session.get(EditorialTask, self._task_id)
        if task is None:
            raise TaskNotFoundError(f"No EditorialTask with id {self._task_id}")
        news_event = await self._session.get(NewsEvent, task.event_id)
        if news_event is None:
            raise PermanentStepFailureError(f"No NewsEvent with id {task.event_id} for task {task.id}")

        # Amendment A (§15): resolve the capability-name -> AICapability mapping
        # through the single centralized table. Not used for persistence here
        # (Phase 6 writes nothing) - validated eagerly so an unmapped capability
        # name fails fast as a configuration error, not silently.
        try:
            resolve_ai_capability(step.capability)
        except CapabilityConfigurationError as error:
            raise PermanentStepFailureError(str(error)) from error

        try:
            _definition, capability = self._registry.resolve(step.capability)
        except UnknownCapabilityError as error:
            raise PermanentStepFailureError(
                f"Cannot resolve capability '{step.capability}': {error}"
            ) from error

        context = self._build_context(task, news_event, step, attempt)

        try:
            result = await capability.execute(context)
        except RetryableCapabilityError as error:
            raise StepExecutionError(str(error)) from error
        except CapabilityTimeoutError as error:
            raise StepExecutionError(str(error)) from error
        except (PermanentCapabilityError, ValidationCapabilityError, CapabilityConfigurationError) as error:
            raise PermanentStepFailureError(str(error)) from error

        if result.status != "SUCCESS":
            raise PermanentStepFailureError(
                f"Capability '{step.capability}' returned status={result.status} "
                "without raising a CapabilityError - contract violation."
            )

        structured_output = result.structured_output or {}

        # Phase 15 M4: deterministic Editorial Score V2 post-processing, only for the "scoring"
        # step, only after its own LLM call already succeeded above - see
        # services/editorial_scoring.py's own docstring for why this is the correct seam (it is
        # a no-op, zero-DB-query passthrough unless editorial_scoring_version == "v2").
        if step.capability == "scoring":
            structured_output = await apply_editorial_scoring_v2(
                self._session, news_event, structured_output, task_id=self._task_id
            )

        # Phase 15 M5: deterministic Fact Safety post-processing, only for the "quality" step -
        # the same architectural seam M4 already proved out for "scoring". Zero new DB queries:
        # `news_event` is already loaded above, and Research's completed step_results are already
        # present on `context.business.workflow_state.step_results` (see services/
        # fact_safety.py's own docstring for why this is the safest available boundary). A
        # no-op, zero-processing passthrough unless fact_safety_mode != "off".
        if step.capability == "quality":
            research_output = context.business.workflow_state.step_results.get("research", {})
            copywriting_output = context.business.workflow_state.step_results.get("copywriting", {})
            structured_output = apply_fact_safety(
                news_event.title, news_event.content, news_event.url,
                research_output, copywriting_output, structured_output,
            )

        return structured_output

    def _build_context(
        self, task: EditorialTask, news_event: NewsEvent, step: WorkflowStepDefinition, attempt: int
    ) -> CapabilityContext:
        state = WorkflowExecutionState.model_validate(task.workflow)

        news_event_snapshot = NewsEventSnapshot(
            id=news_event.id,
            title=news_event.title,
            summary=news_event.summary,
            content=news_event.content,
            url=news_event.url,
            category=news_event.category.value,
            published_at=news_event.published_at,
        )
        workflow_state_snapshot = WorkflowExecutionStateSnapshot(
            workflow_name=state.workflow_name.value,
            workflow_version=state.workflow_version,
            completed_steps=list(state.completed_steps),
            step_results={
                r.step_name: r.result
                for r in state.step_results
                if r.status == "SUCCESS" and r.result is not None
            },
        )

        return CapabilityContext(
            business=BusinessContext(
                news_event=news_event_snapshot,
                workflow_state=workflow_state_snapshot,
                # Explicit injection (docs/content_generation_language_final_implementation_plan.md)
                # - never left to BusinessContext.language's own implicit schema default.
                language=settings.default_content_language,
            ),
            runtime=RuntimeContext(
                task_id=task.id,
                event_id=task.event_id,
                capability_name=step.capability,
                priority=task.priority,
                attempt=attempt,
                iteration_count=state.iteration_count,
            ),
            execution=ExecutionContext(),
        )
