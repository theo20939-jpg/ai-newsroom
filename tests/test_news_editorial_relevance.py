"""Tests for services/news_editorial_relevance.py - the deterministic, LLM-free editorial-
relevance tiering module (topic-skew fix). Every case below is one of the real headline-style
examples specified for this checkpoint."""
import pytest

from services.news_editorial_relevance import (
    ADJACENT,
    CORE,
    OUT_OF_SCOPE,
    PERIPHERAL,
    classify_editorial_relevance,
)

# ---------------------------------------------------------------------------
# CORE - product/tech action is the subject
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "OpenAI releases GPT-5.7 with new reasoning mode",
        "Anthropic adds voice mode to Claude",
        "Samsung unveils Galaxy S27",
        "Nvidia launches RTX 6090",
        "Apple releases iOS security update fixing actively exploited bug",
    ],
)
def test_core_product_headlines(title: str) -> None:
    decision = classify_editorial_relevance(title)
    assert decision.tier == CORE
    assert decision.rank_adjustment > 0
    assert decision.major_impact_override is False


# ---------------------------------------------------------------------------
# PERIPHERAL - funding / valuation / market / employment
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "Nvidia invests $1.5B in data center developer",
        "Wispr raises $280M at $2B valuation",
        "Norway wealth fund warns of AI stock market bubble",
        "AI wealth fuels San Francisco housing frenzy",
        "Engineering graduates face hiring freeze as AI reshapes jobs",
    ],
)
def test_peripheral_finance_headlines(title: str) -> None:
    decision = classify_editorial_relevance(title)
    assert decision.tier == PERIPHERAL
    assert decision.rank_adjustment < 0
    assert decision.major_impact_override is False


# ---------------------------------------------------------------------------
# Legal / regulatory - generic vs landmark
# ---------------------------------------------------------------------------


def test_generic_minor_ai_regulation_is_peripheral_without_override() -> None:
    decision = classify_editorial_relevance("EU proposes new AI regulation for chatbot transparency")
    assert decision.tier == PERIPHERAL
    assert decision.major_impact_override is False


def test_landmark_antitrust_ruling_gets_major_impact_override() -> None:
    decision = classify_editorial_relevance(
        "Meta faces landmark antitrust ruling that could force Instagram divestiture"
    )
    assert decision.tier == PERIPHERAL
    assert decision.major_impact_override is True
    assert decision.rank_adjustment > 0


# ---------------------------------------------------------------------------
# OUT_OF_SCOPE - unambiguous non-tech noise
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "Universal Health Coverage Could Save $1 Trillion, Report Finds",
        "Actress Hayden Panettiere has died at 36",
        "Monzo chair Gary Hoffman is leaving amid a shareholder dispute",
    ],
)
def test_out_of_scope_headlines(title: str) -> None:
    decision = classify_editorial_relevance(title)
    assert decision.tier == OUT_OF_SCOPE
    assert decision.rank_adjustment < 0


# ---------------------------------------------------------------------------
# AI-as-subject vs AI-as-context
# ---------------------------------------------------------------------------


def test_ai_product_launch_is_core() -> None:
    decision = classify_editorial_relevance("OpenAI launches new image model")
    assert decision.tier == CORE


def test_ai_driven_market_fear_is_peripheral_not_core() -> None:
    decision = classify_editorial_relevance("Stock market may crash because of AI boom")
    assert decision.tier == PERIPHERAL


def test_ai_funding_headline_is_peripheral_not_core() -> None:
    decision = classify_editorial_relevance("Startup raises $500M for AI models")
    assert decision.tier == PERIPHERAL


def test_ai_feature_addition_is_core() -> None:
    decision = classify_editorial_relevance("Google adds Gemini live translation to Android")
    assert decision.tier == CORE


# ---------------------------------------------------------------------------
# Ambiguous legal/regulatory: real potential impact, must not be auto-excluded
# ---------------------------------------------------------------------------


def test_apple_forced_regulatory_change_is_not_out_of_scope() -> None:
    decision = classify_editorial_relevance("Apple forced to change App Tracking Transparency rules in EU")
    assert decision.tier != OUT_OF_SCOPE
    assert decision.tier == PERIPHERAL
    assert decision.major_impact_override is True


# ---------------------------------------------------------------------------
# Subject-aware earliest-position heuristic - the worked example from the task brief
# ---------------------------------------------------------------------------


def test_product_launch_mentioned_after_funding_is_still_core() -> None:
    decision = classify_editorial_relevance("OpenAI launches GPT-X after raising $10B")
    assert decision.tier == CORE


def test_funding_as_the_actual_subject_is_peripheral() -> None:
    decision = classify_editorial_relevance("OpenAI raises $10B to fund GPT-X development")
    assert decision.tier == PERIPHERAL


# ---------------------------------------------------------------------------
# Neutral default / content fallback / determinism
# ---------------------------------------------------------------------------


def test_no_keyword_evidence_defaults_to_neutral_adjacent() -> None:
    decision = classify_editorial_relevance("A quiet Tuesday in the newsroom")
    assert decision.tier == ADJACENT
    assert decision.rank_adjustment == 0


def test_content_is_consulted_when_title_has_no_signal() -> None:
    decision = classify_editorial_relevance(
        "Company shares update", content="The startup raises $50M in a new funding round."
    )
    assert decision.tier == PERIPHERAL


def test_yo_and_ye_cyrillic_spelling_variants_match_identically() -> None:
    """Real backtest finding: the same story appeared with both "привлёк" (ё) and "привлек"
    (е) spellings across two sources - both must classify the same way."""
    yo_spelling = classify_editorial_relevance("Databricks привлёк $5 млрд при оценке в $190 млрд")
    ye_spelling = classify_editorial_relevance("Databricks привлек $5 млрд при оценке в $190 млрд")
    assert yo_spelling.tier == PERIPHERAL
    assert yo_spelling == ye_spelling


def test_classification_is_deterministic() -> None:
    title = "Nvidia launches RTX 6090"
    first = classify_editorial_relevance(title)
    second = classify_editorial_relevance(title)
    assert first == second


# ---------------------------------------------------------------------------
# Rank-adjustment calibration - the worked examples from the task brief
# ---------------------------------------------------------------------------


def test_core_82_beats_generic_peripheral_90() -> None:
    core = classify_editorial_relevance("Nvidia launches RTX 6090")
    peripheral = classify_editorial_relevance("Wispr raises $280M at $2B valuation")
    assert 82 + core.rank_adjustment > 90 + peripheral.rank_adjustment


def test_landmark_override_can_beat_a_lower_core_score() -> None:
    core = classify_editorial_relevance("Anthropic adds voice mode to Claude")
    override = classify_editorial_relevance(
        "Meta faces landmark antitrust ruling that could force Instagram divestiture"
    )
    assert 95 + override.rank_adjustment >= 72 + core.rank_adjustment


# ---------------------------------------------------------------------------
# Corrective checkpoint: ACTION VERB != PRODUCT SUBJECT - a generic launch/release/announce
# verb must not grant CORE without a paired product/tech object nearby.
# ---------------------------------------------------------------------------


def test_generic_ai_policy_launch_is_not_core() -> None:
    decision = classify_editorial_relevance("Israel Launches National AI Action Plan")
    assert decision.tier != CORE


def test_government_launches_investment_fund_is_peripheral() -> None:
    decision = classify_editorial_relevance("Government launches AI investment fund")
    assert decision.tier == PERIPHERAL


def test_eu_launches_regulatory_framework_is_peripheral() -> None:
    decision = classify_editorial_relevance("EU launches AI regulatory framework")
    assert decision.tier == PERIPHERAL


def test_bank_launches_investment_vehicle_is_peripheral() -> None:
    decision = classify_editorial_relevance("Bank launches AI investment vehicle")
    assert decision.tier == PERIPHERAL


def test_company_launches_funding_round_is_peripheral() -> None:
    decision = classify_editorial_relevance("Company launches $500M funding round")
    assert decision.tier == PERIPHERAL


@pytest.mark.parametrize(
    "title",
    [
        "Google launches Gemini 4",
        "OpenAI releases new reasoning model",
        "Apple launches iPhone 18",
        "Anthropic introduces Claude voice mode",
        "Nvidia releases RTX 6090",
        "Microsoft launches new Copilot feature",
        "OpenAI releases SDK update",
    ],
)
def test_launch_release_with_product_object_stays_core(title: str) -> None:
    decision = classify_editorial_relevance(title)
    assert decision.tier == CORE


def test_ru_government_launches_ai_strategy_is_not_core() -> None:
    decision = classify_editorial_relevance("Правительство запустило национальную стратегию по ИИ")
    assert decision.tier != CORE


def test_ru_bank_launches_investment_fund_is_peripheral() -> None:
    decision = classify_editorial_relevance("Банк запустил инвестиционный фонд для ИИ")
    assert decision.tier == PERIPHERAL


@pytest.mark.parametrize(
    "title",
    [
        "OpenAI выпустила новую модель",
        "Apple представила новый iPhone",
        "Google добавила новую функцию Gemini",
    ],
)
def test_ru_product_launch_with_object_stays_core(title: str) -> None:
    decision = classify_editorial_relevance(title)
    assert decision.tier == CORE
