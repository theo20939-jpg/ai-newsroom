"""TELEGRAM-TEXT-ONLY-VISUAL-FALLBACK-REPAIR-1: direct, isolated coverage for
`worker.content_cycle._hold_for_visual_recovery()` - the one new function this repair adds.

The full router-mode integration coverage for the two real production failure classes (no visual
resolved at all; a resolved visual's Telegram send itself failing) lives in
tests/test_router_media_integration.py (updated in this same phase - see e.g.
`test_case_b_no_image_candidates_holds_for_visual_recovery`,
`test_photo_timeout_holds_for_visual_recovery_instead_of_text_fallback`) and
tests/test_content_cycle_story_delivery.py (updated the same way). BREAKING/DATA/QUOTE render
failures reach the exact same gate via the pre-existing "demote to NEWS" fail-safe
(worker/content_cycle.py's own `elif presentation_decision.presentation_type in (PRESENTATION_
DATA, PRESENTATION_QUOTE, PRESENTATION_BREAKING): ... reason="brand_render_failed_demoted_to_
news"` - the demoted post then flows through the identical downstream `had_any_visual` check
those NEWS-shaped tests already prove) - not duplicated here as a separate full pipeline test.

This file covers, in isolation:
- the DB persistence (content_drafts.status -> HOLD_FOR_VISUAL_STATUS), never losing the
  editorial content itself;
- the recovery notice's shape (no keyboard, distinct "warning" prefix, plain send_message);
- dry_run is fully respected (no DB write, no send);
- a genuinely non-editorial (system/operator) message sent via the plain
  send_to_editorial_destination() function directly is completely unaffected by this repair -
  the gate lives entirely inside worker.content_cycle's own router-mode block, never inside
  send_to_editorial_destination() itself.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from database.models.content_draft import ContentDraft, ContentType
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from schemas.editorial_route import EditorialDestination
from services.telegram_routing import send_to_editorial_destination
from tests.test_content_worker_cycle import factory  # noqa: F401,F811 - a pytest fixture, reused as a parameter name below
from worker.content_cycle import (
    HOLD_FOR_VISUAL_STATUS,
    HOLD_REASON_MEDIA_SEND_FAILED,
    HOLD_REASON_NO_VISUAL_RESOLVED,
    _hold_for_visual_recovery,
)

pytestmark = pytest.mark.asyncio

# Same fixed test-only chat id tests/test_router_media_integration.py uses elsewhere in this
# suite - resolve_route() requires a configured chat id or every send is a safe no-op
# ("unconfigured_destination"), which is correct production behavior but not what these tests
# are isolating.
_REAL_CHAT_ID = -1004297182444


async def _seed_draft(factory: async_sessionmaker[AsyncSession]) -> tuple[NewsEvent, ContentDraft]:  # noqa: F811
    async with factory() as session:
        source = NewsSource(id=uuid4(), name="test-source", type=SourceType.RSS, active=True)
        session.add(source)
        await session.flush()
        event = NewsEvent(
            id=uuid4(), source_id=source.id, title="Заголовок без визуала", url="https://example.com/a",
            category=EventCategory.AI, hash=str(uuid4()), published_at=datetime.now(timezone.utc),
        )
        session.add(event)
        await session.flush()
        task = EditorialTask(
            id=uuid4(), event_id=event.id, status=TaskStatus.COMPLETED, priority=TaskPriority.B,
            workflow={"workflow_name": "CONTENT_GENERATION", "step_results": []},
        )
        session.add(task)
        await session.flush()
        draft = ContentDraft(
            id=uuid4(), task_id=task.id, type=ContentType.POST, title=event.title,
            body="Полный текст материала, который нельзя терять.", version=1, status="draft",
        )
        session.add(draft)
        await session.commit()
        await session.refresh(draft)
        return event, draft


async def test_hold_persists_status_and_never_loses_the_body(
    factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    event, draft = await _seed_draft(factory)
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 1

    await _hold_for_visual_recovery(
        factory, bot,
        draft_id=draft.id, event=event, presentation_type="NEWS",
        reason=HOLD_REASON_NO_VISUAL_RESOLVED, dry_run=False,
    )

    async with factory() as session:
        refreshed = (await session.execute(select(ContentDraft).where(ContentDraft.id == draft.id))).scalar_one()
        assert refreshed.status == HOLD_FOR_VISUAL_STATUS
        assert refreshed.body == "Полный текст материала, который нельзя терять."  # never lost
        assert refreshed.title == event.title


async def test_hold_notice_has_no_keyboard_and_is_clearly_marked(
    factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _REAL_CHAT_ID)
    event, draft = await _seed_draft(factory)
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 2

    await _hold_for_visual_recovery(
        factory, bot,
        draft_id=draft.id, event=event, presentation_type="DATA",
        reason=HOLD_REASON_MEDIA_SEND_FAILED, dry_run=False,
    )

    bot.send_message.assert_called_once()
    args, kwargs = bot.send_message.call_args
    assert kwargs["reply_markup"] is None
    assert "⚠️" in args[1]
    assert event.title in args[1]
    assert "DATA" in args[1]


async def test_hold_respects_dry_run_no_write_no_send(
    factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    event, draft = await _seed_draft(factory)
    bot = AsyncMock()

    await _hold_for_visual_recovery(
        factory, bot,
        draft_id=draft.id, event=event, presentation_type="NEWS",
        reason=HOLD_REASON_NO_VISUAL_RESOLVED, dry_run=True,
    )

    bot.send_message.assert_not_called()


async def test_hold_survives_the_notice_send_itself_failing(
    factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """The DB status write (the durable record) must not depend on the best-effort notice
    reaching Telegram - send_to_editorial_destination() already catches TelegramAPIError
    internally and returns sent=False rather than raising (services/telegram_routing.py's own
    established contract), so this never raises here either."""
    from aiogram.exceptions import TelegramAPIError

    event, draft = await _seed_draft(factory)
    bot = AsyncMock()
    bot.send_message.side_effect = TelegramAPIError(method=None, message="boom")  # type: ignore[arg-type]

    await _hold_for_visual_recovery(  # must not raise
        factory, bot,
        draft_id=draft.id, event=event, presentation_type="QUOTE",
        reason=HOLD_REASON_NO_VISUAL_RESOLVED, dry_run=False,
    )

    async with factory() as session:
        refreshed = (await session.execute(select(ContentDraft).where(ContentDraft.id == draft.id))).scalar_one()
        assert refreshed.status == HOLD_FOR_VISUAL_STATUS


async def test_system_message_via_send_to_editorial_destination_directly_is_unaffected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate this repair adds lives entirely inside worker.content_cycle's own router-mode
    NEWS/BREAKING/DATA/QUOTE block - send_to_editorial_destination() itself (the shared transport
    every non-editorial system/operator/debug message also uses, per the Founder invariant's own
    explicit carve-out) is completely untouched: a direct call still sends plain text exactly as
    before, keyboard and all, with no HOLD gate anywhere near it."""
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _REAL_CHAT_ID)
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 99

    outcome = await send_to_editorial_destination(
        bot, EditorialDestination.NEWS, "🛠 system status: worker restarted cleanly",
        dry_run=False, reply_markup=None,
    )

    assert outcome.sent is True
    bot.send_message.assert_called_once()
