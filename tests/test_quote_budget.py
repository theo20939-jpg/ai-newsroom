"""Phase 19 M5: pure, tier-1 unit tests for services.quote_budget - no DB, no network, no LLM."""
from services.quote_budget import fits_within_budget, select_quote_or_omit


def test_fits_within_budget_true_when_under_limit() -> None:
    assert fits_within_budget(non_quote_blocks_length=100, quote_block_length=50, limit=200) is True


def test_fits_within_budget_true_at_exact_limit() -> None:
    assert fits_within_budget(non_quote_blocks_length=100, quote_block_length=100, limit=200) is True


def test_fits_within_budget_false_when_over_limit() -> None:
    assert fits_within_budget(non_quote_blocks_length=150, quote_block_length=100, limit=200) is False


def test_select_quote_or_omit_returns_none_when_no_quote() -> None:
    assert select_quote_or_omit(None, "Speaker", fits=True) == (None, None)


def test_select_quote_or_omit_returns_whole_quote_when_it_fits() -> None:
    assert select_quote_or_omit("A real quote", "Speaker", fits=True) == ("A real quote", "Speaker")


def test_select_quote_or_omit_omits_entirely_when_it_does_not_fit() -> None:
    assert select_quote_or_omit("A real quote", "Speaker", fits=False) == (None, None)


def test_select_quote_or_omit_never_returns_a_partial_string() -> None:
    """The core safety property: the result is always either the exact input quote text, or
    None - never a truncated substring of it."""
    original = "A verbatim quote that must never be cut into a shorter piece."
    text, _ = select_quote_or_omit(original, "Speaker", fits=False)
    assert text is None
    text, _ = select_quote_or_omit(original, "Speaker", fits=True)
    assert text == original
