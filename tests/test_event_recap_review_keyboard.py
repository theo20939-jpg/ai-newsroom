"""NINJA PULSE RECAP Phase R2 integration, Phase D.0: bot.keyboards.event_recap_review - pure
codec + keyboard builder, no database access, no aiogram Bot call. Mirrors tests/
test_telegraph_shortlist.py's own established codec-test style.

Phase D.0 change from Phase C.1: the keyboard is now keyed on the durable `EventRecapReview.id`
(not `EventRecapCandidate.story_id`) and returns `None` once a final decision is recorded -
mirrors bot/keyboards/telegraph_article_review.py's own identical "terminal state, no keyboard"
convention.
"""
from __future__ import annotations

from uuid import uuid4

from bot.keyboards.event_recap_review import (
    build_event_recap_review_keyboard,
    encode_callback_data,
    parse_callback_data,
)
from database.models.event_recap_review import EventRecapReview, EventRecapReviewStatus


def _review(status: EventRecapReviewStatus = EventRecapReviewStatus.PENDING) -> EventRecapReview:
    return EventRecapReview(id=uuid4(), recap_task_id=uuid4(), status=status)


def test_encode_decode_round_trip_for_both_actions() -> None:
    review_id = uuid4()
    for action in ("approve", "needs_revision"):
        data = encode_callback_data(action, review_id)
        assert data == f"eventrecap:{action}:{review_id}"
        assert parse_callback_data(data) == (action, review_id)


def test_parse_rejects_wrong_prefix() -> None:
    assert parse_callback_data(f"tgartrev:approve:{uuid4()}") is None


def test_parse_rejects_unknown_action() -> None:
    assert parse_callback_data(f"eventrecap:publish:{uuid4()}") is None


def test_parse_rejects_old_reject_action() -> None:
    """Phase C.1's own "reject" action string is intentionally no longer recognized - Phase D.0
    renamed it to "needs_revision" to match EventRecapReviewStatus.NEEDS_REVISION exactly."""
    assert parse_callback_data(f"eventrecap:reject:{uuid4()}") is None


def test_parse_rejects_malformed_uuid() -> None:
    assert parse_callback_data("eventrecap:approve:not-a-uuid") is None


def test_parse_rejects_malformed_shape() -> None:
    assert parse_callback_data("eventrecap:approve") is None
    assert parse_callback_data("") is None


def test_keyboard_has_exactly_two_buttons_while_pending() -> None:
    review = _review()
    keyboard = build_event_recap_review_keyboard(review)
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 1
    row = keyboard.inline_keyboard[0]
    assert len(row) == 2
    assert row[0].callback_data == encode_callback_data("approve", review.id)
    assert row[1].callback_data == encode_callback_data("needs_revision", review.id)


def test_keyboard_is_none_once_approved() -> None:
    review = _review(EventRecapReviewStatus.APPROVED)
    assert build_event_recap_review_keyboard(review) is None


def test_keyboard_is_none_once_needs_revision() -> None:
    review = _review(EventRecapReviewStatus.NEEDS_REVISION)
    assert build_event_recap_review_keyboard(review) is None


def test_keyboard_never_launches_publication() -> None:
    """No button text/callback references publishing - approve/needs_revision only record a
    review decision, never trigger publication (module docstring)."""
    review = _review()
    keyboard = build_event_recap_review_keyboard(review)
    assert keyboard is not None
    for row in keyboard.inline_keyboard:
        for button in row:
            assert "publish" not in (button.callback_data or "").lower()
            assert "опублик" not in button.text.lower()


# ---------------------------------------------------------------------------------------------
# Phase I.2.2L - source-verification button (Section 10, requirements A-F at the keyboard level)
# ---------------------------------------------------------------------------------------------


def test_source_url_adds_a_second_row_retaining_the_decision_buttons() -> None:
    """Section 10.A + 10.B: the existing Approve/Needs-revision row must remain untouched, and a
    second row must be added containing exactly one URL button pointing at `source_url`."""
    review = _review()
    keyboard = build_event_recap_review_keyboard(review, source_url="https://example.com/article")
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 2

    decision_row = keyboard.inline_keyboard[0]
    assert len(decision_row) == 2
    assert decision_row[0].callback_data == encode_callback_data("approve", review.id)
    assert decision_row[1].callback_data == encode_callback_data("needs_revision", review.id)

    source_row = keyboard.inline_keyboard[1]
    assert len(source_row) == 1
    assert source_row[0].url == "https://example.com/article"
    assert "Источник" in source_row[0].text


def test_missing_source_url_omits_the_second_row() -> None:
    """Section 10.F: `source_url=None` (the default) must produce exactly the original one-row,
    two-button keyboard - no placeholder/dead button, no crash."""
    review = _review()
    keyboard = build_event_recap_review_keyboard(review)
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 1

    keyboard_explicit_none = build_event_recap_review_keyboard(review, source_url=None)
    assert keyboard_explicit_none is not None
    assert len(keyboard_explicit_none.inline_keyboard) == 1

    keyboard_empty_string = build_event_recap_review_keyboard(review, source_url="")
    assert keyboard_empty_string is not None
    assert len(keyboard_empty_string.inline_keyboard) == 1


def test_source_button_never_carries_the_ninja_pulse_subscribe_cta() -> None:
    """Section 10.D: this internal review UX must never gain the public NINJA PULSE subscribe
    CTA, regardless of a source URL being present."""
    review = _review()
    keyboard = build_event_recap_review_keyboard(review, source_url="https://example.com/article")
    assert keyboard is not None
    for row in keyboard.inline_keyboard:
        for button in row:
            assert "Подписаться" not in button.text
            assert button.url != "https://t.me/ninja_pulse"


def test_exactly_one_source_button_never_duplicated() -> None:
    """Section 10.E: exactly one source-verification URL button total, never duplicated across
    rows even if this function were called with the same source_url more than once per message."""
    review = _review()
    keyboard = build_event_recap_review_keyboard(review, source_url="https://example.com/article")
    assert keyboard is not None
    url_buttons = [button for row in keyboard.inline_keyboard for button in row if button.url]
    assert len(url_buttons) == 1


def test_source_button_only_present_while_pending() -> None:
    """A source_url passed for an already-decided review is moot - the whole keyboard, including
    any source row, must still disappear once a final decision has been recorded (mirrors the
    pre-existing terminal-state contract this phase does not change)."""
    for status in (EventRecapReviewStatus.APPROVED, EventRecapReviewStatus.NEEDS_REVISION):
        review = _review(status)
        assert build_event_recap_review_keyboard(review, source_url="https://example.com/article") is None
