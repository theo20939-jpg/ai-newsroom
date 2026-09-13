"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-CUTOVER-1 (S5/S9/S13/S20): the orchestrator's new,
additive cutover behavior - durable recovery persistence, `require_media`/`NO_SUITABLE_MEDIA`,
`MEDIA_RESEARCH_TIMEOUT`, and the four-way `OrchestratorVerdict`. Every pre-existing test in
tests/test_editorial_pipeline_orchestrator.py continues to pass unmodified (verified separately) -
this file only exercises what is NEW."""
from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft import ContentDraft, ContentType
from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.recovery_job import RecoveryJobState
from services.editorial_pipeline.contracts import OrchestratorVerdict, Platform, PresentationFormat
from services.editorial_pipeline.evidence import build_evidence_pack
from services.editorial_pipeline.orchestrator import run_editorial_production_pipeline
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


async def _render_success(composition_plan, structured_content):
    return "photo", f"<b>{getattr(structured_content, 'headline', 'x')}</b>"


async def _render_none(composition_plan, structured_content):
    return None


async def test_durable_path_render_failure_persists_a_real_recovery_row_and_returns_retry(
    db_session: AsyncSession,
) -> None:
    draft = await _make_content_draft(db_session)
    evidence = build_evidence_pack(news_event_id=uuid.uuid4(), story_id=None, source_url=None, research_facts=[])
    recovery_service = RecoveryService()

    result = await run_editorial_production_pipeline(
        content_draft_id=draft.id, presentation_format=PresentationFormat.NEWS, title="Title",
        main_body="Body", evidence=evidence, platform=Platform.TELEGRAM, render=_render_none,
        session=db_session, recovery_service=recovery_service,
    )

    assert not result.is_ready
    assert result.verdict == OrchestratorVerdict.RETRY
    assert result.persisted_recovery_job_id is not None
    assert result.next_retry_at is not None

    row = await recovery_service.get(db_session, recovery_job_id=result.persisted_recovery_job_id)
    assert row is not None
    assert row.state == RecoveryJobState.PENDING
    assert row.reason_code.value == "RENDER_FAILED"
    assert row.attempt_count == 1


async def test_quality_gate_failure_is_terminal_on_first_failure_and_maps_to_block(
    db_session: AsyncSession,
) -> None:
    draft = await _make_content_draft(db_session)
    evidence = build_evidence_pack(
        news_event_id=uuid.uuid4(), story_id=None, source_url=None,
        research_facts=["Рекомендованная цена автомобиля начинается с 290 тыс. юаней."],
    )
    recovery_service = RecoveryService()

    async def render_with_defect(composition_plan, structured_content):
        return "photo", "Рекомендованная цена автомобиля начинается с юаней."

    result = await run_editorial_production_pipeline(
        content_draft_id=draft.id, presentation_format=PresentationFormat.DATA,
        title="Представлен минивэн SAIC Maxus 9 2027", main_body="SAIC представила минивэн.",
        evidence=evidence, platform=Platform.TELEGRAM, render=render_with_defect,
        session=db_session, recovery_service=recovery_service,
    )

    assert not result.is_ready
    assert result.verdict == OrchestratorVerdict.BLOCK
    row = await recovery_service.get(db_session, recovery_job_id=result.persisted_recovery_job_id)
    assert row is not None
    assert row.state == RecoveryJobState.TERMINAL_HOLD  # quality failures never bounded-retried
    assert row.max_attempts == 1


async def test_retrying_the_same_draft_increments_the_durable_row_instead_of_creating_a_new_one(
    db_session: AsyncSession,
) -> None:
    draft = await _make_content_draft(db_session)
    evidence = build_evidence_pack(news_event_id=uuid.uuid4(), story_id=None, source_url=None, research_facts=[])
    recovery_service = RecoveryService()

    first = await run_editorial_production_pipeline(
        content_draft_id=draft.id, presentation_format=PresentationFormat.NEWS, title="Title",
        main_body="Body", evidence=evidence, platform=Platform.TELEGRAM, render=_render_none,
        session=db_session, recovery_service=recovery_service,
    )
    second = await run_editorial_production_pipeline(
        content_draft_id=draft.id, presentation_format=PresentationFormat.NEWS, title="Title",
        main_body="Body", evidence=evidence, platform=Platform.TELEGRAM, render=_render_none,
        session=db_session, recovery_service=recovery_service,
    )

    assert first.persisted_recovery_job_id == second.persisted_recovery_job_id
    row = await recovery_service.get(db_session, recovery_job_id=second.persisted_recovery_job_id)
    assert row.attempt_count == 2
    assert row.state == RecoveryJobState.RETRYING
    assert second.verdict == OrchestratorVerdict.RETRY  # still not exhausted (default max_attempts=3)


async def test_a_later_successful_run_can_mark_the_open_recovery_recovered(
    db_session: AsyncSession,
) -> None:
    draft = await _make_content_draft(db_session)
    evidence = build_evidence_pack(news_event_id=uuid.uuid4(), story_id=None, source_url=None, research_facts=["a fact"])
    recovery_service = RecoveryService()

    failed = await run_editorial_production_pipeline(
        content_draft_id=draft.id, presentation_format=PresentationFormat.NEWS, title="Title",
        main_body="Body", evidence=evidence, platform=Platform.TELEGRAM, render=_render_none,
        session=db_session, recovery_service=recovery_service,
    )
    assert failed.verdict == OrchestratorVerdict.RETRY
    open_job = await recovery_service.find_open_recovery(db_session, content_draft_id=draft.id)
    assert open_job is not None

    succeeded = await run_editorial_production_pipeline(
        content_draft_id=draft.id, presentation_format=PresentationFormat.NEWS, title="Title",
        main_body="Body", evidence=evidence, platform=Platform.TELEGRAM, render=_render_success,
        session=db_session, recovery_service=recovery_service,
    )
    assert succeeded.is_ready
    # the orchestrator itself does not auto-resolve a prior open job on a later success (the
    # worker integration layer owns that decision, per its own dedicated test) - this test only
    # proves mark_recovered() itself, called explicitly here, produces the real transition.
    recovered = await recovery_service.mark_recovered(db_session, job=open_job)
    assert recovered.state == RecoveryJobState.RECOVERED


async def test_require_media_true_holds_news_without_a_render_attempt_when_no_candidate_resolves(
    db_session: AsyncSession,
) -> None:
    draft = await _make_content_draft(db_session)
    evidence = build_evidence_pack(news_event_id=uuid.uuid4(), story_id=None, source_url=None, research_facts=[])
    recovery_service = RecoveryService()
    render_calls = []

    async def render_that_must_never_be_called(composition_plan, structured_content):
        render_calls.append(1)
        return "photo", "should never happen"

    result = await run_editorial_production_pipeline(
        content_draft_id=draft.id, presentation_format=PresentationFormat.NEWS, title="Title",
        main_body="Body", evidence=evidence, platform=Platform.TELEGRAM, render=render_that_must_never_be_called,
        session=db_session, recovery_service=recovery_service, require_media=True,
    )

    assert not result.is_ready
    assert render_calls == []  # never even attempted - the whole point of require_media
    row = await recovery_service.get(db_session, recovery_job_id=result.persisted_recovery_job_id)
    assert row.reason_code.value == "NO_SUITABLE_MEDIA"
    assert row.failed_stage == "media_research"


async def test_require_media_false_still_allows_a_text_appropriate_ready_package(
    db_session: AsyncSession,
) -> None:
    """The pre-existing, more general contract (default require_media=False) must survive even
    with a durable session/recovery_service supplied - require_media is opt-in, not automatic."""
    draft = await _make_content_draft(db_session)
    evidence = build_evidence_pack(news_event_id=uuid.uuid4(), story_id=None, source_url=None, research_facts=["fact"])
    recovery_service = RecoveryService()

    async def render_text_only(composition_plan, structured_content):
        return None, f"<b>{structured_content.headline}</b>\nBody"

    result = await run_editorial_production_pipeline(
        content_draft_id=draft.id, presentation_format=PresentationFormat.NEWS, title="Operator update",
        main_body="Body", evidence=evidence, platform=Platform.TELEGRAM, render=render_text_only,
        session=db_session, recovery_service=recovery_service,  # require_media defaults False
    )
    assert result.is_ready
    assert result.verdict == OrchestratorVerdict.READY


async def test_require_media_true_data_format_never_triggers_no_suitable_media(
    db_session: AsyncSession,
) -> None:
    """DATA's own DATA_TYPOGRAPHIC composition strategy is a legitimate no-media outcome - the
    require_media gate must never fire for DATA. Reuses the exact real Maxus fixture text from
    tests/test_editorial_pipeline_orchestrator.py (the one combination already proven to make
    build_structured_data_content() extract a real StructuredDataContent)."""
    draft = await _make_content_draft(db_session)
    maxus_fact = "Рекомендованная цена автомобиля начинается с 290 тыс. юаней (примерно 3,8 млн рублей)."
    maxus_title = "Представлен минивэн SAIC Maxus 9 2027 с заменой батареи за 90 секунд"
    maxus_body = (
        "SAIC представила минивэн Maxus 9 2027 года. Стартовая цена модели составляет "
        "290 тыс. юаней, что соответствует примерно 3,8 млн рублей."
    )
    evidence = build_evidence_pack(news_event_id=uuid.uuid4(), story_id=None, source_url=None, research_facts=[maxus_fact])
    recovery_service = RecoveryService()

    async def render_data(composition_plan, structured_content):
        return None, f"<b>{structured_content.metric_label}</b>\n{structured_content.metric_value} {structured_content.metric_unit}"

    result = await run_editorial_production_pipeline(
        content_draft_id=draft.id, presentation_format=PresentationFormat.DATA,
        title=maxus_title, main_body=maxus_body,
        evidence=evidence, platform=Platform.TELEGRAM, render=render_data,
        session=db_session, recovery_service=recovery_service, require_media=True,
    )
    assert result.is_ready


async def test_media_research_timeout_produces_a_bounded_recovery_never_a_hang(
    db_session: AsyncSession,
) -> None:
    draft = await _make_content_draft(db_session)
    evidence = build_evidence_pack(news_event_id=uuid.uuid4(), story_id=None, source_url=None, research_facts=[])
    recovery_service = RecoveryService()

    class _NeverFinishesMediaResearchService:
        async def research(self, *args, **kwargs):
            await asyncio.sleep(10)  # far longer than the tiny timeout below
            raise AssertionError("must never actually complete in this test")

    result = await run_editorial_production_pipeline(
        content_draft_id=draft.id, presentation_format=PresentationFormat.NEWS, title="Title",
        main_body="Body", evidence=evidence, platform=Platform.TELEGRAM, render=_render_success,
        session=db_session, recovery_service=recovery_service,
        media_research_service=_NeverFinishesMediaResearchService(), media_research_timeout_seconds=0.05,
    )

    assert not result.is_ready
    row = await recovery_service.get(db_session, recovery_job_id=result.persisted_recovery_job_id)
    assert row.reason_code.value == "MEDIA_RESEARCH_TIMEOUT"
    assert row.failed_stage == "media_research"


async def test_in_process_fallback_path_unaffected_when_no_session_supplied(db_session: AsyncSession) -> None:
    """No session/recovery_service (the pre-existing default) -> byte-identical old in-process
    behavior, `persisted_recovery_job_id` stays None."""
    evidence = build_evidence_pack(news_event_id=uuid.uuid4(), story_id=None, source_url=None, research_facts=[])
    result = await run_editorial_production_pipeline(
        content_draft_id=uuid.uuid4(), presentation_format=PresentationFormat.NEWS, title="Title",
        main_body="Body", evidence=evidence, platform=Platform.TELEGRAM, render=_render_none,
    )
    assert not result.is_ready
    assert result.persisted_recovery_job_id is None
    assert result.recovery_job is not None
    # No durable state to distinguish "still retryable" from "needs review" - the in-process
    # fallback (no session supplied) reports HOLD for any non-terminal-only reason code, exactly
    # matching this path's pre-cutover behavior (it never tracked RETRYING/PENDING at all).
    assert result.verdict == OrchestratorVerdict.HOLD
