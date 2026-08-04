"""Phase 17 M7.2 - quantity claim classification tests (docs/
phase17_m7_2_quantity_classification_report.md, plan: docs/
phase17_m7_2_quantity_classification_plan.md).

Root cause fixed: `services/fact_safety.py` used to type EVERY number+magnitude match "money",
whether or not a currency was actually present - a bare quantity ("320.7 million tokens") could
never resolve (no currency to look up) and was therefore unconditionally `unsupported`/HIGH
regardless of whether it matched evidence (M7 discovery class #1). This file pins the fix: three
claim buckets (money / metric_quantity / generic_quantity), decided by what immediately follows
the number - never by NLP, only by narrow, explicit, hand-curated word lists, matching every other
rule in this module.

Exactly the required test matrix from the M7.2 authorization message, plus the false-negative
regressions it also required.
"""
import pytest

from services.candidate_fact_safety import evaluate_candidate_fact_safety
from services.fact_safety import (
    FactEvidence,
    _metric_matches,
    _money_matches,
    _normalize_ad_hoc_currency,
    _normalize_metric_quantity,
    _resolve_money,
    evaluate_fact_safety,
    extract_claims,
)

# ---------------------------------------------------------------------------
# Currency: PASS (tests 1-6)
# ---------------------------------------------------------------------------


def test_currency_dollar_symbol_million() -> None:
    claims = extract_claims("The company raised $10 million.")
    assert claims["money"] == ["$10 million."]
    assert claims["metric_quantity"] == []
    assert claims["generic_quantity"] == []


def test_currency_russian_full_word_million() -> None:
    claims = extract_claims("Компания привлекла 10 миллионов долларов.")
    assert claims["money"] == ["10 миллионов долларов"]
    assert _resolve_money("10 миллионов долларов") == ("USD", 10_000_000.0)


def test_currency_unrecognized_term_korean_won() -> None:
    """The real, disclosed production example (docs/phase17_m7_2_quantity_classification_plan.md
    §"Failure examples" #3) - "Won" is not in `_CURRENCY_SYMBOLS`, but is still classified and
    resolved as a currency-like term, per M7.2's own approved decision ("do not rely only on
    hardcoded currency names")."""
    claims = extract_claims("The mobile division lost 0.7 trillion Korean Won.")
    assert claims["money"] == ["0.7 trillion Korean Won"]
    resolved = _resolve_money("0.7 trillion Korean Won")
    assert resolved is not None
    currency, amount = resolved
    assert amount == 700_000_000_000.0
    assert currency == "korean won"  # ad hoc code - the literal term, never a guessed real one


def test_currency_ad_hoc_terms_match_each_other_by_same_literal_word() -> None:
    """Two claims naming the SAME unrecognized currency term resolve as equal - this is what lets
    a genuinely-sourced foreign-currency figure (not in `_CURRENCY_SYMBOLS`) still match evidence,
    without inventing a new hardcoded currency-list entry per country."""
    draft = _normalize_ad_hoc_currency("0,7 трлн вон")
    evidence = _normalize_ad_hoc_currency("0,7 трлн вон")
    assert draft is not None and evidence is not None
    assert _money_matches(draft, evidence)


def test_currency_ad_hoc_terms_do_not_match_different_words_or_amounts() -> None:
    """False-negative safety: an unrecognized-currency claim must still require the SAME term and
    SAME amount - never a loose match just because both are "some unknown currency"."""
    a = _normalize_ad_hoc_currency("0,7 трлн вон")
    b = _normalize_ad_hoc_currency("0,7 трлн юаней")  # different term, same amount
    c = _normalize_ad_hoc_currency("0,9 трлн вон")  # same term, different amount
    assert not _money_matches(a, b)
    assert not _money_matches(a, c)


def test_currency_known_currency_takes_priority_over_ad_hoc() -> None:
    """A recognized currency word must resolve via the real currency code (USD), never fall
    through to the ad hoc path - `_resolve_money()`'s own explicit ordering."""
    assert _resolve_money("1.7 billion dollars") == ("USD", 1_700_000_000.0)


# ---------------------------------------------------------------------------
# Metric: PASS (tests 7-12)
# ---------------------------------------------------------------------------


def test_metric_tokens_russian() -> None:
    claims = extract_claims("Модель использовала 320,7 млн токенов.")
    assert claims["metric_quantity"] == ["320,7 млн токенов"]
    assert claims["money"] == []
    assert _normalize_metric_quantity("320,7 млн токенов") == ("tokens", 320_700_000.0)


def test_metric_parameters_russian_trillion_scale() -> None:
    """The real Kimi K3 production case (`ac1f1ff5`) - direct fix target."""
    claims = extract_claims("Модель содержит 2,8 трлн параметров.")
    assert claims["metric_quantity"] == ["2,8 трлн параметров"]
    assert claims["money"] == []
    assert _normalize_metric_quantity("2,8 трлн параметров") == ("parameters", 2_800_000_000_000.0)


def test_metric_bare_number_calls_no_magnitude_word() -> None:
    """"1129 вызовов инструментов" - a bare number (no million/billion) followed directly by a
    recognized metric unit. Previously not extracted at all (no magnitude word, no currency)."""
    claims = extract_claims("Агент сделал 1129 вызовов инструментов.")
    assert claims["metric_quantity"] == ["1129 вызовов"]
    assert _normalize_metric_quantity("1129 вызовов") == ("calls", 1129.0)


def test_metric_english_users_and_requests() -> None:
    assert extract_claims("The API served 150 million requests.")["metric_quantity"] == [
        "150 million requests"
    ]
    assert extract_claims("The platform has 5 million users.")["metric_quantity"] == [
        "5 million users"
    ]


def test_metric_inflected_forms_canonicalize_to_the_same_unit() -> None:
    for text, expected_unit in [
        ("токен", "tokens"), ("токена", "tokens"), ("токенов", "tokens"),
        ("параметр", "parameters"), ("параметра", "parameters"), ("параметров", "parameters"),
        ("пользователь", "users"), ("пользователя", "users"), ("пользователей", "users"),
        ("запрос", "requests"), ("запроса", "requests"), ("запросов", "requests"),
        ("вызов", "calls"), ("вызова", "calls"), ("вызовов", "calls"),
        ("операция", "operations"), ("операции", "operations"), ("операций", "operations"),
    ]:
        result = _normalize_metric_quantity(f"5 {text}")
        assert result is not None, f"failed to normalize '5 {text}'"
        assert result[0] == expected_unit


def test_metric_matches_requires_same_unit_and_amount() -> None:
    a = _normalize_metric_quantity("320,7 млн токенов")
    same = _normalize_metric_quantity("320.7 million tokens")
    different_unit = _normalize_metric_quantity("320,7 млн параметров")
    different_amount = _normalize_metric_quantity("500 млн токенов")
    assert _metric_matches(a, same)
    assert not _metric_matches(a, different_unit)
    assert not _metric_matches(a, different_amount)


# ---------------------------------------------------------------------------
# Generic: REVIEW, not FAIL (tests 13-18)
# ---------------------------------------------------------------------------


def test_generic_vague_russian_billions_of_users() -> None:
    claims = extract_claims("У сервиса миллиарды пользователей.")
    assert claims["generic_quantity"] == ["миллиарды пользователей"]
    assert claims["money"] == []
    assert claims["metric_quantity"] == []


def test_generic_vague_russian_trillions_of_operations() -> None:
    claims = extract_claims("Обрабатываются триллионы операций.")
    assert claims["generic_quantity"] == ["триллионы операций"]


def test_generic_vague_english_billions_of_users() -> None:
    assert extract_claims("The app has billions of users.")["generic_quantity"] == [
        "billions of users"
    ]


def test_generic_vague_english_millions_of_downloads() -> None:
    assert extract_claims("The app has millions of downloads.")["generic_quantity"] == [
        "millions of downloads"
    ]


def test_generic_unresolved_quantity_never_escalates_to_block_by_itself() -> None:
    """The core approved decision: "unknown quantity -> REVIEW, not FAIL". A generic_quantity
    claim with zero matching evidence must land at REVIEW/medium, never BLOCK/high, purely from
    this claim type - the direct fix for the false-positive-severity problem M7 discovery found."""
    result = evaluate_fact_safety(
        "Test", "У сервиса миллиарды пользователей.",
        FactEvidence(source_title="Test", source_content="Completely unrelated content here.", source_url=None),
    )
    assert result["status"] == "review"
    assert result["highest_risk"] == "medium"
    finding = next(f for f in result["findings"] if f["type"] == "generic_quantity")
    assert finding["support"] == "unsupported"
    assert finding["severity"] == "medium"


def test_generic_bare_number_magnitude_no_unit_no_currency() -> None:
    """"2,8 трлн" alone (nothing following) - no currency, no metric unit - is generic_quantity,
    not money (the exact `ac1f1ff5`-shaped case with no trailing word at all)."""
    claims = extract_claims("Стоимость оценивается в 2,8 трлн.")
    assert claims["generic_quantity"] == ["2,8 трлн."]
    assert claims["money"] == []
    assert claims["metric_quantity"] == []


# ---------------------------------------------------------------------------
# Regression: existing money detection unchanged (tests 19-20)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("$1.7 billion", ("USD", 1_700_000_000.0)),
        ("$1,7 млрд", ("USD", 1_700_000_000.0)),
        ("$1.7B", ("USD", 1_700_000_000.0)),
        ("1.7 billion dollars", ("USD", 1_700_000_000.0)),
        ("1,7 млрд долларов", ("USD", 1_700_000_000.0)),
        ("$50", ("USD", 50.0)),
        ("50 dollars", ("USD", 50.0)),
        ("€500 million", ("EUR", 500_000_000.0)),
        ("1,700,000", None),
    ],
)
def test_existing_normalize_money_format_parsing_unchanged(text: str, expected) -> None:
    """Exact regression pin of tests/test_fact_safety.py::test_money_normalization_formats -
    `_normalize_money()` itself was never touched by M7.2 (only what feeds into it changed)."""
    from services.fact_safety import _normalize_money
    assert _normalize_money(text) == expected


def test_existing_money_extraction_from_running_text_unchanged() -> None:
    """The real production case already pinned in M7.1's own test file: a currency-symbol-
    anchored claim extracts and matches exactly as before, unaffected by removing the old
    "magnitude-word-anchored, no currency" branch from `_MONEY_EXTRACT_PATTERN`."""
    ev = FactEvidence(
        source_title="Startup raises $1.7 billion",
        source_content="The company announced it raised $1.7 billion in funding.",
        source_url=None,
    )
    result = evaluate_fact_safety("Компания привлекла $1,7 млрд", "Средства пойдут на развитие.", ev)
    assert result["status"] == "pass"


# ---------------------------------------------------------------------------
# False-negative safety (tests 21-24) - a genuine fabrication must still be caught
# ---------------------------------------------------------------------------


def test_false_negative_safety_fabricated_metric_wrong_number_same_unit() -> None:
    """A candidate claiming "500 million tokens" when evidence says "320.7 million tokens" - same
    unit, different number - must still be caught, HIGH severity, exactly like a real money
    fabrication."""
    audit = evaluate_candidate_fact_safety(
        "Model uses tokens", "The model used 500 million tokens during the test.",
        "Model test", "The model used 320.7 million tokens during the test.",
        research_facts=[],
    )
    assert audit.status.value == "fail"
    assert any("500 million tokens" in f for f in audit.numeric_flags)


def test_false_negative_safety_fabricated_metric_no_evidence_at_all() -> None:
    """A fabricated parameter count with zero supporting evidence anywhere must still escalate to
    FAIL/high - metric_quantity detection must never become a way to smuggle an unchecked large
    number through just because it names a unit."""
    audit = evaluate_candidate_fact_safety(
        "Model announced", "The new model has 9 trillion parameters.",
        "Model announced", "A company announced a new AI model today.",
        research_facts=[],
    )
    assert audit.status.value == "fail"
    assert any("9 trillion parameters" in f for f in audit.numeric_flags)


def test_false_negative_safety_real_currency_fabrication_not_downgraded() -> None:
    """A fabricated, currency-bearing claim must stay at money/HIGH - never accidentally
    reclassified into a lower-severity bucket by the new disambiguation logic."""
    audit = evaluate_candidate_fact_safety(
        "Company raises huge round", "The company raised $9.4 trillion in its latest funding round.",
        "Company raises funding", "The company raised $10 million in its latest funding round.",
        research_facts=[],
    )
    assert audit.status.value == "fail"
    assert any("9.4 trillion" in f for f in audit.numeric_flags)


def test_false_negative_safety_bare_number_no_magnitude_no_unit_still_unextracted() -> None:
    """Out of scope, confirmed unaffected: a bare integer with no magnitude word and no metric
    unit (e.g. "1129 tool calls" reworded generically as just a count) is still not extracted at
    all when no recognized unit follows - this plan never touched bare-number claims in general,
    only the ones with a magnitude word or a recognized metric unit."""
    claims = extract_claims("The team held 1129 meetings this year.")
    assert claims["money"] == []
    assert claims["metric_quantity"] == []
    assert claims["generic_quantity"] == []


# ---------------------------------------------------------------------------
# No duplicate/overlapping extraction (tests 25-27)
# ---------------------------------------------------------------------------


def test_no_double_extraction_currency_symbol_case() -> None:
    """"$1.7 billion" must be extracted exactly once (by `_MONEY_EXTRACT_PATTERN`'s currency-
    symbol branch), never also independently by the new quantity-disambiguation pattern - a
    regression found and fixed during implementation (the negative lookbehind's own purpose)."""
    claims = extract_claims("The company raised $1.7 billion in its latest round.")
    assert claims["money"].count("$1.7 billion") + sum(
        "1.7 billion" in c for c in claims["money"] if c != "$1.7 billion"
    ) == 1


def test_no_double_extraction_decimal_comma_case() -> None:
    """"$1,7 млрд" (Russian decimal comma) must not produce a spurious second match starting
    mid-number after the comma - a real regression found via the existing test suite, not assumed
    safe, and fixed via the lookbehind's digit/separator guard."""
    claims = extract_claims("Компания привлекла $1,7 млрд. Средства пойдут на развитие.")
    assert claims["generic_quantity"] == []
    assert claims["metric_quantity"] == []
    assert len(claims["money"]) == 1


def test_no_double_extraction_metric_with_magnitude_vs_bare_metric_pattern() -> None:
    """"320,7 млн токенов" must be found once (via the magnitude-anchored quantity pattern), not
    twice (once magnitude-anchored, once via the bare-metric pattern that has no magnitude
    requirement)."""
    claims = extract_claims("Модель использовала 320,7 млн токенов.")
    assert len(claims["metric_quantity"]) == 1


# ---------------------------------------------------------------------------
# Real regressions found via the 281-draft production backtest (tests 28-31) - not hypothetical,
# each one flipped a real draft from `pass`/`review` to a spurious `block` before being fixed.
# ---------------------------------------------------------------------------


def test_known_currency_word_never_bleeds_a_second_word_across_a_sentence() -> None:
    """Real production regression (`5e947f0e...`, "Китай взыскал с Trip.com 5,2 млрд юаней.
    Китайский регулятор..."): when the trailing word IS a known currency word ("юаней"), the claim
    string must use ONLY that word - not "юаней\\nКитайский" (the first word of the NEXT
    sentence), which broke normalization and produced a spurious unsupported/HIGH finding for a
    claim that was actually present in evidence."""
    claims = extract_claims("Китай взыскал с Trip.com 5,2 млрд юаней.\nКитайский регулятор объяснил решение.")
    assert claims["money"] == ["5,2 млрд юаней"]


def test_known_currency_word_never_bleeds_a_second_word_same_sentence() -> None:
    """Real production regression (`97323eae...`, "сэкономил 9,2 млрд рублей за счет..."): the
    same bleed also happened WITHIN one sentence when an ordinary word (here "за", a preposition)
    followed a known currency word - not just across sentence boundaries."""
    claims = extract_claims("Компания сэкономила 9,2 млрд рублей за счет автоматизации.")
    assert claims["money"] == ["9,2 млрд рублей"]


def test_ad_hoc_currency_still_allows_two_words_within_one_sentence() -> None:
    """The fix for the two tests above must not regress the legitimate 2-word ad hoc currency
    case ("Korean Won") it was specifically built for."""
    claims = extract_claims("The mobile division lost 0.7 trillion Korean Won.")
    assert claims["money"] == ["0.7 trillion Korean Won"]


def test_vague_quantity_excludes_a_following_preposition() -> None:
    """Real production regression (`d9c0b32c...`, "Иск на миллионы после ранения..." - "a lawsuit
    for millions after [an] injury"): "после" ("after") is a preposition continuing an unrelated
    clause, not the noun being counted - "миллионы после" is not "millions of X" and must not be
    extracted as a generic_quantity claim."""
    claims = extract_claims("Иск на миллионы после ранения при игровом инциденте.")
    assert claims["generic_quantity"] == []


def test_vague_quantity_still_works_with_a_genuine_noun() -> None:
    """The preposition-exclusion fix above must not regress genuine vague-quantity detection."""
    claims = extract_claims("Иск на миллионы пользователей после утечки данных.")
    assert claims["generic_quantity"] == ["миллионы пользователей"]
