"""TELEGRAPH Checkpoint 6 (revised, TELEGRAPH EDITORIAL CHAT DELIVERY): pure Telegram-presentation
tests - bot.telegraph_article_review_formatting and bot.keyboards.telegraph_article_review. No
database, no aiogram Bot/dispatcher, no network - every input is a hand-built TelegraphArticleReview
dataclass instance.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from database.models.telegraph_article_review import TelegraphArticleReview, TelegraphArticleReviewStatus
from bot.keyboards.telegraph_article_review import (
    build_article_review_keyboard,
    encode_callback_data,
    parse_callback_data,
)
from bot.telegraph_article_review_formatting import (
    SAFE_LIMIT,
    ArticleReviewTextTooLongError,
    build_article_body_chunks,
    render_article_footer_text,
    render_article_review_header,
)
from schemas.editorial import EditorialChannel

_ARTICLE: dict[str, Any] = {
    "headline": "Product Y Launch",
    "lead": "Company X released product Y, a development that may reshape the market.",
    "context": [], "timeline": [], "confirmed_facts": ["Fact A.", "Fact B.", "Fact C.", "Fact D."],
    "analysis": [], "implications": [], "background": [], "risks": [],
    "conclusion": "The full impact remains to be seen.", "sources": ["Source A", "Source B"],
}


def _review(*, status: TelegraphArticleReviewStatus = TelegraphArticleReviewStatus.PENDING) -> TelegraphArticleReview:
    return TelegraphArticleReview(
        id=uuid4(), article_task_id=uuid4(), proposal_id=uuid4(), status=status,
        decided_at=None, decided_by_telegram_user_id=None,
        telegram_chat_id=None, telegram_message_id=None, telegram_thread_id=None,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )


def test_header_renders_headline_and_channel_no_lead() -> None:
    text = render_article_review_header(_ARTICLE, EditorialChannel.NINJA_AI)
    assert _ARTICLE["headline"] in text
    assert "TELEGRAPH ARTICLE" in text
    assert _ARTICLE["lead"] not in text  # lead belongs to the body, not the header


def test_header_never_shows_a_status_line() -> None:
    # The header is sent once and never edited again - embedding a status here would go stale
    # the instant a decision is made (only the footer is ever re-rendered).
    text = render_article_review_header(_ARTICLE, EditorialChannel.NINJA_AI)
    assert "Статья одобрена" not in text
    assert "Решение не принято" not in text


def test_header_ninja_ai_channel_displays_correct_label() -> None:
    text = render_article_review_header(_ARTICLE, EditorialChannel.NINJA_AI)
    assert "🥷 Ninja AI" in text
    assert "⚡ Ninja Pulse" not in text


def test_header_ninja_pulse_channel_displays_correct_label() -> None:
    text = render_article_review_header(_ARTICLE, EditorialChannel.NINJA_PULSE)
    assert "⚡ Ninja Pulse" in text
    assert "🥷 Ninja AI" not in text


def test_body_chunks_contain_full_article_never_a_preview() -> None:
    chunks = build_article_body_chunks(_ARTICLE)
    joined = "\n\n".join(chunks)
    assert _ARTICLE["lead"] in joined
    for fact in _ARTICLE["confirmed_facts"]:
        assert fact in joined  # every fact present, not just the first few
    assert _ARTICLE["conclusion"] in joined
    assert "предпросмотр" not in joined  # no "preview" language anywhere


def test_body_chunks_never_contain_sources_or_headline() -> None:
    chunks = build_article_body_chunks(_ARTICLE)
    joined = "\n\n".join(chunks)
    assert _ARTICLE["headline"] not in joined  # headline belongs to the header only
    for source in _ARTICLE["sources"]:
        assert source not in joined  # sources belong to the footer only


def test_body_chunks_each_within_safe_limit() -> None:
    huge_article = {**_ARTICLE, "confirmed_facts": [f"Fact {i} some real detail text here." for i in range(300)]}
    chunks = build_article_body_chunks(huge_article)
    assert len(chunks) > 1  # a genuinely long article must split into multiple messages
    for chunk in chunks:
        assert len(chunk.encode("utf-16-le")) // 2 <= SAFE_LIMIT


def test_body_chunks_never_drop_any_fact_when_split_across_many_messages() -> None:
    huge_article = {**_ARTICLE, "confirmed_facts": [f"Unique fact number {i} with some detail." for i in range(300)]}
    chunks = build_article_body_chunks(huge_article)
    joined = "\n\n".join(chunks)
    for i in range(300):
        assert f"Unique fact number {i} with some detail." in joined


def test_body_chunks_preserve_paragraph_order() -> None:
    article = {
        **_ARTICLE, "context": ["Context 1", "Context 2"], "timeline": ["Timeline 1"],
        "confirmed_facts": ["Fact A.", "Fact B."], "analysis": ["Analysis 1"],
    }
    chunks = build_article_body_chunks(article)
    joined = "\n\n".join(chunks)
    positions = [
        joined.index(article["lead"]), joined.index("Context 1"), joined.index("Context 2"),
        joined.index("Timeline 1"), joined.index("Fact A."), joined.index("Fact B."),
        joined.index("Analysis 1"), joined.index(article["conclusion"]),
    ]
    assert positions == sorted(positions)


def test_body_chunks_never_split_a_single_paragraph_across_two_messages() -> None:
    # An ordinary-length paragraph never gets cut mid-sentence just because it sits near a chunk
    # boundary - it either fits whole in the current chunk or starts a fresh one whole.
    article = {**_ARTICLE, "confirmed_facts": [f"Fact {i}: " + ("x" * 100) for i in range(60)]}
    chunks = build_article_body_chunks(article)
    for i in range(60):
        needle = f"Fact {i}: " + ("x" * 100)
        assert sum(needle in chunk for chunk in chunks) == 1  # present whole, in exactly one chunk


def test_footer_renders_numbered_sources() -> None:
    text = render_article_footer_text(_ARTICLE, _review())
    assert "1. Source A" in text
    assert "2. Source B" in text


def test_footer_renders_current_status_line() -> None:
    approved_text = render_article_footer_text(_ARTICLE, _review(status=TelegraphArticleReviewStatus.APPROVED))
    assert "✅ Статья одобрена" in approved_text
    revision_text = render_article_footer_text(_ARTICLE, _review(status=TelegraphArticleReviewStatus.NEEDS_REVISION))
    assert "✏️ Требуется доработка" in revision_text


def test_footer_within_safe_limit_for_a_normal_article() -> None:
    text = render_article_footer_text(_ARTICLE, _review())
    assert len(text.encode("utf-16-le")) // 2 <= SAFE_LIMIT


def test_footer_raises_rather_than_truncate_when_implausibly_long() -> None:
    huge_sources = {**_ARTICLE, "sources": [f"Source {i} " * 100 for i in range(200)]}
    try:
        render_article_footer_text(huge_sources, _review())
        raised = False
    except ArticleReviewTextTooLongError:
        raised = True
    assert raised  # fails loud rather than silently cutting the source list


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
