"""Phase 19 M8: proves persist_source_intelligence() builds a correctly-shaped
NewsEventSourceIntelligence row. Uses a minimal fake session (mirrors tests/
test_editorial_plan_persistence.py's own established pattern), never touches a real database.
"""
from __future__ import annotations

import uuid

import pytest

from services.source_intelligence import POSSIBLE_ORIGINAL
from services.source_intelligence_persistence import persist_source_intelligence


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, row: object) -> None:
        self.added.append(row)


@pytest.mark.asyncio
async def test_persists_one_row_with_expected_fields() -> None:
    session = _FakeSession()
    event_id = uuid.uuid4()

    await persist_source_intelligence(
        session, news_event_id=event_id, role=POSSIBLE_ORIGINAL, is_first_in_story=True,
        match_type="new_story", reliability_score=0.8,
    )

    assert len(session.added) == 1
    row = session.added[0]
    assert row.news_event_id == event_id
    assert row.role == POSSIBLE_ORIGINAL
    assert row.is_first_in_story is True
    assert row.match_type == "new_story"
    assert row.reliability_score == 0.8


@pytest.mark.asyncio
async def test_none_match_type_and_reliability_persist_as_none() -> None:
    session = _FakeSession()

    await persist_source_intelligence(
        session, news_event_id=uuid.uuid4(), role="UNKNOWN", is_first_in_story=False,
        match_type=None, reliability_score=None,
    )

    row = session.added[0]
    assert row.match_type is None
    assert row.reliability_score is None
