"""TELEGRAPH Checkpoint 6: pure Telegram-presentation tests - bot.telegraph_article_review_
formatting and bot.keyboards.telegraph_article_review. No database, no aiogram Bot/dispatcher, no
network - every input is a hand-built TelegraphArticleReview dataclass instance.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from database.models.telegraph_article_review import TelegraphArticleReview, TelegraphArticleReviewStatus
from bot.keyboards.telegraph_article_review import (
    build_article_review_keyboard,
    encode_callback_data,
    parse_callback_data,
)
from bot.telegraph_article_review_formatting import (
    SAFE_LIMIT,
    render_article_review_text,
)
from schemas.editorial import EditorialChannel

_ARTICLE = {
    "headline": "Product Y Launch",
    "lead": "Company X released product Y, a development that may reshape the market.",
    "context": [], "timeline": [], "confirmed_facts": ["Fact A.", "Fact B.", "Fact C.", "Fact D."],
    "analysis": [], "implications": [], "background": [], "risks": [],
    "conclusion": "The full impact remains to be seen.", "sources": ["Source A", "Source B"],
}


def _review(
    *, status: TelegraphArticleReviewStatus = TelegraphArticleReviewStatus.PENDING,
    published_url: str | None = None,
) -> TelegraphArticleReview:
    return TelegraphArticleReview(
        id=uuid4(), article_task_id=uuid4(), proposal_id=uuid4(), status=status,
        decided_at=None, decided_by_telegram_user_id=None,
        telegram_chat_id=None, telegram_message_id=None, telegram_thread_id=None,
        published_url=published_url, published_at=None,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )


def test_renders_headline_and_lead() -> None:
    text = render_article_review_text(_review(), _ARTICLE, EditorialChannel.NINJA_AI)
    assert _ARTICLE["headline"] in text
    assert _ARTICLE["lead"] in text


def test_renders_bounded_fact_preview_not_all_facts() -> None:
    text = render_article_review_text(_review(), _ARTICLE, EditorialChannel.NINJA_AI)
    assert "Fact A." in text
    assert "и ещё" in text  # only a preview, notes the rest exists


def test_renders_russian_operator_text() -> None:
    text = render_article_review_text(_review(), _ARTICLE, EditorialChannel.NINJA_AI)
    assert "TELEGRAPH ARTICLE" in text
    assert "предпросмотр" in text


def test_renders_current_status_line() -> None:
    approved_text = render_article_review_text(
        _review(status=TelegraphArticleReviewStatus.APPROVED), _ARTICLE, EditorialChannel.NINJA_AI,
    )
    assert "✅ Статья одобрена" in approved_text
    revision_text = render_article_review_text(
        _review(status=TelegraphArticleReviewStatus.NEEDS_REVISION), _ARTICLE, EditorialChannel.NINJA_AI,
    )
    assert "✏️ Требуется доработка" in revision_text


def test_shows_published_url_when_approved_and_published() -> None:
    text = render_article_review_text(
        _review(status=TelegraphArticleReviewStatus.APPROVED, published_url="https://telegra.ph/Test-08-31"),
        _ARTICLE, EditorialChannel.NINJA_AI,
    )
    assert "✅ Статья опубликована" in text
    assert "https://telegra.ph/Test-08-31" in text
    assert "✅ Статья одобрена" in text  # decision status line still present alongside it


def test_no_published_line_when_approved_but_not_yet_published() -> None:
    text = render_article_review_text(
        _review(status=TelegraphArticleReviewStatus.APPROVED, published_url=None), _ARTICLE, EditorialChannel.NINJA_AI,
    )
    assert "Статья опубликована" not in text


def test_no_published_line_while_pending_even_if_url_somehow_set() -> None:
    text = render_article_review_text(
        _review(status=TelegraphArticleReviewStatus.PENDING, published_url="https://telegra.ph/Should-Not-Show"),
        _ARTICLE, EditorialChannel.NINJA_AI,
    )
    assert "Should-Not-Show" not in text


def test_text_within_safe_limit_for_a_normal_article() -> None:
    text = render_article_review_text(_review(), _ARTICLE, EditorialChannel.NINJA_PULSE)
    assert len(text) <= SAFE_LIMIT


def test_never_dumps_full_article_body() -> None:
    huge_article = {**_ARTICLE, "confirmed_facts": [f"Fact {i} " * 50 for i in range(50)]}
    text = render_article_review_text(_review(), huge_article, EditorialChannel.NINJA_PULSE)
    assert len(text) <= SAFE_LIMIT  # bounded preview, never the full 50-fact dump


def test_ninja_ai_channel_displays_correct_label() -> None:
    text = render_article_review_text(_review(), _ARTICLE, EditorialChannel.NINJA_AI)
    assert "🥷 Ninja AI" in text
    assert "⚡ Ninja Pulse" not in text


def test_ninja_pulse_channel_displays_correct_label() -> None:
    text = render_article_review_text(_review(), _ARTICLE, EditorialChannel.NINJA_PULSE)
    assert "⚡ Ninja Pulse" in text
    assert "🥷 Ninja AI" not in text


def test_callback_data_within_telegram_limits() -> None:
    review_id = uuid4()
    data = encode_callback_data("approve", review_id)
    assert len(data.encode("utf-8")) <= 64


def test_callback_data_round_trips() -> None:
    review_id = uuid4()
    data = encode_callback_data("revise", review_id)
    assert parse_callback_data(data) == ("revise", review_id)


def test_parse_rejects_malformed_and_wrong_prefix() -> None:
    assert parse_callback_data("not-a-payload") is None
    assert parse_callback_data("tgshort:approve:" + str(uuid4())) is None
    assert parse_callback_data("tgartrev:approve:not-a-uuid") is None
    assert parse_callback_data("tgartrev:delete:" + str(uuid4())) is None


def test_keyboard_present_while_pending() -> None:
    keyboard = build_article_review_keyboard(_review())
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 1
    assert len(keyboard.inline_keyboard[0]) == 2


def test_keyboard_none_once_decided() -> None:
    assert build_article_review_keyboard(_review(status=TelegraphArticleReviewStatus.APPROVED)) is None
    assert build_article_review_keyboard(_review(status=TelegraphArticleReviewStatus.NEEDS_REVISION)) is None


def test_button_text_never_exposes_internal_uuid() -> None:
    review = _review()
    keyboard = build_article_review_keyboard(review)
    assert keyboard is not None
    for row in keyboard.inline_keyboard:
        for button in row:
            assert str(review.id) not in (button.text or "")
