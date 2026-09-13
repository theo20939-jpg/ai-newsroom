"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-CUTOVER-1 (S20): the real, durable RecoveryService,
backed by the real `recovery_jobs` table (migration a126e750c727) against a real Postgres
connection (tests/conftest.py::db_session - the dedicated pytest database, rolled back at
teardown, never `settings.database_url`)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft import ContentDraft, ContentType
from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.recovery_job import RecoveryJobState
from services.editorial_pipeline.contracts import Platform, RecoveryReasonCode
from services.editorial_pipeline.recovery_service import (
    RecoveryService,
    _next_retry_delay_seconds,
    describe_legacy_hold_for_visual_as_terminal_hold,
)

pytestmark = pytest.mark.asyncio


async def _make_content_draft(session: AsyncSession, *, suffix: str = "") -> ContentDraft:
    """A real EditorialTask -> ContentDraft chain (the FK `recovery_jobs.content_draft_id`
    requires a real row to reference) - rolled back with the rest of the test transaction."""
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


@pytest_asyncio.fixture
async def real_content_draft(db_session: AsyncSession) -> ContentDraft:
    return await _make_content_draft(db_session)


async def test_first_failure_creates_a_pending_job_with_next_retry_at_set(
    db_session: AsyncSession, real_content_draft: ContentDraft,
) -> None:
    service = RecoveryService()
    job = await service.create_or_retry(
        db_session, content_draft_id=real_content_draft.id, platform=Platform.TELEGRAM,
        reason_code=RecoveryReasonCode.NO_SUITABLE_MEDIA, failed_stage="media_research",
        last_error="no truthful candidate", max_attempts=3,
    )
    assert job.state == RecoveryJobState.PENDING
    assert job.attempt_count == 1
    assert job.max_attempts == 3
    assert job.next_retry_at is not None
    assert job.resolved_at is None
    assert job.last_error_summary == "no truthful candidate"


async def test_next_retry_at_follows_the_deterministic_backoff_schedule(
    db_session: AsyncSession, real_content_draft: ContentDraft,
) -> None:
    service = RecoveryService()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    job = await service.create_or_retry(
        db_session, content_draft_id=real_content_draft.id, platform=Platform.TELEGRAM,
        reason_code=RecoveryReasonCode.RENDER_FAILED, failed_stage="render", max_attempts=3, now=now,
    )
    assert job.next_retry_at == now + timedelta(seconds=_next_retry_delay_seconds(1))

    job2 = await service.create_or_retry(
        db_session, content_draft_id=real_content_draft.id, platform=Platform.TELEGRAM,
        reason_code=RecoveryReasonCode.RENDER_FAILED, failed_stage="render", max_attempts=3, now=now,
    )
    assert job2.id == job.id  # same open row, retried in place - not a fresh row
    assert job2.attempt_count == 2
    assert job2.state == RecoveryJobState.RETRYING
    assert job2.next_retry_at == now + timedelta(seconds=_next_retry_delay_seconds(2))


async def test_attempt_count_increments_across_repeated_failures_for_the_same_draft(
    db_session: AsyncSession, real_content_draft: ContentDraft,
) -> None:
    service = RecoveryService()
    counts = []
    for _ in range(3):
        job = await service.create_or_retry(
            db_session, content_draft_id=real_content_draft.id, platform=Platform.TELEGRAM,
            reason_code=RecoveryReasonCode.MEDIA_SEND_FAILED, failed_stage="telegram_transport", max_attempts=5,
        )
        counts.append(job.attempt_count)
    assert counts == [1, 2, 3]


async def test_max_attempts_exhausted_reaches_terminal_hold_and_stops_scheduling_retries(
    db_session: AsyncSession, real_content_draft: ContentDraft,
) -> None:
    service = RecoveryService()
    job = None
    for _ in range(3):
        job = await service.create_or_retry(
            db_session, content_draft_id=real_content_draft.id, platform=Platform.TELEGRAM,
            reason_code=RecoveryReasonCode.MEDIA_RESEARCH_TIMEOUT, failed_stage="media_research", max_attempts=3,
        )
    assert job.attempt_count == 3
    assert job.state == RecoveryJobState.TERMINAL_HOLD
    assert job.next_retry_at is None
    assert job.resolved_at is not None

    # a 4th failure for the SAME draft, after terminal, opens a genuinely NEW recovery cycle
    # (find_open_recovery only ever returns PENDING/RETRYING rows) - never revives a terminal one.
    job2 = await service.create_or_retry(
        db_session, content_draft_id=real_content_draft.id, platform=Platform.TELEGRAM,
        reason_code=RecoveryReasonCode.MEDIA_RESEARCH_TIMEOUT, failed_stage="media_research", max_attempts=3,
    )
    assert job2.id != job.id
    assert job2.attempt_count == 1
    assert job2.state == RecoveryJobState.PENDING


async def test_no_infinite_retry_state_transitions_are_strictly_bounded(
    db_session: AsyncSession, real_content_draft: ContentDraft,
) -> None:
    service = RecoveryService()
    seen_states = []
    for _ in range(10):  # far beyond max_attempts=2 - must still terminate, never loop forever
        job = await service.create_or_retry(
            db_session, content_draft_id=real_content_draft.id, platform=Platform.TELEGRAM,
            reason_code=RecoveryReasonCode.CAPTION_BUDGET_FAILED, failed_stage="caption_budget", max_attempts=2,
        )
        seen_states.append(job.state)
        if job.state == RecoveryJobState.TERMINAL_HOLD:
            break
    assert seen_states[-1] == RecoveryJobState.TERMINAL_HOLD
    assert len(seen_states) == 2  # PENDING then TERMINAL_HOLD - bounded, not unbounded


async def test_successful_retry_marks_recovered(
    db_session: AsyncSession, real_content_draft: ContentDraft,
) -> None:
    service = RecoveryService()
    job = await service.create_or_retry(
        db_session, content_draft_id=real_content_draft.id, platform=Platform.TELEGRAM,
        reason_code=RecoveryReasonCode.NO_SUITABLE_MEDIA, failed_stage="media_research", max_attempts=3,
    )
    assert job.state == RecoveryJobState.PENDING

    recovered = await service.mark_recovered(db_session, job=job)
    assert recovered.state == RecoveryJobState.RECOVERED
    assert recovered.resolved_at is not None
    assert recovered.next_retry_at is None

    # a subsequent lookup for this draft now finds no OPEN recovery - it was genuinely resolved.
    assert await service.find_open_recovery(db_session, content_draft_id=real_content_draft.id) is None


async def test_persisted_state_survives_a_fresh_service_instance_after_a_simulated_restart(
    db_session: AsyncSession, real_content_draft: ContentDraft,
) -> None:
    """S20: 'worker restart/fresh service instance -> persisted recovery state remains
    recoverable'. RecoveryService holds no state of its own - a brand-new instance reading the
    same session/row sees identical durable data, simulating a fresh process after a restart."""
    # MEDIA_SEND_FAILED (a bounded-retryable, non-forced-terminal reason code) - this test's own
    # concern is fresh-instance persistence, not AMBIGUOUS_TRANSPORT_RESULT's own FINAL-HARDENING-1
    # always-terminal behavior (covered separately, see
    # tests/test_unified_pipeline_final_hardening_1.py).
    service_before_restart = RecoveryService()
    job = await service_before_restart.create_or_retry(
        db_session, content_draft_id=real_content_draft.id, platform=Platform.TELEGRAM,
        reason_code=RecoveryReasonCode.MEDIA_SEND_FAILED, failed_stage="telegram_transport", max_attempts=3,
    )
    job_id = job.id

    # A fresh instance - nothing carried over from the one above except the durable row itself.
    service_after_restart = RecoveryService()
    reloaded = await service_after_restart.get(db_session, recovery_job_id=job_id)
    assert reloaded is not None
    assert reloaded.state == RecoveryJobState.PENDING
    assert reloaded.attempt_count == 1
    assert reloaded.reason_code.value == "MEDIA_SEND_FAILED"

    found_open = await service_after_restart.find_open_recovery(db_session, content_draft_id=real_content_draft.id)
    assert found_open is not None
    assert found_open.id == job_id


async def test_due_for_retry_only_returns_rows_whose_next_retry_at_has_passed(
    db_session: AsyncSession, real_content_draft: ContentDraft,
) -> None:
    service = RecoveryService()
    past = datetime.now(timezone.utc) - timedelta(days=1)
    job = await service.create_or_retry(
        db_session, content_draft_id=real_content_draft.id, platform=Platform.TELEGRAM,
        reason_code=RecoveryReasonCode.RENDER_FAILED, failed_stage="render", max_attempts=3, now=past,
    )
    due = await service.due_for_retry(db_session)
    assert any(row.id == job.id for row in due)

    other_draft = await _make_content_draft(db_session, suffix="2")

    future = datetime.now(timezone.utc) + timedelta(days=1)
    not_yet_due_job = await service.create_or_retry(
        db_session, content_draft_id=other_draft.id, platform=Platform.TELEGRAM,
        reason_code=RecoveryReasonCode.RENDER_FAILED, failed_stage="render", max_attempts=3, now=future,
    )
    due_again = await service.due_for_retry(db_session)
    assert not any(row.id == not_yet_due_job.id for row in due_again)


async def test_legacy_hold_for_visual_compatibility_mapping_never_writes_anything() -> None:
    """S10: a pure, read-only description - never a real recovery_jobs row, never a send/retry
    decision of its own."""
    draft_id = uuid.uuid4()
    description = describe_legacy_hold_for_visual_as_terminal_hold(content_draft_id=draft_id)
    assert description["state"] == RecoveryJobState.TERMINAL_HOLD.value
    assert description["terminal"] is True
    assert description["reason_code"] == "LEGACY_HOLD_FOR_VISUAL"
    assert description["content_draft_id"] == str(draft_id)
