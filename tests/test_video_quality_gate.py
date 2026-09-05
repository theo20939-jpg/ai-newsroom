"""MEDIA-PROD-1: services.video_quality_gate - pure, deterministic, no LLM/network/database.
"""
from __future__ import annotations

from services.video_quality_gate import VideoContentClassification, assess_video_text_signals


def test_clean_title_and_content_are_approved() -> None:
    result = assess_video_text_signals(
        title="Company X unveils new chip architecture",
        content="The announcement covers performance benchmarks and release timing.",
    )
    assert result.classification == VideoContentClassification.APPROVED
    assert result.matched_keywords == ()


def test_english_advertisement_keywords_are_detected() -> None:
    result = assess_video_text_signals(
        title="Limited time sale - buy now and save",
        content="This promo is sponsored by our partner brand.",
    )
    assert result.classification == VideoContentClassification.ADVERTISEMENT
    assert "sale" in result.matched_keywords
    assert "buy now" in result.matched_keywords
    assert "promo" in result.matched_keywords
    assert "sponsored" in result.matched_keywords


def test_russian_advertisement_keywords_are_detected() -> None:
    result = assess_video_text_signals(
        title="Специальная акция: скидка 50% на новый гаджет",
        content="Это реклама. Есть промокод.",
    )
    assert result.classification == VideoContentClassification.ADVERTISEMENT
    assert "акция" in result.matched_keywords
    assert "скидка" in result.matched_keywords
    assert "реклама" in result.matched_keywords
    assert "промокод" in result.matched_keywords


def test_buy_now_matches_as_one_phrase_not_duplicated_by_bare_buy() -> None:
    """"buy now" and bare "buy" are both real lexicon entries - the longest-phrase-first
    alternation must not produce a redundant double match for the same text span."""
    result = assess_video_text_signals(title="Buy now while supplies last", content=None)
    assert "buy now" in result.matched_keywords


def test_keyword_substring_inside_an_unrelated_word_is_not_a_false_positive() -> None:
    """Word-boundary matching: "sale" must not fire on "resale" as if it were a standalone ad
    keyword mid-word (the actual word boundary here makes this a real edge case worth locking in)."""
    result = assess_video_text_signals(title="Analysts debate the wholesale resale market", content=None)
    assert result.classification == VideoContentClassification.APPROVED


def test_no_content_field_does_not_crash() -> None:
    result = assess_video_text_signals(title="Ordinary headline with no ad language", content=None)
    assert result.classification == VideoContentClassification.APPROVED


def test_low_value_is_never_produced_by_this_text_only_module() -> None:
    """Documents the deliberate scope limit (module docstring) - LOW_VALUE is reserved for a
    future visual/frame-analysis signal this module does not have."""
    cases = [
        ("Ordinary news headline", "Ordinary body text."),
        ("Buy now - huge sale", "Sponsored content."),
        ("Скидка на новый телефон", "Успейте купить."),
    ]
    for title, content in cases:
        result = assess_video_text_signals(title=title, content=content)
        assert result.classification != VideoContentClassification.LOW_VALUE
