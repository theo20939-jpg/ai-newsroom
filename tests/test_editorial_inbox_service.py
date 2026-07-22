"""Tests for services.editorial_inbox_service.get_latest_editorial_cards (Phase 11 M1, docs/
phase11_telegram_editorial_inbox_architecture_contract.md §6/§7/§24).

Real Postgres (`db_session`, rolled back at teardown via SAVEPOINT) - fixture rows are constructed
directly at the ORM level (mirrors tests/test_triage_orchestrator_claims.py's own
EditorialTask(...)/session.add()/session.commit() convention). No WorkflowRunner, no AI call, no
Capability is needed anywhere in this file - Phase 11 does not require a real workflow run to
produce a COMPLETED EditorialTask for its own tests.

This database is shared with Phase 10's own live-validation history (a real, previously-COMPLETED
ContentDraft persists from Phase 10 M6) - `db_session` only rolls back *this test's own* writes,
not pre-existing committed rows from earlier sessions. Every test below is therefore written to be
correct in the presence of that pre-existing row: membership/relative-order checks against a
generous limit, never a bare `cards == []`/exact-list-equality assumption about global table state.
The one genuine "empty" proof (Contract §24) issues a `DELETE` scoped to this test's own
SAVEPOINT-rolled-back transaction - never committed, never destructive to the real row.
"""
import ast
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft import ContentDraft, ContentType
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from services.editorial_inbox_service import get_latest_editorial_cards

_TESTS_ROOT = Path(__file__).resolve().parent
_SERVICE_FILE = _TESTS_ROOT.parent / "services" / "editorial_inbox_service.py"

_FORBIDDEN_IMPORTS = (
    "workflows.runner",
    "capabilities.executor",
    "capabilities.research_capability",
    "capabilities.intelligence_capability",
    "capabilities.copywriting_capability",
    "capabilities.quality_capability",
    "capabilities.scoring_capability",
    "scripts.run_content_generation",
)

# Generous enough that a fixture-created row is never crowded out of the "latest N" window by
# other data (test-created or pre-existing) sharing this database.
_GENEROUS_LIMIT = 50


async def _make_source(session: AsyncSession) -> NewsSource:
    source = NewsSource(
        name="Test Source", type=SourceType.RSS, url="https://example.com/feed.xml", active=True
    )
    session.add(source)
    await session.flush()
    return source


async def _make_event(
    session: AsyncSession,
    source: NewsSource,
    *,
    title: str = "Test event",
    category: EventCategory = EventCategory.AI,
    url: str | None = "https://example.com/article",
    published_at: datetime | None = None,
) -> NewsEvent:
    event = NewsEvent(
        source_id=source.id,
        title=title,
        content="Test content",
        url=url,
        category=category,
        published_at=published_at,
        hash=f"test-hash-{uuid.uuid4()}",
    )
    session.add(event)
    await session.flush()
    return event


async def _make_task(
    session: AsyncSession, event: NewsEvent, *, status: TaskStatus = TaskStatus.COMPLETED
) -> EditorialTask:
    task = EditorialTask(event_id=event.id, priority=TaskPriority.B, status=status)
    session.add(task)
    await session.flush()
    return task


async def _make_draft(
    session: AsyncSession,
    task: EditorialTask,
    *,
    title: str | None = "Draft title",
    body: str | None = "Draft body.",
    hashtags: list[str] | None = None,
    created_at: datetime | None = None,
) -> ContentDraft:
    draft = ContentDraft(
        task_id=task.id,
        type=ContentType.POST,
        title=title,
        body=body,
        hashtags=hashtags if hashtags is not None else ["#example", "#news"],
        version=1,
        status="draft",
    )
    if created_at is not None:
        draft.created_at = created_at
    session.add(draft)
    await session.flush()
    return draft


async def _eligible_draft(
    session: AsyncSession, *, status: TaskStatus = TaskStatus.COMPLETED, **draft_kwargs: object
) -> tuple[ContentDraft, NewsEvent]:
    source = await _make_source(session)
    event = await _make_event(session, source)
    task = await _make_task(session, event, status=status)
    draft = await _make_draft(session, task, **draft_kwargs)  # type: ignore[arg-type]
    return draft, event


@pytest.mark.asyncio
async def test_completed_task_draft_is_returned(db_session: AsyncSession) -> None:
    draft, _event = await _eligible_draft(db_session)

    cards = await get_latest_editorial_cards(db_session, limit=_GENEROUS_LIMIT)

    assert draft.id in {c.draft_id for c in cards}


@pytest.mark.asyncio
async def test_failed_task_draft_is_excluded(db_session: AsyncSession) -> None:
    draft, _event = await _eligible_draft(db_session, status=TaskStatus.FAILED)

    cards = await get_latest_editorial_cards(db_session, limit=_GENEROUS_LIMIT)

    assert draft.id not in {c.draft_id for c in cards}


@pytest.mark.asyncio
async def test_running_incomplete_tasks_are_excluded(db_session: AsyncSession) -> None:
    excluded_ids: set[uuid.UUID] = set()
    for status in (TaskStatus.CREATED, TaskStatus.RUNNING, TaskStatus.WAITING):
        draft, _event = await _eligible_draft(db_session, status=status)
        excluded_ids.add(draft.id)

    cards = await get_latest_editorial_cards(db_session, limit=_GENEROUS_LIMIT)

    assert excluded_ids.isdisjoint({c.draft_id for c in cards})


@pytest.mark.asyncio
async def test_newest_first_ordering(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    older, _ = await _eligible_draft(db_session, created_at=now - timedelta(minutes=5))
    newer, _ = await _eligible_draft(db_session, created_at=now)

    cards = await get_latest_editorial_cards(db_session, limit=_GENEROUS_LIMIT)

    relevant_order = [c.draft_id for c in cards if c.draft_id in {older.id, newer.id}]
    assert relevant_order == [newer.id, older.id]


@pytest.mark.asyncio
async def test_deterministic_tie_break_by_id_descending(db_session: AsyncSession) -> None:
    shared_ts = datetime.now(timezone.utc)
    first, _ = await _eligible_draft(db_session, created_at=shared_ts)
    second, _ = await _eligible_draft(db_session, created_at=shared_ts)

    cards = await get_latest_editorial_cards(db_session, limit=_GENEROUS_LIMIT)

    relevant_order = [c.draft_id for c in cards if c.draft_id in {first.id, second.id}]
    assert relevant_order == sorted([first.id, second.id], reverse=True)


@pytest.mark.asyncio
async def test_limit_is_enforced(db_session: AsyncSession) -> None:
    for _ in range(6):
        await _eligible_draft(db_session)

    cards = await get_latest_editorial_cards(db_session, limit=5)

    # At least 6 eligible rows exist (the 6 just created) regardless of any other data sharing
    # this database, so a limit of 5 is always fully exercised.
    assert len(cards) == 5


@pytest.mark.asyncio
async def test_empty_result_returns_empty_list(db_session: AsyncSession) -> None:
    # Scoped to this test's own SAVEPOINT-rolled-back transaction only - never committed, never
    # destructive to any pre-existing row (e.g. Phase 10's own M6 live-validation data, which
    # shares this database).
    await db_session.execute(delete(ContentDraft))

    cards = await get_latest_editorial_cards(db_session, limit=5)

    assert cards == []


@pytest.mark.asyncio
async def test_joined_news_event_metadata_is_attached(db_session: AsyncSession) -> None:
    source = await _make_source(db_session)
    event = await _make_event(
        db_session,
        source,
        title="Specific event title",
        category=EventCategory.CYBERSECURITY,
        url="https://example.com/specific?x=1&y=2",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    task = await _make_task(db_session, event)
    draft = await _make_draft(db_session, task, title="Specific draft", body="Specific body")

    cards = await get_latest_editorial_cards(db_session, limit=_GENEROUS_LIMIT)

    matches = [c for c in cards if c.draft_id == draft.id]
    assert len(matches) == 1
    card = matches[0]
    assert card.draft_title == "Specific draft"
    assert card.draft_body == "Specific body"
    assert card.news_title == "Specific event title"
    assert card.news_category == "CYBERSECURITY"
    assert card.news_url == "https://example.com/specific?x=1&y=2"
    assert card.news_published_at == datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_null_news_url_is_handled_without_error(db_session: AsyncSession) -> None:
    source = await _make_source(db_session)
    event = await _make_event(db_session, source, url=None)
    task = await _make_task(db_session, event)
    draft = await _make_draft(db_session, task)

    cards = await get_latest_editorial_cards(db_session, limit=_GENEROUS_LIMIT)

    matches = [c for c in cards if c.draft_id == draft.id]
    assert len(matches) == 1
    assert matches[0].news_url is None


def test_no_ai_or_workflow_import_in_query_service() -> None:
    """Mechanical import-boundary check (mirrors tests/test_capability_testing_convention.py's
    AST-based approach) - proves "no AI generation, no workflow mutation" mechanically."""
    tree = ast.parse(_SERVICE_FILE.read_text(encoding="utf-8"), filename=str(_SERVICE_FILE))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            imported.add(node.module)

    for forbidden in _FORBIDDEN_IMPORTS:
        matching = {name for name in imported if name == forbidden or name.startswith(forbidden + ".")}
        assert not matching, f"editorial_inbox_service.py imports forbidden module(s): {matching}"
