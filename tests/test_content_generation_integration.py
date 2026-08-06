"""Phase 14 M5: offline integration proof for the automatic CONTENT_GENERATION trigger +
Telegram notification chain.

Real Postgres, no separate test database - independent_session_factory() with explicit, FK-safe,
test-owned cleanup. FakeLLMGateway (never a real network call) wired through the REAL, unmodified
capabilities.registry.build_registry() - proving the real Research/Intelligence/Copywriting/
Quality Capability implementations integrate correctly through the full eligibility-query ->
run_content_generation_for_event() -> ContentDraft -> notifier chain, exactly as worker/
content_cycle.py::run_content_cycle() orchestrates them. A mocked Bot - no real Telegram call in
either dry-run or live mode in this file.

CRITICAL isolation note (mirrors tests/test_content_worker_cycle.py's own identical concern,
itself mirroring the real, disclosed Phase 13 M3 incident): every test below narrows settings.
content_generation_freshness_cutoff_hours to a few minutes before calling run_content_cycle(),
so only this test's own just-created rows are ever eligible - never real backlog.
"""
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock
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
from integrations.llm_gateway.tools.registry import ToolRegistry
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import CapabilityUsage
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowType
from services import workflow_service
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_infra import AllowingBudgetGuard
from tests.fakes.research_output import CANONICAL_RESEARCH_OUTPUT
from tests.test_triage_orchestrator_claims import independent_session_factory
from worker.content_cycle import run_content_cycle

_PROMPTS_ROOT = Path("prompts")

_INTELLIGENCE_OUTPUT: dict[str, object] = {
    "significance": 0.7,
    "angle": "Market impact",
    "audience_relevance": "General audience",
    "recommendation": "Publish with standard priority",
}
_COPYWRITING_OUTPUT: dict[str, object] = {
    "title": "Example draft title",
    "body": "Example draft body text.",
    "what_happened": "Example event happened.",
    "why_it_matters": "Example editorial interpretation of the impact.",
    "what_remains_unknown": None,
    "quote": None,
}
_QUALITY_OUTPUT: dict[str, object] = {"passed": True, "issues": []}


def _generate_response(structured_output: dict[str, object]) -> GenerateResponse:
    return GenerateResponse(
        text=None,
        structured_output=structured_output,
        finish_reason="stop",
        model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    )


def _real_capability_registry():
    gateway = FakeLLMGateway(
        generate_responses=[
            _generate_response(CANONICAL_RESEARCH_OUTPUT),
            _generate_response(_INTELLIGENCE_OUTPUT),
            _generate_response(_COPYWRITING_OUTPUT),
            _generate_response(_QUALITY_OUTPUT),
        ]
    )
    registry = build_registry(gateway, FilePromptRepository(_PROMPTS_ROOT), AllowingBudgetGuard(), ToolRegistry())  # type: ignore[arg-type]
    return gateway, registry


@pytest_asyncio.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine, session_factory = independent_session_factory()
    yield session_factory
    await engine.dispose()


@pytest_asyncio.fixture
async def test_source(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[NewsSource]:
    unique_name = f"phase14-m5-integration-test-{uuid4()}"
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
    original = settings.content_generation_freshness_cutoff_hours
    settings.content_generation_freshness_cutoff_hours = 0.05  # 3 minutes
    try:
        yield
    finally:
        settings.content_generation_freshness_cutoff_hours = original


async def _make_completed_news_analysis_event(
    session: AsyncSession, source: NewsSource, *, score: int
) -> NewsEvent:
    event = NewsEvent(
        source_id=source.id,
        title=f"Phase 14 M5 integration test event {uuid4()}",
        category=EventCategory.AI,
        hash=f"phase14-m5-integration-test-{uuid4()}",
        published_at=datetime.now(timezone.utc),
    )
    session.add(event)
    await session.flush()
    await session.commit()

    command = EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.NEWS_ANALYSIS, priority=TaskPriority.B)
    read = await workflow_service.create_task(session, command)
    task = await session.get(EditorialTask, read.id)
    assert task is not None
    task.workflow = {
        **(task.workflow or {}),
        "step_results": [
            {
                "step_name": "scoring", "status": "SUCCESS", "attempt": 1,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
                "result": {"score": score, "rationale": "test"},
            }
        ],
    }
    task.status = TaskStatus.COMPLETED
    await session.commit()
    return event


@pytest.mark.asyncio
async def test_full_chain_dry_run_creates_draft_and_renders_without_sending(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    async with factory() as session:
        event = await _make_completed_news_analysis_event(
            session, test_source, score=settings.content_generation_min_score
        )

    assert settings.content_generation_dry_run is True  # exercising the safe default explicitly
    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()

    result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.eligible_found == 1
    assert result.completed == 1
    assert result.dry_run_rendered == 1
    assert result.notified == 0
    fake_bot.send_message.assert_not_called()

    async with factory() as verify_session:
        content_gen_task = (
            await verify_session.execute(
                select(EditorialTask).where(
                    EditorialTask.event_id == event.id,
                    EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.CONTENT_GENERATION.value,
                )
            )
        ).scalar_one()
        assert content_gen_task.status == TaskStatus.COMPLETED

        draft = (
            await verify_session.execute(select(ContentDraft).where(ContentDraft.task_id == content_gen_task.id))
        ).scalar_one()
        assert draft.title == _COPYWRITING_OUTPUT["title"]
        assert draft.body == _COPYWRITING_OUTPUT["body"]

        # NEWS_ANALYSIS task itself must never be mutated by the content cycle.
        news_analysis_task = (
            await verify_session.execute(
                select(EditorialTask).where(
                    EditorialTask.event_id == event.id,
                    EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value,
                )
            )
        ).scalar_one()
        assert news_analysis_task.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_full_chain_live_mode_sends_exactly_once(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    async with factory() as session:
        await _make_completed_news_analysis_event(session, test_source, score=settings.content_generation_min_score)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()

    original_dry_run = settings.content_generation_dry_run
    original_chat_id = settings.editorial_chat_id
    settings.content_generation_dry_run = False
    settings.editorial_chat_id = 987654321
    try:
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)
    finally:
        settings.content_generation_dry_run = original_dry_run
        settings.editorial_chat_id = original_chat_id

    assert result.completed == 1
    assert result.notified == 1
    assert result.notification_failed == 0
    fake_bot.send_message.assert_called_once()
    call_args = fake_bot.send_message.call_args
    assert call_args.args[0] == 987654321


@pytest.mark.asyncio
async def test_duplicate_guarded_event_never_reprocessed(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    async with factory() as session:
        event = await _make_completed_news_analysis_event(
            session, test_source, score=settings.content_generation_min_score
        )
        # Pre-existing CONTENT_GENERATION sibling, already COMPLETED - simulates an event that
        # already went through the chain once.
        command = EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B)
        existing_read = await workflow_service.create_task(session, command)
        existing_task = await session.get(EditorialTask, existing_read.id)
        assert existing_task is not None
        existing_task.status = TaskStatus.COMPLETED
        await session.commit()

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()

    result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert event.id not in result.event_ids
    assert result.eligible_found == 0
    fake_bot.send_message.assert_not_called()

    async with factory() as verify_session:
        content_gen_tasks = (
            await verify_session.execute(
                select(EditorialTask).where(
                    EditorialTask.event_id == event.id,
                    EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.CONTENT_GENERATION.value,
                )
            )
        ).scalars().all()
        assert len(content_gen_tasks) == 1  # still exactly the one pre-existing task, no second one
