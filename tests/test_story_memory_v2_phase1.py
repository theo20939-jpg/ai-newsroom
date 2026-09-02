"""PHASE STORY-MEMORY-V2-2 Phase 1 (schema + structural fixes only - PHASE STORY-MEMORY-V2-1
design, rollout step 1).

Proves:
1. StoryTelegramDelivery is now recorded after a successful send even when
   TELEGRAM_STORY_REPLY_MODE=off (Structural Fix 1 - the delivery-recording decoupling).
2. TELEGRAM_STORY_REPLY_MODE=off still preserves today's non-reply/thread Telegram behavior.
3. No delivery row is written when the Telegram send fails.
4. A real send + a DB persistence failure afterward still fails safe - no crash, no suppression
   side effect, the existing critical-log path still fires.
5. content_draft_service.py no longer maps RELATED_STORY/SUPPORTING_SOURCE/SEMANTIC_DUPLICATE to
   ContentDraftStoryLink.is_story_update=True merely through is_story_update_match() (Structural
   Fix 2).
6. story_duplicate_guard.py's check_update_would_fail_closed() no longer uses that same collapse
   as fail-closed authority.
7. Legacy/Phase-1 rows with the new nullable columns left NULL (final_decision etc.) fail open -
   existing logic is completely unaffected by their mere presence.
8. No Story Memory V2 final_decision-based routing/suppression/AI Judge runtime path exists yet
   (AST-based "prove it, don't just assert it in prose" check, mirroring
   tests/test_story_memory_v2_shadow_isolation.py's own established technique).

No production/dev database is ever touched - every test here uses the `factory`/`db_session`
fixtures' dedicated, rolled-back-at-teardown pytest database (settings.test_database_url),
exactly like every other test in this suite (tests/conftest.py Barrier 4).
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from database.models.content_draft import ContentDraft, ContentType
from database.models.content_draft_story_link import ContentDraftStoryLink
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from database.models.story_telegram_delivery import DeliveryStatus, DeliveryType, StoryTelegramDelivery
from services.story_duplicate_guard import check_duplicate_story_delivery, check_update_would_fail_closed
from services.story_memory import RELATED_STORY, SEMANTIC_DUPLICATE, STORY_UPDATE, SUPPORTING_SOURCE
from services.story_telegram_delivery import record_delivery
from services.telegram_notifier import NotificationOutcome
from tests.test_content_worker_cycle import (  # noqa: F401,F811 - fixtures reused via import
    _make_completed_news_analysis_task,
    _make_event,
    _real_capability_registry,
    _isolated_freshness_window,
    factory,
    test_source,
)
from worker.content_cycle import run_content_cycle


@pytest.fixture
def _deterministic_delivery_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "image_editorial_preview_enabled", False)
    monkeypatch.setattr(settings, "content_generation_dry_run", False)
    monkeypatch.setattr(settings, "editorial_chat_id", 123456789)


async def _cleanup_editorial_plan_shadow_rows(
    factory: async_sessionmaker[AsyncSession], event_id  # noqa: F811
) -> None:
    """Pre-existing, unrelated gap in tests/test_content_worker_cycle.py::test_source's own
    teardown cleanup chain (out of this phase's scope to fix): it deletes every Phase 18.10/19
    child table EXCEPT content_draft_editorial_plans and news_event_source_intelligence, both
    written by a real "intelligence" step run (via _real_capability_registry() below) -
    capabilities/executor.py::_attach_editorial_plan()'s shadow scaffold and services/
    source_intelligence.py respectively. Left behind, that fixture's own teardown then fails with
    a ForeignKeyViolationError deleting the NewsEvent. Deleting both here first, before
    test_source's own teardown runs, is self-contained test-owned cleanup (this file's own rows
    only), not a change to the shared fixture."""
    from sqlalchemy import delete

    from database.models.content_draft_editorial_plan import ContentDraftEditorialPlan
    from database.models.news_event_source_intelligence import NewsEventSourceIntelligence

    async with factory() as session:
        await session.execute(delete(ContentDraftEditorialPlan).where(ContentDraftEditorialPlan.event_id == event_id))
        await session.execute(
            delete(NewsEventSourceIntelligence).where(NewsEventSourceIntelligence.news_event_id == event_id)
        )
        await session.commit()


async def _make_story_linked_event(
    factory: async_sessionmaker[AsyncSession], test_source, *, match_type: str,  # noqa: F811
) -> tuple[Story, NewsEvent]:
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)
        story = Story(
            id=uuid4(), title=event.title, category=EventCategory.AI, entities=[], keywords=[],
            topic_bucket="product", first_event_id=event.id, event_count=1,
        )
        session.add(story)
        await session.flush()
        session.add(
            NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=match_type, match_score=0.7)
        )
        await session.commit()
    return story, event


# ---------------------------------------------------------------------------------------------
# 1/2/3/4 - delivery-recording decoupling (worker/content_cycle.py)
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delivery_recorded_when_reply_mode_off_but_story_link_exists(
    factory: async_sessionmaker[AsyncSession], test_source, _isolated_freshness_window: None,  # noqa: F811
    _deterministic_delivery_settings: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The core Phase 1 behavior change: a real story-linked draft, sent successfully, with
    TELEGRAM_STORY_REPLY_MODE at its confirmed real production value ("off"), must now produce a
    durable StoryTelegramDelivery row - previously starved entirely under this exact
    configuration (PHASE STORY-MEMORY-PROD-FORENSIC-1's central finding). Telegram send content/
    behavior itself must stay byte-identical: no reply threading, no fail-closed skip."""
    monkeypatch.setattr(settings, "story_memory_mode", "shadow")
    assert settings.telegram_story_reply_mode == "off"  # confirmed real production value

    story, event = await _make_story_linked_event(factory, test_source, match_type=STORY_UPDATE)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()
    with patch(
        "worker.content_cycle.send_editorial_card",
        new=AsyncMock(return_value=NotificationOutcome(chat_id=1, rendered_html="<html>", sent=True, message_id=4242)),
    ) as mock_notify:
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    # Telegram behavior unchanged: standalone post, no reply, no fail-closed skip.
    mock_notify.assert_called_once()
    assert mock_notify.call_args.kwargs["reply_to_message_id"] is None
    assert result.story_fail_closed_review == 0
    assert result.notified == 1

    # NEW this phase: a durable delivery row now exists.
    async with factory() as session:
        delivery = (
            await session.execute(
                select(StoryTelegramDelivery).where(StoryTelegramDelivery.story_id == story.id)
            )
        ).scalar_one()
    assert delivery.delivery_status == DeliveryStatus.SENT
    assert delivery.telegram_message_id == 4242
    assert delivery.delivery_type == DeliveryType.ROOT  # reply_to_message_id was None
    assert delivery.reply_to_message_id is None
    # New Phase 1 audit columns exist but are never populated by this phase's code.
    assert delivery.final_decision is None
    assert delivery.decision_source is None
    assert delivery.communicated_facts is None

    await _cleanup_editorial_plan_shadow_rows(factory, event.id)


@pytest.mark.asyncio
async def test_no_delivery_row_when_telegram_send_fails(
    factory: async_sessionmaker[AsyncSession], test_source, _isolated_freshness_window: None,  # noqa: F811
    _deterministic_delivery_settings: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed send (sent=False) must never produce a delivery row, regardless of the story_link
    now always being looked up."""
    monkeypatch.setattr(settings, "story_memory_mode", "shadow")

    story, event = await _make_story_linked_event(factory, test_source, match_type=STORY_UPDATE)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()
    with patch(
        "worker.content_cycle.send_editorial_card",
        new=AsyncMock(return_value=NotificationOutcome(chat_id=1, rendered_html="<html>", sent=False, message_id=None)),
    ):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.notification_failed == 1
    async with factory() as session:
        count = (
            await session.execute(
                select(StoryTelegramDelivery).where(StoryTelegramDelivery.story_id == story.id)
            )
        ).scalars().all()
    assert count == []
    await _cleanup_editorial_plan_shadow_rows(factory, event.id)


@pytest.mark.asyncio
async def test_send_success_plus_persistence_failure_fails_safe(
    factory: async_sessionmaker[AsyncSession], test_source, _isolated_freshness_window: None,  # noqa: F811
    _deterministic_delivery_settings: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real, successful Telegram send whose subsequent delivery-record persistence fails must:
    not crash the cycle, still count the draft as completed/notified, increment
    story_delivery_persistence_failed, and create no suppression side effect. This exact failure
    mode (previously unreachable under telegram_story_reply_mode=off) is now reachable for real -
    this proves the pre-existing exception handling still holds under the new, wider reachability
    Structural Fix 1 introduces."""
    monkeypatch.setattr(settings, "story_memory_mode", "shadow")

    story, event = await _make_story_linked_event(factory, test_source, match_type=STORY_UPDATE)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()
    with patch(
        "worker.content_cycle.send_editorial_card",
        new=AsyncMock(return_value=NotificationOutcome(chat_id=1, rendered_html="<html>", sent=True, message_id=777)),
    ), patch("worker.content_cycle.record_delivery", side_effect=RuntimeError("simulated DB failure")):
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    assert result.notified == 1
    assert result.completed == 1
    assert result.story_delivery_persistence_failed == 1
    assert result.story_fail_closed_review == 0

    async with factory() as session:
        rows = (
            await session.execute(
                select(StoryTelegramDelivery).where(StoryTelegramDelivery.story_id == story.id)
            )
        ).scalars().all()
    assert rows == []  # the simulated failure means nothing was actually persisted
    await _cleanup_editorial_plan_shadow_rows(factory, event.id)


# ---------------------------------------------------------------------------------------------
# 5/7 - content_draft_service.py: is_story_update_match() retired, transitional is_update=False
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "match_type,expected_is_update",
    [
        (STORY_UPDATE, True),          # unchanged - never part of the proven-wrong collapse
        (SEMANTIC_DUPLICATE, False),   # SAFETY FIX (Concern 2) - must not masquerade as UPDATE
        (SUPPORTING_SOURCE, False),    # FIXED - was wrongly True before this phase
        (RELATED_STORY, False),        # FIXED - was wrongly True before this phase (a DIFFERENT story)
    ],
)
async def test_content_draft_service_narrows_is_story_update_to_the_two_proven_types(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, match_type: str, expected_is_update: bool,
) -> None:
    """Structural Fix 2, narrow form: the old is_story_update_match() collapse treated all four of
    STORY_UPDATE/SUPPORTING_SOURCE/SEMANTIC_DUPLICATE/RELATED_STORY as is_story_update=True. Only
    RELATED_STORY and SUPPORTING_SOURCE were the confirmed forensic defect (PHASE STORY-MEMORY-
    PROD-FORENSIC-1) - this phase's own instruction is the minimum narrow legacy-safe fix, so
    STORY_UPDATE/SEMANTIC_DUPLICATE must remain exactly as before (True), and only the two proven-
    wrong types must change to False.

    Uses db_session (savepoint-rollback, per tests/conftest.py) with a hand-built minimal
    WorkflowRunResult, rather than the full real capability pipeline - avoids that heavier
    fixture's own unrelated multi-table cleanup-ordering fragility, which is out of this phase's
    scope to investigate or fix."""
    from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
    from database.models.news_source import NewsSource, SourceType
    from schemas.workflow import WorkflowRunResult, WorkflowStepResult
    from services.content_draft_service import ContentDraftService

    source = NewsSource(name=f"Phase1 is_update test {uuid4()}", type=SourceType.RSS, active=True)
    db_session.add(source)
    await db_session.flush()
    event = NewsEvent(
        source_id=source.id, title=f"Phase1 is_update test {uuid4()}", content="Body",
        category=EventCategory.AI, hash=f"phase1-is-update-test-{uuid4()}",
    )
    db_session.add(event)
    await db_session.flush()
    story = Story(
        id=uuid4(), title=event.title, category=EventCategory.AI, entities=[], keywords=[],
        topic_bucket="product", first_event_id=event.id, event_count=1,
    )
    db_session.add(story)
    await db_session.flush()
    db_session.add(
        NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=match_type, match_score=0.7)
    )
    task = EditorialTask(
        id=uuid4(), event_id=event.id, status=TaskStatus.COMPLETED, priority=TaskPriority.B,
        workflow={"workflow_name": "CONTENT_GENERATION", "step_results": []},
    )
    db_session.add(task)
    await db_session.flush()

    monkeypatch.setattr(settings, "story_memory_mode", "shadow")

    now = datetime.now(timezone.utc)
    result = WorkflowRunResult(
        task_id=task.id, status="COMPLETED", iterations_used=1,
        step_results=[
            WorkflowStepResult(
                step_name="copywriting", status="SUCCESS", attempt=1, started_at=now, finished_at=now,
                result={
                    "title": "Test title", "main_body": "Test body.", "ending": None, "quote": None,
                    "story_led": False, "viral_potential": "NONE", "meme_potential": "NONE",
                },
            ),
            WorkflowStepResult(
                step_name="research", status="SUCCESS", attempt=1, started_at=now, finished_at=now,
                result={"facts": [], "gaps": [], "confidence": "high"},
            ),
        ],
    )
    draft = await ContentDraftService(db_session).create_from_result(task.id, result, event_id=event.id)
    link = await db_session.get(ContentDraftStoryLink, draft.id)

    assert link is not None
    assert link.is_story_update is expected_is_update, (
        f"match_type={match_type} expected is_story_update={expected_is_update}"
    )
    assert link.generated_as_standalone is None  # reserved column, unpopulated this phase


# ---------------------------------------------------------------------------------------------
# 6 - story_duplicate_guard.py: check_update_would_fail_closed() no longer uses the collapse
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("match_type", [RELATED_STORY, SUPPORTING_SOURCE, SEMANTIC_DUPLICATE])
async def test_check_update_would_fail_closed_never_fires_for_related_story_or_supporting_source(
    factory: async_sessionmaker[AsyncSession], test_source, match_type: str, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    """The confirmed-dangerous case: before this phase, telegram_story_reply_mode="enforce" +
    RELATED_STORY/SUPPORTING_SOURCE + no resolvable root would fail-closed-DROP the draft entirely
    - a real content-loss bug for RELATED_STORY specifically (it always gets its own new Story, so
    a "root" almost never resolves). Must now return False unconditionally for these two types,
    never reaching the fail-closed check at all. SEMANTIC_DUPLICATE is included here too (PHASE
    STORY-MEMORY-V2-2 Phase 1 safety fix, Concern 2) - it must not masquerade as STORY_UPDATE
    merely because no V2 final_decision layer exists yet to represent it properly."""
    monkeypatch.setattr(settings, "telegram_story_reply_mode", "enforce")

    story, event = await _make_story_linked_event(factory, test_source, match_type=match_type)

    async with factory() as session:
        check = await check_update_would_fail_closed(session, event.id)

    assert check.would_fail_closed is False
    assert "is_story_update_match" in check.reason


@pytest.mark.asyncio
async def test_check_update_would_fail_closed_still_reaches_the_check_for_story_update(
    factory: async_sessionmaker[AsyncSession], test_source, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    """Regression: genuine STORY_UPDATE with no resolvable root must still reach (and fire) the
    fail-closed check exactly as before this phase - this type was never part of the proven-wrong
    collapse and its behavior must not change."""
    monkeypatch.setattr(settings, "telegram_story_reply_mode", "enforce")

    story, event = await _make_story_linked_event(factory, test_source, match_type=STORY_UPDATE)

    async with factory() as session:
        check = await check_update_would_fail_closed(session, event.id)

    assert check.would_fail_closed is True  # no root delivery exists for this story -> would drop
    assert "no resolvable root" in check.reason


@pytest.mark.asyncio
async def test_check_update_would_fail_closed_still_noop_when_reply_mode_off(
    factory: async_sessionmaker[AsyncSession], test_source,  # noqa: F811
) -> None:
    """Unaffected regression: the settings.telegram_story_reply_mode != "enforce" guard above the
    retired check still short-circuits first, exactly as before - confirmed production value
    ("off") never reaches the retired branch at all."""
    assert settings.telegram_story_reply_mode == "off"
    story, event = await _make_story_linked_event(factory, test_source, match_type=STORY_UPDATE)

    async with factory() as session:
        check = await check_update_would_fail_closed(session, event.id)

    assert check.would_fail_closed is False
    assert "not enforce" in check.reason


# ---------------------------------------------------------------------------------------------
# 8 - AST-based proof: no Story Memory V2 final_decision / AI Judge runtime path exists yet
# ---------------------------------------------------------------------------------------------

_PHASE1_RESERVED_IDENTIFIERS = (
    "final_decision", "decision_source", "decision_confidence", "judge_error_category",
    "new_facts", "material_delta", "decision_reason", "observed_facts", "published_facts",
    "communicated_facts", "generated_as_standalone", "STORY_JUDGE", "story_judge_mode",
)

_LIVE_RUNTIME_PREFIXES = ("worker/", "capabilities/")


def _source_of(relative_path: str) -> str:
    return Path(relative_path).read_text(encoding="utf-8")


def test_no_live_runtime_file_references_phase1_reserved_identifiers() -> None:
    """Mirrors tests/test_story_memory_v2_shadow_isolation.py's own established AST/string-scan
    technique. None of worker/*.py or capabilities/*.py may reference any Phase 1 reserved
    identifier - proves no final_decision computation, no routing, no AI Judge call, and no
    published_facts/observed_facts runtime advancement exists yet anywhere in the live pipeline."""
    offenders: list[str] = []
    for path in Path(".").rglob("*.py"):
        relative = path.as_posix()
        if "__pycache__" in relative or not relative.startswith(_LIVE_RUNTIME_PREFIXES):
            continue
        source = path.read_text(encoding="utf-8")
        for identifier in _PHASE1_RESERVED_IDENTIFIERS:
            if identifier in source:
                offenders.append(f"{relative} references {identifier!r}")
    assert offenders == [], f"Unexpected live reference to a Story Memory V2 Phase 1 reserved identifier: {offenders}"


def test_no_story_judge_module_exists_yet() -> None:
    """Explicit negative check: no story_judge service/capability/prompt was added this phase."""
    assert not Path("services/story_judge.py").exists()
    assert not Path("capabilities/story_judge_capability.py").exists()
    assert not Path("prompts/story_judge").exists()


def test_is_story_update_match_still_exists_as_a_pure_function_but_has_exactly_zero_live_callers() -> None:
    """is_story_update_match() itself is NOT deleted this phase (its own unit tests still exercise
    it directly) - only its use as live decision truth in the two approved consumers is retired.
    This asserts the retirement directly against the two consumer files' source, rather than only
    against the (looser) reserved-identifier scan above."""
    from services.story_memory import is_story_update_match  # still importable, still a real function

    assert is_story_update_match(STORY_UPDATE) is True  # the function's own pure behavior, unchanged

    for relative in ("services/content_draft_service.py", "services/story_duplicate_guard.py"):
        # AST-based, not substring-based: both files legitimately still MENTION
        # is_story_update_match() in explanatory comments (why it was retired) - only an actual
        # `import` of the name, or a live Call node invoking it, would mean it is still being used
        # as decision truth.
        tree = ast.parse(_source_of(relative))
        imported_names = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        assert "is_story_update_match" not in imported_names, (
            f"{relative} must not import is_story_update_match in Phase 1"
        )
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "is_story_update_match" not in called_names, (
            f"{relative} must not call is_story_update_match() as live decision truth in Phase 1"
        )


# ---------------------------------------------------------------------------------------------
# 9 - PHASE STORY-MEMORY-V2-2 Phase 1 safety fix (Concern 1): the delivery-recording decoupling
# above must not reactivate services/story_duplicate_guard.py::check_duplicate_story_delivery()'s
# pre-existing (Phase 23.1I/23.1P), already-approved real blocking path. That function is called
# unconditionally every router-mode cycle (worker/content_cycle.py) but had never actually blocked
# anything in production because get_root_delivery() never found a row - itself a direct
# consequence of the exact same starvation bug (record_delivery() gated on telegram_story_reply_
# mode != "off") that Structural Fix 1 above fixes. Real duplicate suppression is not authorized
# until Story Memory V2 rollout Step 8, so this function must stay an unconditional fail-open
# no-op for the duration of Phase 1, even once real ROOT/SENT delivery rows exist.
# ---------------------------------------------------------------------------------------------


async def _make_story_with_delivered_root_and_duplicate(
    factory: async_sessionmaker[AsyncSession], test_source, *, match_type: str,  # noqa: F811
) -> tuple[Story, NewsEvent]:
    """Two events on the same Story: `root_event` (NEW_STORY, already delivered ROOT/SENT - a
    real, prior, successful post) and `event` (the given `match_type`, same title as the story's
    root - byte-identical rewording, so services.story_delta_engine's own classify_delta() reports
    NO_NEW_FACTS and compute_would_suppress() reports would_suppress=True, the strongest possible
    case for the old guard to WANT to block - proving the Phase 1 override actually overrides a
    real True signal, not merely a case that was already False)."""
    async with factory() as session:
        root_event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        event.title = root_event.title
        await session.flush()
        story = Story(
            id=uuid4(), title=root_event.title, category=EventCategory.AI, entities=[], keywords=[],
            topic_bucket="product", first_event_id=root_event.id, event_count=2,
        )
        session.add(story)
        await session.flush()
        session.add(NewsEventStoryLink(news_event_id=root_event.id, story_id=story.id, match_type="new_story", match_score=1.0))
        session.add(NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=match_type, match_score=0.9))

        root_task = EditorialTask(
            id=uuid4(), event_id=root_event.id, status=TaskStatus.COMPLETED, priority=TaskPriority.B,
            workflow={"workflow_name": "CONTENT_GENERATION", "step_results": []},
        )
        session.add(root_task)
        await session.flush()
        root_draft = ContentDraft(
            id=uuid4(), task_id=root_task.id, type=ContentType.POST, title="root", body="root body",
            version=1, status="draft",
        )
        session.add(root_draft)
        await session.flush()
        await record_delivery(
            session, story_id=story.id, content_draft_id=root_draft.id, telegram_chat_id=-1004297182444,
            telegram_message_id=999, reply_to_message_id=None, delivery_type=DeliveryType.ROOT,
            delivery_status=DeliveryStatus.SENT, sent_at=datetime.now(timezone.utc),
        )
        await session.commit()
    return story, event


@pytest.mark.asyncio
@pytest.mark.parametrize("match_type", [SEMANTIC_DUPLICATE, SUPPORTING_SOURCE])
async def test_check_duplicate_story_delivery_never_blocks_even_with_real_prior_root_and_no_new_facts(
    factory: async_sessionmaker[AsyncSession], test_source, match_type: str,  # noqa: F811
) -> None:
    """The exact scenario this safety fix targets: a real ROOT/SENT delivery row (the kind
    Structural Fix 1 can now produce even with telegram_story_reply_mode == "off") plus a
    match_type/delta combination that would, under the pre-existing Phase 23.1I/23.1P logic,
    confirm blocked=True. Must return blocked=False during Phase 1 regardless - the underlying
    would_suppress computation still runs and is still surfaced for audit, it just can never
    actually withhold a send yet."""
    story, event = await _make_story_with_delivered_root_and_duplicate(factory, test_source, match_type=match_type)

    async with factory() as check_session:
        result = await check_duplicate_story_delivery(check_session, event.id)

    assert result.blocked is False
    assert result.match_type == match_type
    assert result.would_suppress is True  # the real computation still confirms it WOULD suppress
    assert result.delta_classification == "no_new_facts"


@pytest.mark.asyncio
async def test_check_duplicate_story_delivery_still_allows_story_update_as_before(
    factory: async_sessionmaker[AsyncSession], test_source,  # noqa: F811
) -> None:
    """Regression: STORY_UPDATE was never blocked by this function even before this safety fix
    (services/story_duplicate_guard.py's own module docstring) - must remain unaffected."""
    story, event = await _make_story_with_delivered_root_and_duplicate(
        factory, test_source, match_type=STORY_UPDATE,
    )

    async with factory() as check_session:
        result = await check_duplicate_story_delivery(check_session, event.id)

    assert result.blocked is False
