"""Tests for services.quote_lookup (Phase 19 M5) - the sole lookup/display-resolution seam for a
persisted, verified ContentDraftQuote before Telegram delivery.

Pure unit tests for `resolve_display_text()` only - `get_quote_for_draft()` is a one-line `session.
get()` already exercised end-to-end by tests/test_content_draft_quote_integration.py.
"""
from database.models.content_draft_quote import ContentDraftQuote
from services.quote_lookup import resolve_display_text


def _quote(*, quote_text: str, translated_text: str | None, speaker: str = "Jane Doe") -> ContentDraftQuote:
    return ContentDraftQuote(
        content_draft_id=None, quote_text=quote_text, translated_text=translated_text, speaker=speaker,
    )


def test_translated_text_preferred_when_present() -> None:
    """Phase 23.1P offline acceptance CASE 13 (translated English quote): a verbatim English
    original with a Russian translation must display the Russian translation on-channel, never
    the untranslated English - matches prompts/copywriting/v8.5.yaml's own rule that `speaker` is
    always target-language while the verbatim `text` (quote_text here) stays source-language."""
    quote = _quote(
        quote_text="This is the exact wrong scenario we should be trying to prevent.",
        translated_text="Это именно тот неверный сценарий, которого нам следует избегать.",
    )
    text, speaker = resolve_display_text(quote)
    assert text == "Это именно тот неверный сценарий, которого нам следует избегать."
    assert speaker == "Jane Doe"


def test_falls_back_to_verbatim_original_when_no_translation() -> None:
    """A source already in the target language (or no translation was produced) displays the
    verbatim original unchanged - never blank, never fabricated."""
    quote = _quote(
        quote_text="Мы всегда открыты для диалога с сообществом.", translated_text=None,
    )
    text, speaker = resolve_display_text(quote)
    assert text == "Мы всегда открыты для диалога с сообществом."


def test_never_mutates_the_verbatim_original_field() -> None:
    """quote_text itself (the field quote_verification.py's fail-closed check ran against) must
    never be altered by display resolution - only the returned display tuple changes."""
    original = "The exact verbatim string that was verified."
    quote = _quote(quote_text=original, translated_text="Переведённая версия.")
    resolve_display_text(quote)
    assert quote.quote_text == original
