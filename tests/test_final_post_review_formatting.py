"""Phase I.2: bot.final_post_review_formatting tests. Pure - no aiogram, no database access."""
from __future__ import annotations

import uuid

from bot.final_post_review_formatting import (
    CAPTION_SAFE_LIMIT,
    render_final_post_preview_caption,
    render_final_post_review_control_text,
    telegram_utf16_length,
)
from database.models.final_post_review import FinalPostReview, FinalPostReviewStatus


def _review(status: FinalPostReviewStatus = FinalPostReviewStatus.PENDING) -> FinalPostReview:
    return FinalPostReview(id=uuid.uuid4(), content_draft_id=uuid.uuid4(), status=status)


def test_utf16_length_counts_code_units_not_code_points():
    # A single astral-plane emoji is one Python code point but two UTF-16 code units.
    assert telegram_utf16_length("\U0001F4F0") == 2
    assert len("\U0001F4F0") == 1


def test_preview_caption_contains_title_and_body():
    caption = render_final_post_preview_caption("My Final Title", "My final body text.")
    assert "My Final Title" in caption
    assert "My final body text." in caption


def test_preview_caption_is_html_escaped():
    caption = render_final_post_preview_caption("<script>alert(1)</script>", "A & B")
    assert "<script>" not in caption
    assert "&lt;script&gt;" in caption
    assert "A &amp; B" in caption


def test_preview_caption_never_contains_recap_internal_labels():
    caption = render_final_post_preview_caption("Title", "Body")
    for forbidden in ("Ключевые пункты", "Неопределённость", "Сводка", "recap", "bundle", "evidence"):
        assert forbidden not in caption


def test_preview_caption_never_contains_approve_revision_text():
    caption = render_final_post_preview_caption("Title", "Body")
    for forbidden in ("К публикации", "На доработку", "✅", "✏️"):
        assert forbidden not in caption


def test_preview_caption_reuses_the_real_v81_news_card_renderer():
    """Proves this is the SAME renderer NEWS delivery uses, not a second competing formatter -
    the exact bold-title-then-body shape render_v81_news_card_html() produces."""
    caption = render_final_post_preview_caption("My Title", "My body.")
    assert caption == "<b>My Title</b>\n\nMy body."


def test_control_text_pending_is_short_and_internal():
    text = render_final_post_review_control_text(_review())
    assert "готов к проверке" in text
    assert "К публикации" not in text  # that's the button text, not the message body
    assert "✅" not in text


def test_control_text_pending_may_include_minimal_audit_metadata():
    text = render_final_post_review_control_text(_review(), authoring_prompt_version="2", fact_safety_status="pass")
    assert "v2" in text
    assert "pass" in text


def test_control_text_pending_omits_metadata_when_not_supplied():
    text = render_final_post_review_control_text(_review())
    assert text == "Финальный пост готов к проверке."
    assert "промпт" not in text


def test_control_text_approved_for_publication_is_the_exact_specified_line():
    text = render_final_post_review_control_text(_review(FinalPostReviewStatus.APPROVED_FOR_PUBLICATION))
    assert text == "✅ Пост одобрен к публикации"


def test_control_text_needs_revision_is_the_exact_specified_line():
    text = render_final_post_review_control_text(_review(FinalPostReviewStatus.NEEDS_REVISION))
    assert text == "✏️ Пост требует доработки"


def test_control_text_terminal_states_never_include_audit_metadata():
    text = render_final_post_review_control_text(
        _review(FinalPostReviewStatus.APPROVED_FOR_PUBLICATION),
        authoring_prompt_version="2", fact_safety_status="pass",
    )
    assert text == "✅ Пост одобрен к публикации"  # metadata never leaks into the terminal text


def test_no_silent_truncation_caption_can_exceed_the_safe_limit():
    """This module never truncates - a very long body simply produces a very long (possibly
    over-limit) caption; the caller (notifier) is responsible for measuring and refusing to send,
    never this function."""
    long_body = "x" * (CAPTION_SAFE_LIMIT + 500)
    caption = render_final_post_preview_caption("Title", long_body)
    assert telegram_utf16_length(caption) > CAPTION_SAFE_LIMIT
    assert long_body in caption  # never cut
