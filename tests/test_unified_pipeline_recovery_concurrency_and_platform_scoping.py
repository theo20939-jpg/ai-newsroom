"""UNIFIED-EDITORIAL-PIPELINE-RUNTIME-CLOSURE-1 (S22/S23) - replays R11/R12: recovery lifecycle
identity must be scoped by (content_draft_id, platform), and creating two concurrent open recovery
lifecycles for the SAME identity must be impossible at the database level, not merely discouraged
by application-level convention."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft import ContentDraft, ContentType
from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.recovery_job import RecoveryJob as RecoveryJobRow
from database.models.recovery_job import RecoveryJobState
from services.editorial_pipeline.contracts import Platform, RecoveryReasonCode
from services.editorial_pipeline.recovery_service import RecoveryService

pytestmark = pytest.mark.asyncio


async def _make_content_draft(session: AsyncSession) -> ContentDraft:
    source = NewsSource(name="RS", type=SourceType.RSS, url=f"https://example.com/{uuid.uuid4()}.xml", active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(source_id=source.id, title="T", content="C", category=EventCategory.AI, hash=f"h-{uuid.uuid4()}")
    session.add(event)
    await session.flush()
    task = EditorialTask(event_id=event.id, priority=TaskPriority.B)
    session.add(task)
    await session.flush()
    draft = ContentDraft(task_id=task.id, type=ContentType.POST, title="T", body="B", status="draft")
    session.add(draft)
    await session.flush()
    return draft


@pytest_asyncio.fixture
async def real_content_draft(db_session: AsyncSession) -> ContentDraft:
    return await _make_content_draft(db_session)


# ---------------------------------------------------------------------------
# R12: distinct platform recovery identity for the SAME draft.
# ---------------------------------------------------------------------------


async def test_telegram_and_instagram_recoveries_for_the_same_draft_are_distinct_rows(
    db_session: AsyncSession, real_content_draft: ContentDraft,
) -> None:
    """Before RUNTIME-CLOSURE-1, `find_open_recovery()` looked up by `content_draft_id` alone - a
    Telegram failure for this draft could accidentally find/increment an Instagram recovery row
    for the SAME draft (or vice versa). This must be structurally impossible now."""
    service = RecoveryService()
    telegram_job = await service.create_or_retry(
        db_session, content_draft_id=real_content_draft.id, platform=Platform.TELEGRAM,
        reason_code=RecoveryReasonCode.NO_SUITABLE_MEDIA, failed_stage="media_research",
    )
    instagram_job = await service.create_or_retry(
        db_session, content_draft_id=real_content_draft.id, platform=Platform.INSTAGRAM,
        reason_code=RecoveryReasonCode.NO_SUITABLE_MEDIA, failed_stage="media_research",
    )

    assert telegram_job.id != instagram_job.id
    assert telegram_job.attempt_count == 1
    assert instagram_job.attempt_count == 1  # NOT incremented to 2 - a real, separate lifecycle

    telegram_open = await service.find_open_recovery(db_session, content_draft_id=real_content_draft.id, platform=Platform.TELEGRAM)
    instagram_open = await service.find_open_recovery(db_session, content_draft_id=real_content_draft.id, platform=Platform.INSTAGRAM)
    assert telegram_open is not None and telegram_open.id == telegram_job.id
    assert instagram_open is not None and instagram_open.id == instagram_job.id

    # A second Telegram failure retries the TELEGRAM row only - the Instagram row is untouched.
    telegram_job_2 = await service.create_or_retry(
        db_session, content_draft_id=real_content_draft.id, platform=Platform.TELEGRAM,
        reason_code=RecoveryReasonCode.RENDER_FAILED, failed_stage="render",
    )
    assert telegram_job_2.id == telegram_job.id
    assert telegram_job_2.attempt_count == 2
    reloaded_instagram = await service.get(db_session, recovery_job_id=instagram_job.id)
    assert reloaded_instagram is not None
    assert reloaded_instagram.attempt_count == 1  # unaffected by the Telegram retry


# ---------------------------------------------------------------------------
# R11: concurrency safety - two "simultaneous" attempts to open a recovery lifecycle for the
# IDENTICAL (content_draft_id, platform) identity must converge to exactly one open row, never two.
# ---------------------------------------------------------------------------


async def test_concurrent_create_or_retry_for_the_same_identity_converges_to_one_open_row(
    db_session: AsyncSession, real_content_draft: ContentDraft, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulates the real race `services.editorial_pipeline.recovery_service.RecoveryService.
    create_or_retry()`'s own docstring describes: two callers both call `find_open_recovery()` and
    both see nothing open (neither has committed yet), so both proceed to INSERT a fresh row for
    the exact same (content_draft_id, platform) identity. The real, DB-level partial unique index
    (`ix_recovery_jobs_open_lifecycle_identity`, migration c48f6a1e9d02) must reject the second
    insert, and `create_or_retry()` must recover from that conflict by incrementing the row that
    won, never crash and never leave two open rows behind.

    `find_open_recovery` is monkeypatched to return `None` on its FIRST call only (simulating the
    real race window - both callers reading before either writes) - every call after that uses the
    REAL, unmodified implementation, so the actual conflict-recovery code path
    (`except IntegrityError` inside `create_or_retry()`) is what is genuinely exercised here, not a
    mocked outcome."""
    service = RecoveryService()
    real_find_open_recovery = RecoveryService.find_open_recovery
    call_count = {"n": 0}

    async def _find_open_recovery_first_call_sees_nothing(self, session, *, content_draft_id, platform=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return None  # simulates the race: the OTHER "concurrent" caller's insert hasn't
            # landed yet from this caller's point of view.
        return await real_find_open_recovery(self, session, content_draft_id=content_draft_id, platform=platform)

    monkeypatch.setattr(RecoveryService, "find_open_recovery", _find_open_recovery_first_call_sees_nothing)

    # The "other" concurrent caller's row - inserted directly (bypassing create_or_retry()'s own
    # find-first check), exactly modeling a second transaction that committed first.
    winner = RecoveryJobRow(
        id=uuid.uuid4(), content_draft_id=real_content_draft.id, platform=Platform.TELEGRAM.value,
        reason_code=RecoveryReasonCode.NO_SUITABLE_MEDIA.value, failed_stage="media_research",
        state=RecoveryJobState.PENDING, attempt_count=1, max_attempts=3,
        next_retry_at=datetime.now(timezone.utc),
    )
    db_session.add(winner)
    await db_session.flush()

    # This call's own find_open_recovery() (the patched, first-call-sees-nothing version) reports
    # nothing open, so create_or_retry() proceeds to INSERT a second row for the SAME identity -
    # exactly the race. The real partial unique index must reject it, and the real
    # `except IntegrityError` branch must recover by finding and incrementing `winner` instead.
    result = await service.create_or_retry(
        db_session, content_draft_id=real_content_draft.id, platform=Platform.TELEGRAM,
        reason_code=RecoveryReasonCode.RENDER_FAILED, failed_stage="render",
    )

    assert result.id == winner.id  # converged onto the row that "won" the race, never a duplicate
    assert result.attempt_count == 2  # a real increment, not a fresh attempt_count=1

    open_rows = await db_session.execute(
        RecoveryJobRow.__table__.select().where(
            RecoveryJobRow.content_draft_id == real_content_draft.id,
            RecoveryJobRow.platform == Platform.TELEGRAM.value,
            RecoveryJobRow.state.in_([RecoveryJobState.PENDING, RecoveryJobState.RETRYING]),
        )
    )
    assert len(open_rows.fetchall()) == 1  # exactly one open lifecycle survives, never two
