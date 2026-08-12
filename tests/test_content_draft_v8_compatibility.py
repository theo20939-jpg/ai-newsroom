"""Phase 23.1J - V8 Copywriting / ContentDraft compatibility (docs/
phase23_1j_copywriting_v8_report.md).

Written test-first, mirroring tests/test_content_draft_v6_compatibility.py's own established
shape exactly. V8's schema (title/main_body/ending/expandable_details/quote) is a genuinely
smaller shape than V6/V7's seven/eight narrative sections - `_extract_title_and_body()` needs one
new recognized-schema branch, added alongside (never replacing) the existing V4/V6 branches.
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


def _v8_output(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "title": "OpenAI releases a new model",
        "main_body": "OpenAI released a new flagship model on Thursday. It scores 92% on the industry's standard reasoning benchmark.",
        "ending": None,
        "expandable_details": None,
        "quote": None,
    }
    base.update(overrides)
    return base


async def _seed_event(session: AsyncSession) -> NewsEvent:
    source = NewsSource(id=uuid4(), name=f"phase23-1j-src-{uuid4().hex[:6]}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(
        id=uuid4(), source_id=source.id, title="Phase 23.1J test event",
        content="Original source content for Phase 23.1J tests.",
        category=EventCategory.UNKNOWN, hash=f"phase23-1j-{uuid4()}",
    )
    session.add(event)
    await session.flush()
    return event


async def _make_task(session: AsyncSession, event: NewsEvent):
    return await workflow_service.create_task(
        session,
        EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B),
    )


def _result_for(task_id: object, copywriting_output: dict[str, object]) -> WorkflowRunResult:
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


def test_v8_schema_extracted_from_main_body() -> None:
    title, body = _extract_title_and_body(_v8_output())
    assert title == "OpenAI releases a new model"
    assert "OpenAI released a new flagship model" in body
    assert "scores 92%" in body


def test_v8_ending_included_only_when_present() -> None:
    _title, body_with = _extract_title_and_body(_v8_output(ending="A follow-up model is expected next quarter."))
    assert "follow-up model is expected" in body_with

    _title, body_without = _extract_title_and_body(_v8_output())  # ending=None
    assert "follow-up model is expected" not in body_without


def test_v8_expandable_details_included_for_persistence_even_though_hidden_in_presentation() -> None:
    """Fact Safety/ContentDraft persistence must see expandable_details content (it's still real
    editorial content that can carry factual claims) - only the Telegram presentation layer
    decides to visually hide it behind an expandable blockquote, never the persistence/fact-check
    layer."""
    _title, body = _extract_title_and_body(_v8_output(expandable_details="Supports twelve device models total."))
    assert "twelve device models" in body


def test_v8_section_ordering_is_preserved() -> None:
    _title, body = _extract_title_and_body(_v8_output(
        ending="ENDING-MARKER", expandable_details="DETAILS-MARKER",
    ))
    assert body.index("OpenAI released a new flagship model") < body.index("ENDING-MARKER")
    assert body.index("ENDING-MARKER") < body.index("DETAILS-MARKER")


def test_v8_output_does_not_accidentally_match_the_v6_branch() -> None:
    """A V8 output has none of V6's required keys (opening/context/why_it_matters/what_changed/
    conclusion) - must be recognized via the new V8 branch, not silently fall through to raising
    an unsupported-schema error."""
    title, body = _extract_title_and_body(_v8_output())
    assert title and body  # did not raise


# ---------------------------------------------------------------------------
# ContentDraftService.create_from_result() - integration test (real DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v8_output_creates_content_draft_successfully(db_session: AsyncSession) -> None:
    event = await _seed_event(db_session)
    task = await _make_task(db_session, event)
    result = _result_for(task.id, _v8_output(ending="A material caveat.", expandable_details="Full spec list."))

    service = ContentDraftService(db_session)
    draft = await service.create_from_result(task.id, result, event_id=event.id)

    assert draft is not None
    assert draft.title == "OpenAI releases a new model"
    assert "flagship model" in draft.body
    assert "material caveat" in draft.body
    assert "Full spec list" in draft.body
