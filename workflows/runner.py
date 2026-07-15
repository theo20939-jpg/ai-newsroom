"""WorkflowRunner: executes an EditorialTask's registered WorkflowDefinition.

WorkflowRunner has zero knowledge of any concrete Capability. It interacts
with steps exclusively through the StepExecutor protocol below - there is no
`if step.capability == "..."` or `match capability: case ...` branching
anywhere in this module. Phase 5 ships exactly one StepExecutor
implementation (DeterministicPlaceholderExecutor): synchronous, deterministic,
no AI, no network call.

Iteration and retry are fully independent, per docs/phase5_workflow_engine_planning.md:
- an "iteration" is one complete pass through every step of the definition,
  counted only when that full pass finishes (successfully, or by exhausting
  the iteration budget before starting one) - iteration_count never counts
  a single step's retries.
- a "retry" is a repeated attempt at exactly one step, bounded by that step's
  own max_attempts, and reflected only in EditorialTask.retry_count - it
  never advances iteration_count.
A step's retryable failure that exhausts its own max_attempts fails the task
immediately; it does not consume another iteration or restart the pipeline.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.editorial_task import EditorialTask, TaskStatus
from schemas.workflow import WorkflowExecutionState, WorkflowRunResult, WorkflowStepDefinition, WorkflowStepResult
from workflows.errors import (
    MaxIterationsExceededError,
    PermanentStepFailureError,
    StepExecutionError,
    TaskAlreadyCompletedError,
    TaskAlreadyRunningError,
    TaskNotFoundError,
)
from workflows.registry import WorkflowRegistry
from workflows.registry import registry as default_registry

logger = logging.getLogger(__name__)


class StepExecutor(Protocol):
    """The seam future Capability implementations plug into.

    Phase 5 defines no Capability implementation here - only this contract
    and one deterministic placeholder below.
    """

    async def execute(self, step: WorkflowStepDefinition) -> dict[str, Any]:
        """Execute one step and return its JSON-serializable result.

        Raise StepExecutionError for a retryable failure, or
        PermanentStepFailureError for one that must not be retried.
        """
        ...


class DeterministicPlaceholderExecutor:
    """Phase 5's only StepExecutor: synchronous, deterministic, always succeeds
    with an empty result. Tests inject their own StepExecutor to exercise
    retry/failure paths."""

    async def execute(self, step: WorkflowStepDefinition) -> dict[str, Any]:
        return {}


class WorkflowRunner:
    """Runs one EditorialTask's workflow to completion or failure.

    Only WorkflowRunner ever changes an EditorialTask's status -
    services.workflow_service never does.
    """

    def __init__(self, executor: StepExecutor, registry: WorkflowRegistry = default_registry) -> None:
        self._executor = executor
        self._registry = registry

    async def run(self, session: AsyncSession, task_id: UUID) -> WorkflowRunResult:
        """Advance one EditorialTask through its workflow.

        Raises TaskNotFoundError / TaskAlreadyRunningError / TaskAlreadyCompletedError
        for misuse. Step- and iteration-level failures are not raised - they
        are persisted as a FAILED task and returned as a WorkflowRunResult.
        """
        task = await session.get(EditorialTask, task_id)
        if task is None:
            raise TaskNotFoundError(f"No EditorialTask with id {task_id}")
        if task.status == TaskStatus.RUNNING:
            raise TaskAlreadyRunningError(f"EditorialTask {task_id} is already RUNNING")
        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            raise TaskAlreadyCompletedError(f"EditorialTask {task_id} is already {task.status.value}")

        state = WorkflowExecutionState.model_validate(task.workflow)
        definition = self._registry.resolve(state.workflow_name)

        task.status = TaskStatus.RUNNING
        await session.commit()

        logger.info("Workflow %s starting for task %s", state.workflow_name.value, task_id)

        if state.iteration_count >= definition.max_iterations:
            return await self._fail(
                session, task, state, list(state.step_results), MaxIterationsExceededError.__name__,
                "max_iterations_exceeded",
            )

        step_results: list[WorkflowStepResult] = list(state.step_results)
        remaining_steps = [s for s in definition.steps if s.name not in state.completed_steps]

        for step in remaining_steps:
            state.current_step = step.name
            outcome = await self._run_step(step, step_results, task)

            if outcome == "FAILED":
                if step.required:
                    logger.error("Workflow %s: required step %s failed for task %s", state.workflow_name.value, step.name, task_id)
                    return await self._fail(
                        session, task, state, step_results, "StepFailed",
                        f"step '{step.name}' did not succeed within {step.max_attempts} attempt(s)",
                    )
                logger.warning("Workflow %s: optional step %s failed for task %s, skipping", state.workflow_name.value, step.name, task_id)
                step_results.append(
                    WorkflowStepResult(
                        step_name=step.name,
                        status="SKIPPED",
                        attempt=step.max_attempts,
                        started_at=datetime.now(timezone.utc),
                        finished_at=datetime.now(timezone.utc),
                    )
                )

            state.completed_steps.append(step.name)

        state.iteration_count += 1
        state.current_step = None
        state.step_results = step_results
        state.failure = None
        task.status = TaskStatus.COMPLETED
        task.workflow = state.model_dump(mode="json")
        await session.commit()

        logger.info("Workflow %s completed for task %s (iterations_used=%d)", state.workflow_name.value, task_id, state.iteration_count)
        return WorkflowRunResult(
            task_id=task.id, status="COMPLETED", iterations_used=state.iteration_count, step_results=step_results
        )

    async def _run_step(
        self, step: WorkflowStepDefinition, step_results: list[WorkflowStepResult], task: EditorialTask
    ) -> str:
        """Attempt one step up to its max_attempts. Returns "SUCCESS" or "FAILED".

        Increments task.retry_count once per attempt beyond the first -
        never touches iteration_count, which belongs to the caller.
        """
        for attempt in range(1, step.max_attempts + 1):
            if attempt > 1:
                task.retry_count += 1

            started_at = datetime.now(timezone.utc)
            try:
                result = await self._executor.execute(step)
            except PermanentStepFailureError as error:
                step_results.append(
                    WorkflowStepResult(
                        step_name=step.name, status="FAILED", attempt=attempt,
                        started_at=started_at, finished_at=datetime.now(timezone.utc), error=str(error),
                    )
                )
                return "FAILED"
            except StepExecutionError as error:
                step_results.append(
                    WorkflowStepResult(
                        step_name=step.name, status="FAILED", attempt=attempt,
                        started_at=started_at, finished_at=datetime.now(timezone.utc), error=str(error),
                    )
                )
                if attempt == step.max_attempts:
                    return "FAILED"
                continue
            else:
                step_results.append(
                    WorkflowStepResult(
                        step_name=step.name, status="SUCCESS", attempt=attempt,
                        started_at=started_at, finished_at=datetime.now(timezone.utc), result=result,
                    )
                )
                return "SUCCESS"

        return "FAILED"

    @staticmethod
    async def _fail(
        session: AsyncSession,
        task: EditorialTask,
        state: WorkflowExecutionState,
        step_results: list[WorkflowStepResult],
        error_type: str,
        message: str,
    ) -> WorkflowRunResult:
        """Persist a FAILED task with a JSON-serializable failure record."""
        state.step_results = step_results
        state.failure = {
            "step": state.current_step,
            "error_type": error_type,
            "message": message,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        task.status = TaskStatus.FAILED
        task.workflow = state.model_dump(mode="json")
        await session.commit()
        return WorkflowRunResult(
            task_id=task.id, status="FAILED", iterations_used=state.iteration_count, step_results=step_results
        )
