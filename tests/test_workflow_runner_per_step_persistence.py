"""Tests for Phase 9.5 M1: WorkflowRunner._execute_steps()'s per-step persistence invariant
(docs/phase9_5_workflow_hardening_architecture_contract.md §3-§4).

Runner-level tests, deliberately independent of the Capability framework: test-local
`StepExecutor` implementations (mirroring tests/test_workflow_runner.py's own established
pattern) prove the persistence mechanism directly, including a test-local executor that reads
`task.workflow` itself exactly as `capabilities/executor.py::CapabilityExecutor._build_context()`
does (line 114) - proving the *runner's* new invariant without needing the full Capability/
Gateway stack (that composed proof lives in tests/test_phase9_research_intelligence_integration.py).

Real Postgres via the standard `db_session` fixture (`expire_on_commit=False`) - sufficient for
every test here, since none requires genuine cross-connection visibility (that proof is Phase
9.5 M2's own, separate job, per the Contract's §12 item 2 and §14 rule 10).
"""
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import NewsEvent
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import (
    WorkflowDefinition,
    WorkflowExecutionState,
    WorkflowRetryPolicy,
    WorkflowStepDefinition,
    WorkflowType,
)
from services import workflow_service
from workflows.errors import PermanentStepFailureError, StepExecutionError
from workflows.registry import WorkflowRegistry
from workflows.runner import WorkflowRunner


class _AlwaysSucceeds:
    async def execute(self, step: WorkflowStepDefinition) -> dict[str, Any]:
        return {"step": step.name}


class _SucceedsThenFailsPermanently:
    """step_one always succeeds; step_two always fails permanently - proving §8's interaction
    (a required step's failure after an earlier step's own per-step commit already occurred)."""

    async def execute(self, step: WorkflowStepDefinition) -> dict[str, Any]:
        if step.name == "step_one":
            return {"step": step.name}
        raise PermanentStepFailureError("step_two always fails")


class _FirstStepFailsOnceThenBothSucceed:
    """step_one fails its first attempt (retryable), succeeds its second; step_two always
    succeeds - proving §6's retry-count preservation under the new per-step commit cadence."""

    def __init__(self) -> None:
        self._step_one_attempts = 0

    async def execute(self, step: WorkflowStepDefinition) -> dict[str, Any]:
        if step.name == "step_one":
            self._step_one_attempts += 1
            if self._step_one_attempts == 1:
                raise StepExecutionError("transient failure on first attempt")
        return {"step": step.name}


class _ReadsStepResultsExecutor:
    """Test-local StepExecutor that independently re-fetches `task.workflow` and parses
    `step_results` itself, exactly mirroring `capabilities/executor.py::CapabilityExecutor.
    _build_context()`'s own read (line 114, unmodified by this milestone) - proving the
    runner-level mechanism directly, decoupled from the Capability framework. Records what it
    observed for each step, in call order."""

    def __init__(self, session: AsyncSession, task_id: UUID) -> None:
        self._session = session
        self._task_id = task_id
        self.observed_step_results: list[dict[str, dict[str, Any]]] = []

    async def execute(self, step: WorkflowStepDefinition) -> dict[str, Any]:
        task = await self._session.get(EditorialTask, self._task_id)
        assert task is not None
        state = WorkflowExecutionState.model_validate(task.workflow)
        self.observed_step_results.append(
            {r.step_name: r.result for r in state.step_results if r.status == "SUCCESS" and r.result is not None}
        )
        return {"step": step.name}


def _command(event_id: UUID) -> EditorialTaskCreate:
    return EditorialTaskCreate(event_id=event_id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B)


def _two_step_registry(max_attempts: int = 1) -> WorkflowRegistry:
    """A throwaway registry, mirroring tests/test_workflow_runner.py's own
    `_single_step_registry` precedent - reuses CONTENT_GENERATION locally, never touching the
    real, globally-registered definition."""
    registry = WorkflowRegistry()
    registry.register(
        WorkflowDefinition(
            name=WorkflowType.CONTENT_GENERATION,
            version=1,
            steps=[
                WorkflowStepDefinition(name="step_one", capability="research", max_attempts=max_attempts, timeout_seconds=10),
                WorkflowStepDefinition(name="step_two", capability="research", max_attempts=max_attempts, timeout_seconds=10),
            ],
            max_iterations=3,
            retry_policy=WorkflowRetryPolicy(max_attempts=max_attempts, retryable_error_types=["StepExecutionError"]),
            timeout_seconds=30,
            required_input=["event_id"],
            expected_output=["result"],
        )
    )
    registry.seal()
    return registry


def _one_step_registry() -> WorkflowRegistry:
    registry = WorkflowRegistry()
    registry.register(
        WorkflowDefinition(
            name=WorkflowType.CONTENT_GENERATION,
            version=1,
            steps=[WorkflowStepDefinition(name="only_step", capability="research", max_attempts=1, timeout_seconds=10)],
            max_iterations=3,
            retry_policy=WorkflowRetryPolicy(max_attempts=1, retryable_error_types=["StepExecutionError"]),
            timeout_seconds=30,
            required_input=["event_id"],
            expected_output=["result"],
        )
    )
    registry.seal()
    return registry


# ---------------------------------------------------------------------------
# 1. Same-pass propagation (Contract §12 item 1) - the direct, positive fix-confirmation, at
#    the runner level, independent of the Capability framework.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_pass_propagation_second_step_observes_first_steps_result(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    registry = _two_step_registry()
    task = await workflow_service.create_task(db_session, _command(real_news_event.id), registry=registry)
    executor = _ReadsStepResultsExecutor(db_session, task.id)

    result = await WorkflowRunner(executor=executor, registry=registry).run(db_session, task.id)

    assert result.status == "COMPLETED"
    assert len(executor.observed_step_results) == 2
    # step_one ran first: nothing before it yet.
    assert executor.observed_step_results[0] == {}
    # step_two ran second, within the same run() call: step_one's result IS visible - the
    # exact gap Phase 9.5 M1 closes.
    assert executor.observed_step_results[1] == {"step_one": {"step": "step_one"}}


# ---------------------------------------------------------------------------
# 2. Subsequent-step failure after a committed success (Contract §12 item 4, §8).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subsequent_step_failure_after_committed_success(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    registry = _two_step_registry()
    task = await workflow_service.create_task(db_session, _command(real_news_event.id), registry=registry)

    result = await WorkflowRunner(executor=_SucceedsThenFailsPermanently(), registry=registry).run(db_session, task.id)

    assert result.status == "FAILED"
    assert len(result.step_results) == 2
    assert result.step_results[0].step_name == "step_one"
    assert result.step_results[0].status == "SUCCESS"
    assert result.step_results[0].result == {"step": "step_one"}
    assert result.step_results[1].step_name == "step_two"
    assert result.step_results[1].status == "FAILED"

    persisted = await workflow_service.get_task(db_session, task.id)
    assert persisted.status == TaskStatus.FAILED

    # step_one's own per-step commit already durably recorded it as completed before step_two
    # ever ran - _fail()'s own commit (§8) re-persists this, bounded and self-consistent, never
    # losing it. step_two never reaches the completed_steps append (its failure exits first).
    raw_task = await db_session.get(EditorialTask, task.id)
    assert raw_task is not None
    assert raw_task.workflow is not None
    assert raw_task.workflow["completed_steps"] == ["step_one"]


# ---------------------------------------------------------------------------
# 3. Retry-count durability under the new per-step commit cadence (Contract §12 item 5, §6).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_count_durable_after_per_step_commit(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    registry = _two_step_registry(max_attempts=2)
    task = await workflow_service.create_task(db_session, _command(real_news_event.id), registry=registry)

    result = await WorkflowRunner(executor=_FirstStepFailsOnceThenBothSucceed(), registry=registry).run(
        db_session, task.id
    )

    assert result.status == "COMPLETED"
    persisted = await workflow_service.get_task(db_session, task.id)
    assert persisted.status == TaskStatus.COMPLETED
    assert persisted.retry_count == 1  # exactly one retry (step_one's first attempt), preserved


# ---------------------------------------------------------------------------
# 4. One-step workflow's bounded double-commit is correct (Contract §12 item 6, §10).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_step_workflow_reaches_completed_despite_bounded_double_commit(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    registry = _one_step_registry()
    task = await workflow_service.create_task(db_session, _command(real_news_event.id), registry=registry)

    result = await WorkflowRunner(executor=_AlwaysSucceeds(), registry=registry).run(db_session, task.id)

    assert result.status == "COMPLETED"
    assert len(result.step_results) == 1
    assert result.step_results[0].status == "SUCCESS"
    assert result.step_results[0].result == {"step": "only_step"}

    persisted = await workflow_service.get_task(db_session, task.id)
    assert persisted.status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# 5. Commit-failure propagation (Contract §12 item 3, §7) - targets the new per-step commit
#    specifically, distinct from run()'s own RUNNING-transition commit and any terminal commit.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_step_commit_failure_propagates_uncaught(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    registry = _two_step_registry()
    task = await workflow_service.create_task(db_session, _command(real_news_event.id), registry=registry)

    original_commit = db_session.commit
    call_count = 0

    async def _flaky_commit() -> None:
        nonlocal call_count
        call_count += 1
        # Call #1 is run()'s own RUNNING-transition commit (workflows/runner.py:123) - let it
        # succeed. Call #2 is step_one's new per-step commit (this milestone's own insertion) -
        # fail exactly there.
        if call_count == 2:
            raise RuntimeError("simulated per-step commit failure")
        await original_commit()

    db_session.commit = _flaky_commit  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="simulated per-step commit failure"):
        await WorkflowRunner(executor=_AlwaysSucceeds(), registry=registry).run(db_session, task.id)

    assert call_count == 2  # never reached step_two's or any terminal commit attempt
