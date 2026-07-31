"""Tests for worker.content_cycle's Phase 16 M6 + UX-fixed image-preview hook (docs/
phase16_m6_telegram_editorial_preview_report.md §7, docs/phase16_ux_combined_preview_fix_report.md).
Reuses tests/test_content_worker_cycle.py's own established real-Postgres/fake-LLMGateway
technique (independent_session_factory(), _real_capability_registry()) - imported directly, not
duplicated. The small per-test fixtures (factory/test_source/_isolated_freshness_window) are
duplicated rather than imported, matching this codebase's own convention of not sharing pytest
fixtures across test modules. send_editorial_card and send_news_with_image_preview are both
mocked at the module boundary - no real Telegram API call anywhere in this file.

UX fix: whenever the image-preview flow is active, `send_news_with_image_preview()` REPLACES
`send_editorial_card()` for that draft (never both) - the tests below assert the *other* function
was never called in each branch, not just that the active one was.
"""
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
from database.models.editorial_task import EditorialTask
from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource, SourceType
from services.image_preview_notifier import CombinedCardOutcome
from services.telegram_notifier import NotificationOutcome
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
    unique_name = f"phase16-m6-content-cycle-test-{uuid4()}"
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
    settings.content_generation_freshness_cutoff_hours = 0.05
    try:
        yield
    finally:
        settings.content_generation_freshness_cutoff_hours = original


@pytest.fixture(autouse=True)
def _restore_image_preview_settings():
    original_enabled = settings.image_editorial_preview_enabled
    original_mode = settings.image_candidate_persistence_mode
    yield
    settings.image_editorial_preview_enabled = original_enabled
    settings.image_candidate_persistence_mode = original_mode


@pytest.mark.asyncio
async def test_image_preview_disabled_by_default_uses_the_text_only_card(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    assert settings.image_editorial_preview_enabled is False  # the safe default, exercised directly

    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()

    with (
        patch(
            "worker.content_cycle.send_editorial_card",
            new=AsyncMock(return_value=NotificationOutcome(chat_id=1, rendered_html="<html>", sent=False)),
        ) as mock_notify,
        patch("worker.content_cycle.send_news_with_image_preview", new=AsyncMock()) as mock_preview,
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.completed == 1
    mock_notify.assert_called_once()  # the unchanged text-only path is used
    mock_preview.assert_not_called()
    assert result.image_preview_sent == 0


@pytest.mark.asyncio
async def test_image_preview_enabled_replaces_the_text_card_not_adds_to_it(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    settings.image_editorial_preview_enabled = True
    settings.image_candidate_persistence_mode = "metadata"

    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()

    with (
        patch(
            "worker.content_cycle.send_editorial_card", new=AsyncMock(),
        ) as mock_notify,
        patch(
            "worker.content_cycle.send_news_with_image_preview",
            new=AsyncMock(return_value=CombinedCardOutcome(chat_id=1, sent=True, has_image=True, candidate_count=1)),
        ) as mock_preview,
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.completed == 1
    mock_notify.assert_not_called()  # never both - the combined send is the sole delivery path here
    mock_preview.assert_called_once()
    assert "draft" in mock_preview.call_args.kwargs and "event" in mock_preview.call_args.kwargs
    assert result.notified == 1
    assert result.image_preview_sent == 1
    assert result.notification_failed == 0


@pytest.mark.asyncio
async def test_image_preview_sent_without_an_image_still_counts_as_notified_not_image_preview_sent(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    settings.image_editorial_preview_enabled = True
    settings.image_candidate_persistence_mode = "metadata"

    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()

    with (
        patch("worker.content_cycle.send_editorial_card", new=AsyncMock()) as mock_notify,
        patch(
            "worker.content_cycle.send_news_with_image_preview",
            new=AsyncMock(return_value=CombinedCardOutcome(chat_id=1, sent=True, has_image=False, candidate_count=0)),
        ),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.completed == 1
    mock_notify.assert_not_called()
    assert result.notified == 1  # a message was still sent - just text-only
    assert result.image_preview_sent == 0


@pytest.mark.asyncio
async def test_image_preview_failure_is_counted_as_notification_failed_and_never_raises(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    settings.image_editorial_preview_enabled = True
    settings.image_candidate_persistence_mode = "metadata"

    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()

    async def _broken_preview(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated preview failure")

    with (
        patch("worker.content_cycle.send_editorial_card", new=AsyncMock()) as mock_notify,
        patch("worker.content_cycle.send_news_with_image_preview", new=_broken_preview),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)  # must not raise

    assert result.completed == 1
    mock_notify.assert_not_called()  # the combined path owns delivery entirely when active - no fallback send
    assert result.notification_failed == 1
    assert result.image_preview_sent == 0


@pytest.mark.asyncio
async def test_image_preview_inert_when_persistence_mode_is_off_even_if_flag_enabled(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    settings.image_editorial_preview_enabled = True
    settings.image_candidate_persistence_mode = "off"

    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()

    with (
        patch(
            "worker.content_cycle.send_editorial_card",
            new=AsyncMock(return_value=NotificationOutcome(chat_id=1, rendered_html="<html>", sent=False)),
        ) as mock_notify,
        patch("worker.content_cycle.send_news_with_image_preview", new=AsyncMock()) as mock_preview,
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.completed == 1
    mock_notify.assert_called_once()  # falls back to the unchanged text-only path
    mock_preview.assert_not_called()
