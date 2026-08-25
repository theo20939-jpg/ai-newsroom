"""Phase I.2: bot.keyboards.final_post_review tests. Pure - no aiogram Bot, no database access."""
from __future__ import annotations

import uuid

from bot.keyboards.final_post_review import build_final_post_review_keyboard, encode_callback_data, parse_callback_data
from database.models.final_post_review import FinalPostReview, FinalPostReviewStatus


def test_encode_decode_round_trip():
    review_id = uuid.uuid4()
    data = encode_callback_data("approve", review_id)
    assert parse_callback_data(data) == ("approve", review_id)


def test_prefix_is_finalpost_never_eventrecap():
    data = encode_callback_data("approve", uuid.uuid4())
    assert data.startswith("finalpost:")
    assert "eventrecap" not in data


def test_parse_rejects_malformed_payloads():
    assert parse_callback_data("not-well-formed") is None
    assert parse_callback_data("finalpost:approve") is None
    assert parse_callback_data("finalpost:bogus_action:" + str(uuid.uuid4())) is None
    assert parse_callback_data("finalpost:approve:not-a-uuid") is None
    assert parse_callback_data("eventrecap:approve:" + str(uuid.uuid4())) is None


def test_keyboard_present_while_pending():
    review = FinalPostReview(id=uuid.uuid4(), content_draft_id=uuid.uuid4(), status=FinalPostReviewStatus.PENDING)
    keyboard = build_final_post_review_keyboard(review)
    assert keyboard is not None
    texts = [button.text for row in keyboard.inline_keyboard for button in row]
    assert "✅ К публикации" in texts
    assert "✏️ На доработку" in texts


def test_keyboard_none_once_final():
    for status in (FinalPostReviewStatus.APPROVED_FOR_PUBLICATION, FinalPostReviewStatus.NEEDS_REVISION):
        review = FinalPostReview(id=uuid.uuid4(), content_draft_id=uuid.uuid4(), status=status)
        assert build_final_post_review_keyboard(review) is None


def test_callback_data_scoped_to_exact_review_id():
    review_a = uuid.uuid4()
    review_b = uuid.uuid4()
    assert encode_callback_data("approve", review_a) != encode_callback_data("approve", review_b)
