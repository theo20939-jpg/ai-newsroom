"""Phase 23.1C - V6 Copywriting / ContentDraft compatibility.

Written test-first (docs/phase23_1c_v6_contentdraft_compatibility_report.md's own baseline
section records the exact pre-fix failure): before this milestone, `ContentDraftService.
create_from_result()` reads `copywriting_output["body"]` directly (V4's own schema key) - a hard
`KeyError` for every V6 draft, confirmed live during the Phase 23.1B canary run (0/4 real V6
drafts persisted, all crashed at this exact line).

Two tiers, mirroring tests/test_fact_safety_v6_compatibility.py's own established shape:
- Pure unit tests for `_extract_title_and_body()` itself (no DB).
- Integration tests (real Postgres, db_session) for `ContentDraftService.create_from_result()`,
  using the exact direct-`WorkflowRunResult`-construction technique already established in
  tests/test_evidence_package_degradation.py (lighter than driving a full fake-gateway pipeline
  just to get a specific "copywriting" step output shape).

Six required cases (phase brief "TEST FIRST"):
1. V4 output creates an identical ContentDraft (regression guard, unchanged behavior).
2. V6 output creates a ContentDraft successfully.
3. Missing optional V6 fields (what_happens_next/what_remains_unknown) handled safely.
4. Unsupported schema fails explicitly (a clear, informative error - never a silent skip, never a
   raw unhelpful KeyError).
5. No Telegram calls (structural - this module never imports any Telegram-sending code).
6. Existing ContentDraft tests unchanged (verified via the full regression run, not a new test in
   this file - see the phase report's own §5/§ regression results).
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.editorial_task import TaskPriority
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowRunResult, WorkflowStepResult, WorkflowType
from services import workflow_service
from services.content_draft_service import ContentDraftService, _extract_title_and_body


def _v6_output(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "title": "OpenAI releases a new model",
        "opening": "OpenAI released a new flagship model on Thursday.",
        "context": "The company has shipped a major model roughly every year since 2023.",
        "why_it_matters": "The release raises the bar for reasoning benchmarks industry-wide.",
        "what_changed": "The new model scores 92% on the industry's standard reasoning benchmark.",
        "what_happens_next": None,
        "conclusion": "The model is available to developers starting today.",
        "what_remains_unknown": None,
        "quote": None,
    }
    base.update(overrides)
    return base


async def _seed_event(session: AsyncSession) -> NewsEvent:
    source = NewsSource(id=uuid4(), name=f"phase23-1c-src-{uuid4().hex[:6]}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(
        id=uuid4(), source_id=source.id, title="Phase 23.1C test event",
        content="Original source content for Phase 23.1C tests.",
        category=EventCategory.UNKNOWN, hash=f"phase23-1c-{uuid4()}",
    )
    session.add(event)
    await session.flush()
    return event


async def _make_task(session: AsyncSession, event: NewsEvent):
    return await workflow_service.create_task(
        session,
        EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B),
    )


def _result_for(task_id, copywriting_output: dict[str, object]) -> WorkflowRunResult:
    now = datetime.now(timezone.utc)
    return WorkflowRunResult(
        task_id=task_id, status="COMPLETED", iterations_used=1,
        step_results=[
            WorkflowStepResult(
                step_name="copywriting", status="SUCCESS", attempt=1, started_at=now, finished_at=now,
                result=copywriting_output,
            ),
        ],
    )


# ---------------------------------------------------------------------------
# _extract_title_and_body() - pure unit tests
# ---------------------------------------------------------------------------


def test_v4_body_schema_extracted_unchanged() -> None:
    title, body = _extract_title_and_body({"title": "X", "body": "Y", "hashtags": []})
    assert title == "X"
    assert body == "Y"


def test_v6_schema_extracted_from_narrative_sections() -> None:
    title, body = _extract_title_and_body(_v6_output())
    assert title == "OpenAI releases a new model"
    for expected_fragment in (
        "OpenAI released a new flagship model",
        "shipped a major model roughly every year",
        "raises the bar for reasoning benchmarks",
        "scores 92%",
        "available to developers starting today",
    ):
        assert expected_fragment in body


def test_v6_optional_fields_included_only_when_present() -> None:
    title, body = _extract_title_and_body(_v6_output(
        what_happens_next="A follow-up model is expected next quarter.",
    ))
    assert "follow-up model is expected" in body

    _title2, body2 = _extract_title_and_body(_v6_output())  # both optional fields None
    assert "follow-up model is expected" not in body2


def test_v6_section_ordering_is_preserved() -> None:
    _title, body = _extract_title_and_body(_v6_output(
        what_happens_next="NEXT-MARKER",
        what_remains_unknown="UNKNOWN-MARKER",
    ))
    assert body.index("OpenAI released a new flagship model") < body.index("shipped a major model")
    assert body.index("shipped a major model") < body.index("raises the bar")
    assert body.index("raises the bar") < body.index("scores 92%")
    assert body.index("scores 92%") < body.index("NEXT-MARKER")
    assert body.index("NEXT-MARKER") < body.index("available to developers")
    assert body.index("available to developers") < body.index("UNKNOWN-MARKER")


def test_unsupported_schema_raises_explicit_error() -> None:
    with pytest.raises(ValueError, match="no known Copywriting schema"):
        _extract_title_and_body({"title": "X", "summary_blob": "some text"})


def test_missing_title_raises_explicit_error() -> None:
    with pytest.raises(ValueError):
        _extract_title_and_body({"body": "Y"})


# ---------------------------------------------------------------------------
# CASE 1 - V4 output creates an identical ContentDraft (regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_1_v4_output_creates_identical_content_draft(db_session: AsyncSession) -> None:
    event = await _seed_event(db_session)
    task = await _make_task(db_session, event)
    result = _result_for(task.id, {"title": "A V4 title", "body": "A V4 body.", "hashtags": []})

    draft = await ContentDraftService(db_session).create_from_result(result.task_id, result, event_id=event.id)

    assert draft.title == "A V4 title"
    assert draft.body == "A V4 body."


# ---------------------------------------------------------------------------
# CASE 2 - V6 output creates a ContentDraft successfully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_2_v6_output_creates_content_draft_successfully(db_session: AsyncSession) -> None:
    event = await _seed_event(db_session)
    task = await _make_task(db_session, event)
    result = _result_for(task.id, _v6_output())

    draft = await ContentDraftService(db_session).create_from_result(result.task_id, result, event_id=event.id)

    assert draft.title == "OpenAI releases a new model"
    assert draft.body is not None
    assert "raises the bar for reasoning benchmarks" in draft.body


# ---------------------------------------------------------------------------
# CASE 3 - missing optional V6 fields handled safely
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_3_v6_missing_optional_fields_handled_safely(db_session: AsyncSession) -> None:
    event = await _seed_event(db_session)
    task = await _make_task(db_session, event)
    # what_happens_next/what_remains_unknown both None - the real, common V6 case (Phase 23.1B's
    # own live sample draft had what_happens_next=None).
    result = _result_for(task.id, _v6_output(what_happens_next=None, what_remains_unknown=None))

    draft = await ContentDraftService(db_session).create_from_result(result.task_id, result, event_id=event.id)

    assert draft.title == "OpenAI releases a new model"
    assert draft.body is not None


# ---------------------------------------------------------------------------
# CASE 4 - unsupported schema fails explicitly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_4_unsupported_schema_fails_explicitly_never_persists(db_session: AsyncSession) -> None:
    event = await _seed_event(db_session)
    task = await _make_task(db_session, event)
    result = _result_for(task.id, {"title": "X", "summary_blob": "some future schema shape"})

    with pytest.raises(ValueError, match="no known Copywriting schema"):
        await ContentDraftService(db_session).create_from_result(result.task_id, result, event_id=event.id)

    from sqlalchemy import select

    from database.models.content_draft import ContentDraft

    drafts = (await db_session.execute(select(ContentDraft).where(ContentDraft.task_id == task.id))).scalars().all()
    assert drafts == []


# ---------------------------------------------------------------------------
# CASE 5 - no Telegram calls (structural)
# ---------------------------------------------------------------------------


def test_case_5_content_draft_service_never_imports_telegram_code() -> None:
    from pathlib import Path

    source_text = Path("services/content_draft_service.py").read_text(encoding="utf-8")
    for forbidden in ("aiogram", "telegram_notifier", "telegram_routing", "bot.loader"):
        assert forbidden not in source_text, f"{forbidden} must never appear in content_draft_service.py"
