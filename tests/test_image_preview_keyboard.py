"""Tests for bot.keyboards.image_preview's Phase 16 M6 callback_data codec and keyboard builder
(docs/phase16_m6_telegram_editorial_preview_report.md §6). Pure construction/parsing tests - no
Bot, no dispatcher, no network.
"""
import uuid

import pytest
from aiogram.types import InlineKeyboardMarkup

from bot.keyboards.image_preview import build_image_preview_keyboard, encode_callback_data, parse_callback_data
from services.image_persistence import EditorialImageCandidate


def _candidate(**overrides) -> EditorialImageCandidate:
    base = dict(
        id=uuid.uuid4(), candidate_id="c1", rank=1, relevance_score=80, quality_score=80,
        discovery_method="open_graph_image", source_relationship="same_article",
        relevance_reason="r", width=800, height=600, observed_mime="image/jpeg", image_format="JPEG",
        storage_status="stored", storage_key="images/ab/abc.jpg", telegram_file_id=None,
        editor_decision=None, source_url="https://example.com/a", article_url="https://example.com/a",
        warnings=None, is_expired=False,
    )
    base.update(overrides)
    return EditorialImageCandidate(**base)


def test_encode_decode_roundtrip() -> None:
    draft_id = uuid.uuid4()
    data = encode_callback_data("next", draft_id, 3)
    parsed = parse_callback_data(data)
    assert parsed == ("next", draft_id, 3)


def test_encoded_callback_data_stays_within_telegram_byte_limit() -> None:
    data = encode_callback_data("prev", uuid.uuid4(), 19)
    assert len(data.encode("utf-8")) <= 64


@pytest.mark.parametrize(
    "bad_data",
    [
        "",
        "not-imgprev-at-all",
        "imgprev:onlytwoparts",
        "imgprev:badaction:11111111-1111-1111-1111-111111111111:0",
        "imgprev:next:not-a-uuid:0",
        "imgprev:next:11111111-1111-1111-1111-111111111111:not-an-int",
        "imgprev:next:11111111-1111-1111-1111-111111111111:-1",
        "otherprefix:next:11111111-1111-1111-1111-111111111111:0",
    ],
)
def test_parse_rejects_malformed_callback_data(bad_data: str) -> None:
    assert parse_callback_data(bad_data) is None


def test_parse_rejects_path_or_injection_like_payloads() -> None:
    """docs §9 - callback_data is user-controllable transport; a crafted payload must never be
    interpreted as a valid action/draft/index tuple."""
    assert parse_callback_data("imgprev:use:../../etc/passwd:0") is None
    assert parse_callback_data("imgprev:use:11111111-1111-1111-1111-111111111111:0; DROP TABLE x") is None


def test_keyboard_includes_next_but_not_previous_at_first_index() -> None:
    draft_id = uuid.uuid4()
    candidate = _candidate()
    keyboard = build_image_preview_keyboard(content_draft_id=draft_id, index=0, total=3, candidate=candidate)

    texts = [button.text for row in keyboard.inline_keyboard for button in row]
    assert "⬅️ Previous" not in texts
    assert "➡️ Next" in texts


def test_keyboard_includes_previous_but_not_next_at_last_index() -> None:
    draft_id = uuid.uuid4()
    candidate = _candidate()
    keyboard = build_image_preview_keyboard(content_draft_id=draft_id, index=2, total=3, candidate=candidate)

    texts = [button.text for row in keyboard.inline_keyboard for button in row]
    assert "⬅️ Previous" in texts
    assert "➡️ Next" not in texts


def test_keyboard_omits_nav_row_entirely_when_only_one_candidate() -> None:
    draft_id = uuid.uuid4()
    candidate = _candidate()
    keyboard = build_image_preview_keyboard(content_draft_id=draft_id, index=0, total=1, candidate=candidate)

    texts = [button.text for row in keyboard.inline_keyboard for button in row]
    assert "⬅️ Previous" not in texts
    assert "➡️ Next" not in texts
    assert "✅ Use image" in texts
    assert "🚫 No image" in texts


def test_keyboard_always_includes_use_and_no_image_buttons() -> None:
    draft_id = uuid.uuid4()
    candidate = _candidate()
    keyboard = build_image_preview_keyboard(content_draft_id=draft_id, index=1, total=3, candidate=candidate)

    texts = [button.text for row in keyboard.inline_keyboard for button in row]
    assert "✅ Use image" in texts
    assert "🚫 No image" in texts


def test_keyboard_includes_open_source_url_button_when_url_present() -> None:
    draft_id = uuid.uuid4()
    candidate = _candidate(article_url="https://example.com/article", source_url=None)
    keyboard = build_image_preview_keyboard(content_draft_id=draft_id, index=0, total=1, candidate=candidate)

    url_buttons = [b for row in keyboard.inline_keyboard for b in row if b.url]
    assert len(url_buttons) == 1
    assert url_buttons[0].url == "https://example.com/article"
    assert url_buttons[0].callback_data is None


def test_keyboard_omits_open_source_button_when_no_url() -> None:
    draft_id = uuid.uuid4()
    candidate = _candidate(article_url=None, source_url=None)
    keyboard = build_image_preview_keyboard(content_draft_id=draft_id, index=0, total=1, candidate=candidate)

    url_buttons = [b for row in keyboard.inline_keyboard for b in row if b.url]
    assert url_buttons == []


def test_keyboard_callback_buttons_encode_the_same_draft_id() -> None:
    draft_id = uuid.uuid4()
    candidate = _candidate()
    keyboard = build_image_preview_keyboard(content_draft_id=draft_id, index=1, total=3, candidate=candidate)

    for row in keyboard.inline_keyboard:
        for button in row:
            if button.callback_data:
                parsed = parse_callback_data(button.callback_data)
                assert parsed is not None
                assert parsed[1] == draft_id


def test_keyboard_next_button_index_is_current_plus_one() -> None:
    draft_id = uuid.uuid4()
    candidate = _candidate()
    keyboard = build_image_preview_keyboard(content_draft_id=draft_id, index=1, total=3, candidate=candidate)

    next_button = next(b for row in keyboard.inline_keyboard for b in row if b.text == "➡️ Next")
    parsed = parse_callback_data(next_button.callback_data)
    assert parsed == ("next", draft_id, 2)


def test_keyboard_returns_inline_keyboard_markup() -> None:
    draft_id = uuid.uuid4()
    candidate = _candidate()
    keyboard = build_image_preview_keyboard(content_draft_id=draft_id, index=0, total=1, candidate=candidate)
    assert isinstance(keyboard, InlineKeyboardMarkup)
