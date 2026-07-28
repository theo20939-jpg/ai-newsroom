"""API cost optimization: tests for services.analysis_reuse (pure DB-level) and its wiring into
capabilities.executor.CapabilityExecutor (real WorkflowRunner + real CONTENT_GENERATION
definition, fake Capability I/O only - no live LLM call, matching this codebase's established
integration-test convention, e.g. tests/test_fact_safety.py)."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.executor import CapabilityExecutor
from capabilities.registry import Capability, CapabilityRegistry
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from schemas.capability import CapabilityContext, CapabilityResult
from schemas.capability_definition import CapabilityConfig, CapabilityDefinition
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import (
    WorkflowDefinition,
    WorkflowRetryPolicy,
    WorkflowStepDefinition,
    WorkflowType,
)
from services import workflow_service
from services.analysis_reuse import find_source_news_analysis_task_id, reuse_prior_result
from workflows.registry import WorkflowRegistry
from workflows.runner import WorkflowRunner

UTC = timezone.utc

_RESEARCH_RESULT = {"facts": ["Fact one.", "Fact two."], "confidence": 0.9, "gaps": []}
_INTELLIGENCE_RESULT = {
    "significance": 0.7, "angle": "Market impact",
    "audience_relevance": "General", "recommendation": "Publish",
}


async def _make_source(session: AsyncSession) -> NewsSource:
    source = NewsSource(name=f"Reuse Source {uuid4()}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    return source


async def _make_event(session: AsyncSession, source: NewsSource) -> NewsEvent:
    event = NewsEvent(
        source_id=source.id, title=f"Reuse test event {uuid4()}", content="Some content.",
        category=EventCategory.AI, hash=f"reuse-test-{uuid4()}",
    )
    session.add(event)
    await session.flush()
    return event


async def _make_completed_news_analysis_task(
    session: AsyncSession, event: NewsEvent, *, step_results: list[dict[str, object]]
) -> EditorialTask:
    command = EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.NEWS_ANALYSIS, priority=TaskPriority.B)
    read = await workflow_service.create_task(session, command)
    task = await session.get(EditorialTask, read.id)
    assert task is not None
    task.workflow = {**(task.workflow or {}), "step_results": step_results}
    task.status = TaskStatus.COMPLETED
    await session.commit()
    await session.refresh(task)
    return task


def _step_result(name: str, result: dict[str, object] | None, *, status: str = "SUCCESS") -> dict[str, object]:
    now = datetime.now(UTC).isoformat()
    return {
        "step_name": name, "status": status, "attempt": 1,
        "started_at": now, "finished_at": now, "error": None, "result": result,
    }


# ---------------------------------------------------------------------------
# Pure DB-level tests: services.analysis_reuse
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_source_task_returns_completed_news_analysis_task(db_session: AsyncSession) -> None:
    source = await _make_source(db_session)
    event = await _make_event(db_session, source)
    task = await _make_completed_news_analysis_task(
        db_session, event, step_results=[_step_result("research", _RESEARCH_RESULT)]
    )

    found = await find_source_news_analysis_task_id(db_session, event.id)

    assert found == task.id


@pytest.mark.asyncio
async def test_find_source_task_none_when_no_news_analysis_task_exists(db_session: AsyncSession) -> None:
    source = await _make_source(db_session)
    event = await _make_event(db_session, source)

    found = await find_source_news_analysis_task_id(db_session, event.id)

    assert found is None


@pytest.mark.asyncio
async def test_find_source_task_ignores_incomplete_news_analysis_task(db_session: AsyncSession) -> None:
    source = await _make_source(db_session)
    event = await _make_event(db_session, source)
    command = EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.NEWS_ANALYSIS, priority=TaskPriority.B)
    await workflow_service.create_task(db_session, command)  # left CREATED, never completed

    found = await find_source_news_analysis_task_id(db_session, event.id)

    assert found is None


@pytest.mark.asyncio
async def test_find_source_task_never_matches_a_different_event(db_session: AsyncSession) -> None:
    source = await _make_source(db_session)
    event_a = await _make_event(db_session, source)
    event_b = await _make_event(db_session, source)
    await _make_completed_news_analysis_task(
        db_session, event_a, step_results=[_step_result("research", _RESEARCH_RESULT)]
    )

    found = await find_source_news_analysis_task_id(db_session, event_b.id)

    assert found is None


@pytest.mark.asyncio
async def test_reuse_prior_result_returns_well_formed_research_result(db_session: AsyncSession) -> None:
    source = await _make_source(db_session)
    event = await _make_event(db_session, source)
    task = await _make_completed_news_analysis_task(
        db_session, event, step_results=[_step_result("research", _RESEARCH_RESULT)]
    )

    result = await reuse_prior_result(db_session, task.id, "research")

    assert result == _RESEARCH_RESULT


@pytest.mark.asyncio
async def test_reuse_prior_result_none_for_malformed_result_missing_required_key(db_session: AsyncSession) -> None:
    source = await _make_source(db_session)
    event = await _make_event(db_session, source)
    task = await _make_completed_news_analysis_task(
        db_session, event, step_results=[_step_result("research", {"facts": ["x"]})]  # missing confidence/gaps
    )

    result = await reuse_prior_result(db_session, task.id, "research")

    assert result is None


@pytest.mark.asyncio
async def test_reuse_prior_result_none_when_step_failed(db_session: AsyncSession) -> None:
    source = await _make_source(db_session)
    event = await _make_event(db_session, source)
    task = await _make_completed_news_analysis_task(
        db_session, event, step_results=[_step_result("research", None, status="FAILED")]
    )

    result = await reuse_prior_result(db_session, task.id, "research")

    assert result is None


@pytest.mark.asyncio
async def test_reuse_prior_result_none_for_unsupported_capability_name(db_session: AsyncSession) -> None:
    source = await _make_source(db_session)
    event = await _make_event(db_session, source)
    task = await _make_completed_news_analysis_task(
        db_session, event,
        step_results=[_step_result("copywriting", {"title": "x", "body": "y", "hashtags": []})],
    )

    result = await reuse_prior_result(db_session, task.id, "copywriting")

    assert result is None  # "copywriting" is never a reusable capability, regardless of shape


# ---------------------------------------------------------------------------
# Integration: real WorkflowRunner + real CONTENT_GENERATION definition + CapabilityExecutor
# ---------------------------------------------------------------------------


class _RaisingCapability:
    """Raises if ever actually invoked - proves a step was skipped (reused), not just that its
    fake output happens to match."""

    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        raise AssertionError("this capability must not be called when a prior result is reusable")


class _FakeCapability:
    def __init__(self, output: dict[str, object]) -> None:
        self._output = output

    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        now = datetime.now(UTC)
        return CapabilityResult(
            status="SUCCESS", structured_output=self._output,
            calls=[], started_at=now, finished_at=now, duration_seconds=0.0,
        )


def _content_generation_registry() -> WorkflowRegistry:
    registry = WorkflowRegistry()
    registry.register(
        WorkflowDefinition(
            name=WorkflowType.CONTENT_GENERATION, version=1,
            steps=[
                WorkflowStepDefinition(name="research", capability="research", timeout_seconds=10),
                WorkflowStepDefinition(name="intelligence", capability="intelligence", timeout_seconds=10),
                WorkflowStepDefinition(name="copywriting", capability="copywriting", timeout_seconds=10),
                WorkflowStepDefinition(name="quality", capability="quality", timeout_seconds=10),
            ],
            max_iterations=3,
            retry_policy=WorkflowRetryPolicy(max_attempts=3, retryable_error_types=["StepExecutionError"]),
            timeout_seconds=60, required_input=["event_id"], expected_output=["result"],
        )
    )
    registry.seal()
    return registry


def _capability_registry(
    *, research: Capability, intelligence: Capability, copywriting_output: dict[str, object], quality_output: dict[str, object]
) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(
        CapabilityDefinition(
            name="research", version=1, config=CapabilityConfig(timeout_seconds=10),
            required_context=["news_event"], expected_output_keys=["facts", "confidence", "gaps"],
        ),
        research,
    )
    registry.register(
        CapabilityDefinition(
            name="intelligence", version=1, config=CapabilityConfig(timeout_seconds=10),
            required_context=["news_event"],
            expected_output_keys=["significance", "angle", "audience_relevance", "recommendation"],
        ),
        intelligence,
    )
    registry.register(
        CapabilityDefinition(
            name="copywriting", version=1, config=CapabilityConfig(timeout_seconds=10),
            required_context=["news_event"], expected_output_keys=["title", "body", "hashtags"],
        ),
        _FakeCapability(copywriting_output),
    )
    registry.register(
        CapabilityDefinition(
            name="quality", version=1, config=CapabilityConfig(timeout_seconds=10),
            required_context=["news_event"], expected_output_keys=["passed", "issues"],
        ),
        _FakeCapability(quality_output),
    )
    registry.seal()
    return registry


@pytest.mark.asyncio
async def test_content_generation_reuses_research_and_intelligence_from_completed_news_analysis(
    db_session: AsyncSession,
) -> None:
    source = await _make_source(db_session)
    event = await _make_event(db_session, source)
    await _make_completed_news_analysis_task(
        db_session, event,
        step_results=[
            _step_result("research", _RESEARCH_RESULT),
            _step_result("intelligence", _INTELLIGENCE_RESULT),
        ],
    )

    workflow_registry = _content_generation_registry()
    task = await workflow_service.create_task(
        db_session,
        EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B),
        registry=workflow_registry,
    )
    # research/intelligence are _RaisingCapability - if the reuse path did NOT skip them, this
    # test fails loudly (AssertionError from inside the capability), not silently.
    capability_registry = _capability_registry(
        research=_RaisingCapability(), intelligence=_RaisingCapability(),
        copywriting_output={"title": "T", "body": "B", "hashtags": []},
        quality_output={"passed": True, "issues": []},
    )
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "COMPLETED"
    research_step = next(r for r in result.step_results if r.step_name == "research")
    intelligence_step = next(r for r in result.step_results if r.step_name == "intelligence")
    assert research_step.result == _RESEARCH_RESULT
    assert intelligence_step.result == _INTELLIGENCE_RESULT


@pytest.mark.asyncio
async def test_content_generation_falls_back_to_real_call_when_no_prior_news_analysis_task(
    db_session: AsyncSession,
) -> None:
    source = await _make_source(db_session)
    event = await _make_event(db_session, source)  # no NEWS_ANALYSIS task at all for this event

    workflow_registry = _content_generation_registry()
    task = await workflow_service.create_task(
        db_session,
        EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B),
        registry=workflow_registry,
    )
    fresh_research = {"facts": ["Freshly researched fact."], "confidence": 0.5, "gaps": ["nothing prior"]}
    fresh_intelligence = {
        "significance": 0.3, "angle": "Fresh angle",
        "audience_relevance": "Fresh", "recommendation": "Fresh",
    }
    capability_registry = _capability_registry(
        research=_FakeCapability(fresh_research), intelligence=_FakeCapability(fresh_intelligence),
        copywriting_output={"title": "T", "body": "B", "hashtags": []},
        quality_output={"passed": True, "issues": []},
    )
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    assert result.status == "COMPLETED"
    research_step = next(r for r in result.step_results if r.step_name == "research")
    intelligence_step = next(r for r in result.step_results if r.step_name == "intelligence")
    assert research_step.result == fresh_research
    assert intelligence_step.result == fresh_intelligence


@pytest.mark.asyncio
async def test_content_generation_never_reuses_a_different_events_result(db_session: AsyncSession) -> None:
    source = await _make_source(db_session)
    event_with_prior = await _make_event(db_session, source)
    event_without_prior = await _make_event(db_session, source)
    await _make_completed_news_analysis_task(
        db_session, event_with_prior,
        step_results=[
            _step_result("research", _RESEARCH_RESULT),
            _step_result("intelligence", _INTELLIGENCE_RESULT),
        ],
    )

    workflow_registry = _content_generation_registry()
    task = await workflow_service.create_task(
        db_session,
        EditorialTaskCreate(event_id=event_without_prior.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B),
        registry=workflow_registry,
    )
    fresh_research = {"facts": ["Belongs to event_without_prior."], "confidence": 0.4, "gaps": []}
    fresh_intelligence = {
        "significance": 0.2, "angle": "Own angle",
        "audience_relevance": "Own", "recommendation": "Own",
    }
    capability_registry = _capability_registry(
        research=_FakeCapability(fresh_research), intelligence=_FakeCapability(fresh_intelligence),
        copywriting_output={"title": "T", "body": "B", "hashtags": []},
        quality_output={"passed": True, "issues": []},
    )
    executor = CapabilityExecutor(db_session, task.id, capability_registry)

    result = await WorkflowRunner(executor=executor, registry=workflow_registry).run(db_session, task.id)

    research_step = next(r for r in result.step_results if r.step_name == "research")
    # Must be the FRESH result for this event, never event_with_prior's _RESEARCH_RESULT.
    assert research_step.result == fresh_research
    assert research_step.result != _RESEARCH_RESULT
