"""Tests for bot.image_preview_formatting's Phase 16 M6 pure renderer (docs/
phase16_m6_telegram_editorial_preview_report.md §5). No aiogram/Bot type anywhere in this file -
mirrors tests/test_editorial_card_formatting.py's own established "pure function, zero Telegram
mocking" convention.
"""
import uuid

import pytest

from bot.image_preview_formatting import (
    CAPTION_SAFE_LIMIT,
    _telegram_utf16_length,
    render_decision_confirmation_text,
    render_expired_candidate_alert_text,
    render_image_preview_caption,
    render_no_candidates_text,
    render_unavailable_candidate_alert_text,
)
from services.image_persistence import EditorialImageCandidate


def _candidate(**overrides) -> EditorialImageCandidate:
    base = dict(
        id=uuid.uuid4(), candidate_id="c1", rank=1, relevance_score=91, quality_score=87,
        discovery_method="open_graph_image", source_relationship="same_article",
        relevance_reason="strong metadata overlap", width=1200, height=630,
        observed_mime="image/jpeg", image_format="JPEG", storage_status="stored",
        storage_key="images/ab/abc.jpg", telegram_file_id=None, editor_decision=None,
        source_url="https://vc.ru/some-article", article_url="https://vc.ru/some-article",
        warnings=None, is_expired=False,
    )
    base.update(overrides)
    return EditorialImageCandidate(**base)


def test_caption_contains_core_metadata() -> None:
    candidate = _candidate()
    caption = render_image_preview_caption(candidate, draft_title="My Draft", index=0, total=3)

    assert "My Draft" in caption
    assert "Image 1/3" in caption
    assert "vc.ru" in caption
    assert "Quality: 87/100" in caption
    assert "Relevance: 91/100" in caption
    assert "1200" in caption and "630" in caption
    assert "strong metadata overlap" in caption


def test_caption_escapes_html_in_title_and_reason() -> None:
    candidate = _candidate(relevance_reason="<script>alert(1)</script>")
    caption = render_image_preview_caption(candidate, draft_title="<b>evil</b>", index=0, total=1)

    assert "<script>" not in caption
    assert "&lt;script&gt;" in caption
    assert "<b>evil</b>" not in caption
    assert "&lt;b&gt;evil&lt;/b&gt;" in caption


def test_caption_flags_expired_candidate() -> None:
    candidate = _candidate(is_expired=True)
    caption = render_image_preview_caption(candidate, draft_title="t", index=0, total=1)
    assert "expired" in caption.lower()


def test_caption_flags_metadata_only_when_not_stored() -> None:
    candidate = _candidate(storage_status="not_requested", storage_key=None)
    caption = render_image_preview_caption(candidate, draft_title="t", index=0, total=1)
    assert "metadata only" in caption.lower()


def test_caption_never_contains_a_filesystem_path_or_storage_root() -> None:
    """docs §7 - the Telegram layer must never expose the internal storage root or an absolute
    path. storage_key itself (an internal reference) must never leak into visible text either."""
    candidate = _candidate(storage_key="images/ab/abcdef1234.jpg")
    caption = render_image_preview_caption(candidate, draft_title="t", index=0, total=1)

    assert "images/ab/abcdef1234.jpg" not in caption
    assert "/data/image_storage" not in caption
    assert "C:\\" not in caption and "/home/" not in caption


def test_caption_stays_within_telegram_caption_limit_even_with_a_long_reason() -> None:
    candidate = _candidate(relevance_reason="x" * 5000)
    caption = render_image_preview_caption(candidate, draft_title="t", index=0, total=1)
    assert _telegram_utf16_length(caption) <= CAPTION_SAFE_LIMIT


def test_caption_handles_missing_optional_fields_gracefully() -> None:
    candidate = _candidate(
        quality_score=None, relevance_score=None, width=None, height=None, relevance_reason=None,
    )
    caption = render_image_preview_caption(candidate, draft_title=None, index=4, total=5)
    assert "Image 5/5" in caption
    assert "(untitled draft)" in caption
    assert "no relevance evidence recorded" in caption


def test_no_candidates_text_mentions_draft_title() -> None:
    text = render_no_candidates_text("My Draft")
    assert "My Draft" in text
    assert "No image candidates" in text


def test_no_candidates_text_handles_missing_title() -> None:
    text = render_no_candidates_text(None)
    assert "(untitled draft)" in text


def test_decision_confirmation_text_for_selected() -> None:
    candidate = _candidate()
    text = render_decision_confirmation_text(selected=True, candidate=candidate)
    assert "selected" in text.lower()
    assert "vc.ru" in text


def test_decision_confirmation_text_for_no_image() -> None:
    text = render_decision_confirmation_text(selected=False, candidate=None)
    assert "no image" in text.lower()


def test_alert_texts_are_distinct_and_non_empty() -> None:
    expired = render_expired_candidate_alert_text()
    unavailable = render_unavailable_candidate_alert_text()
    assert expired and unavailable
    assert expired != unavailable


@pytest.mark.parametrize("index,total", [(0, 1), (2, 5), (4, 5)])
def test_index_display_is_one_based(index: int, total: int) -> None:
    candidate = _candidate()
    caption = render_image_preview_caption(candidate, draft_title="t", index=index, total=total)
    assert f"Image {index + 1}/{total}" in caption
