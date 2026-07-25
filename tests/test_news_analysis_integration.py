"""Phase 13 M5: offline integration proof for automatic NEWS_ANALYSIS execution.

Real Postgres, no separate test database - independent_session_factory() (imported from
tests.test_triage_orchestrator_claims, this repository's own already-proven helper) with
explicit, FK-safe, test-owned cleanup. FakeLLMGateway (never a real network call) wired through
the REAL, unmodified capabilities.registry.build_registry() - proving the real Research/
Intelligence/Engagement/Scoring Capability implementations, not test doubles, integrate
correctly through the full eligibility-query -> atomic-claim -> WorkflowRunner chain exactly as
worker/analysis_cycle.py's own run_analysis_cycle() orchestrates them.

CRITICAL isolation note (mirrors tests/test_analysis_worker_cycle.py's own identical concern,
discovered and fixed during M3): run_analysis_cycle() calls the real, deliberately-unscoped
eligibility query against the shared dev database, which currently contains 1000+ genuinely
fresh-eligible NEWS_ANALYSIS/CREATED tasks. Every test below that calls run_analysis_cycle()
narrows settings.news_analysis_freshness_cutoff_hours to a few minutes first, so only this
test's own just-created rows are ever eligible - never real backlog.
"""
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capabilities.registry import build_registry
from core.config import settings
from database.models.content_draft import ContentDraft
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from integrations.prompts.protocol import PromptRepository
from schemas.capability import CapabilityUsage
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowType
from services import workflow_service
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_infra import AllowingBudgetGuard
from tests.fakes.research_output import CANONICAL_RESEARCH_OUTPUT
from tests.test_triage_orchestrator_claims import independent_session_factory
from integrations.llm_gateway.tools.registry import ToolRegistry
from worker.analysis_cycle import run_analysis_cycle

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

_INTELLIGENCE_OUTPUT = {
    "significance": 0.7,
    "angle": "Market impact",
    "audience_relevance": "General audience",
    "recommendation": "Publish with standard priority",
}
_ENGAGEMENT_OUTPUT = {
    "engagement_potential_score": 0.65,
    "audience_fit": "AI/tech enthusiasts",
    "reasoning": "Novel technical development with broad relevance.",
}
_SCORING_OUTPUT = {"score": 85, "rationale": "Broadly relevant."}


def _prompt_repository() -> PromptRepository:
    return FilePromptRepository(_PROMPTS_ROOT)


def _generate_response(structured_output: dict[str, object]) -> GenerateResponse:
    return GenerateResponse(
        text=None,
        structured_output=structured_output,
        finish_reason="stop",
        model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    )


@pytest_asyncio.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine, session_factory = independent_session_factory()
    yield session_factory
    await engine.dispose()


@pytest_asyncio.fixture
async def test_source(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[NewsSource]:
    unique_name = f"phase13-m5-integration-test-{uuid4()}"
    async with factory() as session:
        source = NewsSource(name=unique_name, type=SourceType.RSS, active=True)
        session.add(source)
        await session.commit()

    try:
        yield source
    finally:
        async with factory() as session:
            event_ids = (
                await session.execute(select(NewsEvent.id).where(NewsEvent.source_id == source.id))
            ).scalars().all()
            if event_ids:
                await session.execute(delete(ContentDraft).where(ContentDraft.task_id.in_(
                    select(EditorialTask.id).where(EditorialTask.event_id.in_(event_ids))
                )))
                await session.execute(delete(EditorialTask).where(EditorialTask.event_id.in_(event_ids)))
                await session.execute(delete(NewsEvent).where(NewsEvent.id.in_(event_ids)))
            await session.execute(delete(NewsSource).where(NewsSource.id == source.id))
            await session.commit()


@pytest_asyncio.fixture
async def _isolated_freshness_window() -> AsyncIterator[None]:
    original = settings.news_analysis_freshness_cutoff_hours
    settings.news_analysis_freshness_cutoff_hours = 0.05  # 3 minutes - real backlog confirmed
    # multiple hours old at minimum; this test's own rows are created seconds before use.
    try:
        yield
    finally:
        settings.news_analysis_freshness_cutoff_hours = original


async def _make_event(session: AsyncSession, source: NewsSource, *, published_at) -> NewsEvent:
    event = NewsEvent(
        source_id=source.id,
        title=f"M5 integration test event {uuid4()}",
        category=EventCategory.AI,
        hash=f"m5-integration-test-{uuid4()}",
        published_at=published_at,
    )
    session.add(event)
    await session.flush()
    await session.commit()
    return event


async def _make_created_task(session: AsyncSession, event: NewsEvent, workflow_type: WorkflowType) -> EditorialTask:
    command = EditorialTaskCreate(event_id=event.id, workflow_type=workflow_type, priority=TaskPriority.B)
    read = await workflow_service.create_task(session, command)
    task = await session.get(EditorialTask, read.id)
    assert task is not None
    return task


def _real_capability_registry():
    gateway = FakeLLMGateway(
        generate_responses=[
            _generate_response(CANONICAL_RESEARCH_OUTPUT),
            _generate_response(_INTELLIGENCE_OUTPUT),
            _generate_response(_ENGAGEMENT_OUTPUT),
            _generate_response(_SCORING_OUTPUT),
        ]
    )
    registry = build_registry(gateway, _prompt_repository(), AllowingBudgetGuard(), ToolRegistry())  # type: ignore[arg-type]
    return gateway, registry


@pytest.mark.asyncio
async def test_full_chain_completes_via_run_analysis_cycle_with_real_capabilities(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    """1. Insert a test-owned CREATED NEWS_ANALYSIS task (via workflow_service.create_task(),
    matching the real production shape Triage would produce).
    2. Call run_analysis_cycle() - the full eligibility-query -> atomic-claim -> WorkflowRunner
    chain, using the REAL build_registry()-constructed CapabilityRegistry (FakeLLMGateway
    underneath, never a real network call).
    3. Assert research -> intelligence -> engagement_analysis -> scoring execute in order, each
    step's step_results correctly propagate, final status COMPLETED.
    4. Assert zero CONTENT_GENERATION EditorialTask rows and zero ContentDraft rows exist for
    this event afterward."""
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        task = await _make_created_task(session, event, WorkflowType.NEWS_ANALYSIS)

    gateway, registry = _real_capability_registry()

    result = await run_analysis_cycle(registry, session_factory=factory)

    assert task.id in result.task_ids
    assert result.completed >= 1
    assert result.failed == 0

    async with factory() as verify_session:
        final_task = await verify_session.get(EditorialTask, task.id)
        assert final_task is not None
        assert final_task.status == TaskStatus.COMPLETED

        step_results = final_task.workflow["step_results"]
        assert [r["step_name"] for r in step_results] == [
            "research",
            "intelligence",
            "engagement_analysis",
            "scoring",
        ]
        assert all(r["status"] == "SUCCESS" for r in step_results)
        assert step_results[2]["result"] == _ENGAGEMENT_OUTPUT
        assert step_results[3]["result"] == _SCORING_OUTPUT

        # Propagation: Engagement's own request (3rd gateway call, index 2) reflects both
        # Research's and Intelligence's prior output.
        engagement_request = gateway.received_requests[2]
        engagement_text = "\n".join(
            part.text for message in engagement_request.messages for part in message.content if part.text
        )
        canonical_facts = CANONICAL_RESEARCH_OUTPUT["facts"]
        assert isinstance(canonical_facts, list)
        for fact in canonical_facts:
            assert fact in engagement_text
        assert _INTELLIGENCE_OUTPUT["angle"] in engagement_text

        # CONTENT_GENERATION/ContentDraft boundary - zero, mechanically asserted.
        content_generation_tasks = (
            await verify_session.execute(
                select(EditorialTask).where(
                    EditorialTask.event_id == event.id,
                    EditorialTask.id != task.id,
                )
            )
        ).scalars().all()
        assert content_generation_tasks == []
        draft_rows = (
            await verify_session.execute(select(ContentDraft).where(ContentDraft.task_id == task.id))
        ).scalars().all()
        assert draft_rows == []


@pytest.mark.asyncio
async def test_stale_task_beyond_48h_is_excluded_from_run_analysis_cycle(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    """Backlog-exclusion proof at the run_analysis_cycle() level (not merely the eligibility
    query in isolation, already covered by tests/test_analysis_worker_cycle.py) - a stale
    test-owned task is never claimed/processed."""
    async with factory() as session:
        stale_published_at = datetime.now(timezone.utc) - timedelta(hours=1)  # older than the
        # 3-minute isolated window above, so excluded by it - proves exclusion end to end.
        event = await _make_event(session, test_source, published_at=stale_published_at)
        task = await _make_created_task(session, event, WorkflowType.NEWS_ANALYSIS)

    _, registry = _real_capability_registry()

    result = await run_analysis_cycle(registry, session_factory=factory)

    assert task.id not in result.task_ids

    async with factory() as verify_session:
        final_task = await verify_session.get(EditorialTask, task.id)
        assert final_task is not None
        assert final_task.status == TaskStatus.CREATED  # never touched


@pytest.mark.asyncio
async def test_batch_cap_enforced_within_run_analysis_cycle(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    async with factory() as session:
        created_ids = []
        for _ in range(6):
            event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
            task = await _make_created_task(session, event, WorkflowType.NEWS_ANALYSIS)
            created_ids.append(task.id)

    _, registry = _real_capability_registry()  # only 4 queued responses - only 1 task fully
    # processed via this registry; batch-cap enforcement itself is proven by eligible_found/
    # task_ids length, independent of how many individual tasks the fake gateway can complete.

    result = await run_analysis_cycle(registry, session_factory=factory)

    assert result.eligible_found == 5  # LIMIT settings.news_analysis_batch_size (5), not 6
    assert len(result.task_ids) == 5
    matched = [tid for tid in result.task_ids if tid in created_ids]
    assert len(matched) == 5
