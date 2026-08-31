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


# ---------------------------------------------------------------------------
# DATA-CARD-1: hero-metric editorial hierarchy + never-orphan-a-unit forensic fix.
#
# Root cause (see the phase report): `_find_data_candidate()` returned on the FIRST research fact
# whose extracted (value, unit) pair intersected the copywriting text, with zero preference for a
# CHANGE/multiplier signal over a plain absolute/baseline figure, and its label-building step only
# ever stripped a bare magnitude word ("тыс.") out of the fact, never a trailing currency word
# ("рублей") that immediately followed it - leaving that currency word orphaned with no number.
# ---------------------------------------------------------------------------


def test_price_growth_story_prefers_multiplier_over_the_old_baseline_price():
    """The exact production defect (Samsung PM9A3 SSD price story): "25 тыс." (the OLD baseline
    price) must never win as the hero metric when the story itself is about the price MORE THAN
    DOUBLING and a grounded multiplier phrase exists - editorial hierarchy §1."""
    decision = _decide(
        title="Некоторые серверные SSD в России подорожали втрое с конца 2025 года",
        copywriting_output={
            "main_body": "Серверные накопители Samsung PM9A3 подорожали в 2-2,5 раза с конца 2025 года. "
            "Диск объёмом 960 GB можно было купить за 25 тыс. рублей, теперь он стоит 80 тыс. рублей.",
        },
        research_facts=[
            "SSD Samsung PM9A3 в 2025 году можно было купить за 25 тыс. рублей.",
            "Цены на серверные SSD Samsung PM9A3 выросли в 2-2,5 раза с конца 2025 года.",
            "Samsung PM9A3 960 GB подорожал с 25 тыс. до 80 тыс. рублей.",
        ],
    )
    assert decision.presentation_type == DATA
    candidate = decision.data_candidate
    assert candidate is not None
    assert candidate.value != "25"  # the old baseline price must never win
    assert "раз" in candidate.unit or "2" in candidate.value  # the multiplier won instead


def test_multiplier_value_and_unit_are_extracted_correctly():
    decision = _decide(
        title="SSD prices surge",
        copywriting_output={"main_body": "Server SSD prices climbed в 2-2,5 раза since late 2025."},
        research_facts=["Server SSD prices increased в 2-2,5 раза since late 2025, dealers confirmed."],
    )
    assert decision.presentation_type == DATA
    candidate = decision.data_candidate
    assert candidate is not None
    assert candidate.value == "2–2,5"
    assert candidate.unit == "раза"
    assert "climbed" not in candidate.label and "increased" in candidate.label  # from the FACT, not the copy


def test_percentage_change_is_extracted_and_outranks_a_grounded_absolute_value():
    decision = _decide(
        title="Company X reports strong quarter",
        copywriting_output={"main_body": "Company X profits grew by 35% to $500 million this quarter."},
        research_facts=[
            "Company X's quarterly revenue reached $500 million this quarter.",
            "Company X reported profits grew by 35% this quarter, beating estimates.",
        ],
    )
    assert decision.presentation_type == DATA
    candidate = decision.data_candidate
    assert candidate is not None
    assert candidate.value == "35"
    assert candidate.unit == "%"


def test_range_delta_from_x_to_y_is_extracted_with_units_attached():
    decision = _decide(
        title="SSD Samsung PM9A3 подорожал",
        copywriting_output={"main_body": "Цена SSD Samsung PM9A3 960 GB выросла с 25 тыс. до 80 тыс. рублей."},
        research_facts=[
            "Цена на SSD Samsung PM9A3 960 GB выросла с 25 тыс. до 80 тыс. рублей за последний год.",
        ],
    )
    assert decision.presentation_type == DATA
    candidate = decision.data_candidate
    assert candidate is not None
    assert candidate.value == "25 → 80"
    assert "тыс" in candidate.unit and "рубл" in candidate.unit  # unit stays attached (§5)
    assert "за" not in candidate.label.split() or candidate.label.rstrip(".").split()[-1] not in ("за", "до", "на")


def test_monetary_unit_stays_attached_to_an_absolute_value_never_orphaned():
    """The other half of the production defect: an absolute magnitude value's currency word must
    be captured as part of the unit, never left dangling in the label."""
    decision = _decide(
        title="ChatGPT Plus price increase",
        copywriting_output={"main_body": "ChatGPT Plus now costs 25 тыс. рублей per year in some markets."},
        research_facts=["ChatGPT Plus in some markets can be bought for 25 тыс. рублей per year."],
    )
    assert decision.presentation_type == DATA
    candidate = decision.data_candidate
    assert candidate is not None
    assert candidate.value == "25"
    assert "рубл" in candidate.unit  # currency retained on the value/unit side (§5)
    assert "за рубл" not in candidate.label.lower()  # never orphaned in the label (§4)
    assert "for рубл" not in candidate.label.lower()


def test_no_orphaned_preposition_labels_of_any_kind():
    """§4's own three named examples, directly."""
    for main_body, fact in (
        ("Price was 25 тыс. рублей.", "Item could be bought for 25 тыс. рублей."),
        ("Now $80 million.", "Company is now valued at $80 million, filings show."),
        ("Grew by 35 процентов.", "Revenue grew by 35 процентов this year, per the report."),
    ):
        decision = _decide(
            title="Numeric story", copywriting_output={"main_body": main_body}, research_facts=[fact],
        )
        assert decision.presentation_type == DATA
        candidate = decision.data_candidate
        assert candidate is not None
        label_lower = candidate.label.lower()
        for orphan in ("за рубл", "for рубл", "до доллар", "to $", "на процент", "at процент"):
            assert orphan not in label_lower, f"orphaned unit leaked into label: {candidate.label!r}"


def test_absolute_value_still_wins_when_it_is_itself_the_point_no_change_signal_present():
    """Editorial hierarchy §3: with no multiplier/range/percentage grounded anywhere, a plain
    absolute value remains a valid, legitimate hero metric - this must keep working exactly as
    before (backward-compatible with the pre-existing "500 million users" DATA case)."""
    decision = _decide(
        title="ChatGPT reaches new milestone",
        copywriting_output={"main_body": "ChatGPT reached 500 million weekly users, OpenAI said."},
        research_facts=["ChatGPT reached 500 million weekly users in August 2026."],
    )
    assert decision.presentation_type == DATA
    candidate = decision.data_candidate
    assert candidate is not None
    assert candidate.value == "500"
    assert candidate.unit == "million"


def test_unverified_multiplier_never_fabricates_a_data_card():
    """Grounding still applies to the new multiplier/range extractors - a multiplier proposed by
    copywriting but absent from every research fact must not be trusted (mirrors
    test_unverified_data_falls_back_to_news for the pre-existing magnitude path)."""
    decision = _decide(
        title="SSD prices surge",
        copywriting_output={"main_body": "Server SSD prices climbed в 3 раза since late 2025."},
        research_facts=["Server SSD prices increased noticeably since late 2025, dealers say."],
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
