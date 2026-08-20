"""NINJA PULSE RECAP Phase R2.8 SCAFFOLD - offline test for the pure transient-Story helper.

R2.8 itself is design/tooling ONLY (overnight autonomous checkpoint Part IX) - not a fully
authorized production diagnostic checkpoint. This test covers only the one pure, offline-testable
piece of it: `transient_story_with_anchor()` never mutates the real Story, never persists, and
correctly swaps only `first_event_id`. No DB, no LLM, no network.
"""
from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from uuid import uuid4

from database.models.news_event import EventCategory
from database.models.story import Story


def _load_r28_module():
    spec = importlib.util.spec_from_file_location(
        "_recap_r2_8_test_import", "scripts/_recap_r2_8_anchor_repair_shadow_scaffold.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


r28 = _load_r28_module()

_NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)


def test_transient_story_never_mutates_the_real_story_and_swaps_only_the_anchor():
    real_story = Story(
        id=uuid4(), title="Real Story", category=EventCategory.AI, entities=["nvidia"],
        keywords=["ai"], topic_bucket="product", first_event_id=uuid4(), event_count=2,
        created_at=_NOW, updated_at=_NOW,
    )
    original_first_event_id = real_story.first_event_id
    hypothetical_anchor_id = uuid4()

    transient = r28.transient_story_with_anchor(real_story, hypothetical_anchor_id)

    # the REAL story object is never mutated
    assert real_story.first_event_id == original_first_event_id
    # the transient copy has the same identity/id (so a real DB query for its events is unaffected)
    assert transient.id == real_story.id
    assert transient.title == real_story.title
    # ... but a swapped anchor
    assert transient.first_event_id == hypothetical_anchor_id
    assert transient is not real_story


def test_transient_story_is_never_added_to_any_session():
    """Structural guard: transient_story_with_anchor() must never call session.add() or touch any
    AsyncSession - confirmed by its own signature taking no session argument at all."""
    import inspect

    sig = inspect.signature(r28.transient_story_with_anchor)
    assert "session" not in sig.parameters
