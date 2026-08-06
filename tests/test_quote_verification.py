"""Phase 18.10 M5: pure, tier-1 unit tests for services.quote_verification.verify_quote() - the
anti-fabrication backstop. No DB, no LLM.
"""

from services.quote_verification import verify_quote


def test_verbatim_quote_verifies() -> None:
    source = 'The CEO said, "We are building a new platform for developers," during the keynote.'
    assert verify_quote("We are building a new platform for developers", source) is True


def test_paraphrased_quote_fails_verification() -> None:
    source = 'The CEO said the company was working on tools for developers.'
    assert verify_quote("We are building a new platform for developers", source) is False


def test_quote_not_present_at_all_fails() -> None:
    source = "Completely unrelated article text about something else entirely."
    assert verify_quote("We are building a new platform for developers", source) is False


def test_empty_quote_never_verifies() -> None:
    assert verify_quote("", "Any source text at all") is False
    assert verify_quote("   ", "Any source text at all") is False


def test_missing_source_never_verifies() -> None:
    assert verify_quote("Some quote", None) is False
    assert verify_quote("Some quote", "") is False


def test_case_and_punctuation_insensitive_match_still_verifies() -> None:
    """fuzzy_phrase_contains() normalizes casefold/quote-stripping/dashes - a quote extracted
    with different surrounding punctuation than the raw source should still verify."""
    source = 'She said: «We will ship this by the end of the year» in the interview.'
    assert verify_quote("we will ship this by the end of the year", source) is True


def test_conflicting_or_altered_quote_fails() -> None:
    source = 'The spokesperson said, "Sales grew by ten percent this quarter."'
    assert verify_quote("Sales grew by twenty percent this quarter", source) is False
