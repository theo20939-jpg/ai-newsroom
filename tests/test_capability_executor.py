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
from schemas.capability import CapabilityCall, CapabilityResult, CapabilityUsage
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
from capabilities.research_capability import CAPABILITY_NAME as RESEARCH_CAPABILITY_NAME
from capabilities.research_capability import ResearchCapability
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.protocol import RenderedPrompt
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
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository
from tests.fakes.research_output import CANONICAL_RESEARCH_OUTPUT
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


class _SpyCapability:
    """Phase 23.1P test helper - captures the CapabilityContext it receives so a test can inspect
    fields (`quote_source_text`) that never appear in the structured_output itself."""

    def __init__(self) -> None:
        self.received_context: object = None

    async def execute(self, context):  # noqa: ANN001 - test spy, matches Capability protocol duck-typing
        self.received_context = context
        now = datetime.now(timezone.utc)
        return CapabilityResult(
            status="SUCCESS", structured_output={"ok": True}, calls=[],
            started_at=now, finished_at=now, duration_seconds=0.0,
        )


@pytest.mark.asyncio
async def test_quote_source_text_populated_from_full_text_acquisition_for_copywriting_step(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 23.1P (docs/phase23_1p_story_memory_quotes_gate_report.md): the real executor wiring
    - a FULL_TEXT NewsEventArticleAcquisition row must populate BusinessContext.quote_source_text
    for the "copywriting" step specifically, cleaned via the already-existing
    services/article_cleaning.py, when article_acquisition_mode != "off"."""
    from database.models.news_event_article_acquisition import NewsEventArticleAcquisition

    monkeypatch.setattr(settings, "article_acquisition_mode", "shadow")
    db_session.add(NewsEventArticleAcquisition(
        news_event_id=real_news_event.id, acquisition_status="FULL_TEXT",
        effective_completeness_status="FULL_TEXT",
        raw_extracted_text="A spokesperson said: \"This is the real, richer quote from the full article.\"",
        extracted_char_count=80, triggered_by="test",
    ))
    await db_session.flush()

    workflow_registry = _single_step_workflow_registry("copywriting")
    task = await _created_task(db_session, real_news_event, workflow_registry)
    spy = _SpyCapability()
    capability_registry = _capability_registry("copywriting", spy)
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "COMPLETED"
    assert spy.received_context is not None
    assert "real, richer quote" in (spy.received_context.business.quote_source_text or "")


@pytest.mark.asyncio
async def test_quote_source_text_stays_none_when_acquisition_mode_off(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """article_acquisition_mode == "off" (a real, valid production configuration) must never
    attempt the acquisition read at all - byte-identical to pre-23.1P behavior."""
    monkeypatch.setattr(settings, "article_acquisition_mode", "off")
    workflow_registry = _single_step_workflow_registry("copywriting")
    task = await _created_task(db_session, real_news_event, workflow_registry)
    spy = _SpyCapability()
    capability_registry = _capability_registry("copywriting", spy)
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert spy.received_context.business.quote_source_text is None


@pytest.mark.asyncio
async def test_quote_source_text_not_populated_for_non_copywriting_steps(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scoped to "copywriting" only - a "research" step must never receive quote_source_text, even
    with a real FULL_TEXT acquisition present (Research's own article_evidence_text/enforce gate,
    completely untouched by this phase, is a separate mechanism)."""
    from database.models.news_event_article_acquisition import NewsEventArticleAcquisition

    monkeypatch.setattr(settings, "article_acquisition_mode", "shadow")
    db_session.add(NewsEventArticleAcquisition(
        news_event_id=real_news_event.id, acquisition_status="FULL_TEXT",
        effective_completeness_status="FULL_TEXT",
        raw_extracted_text="A spokesperson said something quotable here.",
        extracted_char_count=44, triggered_by="test",
    ))
    await db_session.flush()

    workflow_registry = _single_step_workflow_registry("research")
    task = await _created_task(db_session, real_news_event, workflow_registry)
    spy = _SpyCapability()
    capability_registry = _capability_registry("research", spy)
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert spy.received_context.business.quote_source_text is None


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


_RESEARCH_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {"type": "array"},
        "confidence": {"type": "number"},
        "gaps": {"type": "array"},
    },
    "required": ["facts", "confidence", "gaps"],
}


def _research_prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(
            name=RESEARCH_CAPABILITY_NAME, version="2",
            system="You are a fake research assistant for tests.", rules=["Do not invent facts."],
            output_schema=_RESEARCH_OUTPUT_SCHEMA,
        )
    )
    return repository


@pytest.mark.asyncio
async def test_real_research_capability_truncation_is_retried_then_succeeds(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    """End-to-end regression for the production truncation fix (333/333 failed NEWS_ANALYSIS
    Research tasks, finish_reason='length'): the REAL ResearchCapability - not a fake - raising
    RetryableCapabilityError for a truncated response must be retried by CapabilityExecutor's
    existing, unmodified StepExecutionError mapping and WorkflowRunner's existing, unmodified
    per-step retry loop, exactly like any other transient failure, and succeed once a subsequent
    attempt returns a complete response."""
    workflow_registry = _single_step_workflow_registry("research", max_attempts=2)
    task = await _created_task(db_session, real_news_event, workflow_registry)
    gateway = FakeLLMGateway(
        generate_responses=[
            GenerateResponse(
                text=None, structured_output=None, finish_reason="length",
                model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=520, output_tokens=450),
            ),
            GenerateResponse(
                text=None, structured_output=CANONICAL_RESEARCH_OUTPUT, finish_reason="stop",
                model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=520, output_tokens=210),
            ),
        ]
    )
    real_research_capability = ResearchCapability(gateway, _research_prompt_repository())
    capability_registry = _capability_registry("research", real_research_capability)
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "COMPLETED"
    assert result.step_results[0].status == "FAILED"  # truncated attempt, retried (not permanent)
    assert result.step_results[1].status == "SUCCESS"  # retry succeeded
    assert result.step_results[1].result == CANONICAL_RESEARCH_OUTPUT
    persisted = await workflow_service.get_task(db_session, task.id)
    assert persisted.retry_count == 1
    assert persisted.status == TaskStatus.COMPLETED


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
    """A real CapabilityResult produced through the executor's full path maps cleanly through
    AIExecutionMapper. API cost optimization reversed Amendment B's "never writes" rule, but
    only when `cost_tracker`/`pricing_catalog` are explicitly supplied (tests/
    test_cost_recording_integration.py covers that opt-in path) - the constructor call here
    omits both, so zero rows are still written, exactly as before."""
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


@pytest.mark.parametrize(
    ("capability_name", "expected_max_tokens", "expected_reasoning_effort"),
    [
        ("research", 1000, "none"),
        ("intelligence", 500, "low"),
        ("engagement", 350, "low"),
        ("scoring", 250, "low"),
        ("copywriting", 600, "low"),
        ("quality", 400, "low"),
    ],
)
def test_build_context_sets_capability_specific_token_limit_and_reasoning_effort(
    capability_name: str, expected_max_tokens: int, expected_reasoning_effort: str
) -> None:
    """API cost optimization (docs/api_cost_optimization_report.md): centralized, per-capability
    output-token ceiling and reasoning effort, set once in _build_context() - every capability
    file already reads context.execution.max_tokens/reasoning_effort generically."""
    task = EditorialTask(
        id=uuid4(),
        event_id=uuid4(),
        priority=TaskPriority.B,
        status=TaskStatus.RUNNING,
        workflow={"workflow_name": "CONTENT_GENERATION", "workflow_version": 1, "current_step": capability_name},
    )
    news_event = NewsEvent(
        id=task.event_id, source_id=uuid4(), title="Headline", summary=None, content="Body",
        url=None, category=EventCategory.AI, published_at=None,
    )
    step = WorkflowStepDefinition(name=capability_name, capability=capability_name, timeout_seconds=30)
    capability_executor = CapabilityExecutor(session=None, task_id=task.id, registry=None)  # type: ignore[arg-type]

    context = capability_executor._build_context(task, news_event, step, attempt=1)

    assert context.execution.max_tokens == expected_max_tokens
    assert context.execution.reasoning_effort == expected_reasoning_effort
