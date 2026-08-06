"""Phase 18.10 M6/M7: pure, tier-1 unit tests for services.content_quality_gates. No DB, no LLM.
"""
from services.content_quality_gates import (
    check_blockquote_well_formed,
    check_no_duplicate_source_headline,
    check_no_generic_filler,
    check_no_headline_body_repetition,
    check_no_unsupported_competitive_claim,
    check_quote_has_attribution,
    check_quote_traceable,
    check_update_not_repeating_root,
    check_why_it_matters_present,
    evaluate_content_quality_gates,
)


# --- headline/body repetition ------------------------------------------------------------------


def test_body_that_just_repeats_the_title_fails() -> None:
    title = "Company X launches new product Y today"
    body = "Company X launches new product Y today. More details follow."
    assert check_no_headline_body_repetition(title, body) is False


def test_body_that_adds_new_information_passes() -> None:
    title = "Company X launches new product Y"
    body = "The device ships next month starting at $499, targeting enterprise customers."
    assert check_no_headline_body_repetition(title, body) is True


# --- duplicate source headline -------------------------------------------------------------------


def test_untranslated_source_headline_leaking_into_body_fails() -> None:
    source_title = "Company Announces Revolutionary New AI Chip"
    body = "Компания представила новый чип. Company Announces Revolutionary New AI Chip"
    assert check_no_duplicate_source_headline(body, source_title) is False


def test_translated_body_without_source_headline_passes() -> None:
    source_title = "Company Announces Revolutionary New AI Chip"
    body = "Компания представила новый чип, ориентированный на дата-центры."
    assert check_no_duplicate_source_headline(body, source_title) is True


def test_no_source_title_available_passes_by_default() -> None:
    assert check_no_duplicate_source_headline("Any body text", None) is True


# --- generic filler / unsupported competitive claims --------------------------------------------


def test_generic_filler_phrase_fails() -> None:
    assert check_no_generic_filler("This is a normal sentence. This is an important development.") is False


def test_clean_text_without_filler_passes() -> None:
    assert check_no_generic_filler("The company reported a 12% increase in quarterly revenue.") is True


def test_unsupported_superlative_fails() -> None:
    assert check_no_unsupported_competitive_claim("This is the best in the world, unmatched by rivals.") is False


def test_specific_factual_claim_passes() -> None:
    assert check_no_unsupported_competitive_claim("The chip runs 30% faster than its predecessor.") is True


# --- why_it_matters -------------------------------------------------------------------------------


def test_empty_why_it_matters_fails() -> None:
    assert check_why_it_matters_present(None) is False
    assert check_why_it_matters_present("") is False
    assert check_why_it_matters_present("Too short") is False  # below the minimum length


def test_why_it_matters_restating_what_happened_fails() -> None:
    what_happened = "The company released a new smartphone with a faster processor today."
    why_it_matters = "The company released a new smartphone with a faster processor today."
    assert check_why_it_matters_present(why_it_matters, what_happened) is False


def test_genuine_editorial_interpretation_passes() -> None:
    what_happened = "The company released a new smartphone with a faster processor today."
    why_it_matters = "This pressures rivals to accelerate their own hardware roadmaps this quarter."
    assert check_why_it_matters_present(why_it_matters, what_happened) is True


# --- quote traceability / attribution --------------------------------------------------------------


def test_no_quote_at_all_passes_traceability_and_attribution() -> None:
    assert check_quote_traceable(None, "any source") is True
    assert check_quote_has_attribution(None, None) is True


def test_verbatim_quote_is_traceable() -> None:
    source = 'The CEO said, "We will double our engineering team next year."'
    assert check_quote_traceable("We will double our engineering team next year", source) is True


def test_fabricated_quote_is_untraceable() -> None:
    source = "The company announced a new product line."
    assert check_quote_traceable("We will double our engineering team next year", source) is False


def test_quote_with_generic_speaker_fails_attribution() -> None:
    assert check_quote_has_attribution("Some quote text", "someone") is False
    assert check_quote_has_attribution("Some quote text", "") is False
    assert check_quote_has_attribution("Some quote text", None) is False


def test_quote_with_real_speaker_passes_attribution() -> None:
    assert check_quote_has_attribution("Some quote text", "Jane Smith, CEO") is True
    assert check_quote_has_attribution("Some quote text", "Company X") is True


# --- blockquote well-formedness -------------------------------------------------------------------


def test_balanced_blockquote_passes() -> None:
    assert check_blockquote_well_formed("<b>Title</b>\n<blockquote>Quote text</blockquote>") is True


def test_unbalanced_blockquote_fails() -> None:
    assert check_blockquote_well_formed("<blockquote>Quote text without closing tag") is False


def test_no_blockquote_at_all_passes() -> None:
    assert check_blockquote_well_formed("<b>Title</b>\nJust plain text.") is True


# --- update-repeats-root ---------------------------------------------------------------------------


def test_non_update_always_passes_regardless_of_root_similarity() -> None:
    assert check_update_not_repeating_root("Any body", is_update=False, root_body="Any body") is True


def test_update_that_is_mostly_the_same_as_root_fails() -> None:
    root = "Company X launched product Y today with these specifications and pricing details included here."
    update = "Company X launched product Y today with these specifications and pricing details included here."
    assert check_update_not_repeating_root(update, is_update=True, root_body=root) is False


def test_update_containing_a_real_delta_passes() -> None:
    root = "Company X launched product Y today."
    update = "New benchmark results show product Y outperforms its predecessor by 40% in single-core tests."
    assert check_update_not_repeating_root(update, is_update=True, root_body=root) is True


# --- aggregator -------------------------------------------------------------------------------------


def test_aggregator_reports_all_gates_passing_for_clean_content() -> None:
    report = evaluate_content_quality_gates(
        title="Company X launches product Y",
        body="The device ships next month with enterprise-focused features.",
        why_it_matters="This intensifies competition in the enterprise hardware segment this year.",
        what_happened="Company X launched product Y today.",
    )
    assert report.passed is True
    assert report.failed_gates == []


def test_aggregator_reports_specific_failed_gates() -> None:
    report = evaluate_content_quality_gates(
        title="Company X launches product Y",
        body="Company X launches product Y. This is an important development.",
        why_it_matters=None,
    )
    assert report.passed is False
    assert "why_it_matters_present" in report.failed_gates
    assert "no_generic_filler" in report.failed_gates
