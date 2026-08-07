"""Phase 19 M7: proves persist_story_context_snapshot() builds a correctly-shaped
StoryContextSnapshot row from a list of StoryTimelineEntry objects. Uses a minimal fake session
(captures the one row passed to .add(), never touches a real database) - mirrors tests/
test_editorial_plan_persistence.py's own established pattern exactly.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from services.story_context import StoryTimelineEntry
from services.story_context_persistence import persist_story_context_snapshot


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, row: object) -> None:
        self.added.append(row)


def _entry(**overrides: object) -> StoryTimelineEntry:
    defaults: dict[str, object] = dict(
        event_id=uuid.uuid4(), source="Example Source",
        published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        collected_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        match_type="new_story", match_score=1.0, source_role=None, content_draft_id=None,
        telegram_message_id=None, delta="new_story", already_published=False,
        introduced_new_facts=["launch"], confirmed_existing_facts=[],
    )
    defaults.update(overrides)
    return StoryTimelineEntry(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_persists_one_row_with_serialized_timeline() -> None:
    session = _FakeSession()
    event_id = uuid.uuid4()
    story_id = uuid.uuid4()
    timeline = [_entry(), _entry(match_type="story_update", delta="new_information")]

    await persist_story_context_snapshot(session, event_id=event_id, story_id=story_id, timeline=timeline)

    assert len(session.added) == 1
    row = session.added[0]
    assert row.event_id == event_id
    assert row.story_id == story_id
    assert row.content_draft_id is None
    assert len(row.timeline) == 2
    assert row.timeline[0]["match_type"] == "new_story"
    assert row.timeline[1]["match_type"] == "story_update"
    assert row.timeline[0]["event_id"] == str(timeline[0].event_id)
    assert row.timeline[0]["published_at"] == timeline[0].published_at.isoformat()


@pytest.mark.asyncio
async def test_content_draft_id_is_persisted_when_provided() -> None:
    session = _FakeSession()
    content_draft_id = uuid.uuid4()

    await persist_story_context_snapshot(
        session, event_id=uuid.uuid4(), story_id=uuid.uuid4(), timeline=[_entry()],
        content_draft_id=content_draft_id,
    )

    assert session.added[0].content_draft_id == content_draft_id


@pytest.mark.asyncio
async def test_none_fields_serialize_to_none_not_string() -> None:
    session = _FakeSession()
    entry = _entry(published_at=None, telegram_message_id=None, source=None, source_role=None)

    await persist_story_context_snapshot(session, event_id=uuid.uuid4(), story_id=uuid.uuid4(), timeline=[entry])

    row_entry = session.added[0].timeline[0]
    assert row_entry["published_at"] is None
    assert row_entry["telegram_message_id"] is None
    assert row_entry["source"] is None
    assert row_entry["source_role"] is None
