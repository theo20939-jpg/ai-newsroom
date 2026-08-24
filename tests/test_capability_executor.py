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


# ---------------------------------------------------------------------------
# NINJA PULSE RECAP Phase R2 integration, Phase B.1 - the EVENT_RECAP-only branch in
# CapabilityExecutor.execute() (mirrors the TELEGRAPH_ARTICLE branch above it exactly): resolves
# a Story via NewsEventStoryLink, calls the existing, unmodified services.event_recap.
# build_event_recap_candidate(session, story, force_shadow=True), and threads the existing,
# unmodified render_event_recap_bundle_text()'s output into context.business.
# event_recap_evidence_text. The candidate-building/rendering functions themselves are
# monkeypatched (never a hand-rolled EventRecapCandidate/announcement fixture) - this section
# proves the EXECUTOR's own plumbing (branch condition, Story resolution, force_shadow=True,
# error mapping, context threading), not services/event_recap.py's own synthesis/clustering
# behavior (tests/test_event_recap.py already covers that exhaustively).
# ---------------------------------------------------------------------------

_PHASE_B1_FAKE_EVIDENCE_TEXT = "Story: Fake Recap Story\n\nANNOUNCEMENT CONTEXT:\n\n- [ORIGIN]\nFake headline"


def _event_recap_workflow_registry() -> WorkflowRegistry:
    registry = WorkflowRegistry()
    registry.register(
        WorkflowDefinition(
            name=WorkflowType.EVENT_RECAP,
            version=1,
            steps=[
                WorkflowStepDefinition(
                    name="synthesize_recap", capability="event_recap", max_attempts=1, timeout_seconds=10,
                )
            ],
            max_iterations=1,
            retry_policy=WorkflowRetryPolicy(max_attempts=1, retryable_error_types=["StepExecutionError"]),
            timeout_seconds=60,
            required_input=["event_id"],
            expected_output=["recap_title", "recap_summary", "key_takeaways", "uncertainty_notes"],
        )
    )
    registry.seal()
    return registry


async def _created_event_recap_task(
    session: AsyncSession, event: NewsEvent, workflow_registry: WorkflowRegistry
) -> EditorialTaskRead:
    command = EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.EVENT_RECAP, priority=TaskPriority.C)
    return await workflow_service.create_task(session, command, registry=workflow_registry)


async def _seed_story_link(session: AsyncSession, *, anchor_event: NewsEvent):
    """A minimal, real Story + NewsEventStoryLink row - just enough for the executor's own
    NewsEventStoryLink -> Story resolution to succeed. build_event_recap_candidate() itself is
    monkeypatched in every test below, so this Story is never actually clustered/read by it -
    only resolved by id."""
    from database.models.news_event import EventCategory as _EventCategory
    from database.models.story import Story
    from database.models.story_link import NewsEventStoryLink
    from services.story_memory import NEW_STORY

    story = Story(
        title=anchor_event.title, category=_EventCategory.AI, entities=[], keywords=[],
        topic_bucket="test", first_event_id=anchor_event.id, event_count=1,
    )
    session.add(story)
    await session.flush()
    session.add(
        NewsEventStoryLink(
            news_event_id=anchor_event.id, story_id=story.id, match_type=NEW_STORY, match_score=1.0,
        )
    )
    await session.flush()
    return story


@pytest.mark.asyncio
async def test_event_recap_branch_populates_evidence_text_and_reaches_capability_success(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proves the full deterministic chain: EditorialTask(EVENT_RECAP) -> WorkflowRunner ->
    CapabilityExecutor -> Story resolution -> build_event_recap_candidate(force_shadow=False,
    research_complete=True) -> render_event_recap_bundle_text() ->
    CapabilityContext.business.event_recap_evidence_text -> a spy Capability that captures the
    context it received. No `precomputed_event_recap_candidate` is passed to this executor, so
    this exercises its Phase G.1 fallback path (any caller that bypasses the processor's own
    pre-check) - build_event_recap_candidate/render_event_recap_bundle_text are monkeypatched to
    isolate the executor's own plumbing."""
    import services.event_recap as event_recap_module
    from services.event_recap import EventRecapBuildResult

    call_kwargs: dict = {}
    build_call_count = 0
    render_call_count = 0
    _SENTINEL_CANDIDATE = object()

    async def _fake_build(session, story, *, force_shadow=False, now=None, research_complete=False):
        nonlocal build_call_count
        build_call_count += 1
        call_kwargs["session"] = session
        call_kwargs["story"] = story
        call_kwargs["force_shadow"] = force_shadow
        call_kwargs["research_complete"] = research_complete
        return EventRecapBuildResult(candidate=_SENTINEL_CANDIDATE, rejected=False, rejection_reasons=[])

    def _fake_render(candidate):
        nonlocal render_call_count
        render_call_count += 1
        assert candidate is _SENTINEL_CANDIDATE
        return _PHASE_B1_FAKE_EVIDENCE_TEXT

    monkeypatch.setattr(event_recap_module, "build_event_recap_candidate", _fake_build)
    monkeypatch.setattr(event_recap_module, "render_event_recap_bundle_text", _fake_render)

    story = await _seed_story_link(db_session, anchor_event=real_news_event)
    workflow_registry = _event_recap_workflow_registry()
    task = await _created_event_recap_task(db_session, real_news_event, workflow_registry)

    spy = _SpyCapability()
    capability_registry = _capability_registry("event_recap", spy)
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "COMPLETED"
    assert build_call_count == 1  # build_event_recap_candidate() is actually called, exactly once
    assert call_kwargs["story"].id == story.id
    assert call_kwargs["force_shadow"] is False  # Phase G.1: production/manual never bypasses readiness
    assert call_kwargs["research_complete"] is True  # Phase G.1: R2 has no separate research stage
    assert render_call_count == 1  # render_event_recap_bundle_text() is actually called, exactly once
    assert spy.received_context is not None
    assert spy.received_context.business.event_recap_evidence_text == _PHASE_B1_FAKE_EVIDENCE_TEXT
    assert spy.received_context.business.event_recap_candidate is _SENTINEL_CANDIDATE
    assert await _ai_execution_count(db_session) == 0  # zero AI calls anywhere in this chain


@pytest.mark.asyncio
async def test_event_recap_branch_delivers_candidate_to_the_real_capability_and_completes_synthesis(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase B.2: same chain as the test above, but with the REAL EventRecapCapability (never a
    spy) as the registered capability, and a REAL (in-memory, no DB) EventRecapCandidate - proves
    the full chain EditorialTask(EVENT_RECAP) -> WorkflowRunner -> CapabilityExecutor -> Story
    resolution -> build_event_recap_candidate(force_shadow=False, research_complete=True) [Phase
    G.1 fallback path - no precomputed candidate passed] -> CapabilityContext.business.
    event_recap_candidate -> EventRecapCapability.execute() -> synthesize_event_recap() ->
    call_generate() -> FakeLLMGateway -> real recap_title/recap_summary/key_takeaways/
    uncertainty_notes reflected in the persisted WorkflowStepResult."""
    import services.event_recap as event_recap_module
    from capabilities.event_recap_capability import EVENT_RECAP_CAPABILITY_DEFINITION, EventRecapCapability
    from services.event_recap import EVENT_RECAP_PROMPT_NAME, EVENT_RECAP_PROMPT_VERSION, EventRecapBuildResult
    from tests.test_event_recap import _candidate_from_titles

    real_candidate = _candidate_from_titles(
        ["Apple unveils new Watch Ultra priced at $999"], "Apple unveils new Watch Ultra",
    )

    async def _fake_build(session, story, *, force_shadow=False, now=None, research_complete=False):
        assert force_shadow is False
        assert research_complete is True
        return EventRecapBuildResult(candidate=real_candidate, rejected=False, rejection_reasons=[])

    monkeypatch.setattr(event_recap_module, "build_event_recap_candidate", _fake_build)
    # render_event_recap_bundle_text() is left completely unmonkeypatched here - runs for real.

    await _seed_story_link(db_session, anchor_event=real_news_event)
    workflow_registry = _event_recap_workflow_registry()
    task = await _created_event_recap_task(db_session, real_news_event, workflow_registry)

    prompt_repository = FakePromptRepository()
    prompt_repository.register(
        RenderedPrompt(
            name=EVENT_RECAP_PROMPT_NAME, version=EVENT_RECAP_PROMPT_VERSION,
            system="You are a fake recap analyst.", rules=["Never invent facts."],
            output_schema={
                "type": "object",
                "properties": {
                    "recap_title": {"type": "string"}, "recap_summary": {"type": "string"},
                    "key_takeaways": {"type": "array"}, "uncertainty_notes": {"type": "array"},
                },
                "required": ["recap_title", "recap_summary", "key_takeaways", "uncertainty_notes"],
            },
        )
    )
    valid_output = {
        "recap_title": "Example Recap Title", "recap_summary": "Example recap summary.",
        "key_takeaways": ["First takeaway."], "uncertainty_notes": [],
    }
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=valid_output, finish_reason="stop",
            model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=100, output_tokens=50),
        )
    )
    capability_registry = CapabilityRegistry()
    capability_registry.register(
        EVENT_RECAP_CAPABILITY_DEFINITION, EventRecapCapability(gateway, prompt_repository),
    )
    capability_registry.seal()
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "COMPLETED"
    assert len(result.step_results) == 1
    assert result.step_results[0].status == "SUCCESS"
    assert result.step_results[0].result == valid_output
    assert len(gateway.received_requests) == 1  # the Gateway was actually reached
    assert await _ai_execution_count(db_session) == 0  # no cost_tracker passed to this executor


@pytest.mark.asyncio
async def test_event_recap_branch_missing_story_link_raises_permanent_step_failure(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No NewsEventStoryLink row exists for this event - the branch must fail closed before ever
    calling build_event_recap_candidate()."""
    import services.event_recap as event_recap_module

    async def _fake_build(*args, **kwargs):
        raise AssertionError("build_event_recap_candidate must not be called when the Story link is missing")

    monkeypatch.setattr(event_recap_module, "build_event_recap_candidate", _fake_build)

    workflow_registry = _event_recap_workflow_registry()
    task = await _created_event_recap_task(db_session, real_news_event, workflow_registry)
    capability_registry = _capability_registry("event_recap", _SpyCapability())
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "FAILED"
    assert "NewsEventStoryLink" in (result.step_results[0].error or "")


@pytest.mark.asyncio
async def test_event_recap_branch_missing_story_raises_permanent_step_failure(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NewsEventStoryLink resolves to a Story id `session.get(Story, ...)` cannot find - the
    branch must fail closed before ever calling build_event_recap_candidate(). A real orphaned
    story_id cannot be persisted (news_event_story_links.story_id has a real FK to stories.id,
    enforced by Postgres itself) - this is defense-in-depth for a state the DB already prevents,
    exactly mirroring the identical, equally DB-unreachable "Story not found" check the
    TELEGRAPH_ARTICLE branch above already has. Proven here by intercepting only this one
    session.get(Story, ...) call on the real db_session - every other session.get() call in the
    same chain (EditorialTask/NewsEvent/NewsEventStoryLink) passes through unchanged."""
    from database.models.story import Story

    real_story = await _seed_story_link(db_session, anchor_event=real_news_event)
    real_get = db_session.get

    async def _get_with_story_missing(model, ident, *args, **kwargs):
        if model is Story and ident == real_story.id:
            return None
        return await real_get(model, ident, *args, **kwargs)

    monkeypatch.setattr(db_session, "get", _get_with_story_missing)

    import services.event_recap as event_recap_module

    async def _fake_build(*args, **kwargs):
        raise AssertionError("build_event_recap_candidate must not be called when the Story is missing")

    monkeypatch.setattr(event_recap_module, "build_event_recap_candidate", _fake_build)

    workflow_registry = _event_recap_workflow_registry()
    task = await _created_event_recap_task(db_session, real_news_event, workflow_registry)
    capability_registry = _capability_registry("event_recap", _SpyCapability())
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "FAILED"
    assert "Story" in (result.step_results[0].error or "")
    assert "not found" in (result.step_results[0].error or "")


@pytest.mark.asyncio
async def test_event_recap_branch_rejected_candidate_raises_permanent_step_failure(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """build_event_recap_candidate() rejecting (e.g. Story Integrity failure) must fail the step
    closed, surfacing the existing rejection_reasons - never inventing new decision logic here.
    Phase G.1: this is the executor's own fail-closed fallback (no precomputed candidate passed) -
    the defense-in-depth path a direct/future caller bypassing the processor's own pre-check would
    hit; `force_shadow=False`/`research_complete=True` mirror the processor's own contract exactly."""
    import services.event_recap as event_recap_module
    from services.event_recap import EventRecapBuildResult

    async def _fake_build_rejected(session, story, *, force_shadow=False, now=None, research_complete=False):
        assert force_shadow is False
        assert research_complete is True
        return EventRecapBuildResult(
            candidate=None, rejected=True, rejection_reasons=["fake_integrity_failure_reason"],
        )

    monkeypatch.setattr(event_recap_module, "build_event_recap_candidate", _fake_build_rejected)

    await _seed_story_link(db_session, anchor_event=real_news_event)
    workflow_registry = _event_recap_workflow_registry()
    task = await _created_event_recap_task(db_session, real_news_event, workflow_registry)
    capability_registry = _capability_registry("event_recap", _SpyCapability())
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "FAILED"
    assert "fake_integrity_failure_reason" in (result.step_results[0].error or "")


@pytest.mark.asyncio
async def test_event_recap_branch_uses_precomputed_candidate_without_rebuilding(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase G.1 race-safety contract: when `CapabilityExecutor` is constructed with a
    `precomputed_event_recap_candidate`, the branch must use that exact object and never call
    build_event_recap_candidate() again - re-querying here would open a new, snapshot-inconsistent
    transaction (Phase G.0.2's own forensic finding) that could see Story state the caller's own
    readiness decision never saw."""
    import services.event_recap as event_recap_module

    async def _fake_build(*args, **kwargs):
        raise AssertionError(
            "build_event_recap_candidate must not be called when a precomputed candidate was supplied"
        )

    monkeypatch.setattr(event_recap_module, "build_event_recap_candidate", _fake_build)

    render_call_count = 0
    _SENTINEL_CANDIDATE = object()

    def _fake_render(candidate):
        nonlocal render_call_count
        render_call_count += 1
        assert candidate is _SENTINEL_CANDIDATE
        return _PHASE_B1_FAKE_EVIDENCE_TEXT

    monkeypatch.setattr(event_recap_module, "render_event_recap_bundle_text", _fake_render)

    workflow_registry = _event_recap_workflow_registry()
    task = await _created_event_recap_task(db_session, real_news_event, workflow_registry)
    spy = _SpyCapability()
    capability_registry = _capability_registry("event_recap", spy)
    executor = CapabilityExecutor(
        db_session, task.id, capability_registry, precomputed_event_recap_candidate=_SENTINEL_CANDIDATE,
    )

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "COMPLETED"
    assert render_call_count == 1
    assert spy.received_context is not None
    assert spy.received_context.business.event_recap_candidate is _SENTINEL_CANDIDATE
    assert spy.received_context.business.event_recap_evidence_text == _PHASE_B1_FAKE_EVIDENCE_TEXT


def test_build_context_event_recap_evidence_text_defaults_to_none_for_other_capabilities() -> None:
    """Item 11: for any non-event_recap capability, the new field stays None - byte-identical to
    every capability's own existing behavior before this field existed."""
    task = EditorialTask(
        id=uuid4(), event_id=uuid4(), priority=TaskPriority.B, status=TaskStatus.RUNNING,
        workflow={"workflow_name": "CONTENT_GENERATION", "workflow_version": 1, "current_step": "research"},
    )
    news_event = NewsEvent(
        id=task.event_id, source_id=uuid4(), title="Headline", summary=None, content="Body",
        url=None, category=EventCategory.AI, published_at=None,
    )
    step = WorkflowStepDefinition(name="research", capability="research", timeout_seconds=30)
    capability_executor = CapabilityExecutor(session=None, task_id=task.id, registry=None)  # type: ignore[arg-type]

    context = capability_executor._build_context(task, news_event, step, attempt=1)

    assert context.business.event_recap_evidence_text is None
    assert context.business.event_recap_candidate is None  # Phase B.2's own new field, same default


def test_build_context_threads_event_recap_evidence_text_and_candidate_when_supplied() -> None:
    """Pure unit proof that _build_context()'s own new parameters reach BusinessContext
    unchanged - no DB, no workflow run, mirrors the existing per-capability token-limit test
    above in style."""
    task = EditorialTask(
        id=uuid4(), event_id=uuid4(), priority=TaskPriority.C, status=TaskStatus.RUNNING,
        workflow={"workflow_name": "EVENT_RECAP", "workflow_version": 1, "current_step": "synthesize_recap"},
    )
    news_event = NewsEvent(
        id=task.event_id, source_id=uuid4(), title="Headline", summary=None, content="Body",
        url=None, category=EventCategory.AI, published_at=None,
    )
    step = WorkflowStepDefinition(name="synthesize_recap", capability="event_recap", timeout_seconds=30)
    capability_executor = CapabilityExecutor(session=None, task_id=task.id, registry=None)  # type: ignore[arg-type]
    _sentinel_candidate = object()

    context = capability_executor._build_context(
        task, news_event, step, attempt=1, event_recap_evidence_text=_PHASE_B1_FAKE_EVIDENCE_TEXT,
        event_recap_candidate=_sentinel_candidate,
    )

    assert context.business.event_recap_evidence_text == _PHASE_B1_FAKE_EVIDENCE_TEXT
    assert context.business.event_recap_candidate is _sentinel_candidate
