"""NINJA PULSE RECAP Phase R2 integration, Phase C.1: bot.keyboards.event_recap_review - pure
codec + keyboard builder, no database, no aiogram Bot call. Mirrors tests/
test_telegraph_shortlist.py's own established codec-test style.
"""
from __future__ import annotations

from uuid import uuid4

from bot.keyboards.event_recap_review import (
    build_event_recap_review_keyboard,
    encode_callback_data,
    parse_callback_data,
)


def test_encode_decode_round_trip_for_both_actions() -> None:
    story_id = uuid4()
    for action in ("approve", "reject"):
        data = encode_callback_data(action, story_id)
        assert data == f"evrecrev:{action}:{story_id}"
        assert parse_callback_data(data) == (action, story_id)


def test_parse_rejects_wrong_prefix() -> None:
    assert parse_callback_data(f"tgartrev:approve:{uuid4()}") is None


def test_parse_rejects_unknown_action() -> None:
    assert parse_callback_data(f"evrecrev:publish:{uuid4()}") is None


def test_parse_rejects_malformed_uuid() -> None:
    assert parse_callback_data("evrecrev:approve:not-a-uuid") is None


def test_parse_rejects_malformed_shape() -> None:
    assert parse_callback_data("evrecrev:approve") is None
    assert parse_callback_data("") is None


def test_keyboard_has_exactly_two_buttons_never_none() -> None:
    """Unlike build_article_review_keyboard(), never returns None for a "terminal state" - Phase
    C.1 has no persisted decision state to check (bot/keyboards/event_recap_review.py's own
    docstring)."""
    story_id = uuid4()
    keyboard = build_event_recap_review_keyboard(story_id)
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 1
    row = keyboard.inline_keyboard[0]
    assert len(row) == 2
    assert row[0].callback_data == encode_callback_data("approve", story_id)
    assert row[1].callback_data == encode_callback_data("reject", story_id)


def test_keyboard_never_launches_publication() -> None:
    """No button text/callback references publishing - approve/reject only prepare for a future
    review flow (module docstring)."""
    keyboard = build_event_recap_review_keyboard(uuid4())
    for row in keyboard.inline_keyboard:
        for button in row:
            assert "publish" not in (button.callback_data or "").lower()
            assert "опублик" not in button.text.lower()
