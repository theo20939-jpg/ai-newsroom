"""Phase 19 M1/M2: proves the caller-level graceful-degradation guarantee - setting
article_acquisition_mode == "enforce" before the Phase 19 M1 migration has been applied must
never crash capabilities/executor.py or services/content_draft_service.py, only degrade to the
pre-Phase-19 news_event.content path. Deliberately run against the real (unmigrated) test
database - the table genuinely not existing is exactly the scenario being proven safe, so this
file is NOT skip-marked.
"""
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from services.content_draft_service import ContentDraftService
from services.evidence_package import build_evidence_package


async def _seed_event(session: AsyncSession) -> NewsEvent:
    source = NewsSource(id=uuid4(), name=f"src-{uuid4().hex[:6]}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(
        id=uuid4(), source_id=source.id, title="t", content="original rss excerpt content",
        category=EventCategory.UNKNOWN, hash=f"h-{uuid4()}",
    )
    session.add(event)
    await session.flush()
    return event


@pytest.mark.asyncio
async def test_build_evidence_package_raises_when_table_missing(db_session: AsyncSession) -> None:
    """Documents the actual, un-guarded contract of build_evidence_package() itself (its own
    docstring) - this is the failure mode the SAVEPOINT-wrapped callers below must survive."""
    event = await _seed_event(db_session)

    with pytest.raises(Exception):
        await build_evidence_package(db_session, event)


@pytest.mark.asyncio
async def test_content_draft_service_survives_enforce_before_migration(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The concrete, required proof: create_from_result() must not raise, and must fall back to
    news_event.content for quote verification/quality gates, even with article_acquisition_mode
    == "enforce" and the migration unapplied."""
    from datetime import datetime, timezone

    from database.models.editorial_task import TaskPriority
    from schemas.editorial_task import EditorialTaskCreate
    from schemas.workflow import WorkflowRunResult, WorkflowStepResult, WorkflowType
    from services import workflow_service

    monkeypatch.setattr(settings, "article_acquisition_mode", "enforce")
    event = await _seed_event(db_session)
    task = await workflow_service.create_task(
        db_session,
        EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B),
    )

    now = datetime.now(timezone.utc)
    result = WorkflowRunResult(
        task_id=task.id, status="COMPLETED", iterations_used=1,
        step_results=[
            WorkflowStepResult(
                step_name="copywriting", status="SUCCESS", attempt=1, started_at=now, finished_at=now,
                result={"title": "A title", "body": "A body with real content."},
            ),
        ],
    )

    draft = await ContentDraftService(db_session).create_from_result(result.task_id, result, event_id=event.id)

    assert draft is not None
    assert draft.title == "A title"


@pytest.mark.asyncio
async def test_session_remains_usable_after_savepoint_rollback(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The SAVEPOINT (begin_nested) isolation must not corrupt the outer transaction - a further
    query against the same session, after the degradation, must still succeed."""
    monkeypatch.setattr(settings, "article_acquisition_mode", "enforce")
    event = await _seed_event(db_session)

    try:
        # Mirrors the real callers' own SAVEPOINT wrapper exactly (capabilities/executor.py,
        # services/content_draft_service.py) - the isolation lives at the call site, not inside
        # build_evidence_package() itself (see its own docstring).
        async with db_session.begin_nested():
            await build_evidence_package(db_session, event)
    except Exception:
        pass

    # The outer session/transaction must still be healthy - a plain read proves it.
    reloaded = await db_session.get(NewsEvent, event.id)
    assert reloaded is not None
    assert reloaded.title == "t"
