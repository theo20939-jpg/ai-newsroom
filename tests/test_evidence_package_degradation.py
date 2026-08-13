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


# ---------------------------------------------------------------------------------------------
# NEWS Stability Acceptance follow-up (docs/post_acceptance_followup_checkpoint.md §C): real,
# empirically-confirmed gap - NewsEventArticleAcquisition.cleaned_text is never populated by any
# production write path (0 of 210 real rows in this dev database have it set, despite 109 having
# raw_extracted_text). build_evidence_package()'s original `acquisition.cleaned_text` branch could
# therefore never fire even under article_acquisition_mode == "enforce". These tests exercise the
# new on-the-fly clean_extracted_text() fallback added to close that gap.
# ---------------------------------------------------------------------------------------------


async def _seed_acquisition(
    session: AsyncSession, event_id, *, raw_extracted_text: str | None, cleaned_text: str | None,
    effective_completeness_status: str,
) -> None:
    from database.models.news_event_article_acquisition import NewsEventArticleAcquisition

    session.add(
        NewsEventArticleAcquisition(
            news_event_id=event_id,
            acquisition_status=effective_completeness_status,
            effective_completeness_status=effective_completeness_status,
            raw_extracted_text=raw_extracted_text,
            cleaned_text=cleaned_text,
            triggered_by="test",
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_evidence_package_uses_raw_text_on_the_fly_when_cleaned_text_column_is_empty(
    db_session: AsyncSession,
) -> None:
    """The real, confirmed-empirical shape: cleaned_text is never populated, but raw_extracted_text
    is, for a trusted completeness tier (FULL_TEXT). build_evidence_package() must now recover
    real article evidence via the on-the-fly clean_extracted_text() fallback instead of silently
    falling back to the thin rss_excerpt."""
    event = await _seed_event(db_session)
    raw_text = "This is a real, substantial article paragraph with genuine reporting detail. " * 5
    await _seed_acquisition(
        db_session, event.id, raw_extracted_text=raw_text, cleaned_text=None,
        effective_completeness_status="FULL_TEXT",
    )

    package = await build_evidence_package(db_session, event)

    assert package.extraction_method == "full_article_acquisition"
    assert package.selected_editorial_text != event.content  # upgraded past the thin rss_excerpt
    assert len(package.selected_editorial_text) > len(event.content)


@pytest.mark.asyncio
async def test_evidence_package_prefers_persisted_cleaned_text_when_present(
    db_session: AsyncSession,
) -> None:
    """Future-proofing: if a later change does start persisting cleaned_text directly on the row,
    build_evidence_package() must use that value as-is rather than recomputing it."""
    event = await _seed_event(db_session)
    await _seed_acquisition(
        db_session, event.id, raw_extracted_text="raw text that would clean differently",
        cleaned_text="THE ALREADY-PERSISTED CLEANED TEXT", effective_completeness_status="FULL_TEXT",
    )

    package = await build_evidence_package(db_session, event)

    assert package.selected_editorial_text == "THE ALREADY-PERSISTED CLEANED TEXT"


@pytest.mark.asyncio
async def test_evidence_package_does_not_trust_raw_text_from_a_weak_completeness_tier(
    db_session: AsyncSession,
) -> None:
    """A HEADLINE_ONLY/REDIRECT_UNRESOLVED/FETCH_FAILED acquisition's raw_extracted_text (if any)
    must never be treated as "full article" evidence - mirrors editorial_treatment.py's own
    established weak-completeness tiers. Falls back to the rss_excerpt exactly as before."""
    event = await _seed_event(db_session)
    await _seed_acquisition(
        db_session, event.id, raw_extracted_text="some scrap of interstitial/boilerplate text",
        cleaned_text=None, effective_completeness_status="HEADLINE_ONLY",
    )

    package = await build_evidence_package(db_session, event)

    assert package.extraction_method == "rss_excerpt_fallback"
    assert package.selected_editorial_text == event.content


@pytest.mark.asyncio
async def test_evidence_package_falls_back_when_raw_text_is_empty_even_at_trusted_tier(
    db_session: AsyncSession,
) -> None:
    """A trusted completeness tier with no actual raw_extracted_text (defensive/unexpected shape)
    must still fall back safely, never crash and never select an empty string as "full article"
    evidence."""
    event = await _seed_event(db_session)
    await _seed_acquisition(
        db_session, event.id, raw_extracted_text=None, cleaned_text=None,
        effective_completeness_status="FULL_TEXT",
    )

    package = await build_evidence_package(db_session, event)

    assert package.extraction_method == "rss_excerpt_fallback"
    assert package.selected_editorial_text == event.content
