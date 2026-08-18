"""Tests for services/presentation_director.py - NINJA PULSE Visual System v1's deterministic
AI-proposes/guard-validates presentation layer. Zero LLM calls in this module or its tests."""
from uuid import UUID

from services.editorial_treatment import MAJOR as _MAJOR, STANDARD as _STANDARD
from services.presentation_director import (
    BREAKING,
    CATEGORY_AI,
    CATEGORY_SECURITY,
    DATA,
    NEWS,
    QUOTE,
    build_editorial_code,
    classify_presentation_category,
    decide_presentation,
)


def _decide(**overrides):
    defaults = dict(
        title="Anthropic adds voice mode to Claude", content=None,
        copywriting_output={"main_body": "Anthropic released a new voice feature."},
        treatment=_STANDARD, scoring_score=80, research_facts=[], quote_text=None, quote_speaker=None,
    )
    defaults.update(overrides)
    return decide_presentation(**defaults)


# ---------------------------------------------------------------------------
# §37 presentation selection - ordinary/BREAKING/DATA/QUOTE/fail-closed cases
# ---------------------------------------------------------------------------


def test_ordinary_story_is_news():
    decision = _decide()
    assert decision.presentation_type == NEWS


def test_major_verified_announcement_is_breaking():
    decision = _decide(
        title="OpenAI unveils GPT-6, its most capable model yet",
        copywriting_output={"main_body": "OpenAI unveils GPT-6.", "viral_potential": "HIGH"},
        treatment=_MAJOR, scoring_score=95,
    )
    assert decision.presentation_type == BREAKING


def test_verified_strong_numeric_story_is_data():
    decision = _decide(
        title="ChatGPT reaches new milestone",
        copywriting_output={"main_body": "ChatGPT reached 500 million weekly users, OpenAI said."},
        research_facts=["ChatGPT reached 500 million weekly users in August 2026."],
    )
    assert decision.presentation_type == DATA
    assert decision.data_candidate is not None
    assert decision.data_candidate.value == "500"


def test_verified_strong_attributed_quote_is_quote():
    decision = _decide(
        title="OpenAI exec speaks out",
        copywriting_output={"main_body": "He shared his thoughts."},
        quote_text="We are building a new interface.", quote_speaker="Jane Doe",
    )
    assert decision.presentation_type == QUOTE
    assert decision.quote_candidate is not None
    assert decision.quote_candidate.text == "We are building a new interface."


def test_unverified_data_falls_back_to_news():
    """Presented number does not match any Research fact - must never be trusted."""
    decision = _decide(
        title="ChatGPT reaches new milestone",
        copywriting_output={"main_body": "ChatGPT reached 550 million weekly users, OpenAI said."},
        research_facts=["ChatGPT reached 500 million weekly users in August 2026."],
    )
    assert decision.presentation_type == NEWS


def test_data_with_no_research_facts_falls_back_to_news():
    decision = _decide(
        title="ChatGPT reaches new milestone",
        copywriting_output={"main_body": "ChatGPT reached 500 million weekly users, OpenAI said."},
        research_facts=[],
    )
    assert decision.presentation_type == NEWS


def test_unverified_quote_missing_speaker_falls_back_to_news():
    decision = _decide(quote_text="We are building a new interface.", quote_speaker=None)
    assert decision.presentation_type == NEWS


def test_unverified_quote_missing_text_falls_back_to_news():
    decision = _decide(quote_text=None, quote_speaker="Jane Doe")
    assert decision.presentation_type == NEWS


def test_ai_suggests_breaking_but_guard_insufficient_score_falls_back_to_news():
    decision = _decide(
        title="OpenAI unveils GPT-6",
        copywriting_output={"main_body": "OpenAI unveils GPT-6.", "viral_potential": "HIGH"},
        treatment=_MAJOR, scoring_score=60,  # below the BREAKING floor
    )
    assert decision.presentation_type != BREAKING
    assert decision.presentation_type == NEWS


def test_ai_suggests_breaking_but_guard_insufficient_treatment_falls_back_to_news():
    decision = _decide(
        title="OpenAI unveils GPT-6",
        copywriting_output={"main_body": "OpenAI unveils GPT-6.", "viral_potential": "HIGH"},
        treatment=_STANDARD, scoring_score=95,  # MAJOR treatment required, not met
    )
    assert decision.presentation_type != BREAKING


def test_ai_vetoes_breaking_via_low_viral_potential():
    decision = _decide(
        title="OpenAI unveils GPT-6",
        copywriting_output={"main_body": "OpenAI unveils GPT-6.", "viral_potential": "LOW"},
        treatment=_MAJOR, scoring_score=95,
    )
    assert decision.presentation_type != BREAKING


def test_generic_normal_story_never_accidentally_becomes_breaking_data_or_quote():
    decision = _decide(
        title="Startup releases new productivity app",
        copywriting_output={"main_body": "The app launches today with new features."},
        treatment=_STANDARD, scoring_score=75,
    )
    assert decision.presentation_type == NEWS


def test_breaking_enabled_false_disables_breaking_for_first_canary_but_not_other_types():
    """Pre-commit correction: `presentation_breaking_enabled=False` (settings.presentation_
    breaking_enabled) must suppress BREAKING specifically without touching DATA/QUOTE/NEWS
    evaluation for the same story shape."""
    decision = _decide(
        title="OpenAI unveils GPT-6",
        copywriting_output={"main_body": "OpenAI unveils GPT-6.", "viral_potential": "HIGH"},
        treatment=_MAJOR, scoring_score=95, breaking_enabled=False,
    )
    assert decision.presentation_type != BREAKING
    assert decision.presentation_type == NEWS  # falls through to the normal DATA/QUOTE/NEWS chain


def test_breaking_enabled_true_is_the_default_and_preserves_existing_behavior():
    decision = _decide(
        title="OpenAI unveils GPT-6",
        copywriting_output={"main_body": "OpenAI unveils GPT-6.", "viral_potential": "HIGH"},
        treatment=_MAJOR, scoring_score=95,
    )
    assert decision.presentation_type == BREAKING


def test_breaking_frequency_cap_forces_news_once_exhausted():
    decision = _decide(
        title="OpenAI unveils GPT-6",
        copywriting_output={"main_body": "OpenAI unveils GPT-6.", "viral_potential": "HIGH"},
        treatment=_MAJOR, scoring_score=95,
        breaking_count_this_cycle=1, breaking_max_per_cycle=1,
    )
    assert decision.presentation_type != BREAKING


# ---------------------------------------------------------------------------
# Category (display-only) behavior
# ---------------------------------------------------------------------------


def test_category_ai_for_ai_product_story():
    category = classify_presentation_category("OpenAI releases new reasoning model", None, [])
    assert category == CATEGORY_AI


def test_category_security_for_vulnerability_story():
    category = classify_presentation_category("Critical vulnerability found in popular router firmware", None, [])
    assert category == CATEGORY_SECURITY


# ---------------------------------------------------------------------------
# Editorial code (display-only, deterministic)
# ---------------------------------------------------------------------------


def test_editorial_code_is_deterministic_and_correctly_shaped():
    identifier = UUID("12345678-1234-5678-1234-567812345678")
    code_a = build_editorial_code(identifier)
    code_b = build_editorial_code(identifier)
    assert code_a == code_b
    assert code_a.startswith("NP-")
    assert len(code_a) == 7  # "NP-" + 4 digits
    assert code_a[3:].isdigit()


def test_editorial_code_differs_across_identifiers():
    a = build_editorial_code(UUID("11111111-1111-1111-1111-111111111111"))
    b = build_editorial_code(UUID("22222222-2222-2222-2222-222222222222"))
    assert a != b
