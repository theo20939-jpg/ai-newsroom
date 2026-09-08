"""DIRECTOR-CONTROL-PLANE-1A §33-34: required pre-generation-gate + shadow-mode tests against the
REAL run_content_cycle() loop. Reuses tests/test_content_worker_cycle.py's own established real-
Postgres/fake-LLMGateway technique (independent_session_factory(), _real_capability_registry()) -
imported, not duplicated. Small per-test fixtures duplicated per this codebase's own convention of
never sharing pytest fixtures across test modules."""
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from database.models.content_draft import ContentDraft
from database.models.director_editorial_decision import DirectorEditorialDecision
from database.models.editorial_task import EditorialTask
from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource, SourceType
from tests.test_content_worker_cycle import _make_completed_news_analysis_task, _make_event, _real_capability_registry
from tests.test_triage_orchestrator_claims import independent_session_factory
from worker.content_cycle import run_content_cycle

_PROMPTS_ROOT_PATH = Path("prompts")


@pytest_asyncio.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine, session_factory = independent_session_factory()
    yield session_factory
    await engine.dispose()


@pytest_asyncio.fixture
async def test_source(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[NewsSource]:
    unique_name = f"director-gate-pregeneration-test-{uuid4()}"
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
                await session.execute(delete(DirectorEditorialDecision).where(DirectorEditorialDecision.event_id.in_(event_ids)))
                await session.execute(delete(NewsEvent).where(NewsEvent.id.in_(event_ids)))
            await session.execute(delete(NewsSource).where(NewsSource.id == source.id))
            await session.commit()


@pytest_asyncio.fixture
async def _isolated_freshness_window() -> AsyncIterator[None]:
    original = settings.content_generation_freshness_cutoff_hours
    settings.content_generation_freshness_cutoff_hours = 0.05
    try:
        yield
    finally:
        settings.content_generation_freshness_cutoff_hours = original


@pytest_asyncio.fixture
async def _gate_enabled() -> AsyncIterator[None]:
    original = settings.telegram_editorial_gate_enabled
    settings.telegram_editorial_gate_enabled = True
    try:
        yield
    finally:
        settings.telegram_editorial_gate_enabled = original


async def _make_event_with_content(
    session: AsyncSession, source: NewsSource, *, published_at: datetime, content: str | None,
) -> NewsEvent:
    event = await _make_event(session, source, published_at=published_at)
    event.content = content
    await session.commit()
    return event


@pytest.mark.asyncio
async def test_gate_off_preserves_existing_pipeline_behavior_but_still_persists_decision(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None,
) -> None:
    """Spec §7/§34: OFF -> normal queue unchanged, but a real DirectorEditorialDecision is still
    persisted (shadow, never suppressed)."""
    assert settings.telegram_editorial_gate_enabled is False
    async with factory() as session:
        event = await _make_event_with_content(
            session, test_source, published_at=datetime.now(timezone.utc), content="Real story content with facts.",
        )
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()

    result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.completed == 1
    assert result.gate_generation_suppressed == 0
    assert result.gate_total_stories == 1

    async with factory() as session:
        decision = (await session.execute(
            select(DirectorEditorialDecision).where(DirectorEditorialDecision.event_id == event.id)
        )).scalar_one()
    assert decision is not None


@pytest.mark.asyncio
async def test_gate_on_hold_prevents_content_generation(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None,
    _gate_enabled: None,
) -> None:
    """Spec §33: HOLD -> content generator NOT CALLED. An event that IS eligible (has a completed
    NEWS_ANALYSIS task, so _select_eligible_events() surfaces it) but has no content at all and no
    article acquisition row has has_sufficient_facts=False -> HOLD, deterministically."""
    async with factory() as session:
        event = await _make_event_with_content(session, test_source, published_at=datetime.now(timezone.utc), content=None)
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()

    with patch(
        "worker.content_cycle.run_content_generation_for_event",
        new=AsyncMock(side_effect=AssertionError("content generator must not be called for a HOLD decision")),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.completed == 0
    assert result.gate_hold == 1
    assert result.gate_generation_suppressed == 1


@pytest.mark.asyncio
async def test_gate_on_send_to_editor_continues_normal_generation(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None,
    _gate_enabled: None,
) -> None:
    """Spec §33: SEND_TO_EDITOR -> normal generation continues."""
    async with factory() as session:
        event = await _make_event_with_content(
            session, test_source, published_at=datetime.now(timezone.utc), content="Substantial real article content about AI.",
        )
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()

    result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.completed == 1
    assert result.gate_generation_suppressed == 0
    assert result.gate_send_to_editor + result.gate_priority + result.gate_breaking == 1


@pytest.mark.asyncio
async def test_gate_llm_unavailable_does_not_collapse_the_pipeline(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None,
    _gate_enabled: None,
) -> None:
    """Spec §6/§33: a gate evaluation failure (simulated here as build_gate_input_for_event raising)
    fails OPEN - generation proceeds unsuppressed rather than the whole cycle collapsing."""
    async with factory() as session:
        event = await _make_event_with_content(
            session, test_source, published_at=datetime.now(timezone.utc), content="Some content.",
        )
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()

    with patch(
        "worker.content_cycle.run_pre_generation_gate", new=AsyncMock(side_effect=RuntimeError("gate unavailable")),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.completed == 1  # generation still happened - fail-open, queue never collapsed
