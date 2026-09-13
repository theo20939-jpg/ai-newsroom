"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-FINAL-HARDENING-1 §11-§15: hardened
`AMBIGUOUS_TRANSPORT_RESULT` semantics. Founder invariant: "UNKNOWN ACCEPTANCE MUST NEVER TRIGGER
AUTOMATIC RESEND" - a duplicate published post is worse than a HOLD.

Uses the EXISTING recovery architecture (`services.editorial_pipeline.recovery_service.
RecoveryService`) - no new retry subsystem is built or exercised here (§15's own explicit
instruction: "Do NOT build one in this phase"). These tests only prove the DOMAIN RULE is safe
before any such consumer could ever be added.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft import ContentDraft, ContentType
from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.recovery_job import RecoveryJobState
from schemas.editorial_route import EditorialDestination
from services.editorial_pipeline.contracts import Platform, RecoveryReasonCode
from services.editorial_pipeline.recovery_service import RecoveryService
from services.telegram_routing import send_photo_to_editorial_destination

pytestmark = pytest.mark.asyncio

_REAL_CHAT_ID = -1004297182444
_REAL_NEWS_TOPIC_ID = 2


async def _make_content_draft(session: AsyncSession, *, suffix: str = "") -> ContentDraft:
    source = NewsSource(name=f"RS{suffix}", type=SourceType.RSS, url=f"https://example.com/rs{suffix}.xml", active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(
        source_id=source.id, title=f"T{suffix}", content=f"C{suffix}", category=EventCategory.AI,
        hash=f"h{suffix}-{uuid.uuid4()}",
    )
    session.add(event)
    await session.flush()
    task = EditorialTask(event_id=event.id, priority=TaskPriority.B)
    session.add(task)
    await session.flush()
    draft = ContentDraft(task_id=task.id, type=ContentType.POST, title=f"T{suffix}", body=f"B{suffix}", status="draft")
    session.add(draft)
    await session.flush()
    return draft


@pytest.fixture
def fake_bot(monkeypatch: pytest.MonkeyPatch):
    from core.config import settings

    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _REAL_CHAT_ID)
    monkeypatch.setattr(settings, "news_topic_id", _REAL_NEWS_TOPIC_ID)
    return AsyncMock()


# ---------------------------------------------------------------------------
# A. send succeeds -> SENT -> no recovery job requiring resend
# ---------------------------------------------------------------------------


async def test_a_send_succeeds_no_recovery_job_created(fake_bot, db_session: AsyncSession) -> None:
    draft = await _make_content_draft(db_session)
    fake_bot.send_photo.return_value.message_id = 111

    outcome = await send_photo_to_editorial_destination(
        fake_bot, EditorialDestination.NEWS, "file-id", "caption", dry_run=False,
    )
    assert outcome.sent is True
    assert outcome.ambiguous is False

    service = RecoveryService()
    assert await service.find_open_recovery(db_session, content_draft_id=draft.id) is None


# ---------------------------------------------------------------------------
# B. definite pre-acceptance failure -> normal recoverable (bounded-retry) failure behavior
# ---------------------------------------------------------------------------


async def test_b_definite_failure_is_bounded_retryable_not_forced_terminal(fake_bot, db_session: AsyncSession) -> None:
    draft = await _make_content_draft(db_session)
    fake_bot.send_photo.side_effect = TelegramAPIError(method=None, message="Bad Request: chat not found")  # type: ignore[arg-type]

    outcome = await send_photo_to_editorial_destination(
        fake_bot, EditorialDestination.NEWS, "file-id", "caption", dry_run=False,
    )
    assert outcome.sent is False
    assert outcome.ambiguous is False

    service = RecoveryService()
    row = await service.create_or_retry(
        db_session, content_draft_id=draft.id, platform=Platform.TELEGRAM,
        reason_code=RecoveryReasonCode.MEDIA_SEND_FAILED, failed_stage="telegram_transport",
        last_error=outcome.reason,
    )
    assert row.state == RecoveryJobState.PENDING  # normal bounded-retry semantics, NOT forced terminal
    assert row.max_attempts == 3
    assert row.next_retry_at is not None


# ---------------------------------------------------------------------------
# C. timeout / unknown acceptance -> AMBIGUOUS_TRANSPORT_RESULT -> persisted -> resend forbidden
# ---------------------------------------------------------------------------


async def test_c_ambiguous_timeout_is_persisted_terminal_never_bounded_retryable(fake_bot, db_session: AsyncSession) -> None:
    draft = await _make_content_draft(db_session)
    fake_bot.send_photo.side_effect = TelegramAPIError(method=None, message="Request timeout error")  # type: ignore[arg-type]

    outcome = await send_photo_to_editorial_destination(
        fake_bot, EditorialDestination.NEWS, "file-id", "caption", dry_run=False,
    )
    assert outcome.sent is False
    assert outcome.ambiguous is True

    service = RecoveryService()
    row = await service.create_or_retry(
        db_session, content_draft_id=draft.id, platform=Platform.TELEGRAM,
        reason_code=RecoveryReasonCode.AMBIGUOUS_TRANSPORT_RESULT, failed_stage="telegram_transport",
        last_error=outcome.reason,
    )
    assert row.state == RecoveryJobState.TERMINAL_HOLD  # forced terminal on the FIRST occurrence
    assert row.next_retry_at is None
    assert row.max_attempts == 1
    assert row.resolved_at is not None

    # "automatic resend forbidden": the row is durably persisted (queryable directly), but
    # structurally invisible to the one query a retry-consumer would ever use to find work.
    assert await service.find_open_recovery(db_session, content_draft_id=draft.id) is None
    assert row not in await service.due_for_retry(db_session)


# ---------------------------------------------------------------------------
# D. a future generic RecoveryService retry method invoked on an ambiguous job must not produce
#    a send attempt
# ---------------------------------------------------------------------------


async def test_d_due_for_retry_never_returns_an_ambiguous_terminal_row(db_session: AsyncSession) -> None:
    draft = await _make_content_draft(db_session)
    service = RecoveryService()
    row = await service.create_or_retry(
        db_session, content_draft_id=draft.id, platform=Platform.TELEGRAM,
        reason_code=RecoveryReasonCode.AMBIGUOUS_TRANSPORT_RESULT, failed_stage="telegram_transport",
        last_error="Request timeout error",
    )
    assert row.state == RecoveryJobState.TERMINAL_HOLD

    # `due_for_retry()` IS the query a future retry-consumer would call - proving it never surfaces
    # this row is the domain-level guarantee that no send attempt could ever result from it, without
    # this phase building (or needing to build) any actual consumer.
    due = await service.due_for_retry(db_session)
    assert row.id not in {r.id for r in due}


# ---------------------------------------------------------------------------
# E. multiple processing passes over the same ambiguous recovery job -> zero duplicate sends
# ---------------------------------------------------------------------------


async def test_e_repeated_processing_of_the_same_ambiguous_job_never_reopens_it(
    fake_bot, db_session: AsyncSession,
) -> None:
    draft = await _make_content_draft(db_session)
    service = RecoveryService()
    AMBIGUOUS_AUTO_RESEND_COUNT = 0

    first = await service.create_or_retry(
        db_session, content_draft_id=draft.id, platform=Platform.TELEGRAM,
        reason_code=RecoveryReasonCode.AMBIGUOUS_TRANSPORT_RESULT, failed_stage="telegram_transport",
        last_error="Request timeout error",
    )
    assert first.state == RecoveryJobState.TERMINAL_HOLD

    # Simulate several later "processing passes" (e.g. a hypothetical scheduler waking up
    # repeatedly) - each one first checks find_open_recovery()/due_for_retry() as any real
    # consumer would, and (since this phase builds no consumer) never calls a send function itself.
    for _ in range(5):
        open_job = await service.find_open_recovery(db_session, content_draft_id=draft.id)
        due = await service.due_for_retry(db_session)
        assert open_job is None
        assert first.id not in {r.id for r in due}
        if open_job is not None:  # dead code if the invariant holds - documents the guard explicitly
            await fake_bot.send_photo()
            AMBIGUOUS_AUTO_RESEND_COUNT += 1

    assert AMBIGUOUS_AUTO_RESEND_COUNT == 0
    fake_bot.send_photo.assert_not_called()

    reloaded = await service.get(db_session, recovery_job_id=first.id)
    assert reloaded is not None
    assert reloaded.state == RecoveryJobState.TERMINAL_HOLD  # never drifted back to PENDING/RETRYING
