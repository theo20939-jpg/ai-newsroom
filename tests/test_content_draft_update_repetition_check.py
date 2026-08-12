"""NEWS Output Stability Fix (Case C, docs/news_output_stability_forensic_report.md §4):
services.content_draft_service.ContentDraftService.create_from_result() now resolves the real
story_link/is_update/root_body BEFORE calling evaluate_content_quality_gates(), so
check_update_not_repeating_root() (services/content_quality_gates.py, already built, previously
always silently defaulted to is_update=False) actually receives real inputs.

Real Postgres (db_session, rolled back). Requires the Phase 18.10 stories/news_event_story_links/
content_draft_story_links tables - already applied in this environment (verified via `alembic
current` = f2654fa00185, whose migration chain includes c2bc6affb100/0fac25b59455 as ancestors),
so no skip marker is needed here (unlike the stale one on
tests/test_content_draft_story_link_integration.py, out of scope for this fix).
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft import ContentDraft, ContentType
from database.models.content_draft_story_link import ContentDraftStoryLink
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from database.models.story_telegram_delivery import DeliveryStatus, DeliveryType, StoryTelegramDelivery
from services.content_draft_service import ContentDraftService
from services.story_memory import NEW_STORY, STORY_UPDATE

# Calibrated directly against the real services.text_normalization.token_overlap_ratio() (not
# guessed): _ROOT_BODY vs _REPEAT_UPDATE_BODY = 0.857 (>= the 0.6 threshold - fails, i.e. IS
# repetition); _ROOT_BODY vs _GENUINE_UPDATE_BODY = 0.185 (< 0.6 - passes, i.e. NOT repetition).
_ROOT_BODY = (
    "Honor unveiled a robotic phone concept with a four axis stabilized camera mount priced at "
    "nine thousand nine hundred ninety nine yuan for the Chinese market at a launch event today"
)
_REPEAT_UPDATE_BODY = (
    "Honor unveiled a robotic phone concept with a four axis stabilized camera mount priced at "
    "nine thousand nine hundred ninety nine yuan for the Chinese market at a launch event today "
    "and it is now available for purchase"
)
_GENUINE_UPDATE_BODY = (
    "Honor confirmed that the robotic phone is now shipping worldwide with international "
    "availability starting next week across European and Asian retail outlets following its "
    "earlier limited regional debut"
)


async def _make_source(session: AsyncSession) -> NewsSource:
    source = NewsSource(name=f"Update Repetition Test Source {uuid4()}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    return source


async def _make_event(session: AsyncSession, source: NewsSource, *, title: str | None = None) -> NewsEvent:
    event = NewsEvent(
        source_id=source.id, title=title or f"Update repetition test event {uuid4()}", content="Body",
        category=EventCategory.AI, hash=f"update-repetition-test-{uuid4()}",
    )
    session.add(event)
    await session.flush()
    return event


async def _make_story(session: AsyncSession, *, first_event_id) -> Story:
    story = Story(
        id=uuid4(), title=f"Story {uuid4()}", category=EventCategory.AI, entities=[], keywords=[],
        topic_bucket="product", first_event_id=first_event_id, event_count=2,
    )
    session.add(story)
    await session.flush()
    return story


async def _seed_sent_root(session: AsyncSession, *, story: Story, root_body: str) -> ContentDraft:
    """A real, minimal ROOT ContentDraft + a SENT StoryTelegramDelivery pointing at it - the exact
    shape services.story_telegram_delivery.get_root_delivery() (reused by the fix under test)
    requires to consider a root "real" (see that function's own docstring: only a SENT root ever
    counts)."""
    task = EditorialTask(
        id=uuid4(), event_id=story.first_event_id, status=TaskStatus.COMPLETED, priority=TaskPriority.B,
        workflow={"workflow_name": "CONTENT_GENERATION", "step_results": []},
    )
    session.add(task)
    await session.flush()
    root_draft = ContentDraft(
        id=uuid4(), task_id=task.id, type=ContentType.POST, title="Root title", body=root_body,
        version=1, status="draft",
    )
    session.add(root_draft)
    await session.flush()
    session.add(
        StoryTelegramDelivery(
            id=uuid4(), story_id=story.id, content_draft_id=root_draft.id, telegram_chat_id=-1004297182444,
            telegram_message_id=999, reply_to_message_id=None, delivery_type=DeliveryType.ROOT,
            delivery_status=DeliveryStatus.SENT, idempotency_key=f"root-{uuid4()}",
            sent_at=datetime.now(timezone.utc),
        )
    )
    await session.flush()
    return root_draft


async def _run_with_body(session: AsyncSession, event_id, *, body: str):
    """Mirrors tests.test_content_draft_service._run_content_generation_to_completed() exactly,
    but with a caller-controlled copywriting body - that helper's own fixed _COPYWRITING_OUTPUT
    body can't be varied per test case, which this fix's tests need (a calibrated overlap ratio
    against a real root body)."""
    from capabilities.executor import CapabilityExecutor
    from capabilities.registry import build_registry
    from integrations.llm_gateway.protocol import GenerateResponse
    from integrations.llm_gateway.tools.registry import ToolRegistry
    from integrations.prompts.file_repository import FilePromptRepository
    from schemas.capability import CapabilityUsage
    from schemas.editorial_task import EditorialTaskCreate
    from schemas.workflow import WorkflowType
    from services import workflow_service
    from tests.fakes.fake_gateway import FakeLLMGateway
    from tests.fakes.fake_infra import AllowingBudgetGuard
    from tests.fakes.research_output import CANONICAL_RESEARCH_OUTPUT
    from tests.test_content_draft_service import _INTELLIGENCE_OUTPUT, _PROMPTS_ROOT, _QUALITY_OUTPUT
    from workflows.registry import registry as real_workflow_registry
    from workflows.runner import WorkflowRunner

    copywriting_output = {
        "title": "Update repetition test title", "body": body, "what_happened": "Something happened.",
        "why_it_matters": "It matters for testing.", "what_remains_unknown": None, "quote": None,
    }

    def _generate_response(structured_output: dict) -> GenerateResponse:
        return GenerateResponse(
            text=None, structured_output=structured_output, finish_reason="stop",
            model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=10, output_tokens=5),
        )

    gateway = FakeLLMGateway(generate_responses=[
        _generate_response(CANONICAL_RESEARCH_OUTPUT), _generate_response(_INTELLIGENCE_OUTPUT),
        _generate_response(copywriting_output), _generate_response(_QUALITY_OUTPUT),
    ])
    capability_registry = build_registry(
        gateway, FilePromptRepository(_PROMPTS_ROOT), AllowingBudgetGuard(), ToolRegistry()  # type: ignore[arg-type]
    )
    command = EditorialTaskCreate(event_id=event_id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B)
    task = await workflow_service.create_task(session, command)
    executor = CapabilityExecutor(session, task.id, capability_registry)
    result = await WorkflowRunner(executor=executor, registry=real_workflow_registry).run(session, task.id)
    return task.id, result


@pytest.mark.asyncio
async def test_genuine_update_with_new_material_passes_the_repetition_check(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("core.config.settings.story_memory_mode", "shadow")
    source = await _make_source(db_session)
    root_event = await _make_event(db_session, source)
    story = await _make_story(db_session, first_event_id=root_event.id)
    await _seed_sent_root(db_session, story=story, root_body=_ROOT_BODY)

    update_event = await _make_event(db_session, source)
    db_session.add(NewsEventStoryLink(news_event_id=update_event.id, story_id=story.id, match_type=STORY_UPDATE, match_score=0.8))
    await db_session.flush()

    task_id, result = await _run_with_body(db_session, update_event.id, body=_GENUINE_UPDATE_BODY)
    draft = await ContentDraftService(db_session).create_from_result(task_id, result, event_id=update_event.id)

    link = await db_session.get(ContentDraftStoryLink, draft.id)
    assert link is not None
    assert link.is_story_update is True  # Telegram threading unaffected by this fix


@pytest.mark.asyncio
async def test_rewritten_root_with_tiny_delta_fails_the_repetition_check(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr("core.config.settings.story_memory_mode", "shadow")
    source = await _make_source(db_session)
    root_event = await _make_event(db_session, source)
    story = await _make_story(db_session, first_event_id=root_event.id)
    await _seed_sent_root(db_session, story=story, root_body=_ROOT_BODY)

    update_event = await _make_event(db_session, source)
    db_session.add(NewsEventStoryLink(news_event_id=update_event.id, story_id=story.id, match_type=STORY_UPDATE, match_score=0.8))
    await db_session.flush()

    task_id, result = await _run_with_body(db_session, update_event.id, body=_REPEAT_UPDATE_BODY)
    with caplog.at_level("WARNING"):
        await ContentDraftService(db_session).create_from_result(task_id, result, event_id=update_event.id)

    # Non-blocking policy preserved unchanged (this fix wires inputs, not enforcement) - the
    # draft is still created, but the gate failure is now real and observable, unlike before this
    # fix, when is_update always defaulted to False and this gate could never fail for anyone.
    failure_logs = [r for r in caplog.records if r.message == "content_quality_gate_failures"]
    assert len(failure_logs) == 1
    assert "update_not_repeating_root" in failure_logs[0].failed_gates  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_new_story_is_unaffected_by_the_repetition_check(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """A NEW_STORY match must never be treated as an update, regardless of how similar its body
    text happens to be to anything else - is_update stays False, so
    check_update_not_repeating_root() trivially passes by its own existing design."""
    monkeypatch.setattr("core.config.settings.story_memory_mode", "shadow")
    source = await _make_source(db_session)
    event = await _make_event(db_session, source)
    story = await _make_story(db_session, first_event_id=event.id)
    db_session.add(NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=NEW_STORY, match_score=1.0))
    await db_session.flush()

    # Deliberately reuses the "repeat" body - even maximal self-similarity must not fail a
    # NEW_STORY draft, since is_update is the gate, not text similarity alone.
    task_id, result = await _run_with_body(db_session, event.id, body=_REPEAT_UPDATE_BODY)
    with caplog.at_level("WARNING"):
        draft = await ContentDraftService(db_session).create_from_result(task_id, result, event_id=event.id)

    failure_logs = [r for r in caplog.records if r.message == "content_quality_gate_failures"]
    for record in failure_logs:
        assert "update_not_repeating_root" not in record.failed_gates  # type: ignore[attr-defined]

    link = await db_session.get(ContentDraftStoryLink, draft.id)
    assert link is not None
    assert link.is_story_update is False


@pytest.mark.asyncio
async def test_update_with_no_delivered_root_follows_existing_safe_default(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """Story Memory classifies this as an update, but no root was ever successfully delivered to
    Telegram (no SENT StoryTelegramDelivery row exists) - root_body stays None, and
    check_update_not_repeating_root()'s own existing design (services/content_quality_gates.py)
    already treats an unknown root body as a pass, not a failure. This fix must not invent a new,
    stricter policy for this case."""
    monkeypatch.setattr("core.config.settings.story_memory_mode", "shadow")
    source = await _make_source(db_session)
    root_event = await _make_event(db_session, source)
    story = await _make_story(db_session, first_event_id=root_event.id)
    # No _seed_sent_root() call - no root delivery exists at all.

    update_event = await _make_event(db_session, source)
    db_session.add(NewsEventStoryLink(news_event_id=update_event.id, story_id=story.id, match_type=STORY_UPDATE, match_score=0.8))
    await db_session.flush()

    task_id, result = await _run_with_body(db_session, update_event.id, body=_REPEAT_UPDATE_BODY)
    with caplog.at_level("WARNING"):
        await ContentDraftService(db_session).create_from_result(task_id, result, event_id=update_event.id)

    failure_logs = [r for r in caplog.records if r.message == "content_quality_gate_failures"]
    for record in failure_logs:
        assert "update_not_repeating_root" not in record.failed_gates  # type: ignore[attr-defined]
