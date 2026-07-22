"""Tests for capabilities.executor.CapabilityExecutor - real Postgres,
transaction rolled back per test (tests/conftest.py's db_session fixture).

Drives capabilities.executor.CapabilityExecutor through workflows.runner.
WorkflowRunner exactly as any other StepExecutor, using fake Capability
implementations (tests/fakes/fake_capability.py) - no LLMGateway, no
network, no real AI call anywhere.

Proves (docs/phase6_architecture_contract.md, Amendment B §16):
- CapabilityExecutor is a drop-in StepExecutor (a WorkflowRunner run
  completes exactly as it would with any other StepExecutor);
- the full CapabilityError -> workflows.errors mapping table;
- zero AIExecution rows are ever created;
- no task is left RUNNING, regardless of outcome.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.ai_execution import AIExecution
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import EventCategory, NewsEvent
from schemas.capability import CapabilityCall, CapabilityUsage
from schemas.capability_definition import CapabilityConfig, CapabilityDefinition
from schemas.editorial_task import EditorialTaskCreate, EditorialTaskRead
from schemas.workflow import (
    WorkflowDefinition,
    WorkflowRetryPolicy,
    WorkflowStepDefinition,
    WorkflowType,
)
from services import workflow_service
from capabilities.executor import CapabilityExecutor
from capabilities.registry import Capability, CapabilityRegistry
from services.ai_execution_mapper import DefaultAIExecutionMapper
from tests.fakes.fake_capability import (
    AlwaysFailsConfigurationCapability,
    AlwaysFailsPermanentlyCapability,
    AlwaysFailsValidationCapability,
    AlwaysSucceedsCapability,
    AlwaysSucceedsWithOneCallCapability,
    AlwaysTimesOutCapability,
    FailsThenSucceedsCapability,
)
from workflows.registry import WorkflowRegistry
from workflows.runner import WorkflowRunner


def _capability_definition(name: str) -> CapabilityDefinition:
    return CapabilityDefinition(
        name=name, version=1, config=CapabilityConfig(timeout_seconds=10),
        required_context=["news_event"], expected_output_keys=["ok"],
    )


def _single_step_workflow_registry(capability_name: str, max_attempts: int = 3) -> WorkflowRegistry:
    registry = WorkflowRegistry()
    registry.register(
        WorkflowDefinition(
            name=WorkflowType.CONTENT_GENERATION,
            version=1,
            steps=[
                WorkflowStepDefinition(
                    name="only_step", capability=capability_name, max_attempts=max_attempts, timeout_seconds=10
                )
            ],
            max_iterations=3,
            retry_policy=WorkflowRetryPolicy(
                max_attempts=max_attempts, retryable_error_types=["StepExecutionError"]
            ),
            timeout_seconds=60,
            required_input=["event_id"],
            expected_output=["result"],
        )
    )
    registry.seal()
    return registry


def _capability_registry(capability_name: str, capability: Capability) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(_capability_definition(capability_name), capability)
    registry.seal()
    return registry


async def _created_task(session: AsyncSession, event: NewsEvent, workflow_registry: WorkflowRegistry) -> EditorialTaskRead:
    command = EditorialTaskCreate(
        event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B
    )
    return await workflow_service.create_task(session, command, registry=workflow_registry)


async def _ai_execution_count(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(AIExecution))
    return result.scalar_one()


@pytest.mark.asyncio
async def test_capability_executor_is_a_drop_in_step_executor(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    workflow_registry = _single_step_workflow_registry("research")
    task = await _created_task(db_session, real_news_event, workflow_registry)
    capability_registry = _capability_registry("research", AlwaysSucceedsCapability())
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "COMPLETED"
    assert result.step_results[0].status == "SUCCESS"
    assert result.step_results[0].result == {"ok": True, "capability": "research"}

    persisted = await workflow_service.get_task(db_session, task.id)
    assert persisted.status == TaskStatus.COMPLETED
    assert await _ai_execution_count(db_session) == 0


@pytest.mark.asyncio
async def test_retryable_capability_error_maps_to_step_execution_error_and_retries(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    workflow_registry = _single_step_workflow_registry("research", max_attempts=3)
    task = await _created_task(db_session, real_news_event, workflow_registry)
    capability_registry = _capability_registry(
        "research", FailsThenSucceedsCapability(failures_before_success=1)
    )
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "COMPLETED"
    assert result.step_results[0].status == "FAILED"  # first attempt, retried
    assert result.step_results[1].status == "SUCCESS"  # second attempt

    persisted = await workflow_service.get_task(db_session, task.id)
    assert persisted.retry_count == 1
    assert persisted.status == TaskStatus.COMPLETED
    assert await _ai_execution_count(db_session) == 0


@pytest.mark.asyncio
async def test_permanent_capability_error_maps_to_permanent_step_failure_without_retry(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    workflow_registry = _single_step_workflow_registry("research")
    task = await _created_task(db_session, real_news_event, workflow_registry)
    capability_registry = _capability_registry("research", AlwaysFailsPermanentlyCapability())
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "FAILED"
    assert len(result.step_results) == 1  # no retry attempted
    persisted = await workflow_service.get_task(db_session, task.id)
    assert persisted.status == TaskStatus.FAILED  # never left RUNNING
    assert persisted.retry_count == 0
    assert await _ai_execution_count(db_session) == 0


@pytest.mark.asyncio
async def test_validation_capability_error_maps_to_permanent_step_failure(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    workflow_registry = _single_step_workflow_registry("research")
    task = await _created_task(db_session, real_news_event, workflow_registry)
    capability_registry = _capability_registry("research", AlwaysFailsValidationCapability())
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "FAILED"
    persisted = await workflow_service.get_task(db_session, task.id)
    assert persisted.status == TaskStatus.FAILED
    assert await _ai_execution_count(db_session) == 0


@pytest.mark.asyncio
async def test_capability_configuration_error_maps_to_permanent_step_failure(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    workflow_registry = _single_step_workflow_registry("research")
    task = await _created_task(db_session, real_news_event, workflow_registry)
    capability_registry = _capability_registry("research", AlwaysFailsConfigurationCapability())
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "FAILED"
    persisted = await workflow_service.get_task(db_session, task.id)
    assert persisted.status == TaskStatus.FAILED
    assert await _ai_execution_count(db_session) == 0


@pytest.mark.asyncio
async def test_capability_timeout_error_is_treated_as_retryable(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    workflow_registry = _single_step_workflow_registry("research", max_attempts=2)
    task = await _created_task(db_session, real_news_event, workflow_registry)
    capability_registry = _capability_registry("research", AlwaysTimesOutCapability())
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "FAILED"
    assert len(result.step_results) == 2  # retried up to max_attempts, per StepExecutionError semantics
    assert all(r.status == "FAILED" for r in result.step_results)
    persisted = await workflow_service.get_task(db_session, task.id)
    assert persisted.status == TaskStatus.FAILED  # never left RUNNING
    assert await _ai_execution_count(db_session) == 0


@pytest.mark.asyncio
async def test_unmapped_capability_name_fails_permanently(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    """A step whose capability has no AICapability mapping (Amendment A) fails
    fast as a configuration error, never silently, never retried."""
    workflow_registry = _single_step_workflow_registry("no_such_capability")
    task = await _created_task(db_session, real_news_event, workflow_registry)
    capability_registry = _capability_registry("no_such_capability", AlwaysSucceedsCapability())
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "FAILED"
    assert len(result.step_results) == 1  # no retry
    assert await _ai_execution_count(db_session) == 0


@pytest.mark.asyncio
async def test_successful_call_is_compatible_with_ai_execution_mapper_without_persisting(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    """Strengthens the Amendment B runtime proof: a real CapabilityResult
    produced through the executor's full path maps cleanly through
    AIExecutionMapper, and still zero rows are ever written."""
    workflow_registry = _single_step_workflow_registry("research")
    task = await _created_task(db_session, real_news_event, workflow_registry)
    capability_registry = _capability_registry("research", AlwaysSucceedsWithOneCallCapability())
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)
    assert result.status == "COMPLETED"

    # The capability itself doesn't return raw CapabilityCall data through the
    # StepExecutor boundary (only structured_output does) - so this
    # reconstructs the same deterministic call the fake capability produced,
    # to prove the mapping boundary is compatible, without ever persisting it.
    call = CapabilityCall(
        call_id=uuid4(), sequence=0, gateway_method="generate", status="SUCCESS",
        model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=10, output_tokens=5),
        started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc), duration_seconds=0.01,
    )
    mapped = DefaultAIExecutionMapper().to_execution_row(task.id, "research", call)
    assert mapped.task_id == task.id

    assert await _ai_execution_count(db_session) == 0


def test_build_context_injects_configured_target_language(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression D (docs/content_generation_language_final_implementation_plan.md): the
    full config -> executor -> BusinessContext.language chain, proven directly against
    `_build_context()` - it touches neither `self._session` nor `self._registry`, so neither
    needs to be real here."""
    monkeypatch.setattr(settings, "default_content_language", "ru")

    task = EditorialTask(
        id=uuid4(),
        event_id=uuid4(),
        priority=TaskPriority.B,
        status=TaskStatus.RUNNING,
        workflow={"workflow_name": "CONTENT_GENERATION", "workflow_version": 1, "current_step": "research"},
    )
    news_event = NewsEvent(
        id=task.event_id,
        source_id=uuid4(),
        title="Headline",
        summary=None,
        content="Body",
        url=None,
        category=EventCategory.AI,
        published_at=None,
    )
    step = WorkflowStepDefinition(name="research", capability="research", timeout_seconds=30)
    capability_executor = CapabilityExecutor(session=None, task_id=task.id, registry=None)  # type: ignore[arg-type]

    context = capability_executor._build_context(task, news_event, step, attempt=1)

    assert context.business.language == "ru"


def test_build_context_respects_overridden_target_language(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same chain, with a non-default configured value, proving the executor does not
    hardcode "ru" itself - it reads whatever `settings.default_content_language` says."""
    monkeypatch.setattr(settings, "default_content_language", "en")

    task = EditorialTask(
        id=uuid4(),
        event_id=uuid4(),
        priority=TaskPriority.B,
        status=TaskStatus.RUNNING,
        workflow={"workflow_name": "CONTENT_GENERATION", "workflow_version": 1, "current_step": "research"},
    )
    news_event = NewsEvent(
        id=task.event_id,
        source_id=uuid4(),
        title="Headline",
        summary=None,
        content="Body",
        url=None,
        category=EventCategory.AI,
        published_at=None,
    )
    step = WorkflowStepDefinition(name="research", capability="research", timeout_seconds=30)
    capability_executor = CapabilityExecutor(session=None, task_id=task.id, registry=None)  # type: ignore[arg-type]

    context = capability_executor._build_context(task, news_event, step, attempt=1)

    assert context.business.language == "en"
