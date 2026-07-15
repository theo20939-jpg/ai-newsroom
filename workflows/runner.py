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

Two independent timeout boundaries are enforced:
- WorkflowStepDefinition.timeout_seconds wraps each individual
  StepExecutor.execute() call. A step that exceeds it raises StepTimeoutError,
  which is treated exactly like a retryable StepExecutionError.
- WorkflowDefinition.timeout_seconds wraps the entire remaining step loop for
  this run() call. Exceeding it always fails the task via WorkflowTimeoutError
  - never retried, never confused with a single step's own timeout, because
  every step-level TimeoutError is converted to StepTimeoutError and fully
  handled inside _run_step() before it could ever reach the outer wrapper;
  the outer wrapper's TimeoutError can therefore only ever mean the whole-run
  budget was exceeded.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.editorial_task import EditorialTask, TaskStatus
from schemas.workflow import (
    WorkflowDefinition,
    WorkflowExecutionState,
    WorkflowRunResult,
    WorkflowStepDefinition,
    WorkflowStepResult,
)
from workflows.errors import (
    PermanentStepFailureError,
    StepExecutionError,
    StepTimeoutError,
    TaskAlreadyCompletedError,
    TaskAlreadyRunningError,
    TaskNotFoundError,
    WorkflowTimeoutError,
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
        PermanentStepFailureError for one that must not be retried. A step
        that runs past WorkflowStepDefinition.timeout_seconds is cancelled by
        the Runner itself - implementations don't need to enforce their own
        timeout.
        """
        ...


class DeterministicPlaceholderExecutor:
    """Phase 5's only StepExecutor: synchronous, deterministic, always succeeds
    with an empty result. Tests inject their own StepExecutor to exercise
    retry/failure/timeout paths."""

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
        for misuse. Step-, iteration-, and timeout-level failures are not
        raised - they are persisted as a FAILED task and returned as a
        WorkflowRunResult, so a task is never left RUNNING because of them.
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
                session, task, state, list(state.step_results), "MaxIterationsExceededError",
                "max_iterations_exceeded",
            )

        try:
            return await asyncio.wait_for(
                self._execute_steps(session, task, state, definition), timeout=definition.timeout_seconds
            )
        except TimeoutError:
            logger.error(
                "Workflow %s exceeded its overall timeout of %ds for task %s",
                state.workflow_name.value, definition.timeout_seconds, task_id,
            )
            return await self._fail(
                session, task, state, list(state.step_results), WorkflowTimeoutError.__name__,
                f"workflow exceeded its overall timeout of {definition.timeout_seconds}s",
            )

    async def _execute_steps(
        self,
        session: AsyncSession,
        task: EditorialTask,
        state: WorkflowExecutionState,
        definition: WorkflowDefinition,
    ) -> WorkflowRunResult:
        """Run every remaining step to completion, or fail the task. Wrapped by
        run()'s outer asyncio.wait_for, which enforces the whole-workflow timeout."""
        step_results: list[WorkflowStepResult] = list(state.step_results)
        remaining_steps = [s for s in definition.steps if s.name not in state.completed_steps]

        for step in remaining_steps:
            state.current_step = step.name
            outcome = await self._run_step(task, state.workflow_name.value, step, step_results)

            if outcome == "FAILED":
                if step.required:
                    logger.error(
                        "Workflow %s: required step %s failed for task %s",
                        state.workflow_name.value, step.name, task.id,
                    )
                    return await self._fail(
                        session, task, state, step_results, "StepFailed",
                        f"step '{step.name}' did not succeed within {step.max_attempts} attempt(s)",
                    )
                logger.warning(
                    "Workflow %s: optional step %s failed for task %s, skipping",
                    state.workflow_name.value, step.name, task.id,
                )
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

        logger.info(
            "Workflow %s completed for task %s (iterations_used=%d)",
            state.workflow_name.value, task.id, state.iteration_count,
        )
        return WorkflowRunResult(
            task_id=task.id, status="COMPLETED", iterations_used=state.iteration_count, step_results=step_results
        )

    async def _run_step(
        self,
        task: EditorialTask,
        workflow_name: str,
        step: WorkflowStepDefinition,
        step_results: list[WorkflowStepResult],
    ) -> str:
        """Attempt one step up to its max_attempts. Returns "SUCCESS" or "FAILED".

        A per-attempt timeout (StepTimeoutError) is treated exactly like a
        retryable StepExecutionError - retried up to max_attempts, never
        raised past this method. Increments task.retry_count once per attempt
        beyond the first - never touches iteration_count, which belongs to
        the caller.
        """
        for attempt in range(1, step.max_attempts + 1):
            if attempt > 1:
                task.retry_count += 1

            started_at = datetime.now(timezone.utc)
            try:
                try:
                    result = await asyncio.wait_for(self._executor.execute(step), timeout=step.timeout_seconds)
                except TimeoutError as timeout_error:
                    raise StepTimeoutError(
                        f"step '{step.name}' (task={task.id}, workflow={workflow_name}) "
                        f"exceeded its timeout of {step.timeout_seconds}s"
                    ) from timeout_error
            except PermanentStepFailureError as error:
                step_results.append(
                    WorkflowStepResult(
                        step_name=step.name, status="FAILED", attempt=attempt,
                        started_at=started_at, finished_at=datetime.now(timezone.utc), error=str(error),
                    )
                )
                return "FAILED"
            except (StepExecutionError, StepTimeoutError) as error:
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
        """Persist a FAILED task with a JSON-serializable failure record.

        Always transitions RUNNING -> FAILED here, so no caller path can leave
        a task RUNNING - including the whole-workflow timeout branch in run().
        """
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
