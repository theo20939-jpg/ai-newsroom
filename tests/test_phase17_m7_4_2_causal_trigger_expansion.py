"""Phase 17 M7.4.2 - causal trigger expansion tests (docs/
phase17_m7_4_2_causal_trigger_expansion_report.md, discovery: docs/
phase17_m7_4_causal_calibration_discovery.md).

Adds the missing causal-verb constructions M7 discovery found invisible to `_CAUSAL_RE`:
привело к / приводит к / вызвало / стало причиной (RU) and caused / led to / resulted in (EN).
Shipped strictly AFTER M7.4.1's hedge-awareness fix (`tests/test_phase17_m7_4_1_causal_hedge_
calibration.py`) - the whole point of this file is to prove that sequencing was load-bearing:
every hedged example that now newly matches `_CAUSAL_RE` (because it contains one of these new
triggers) must still be correctly excluded by the hedge check M7.4.1 already put in place.
"""
from services.candidate_fact_safety import (
    _CAUSAL_RE,
    _scan_qualitative_flags,
    evaluate_candidate_fact_safety,
)

# ---------------------------------------------------------------------------
# New triggers detected (tests 1-9)
# ---------------------------------------------------------------------------


def test_privelo_k_now_detected() -> None:
    assert _scan_qualitative_flags("X привело к Y.") == ["causal_connector: X привело к Y"]


def test_privodit_k_now_detected() -> None:
    assert _scan_qualitative_flags("X приводит к росту прибыли.") == [
        "causal_connector: X приводит к росту прибыли"
    ]


def test_vyzvalo_now_detected() -> None:
    assert _scan_qualitative_flags("X вызвало снижение.") == ["causal_connector: X вызвало снижение"]


def test_stalo_prichinoi_now_detected() -> None:
    assert _scan_qualitative_flags("Это стало причиной роста.") == [
        "causal_connector: Это стало причиной роста"
    ]


def test_caused_en_now_detected() -> None:
    assert _scan_qualitative_flags("X caused a decline in revenue.") == [
        "causal_connector: X caused a decline in revenue"
    ]


def test_led_to_en_now_detected() -> None:
    assert _scan_qualitative_flags("X led to a significant decline.") == [
        "causal_connector: X led to a significant decline"
    ]


def test_resulted_in_en_now_detected() -> None:
    assert _scan_qualitative_flags("X resulted in a major shift.") == [
        "causal_connector: X resulted in a major shift"
    ]


def test_grammatical_siblings_of_privelo_k() -> None:
    """Narrow grammatical agreement variants of the same requested construction - all genders/
    numbers of "привести к", not a general conjugation rule."""
    for text in ["Компания привела к росту.", "Меры привели к росту.", "Решение приводят к росту."]:
        assert _CAUSAL_RE.search(text) is not None, text


def test_grammatical_siblings_of_vyzvalo() -> None:
    for text in ["Решение вызвал рост.", "Мера вызвала рост.", "Действия вызвали рост."]:
        assert _CAUSAL_RE.search(text) is not None, text


# ---------------------------------------------------------------------------
# The sequencing requirement, proven directly (tests 10-14) - every hedged example that now
# matches _CAUSAL_RE via a NEW trigger must still be excluded by M7.4.1's hedge check
# ---------------------------------------------------------------------------


def test_hedged_privelo_k_still_not_flagged() -> None:
    text = "Нельзя утверждать, что X привело к Y."
    assert _CAUSAL_RE.search(text) is not None  # now matches (new trigger) ...
    assert _scan_qualitative_flags(text) == []  # ... but is still correctly excluded


def test_hedged_vyzvalo_still_not_flagged() -> None:
    text = "Нет доказательств, что X вызвало Y."
    assert _CAUSAL_RE.search(text) is not None
    assert _scan_qualitative_flags(text) == []


def test_hedged_stalo_prichinoi_still_not_flagged() -> None:
    text = "Поэтому нельзя сделать вывод, что X стало причиной Y."
    assert _CAUSAL_RE.search(text) is not None
    assert _scan_qualitative_flags(text) == []


def test_hedged_caused_en_still_not_flagged() -> None:
    text = "It is unclear whether X caused the decline."
    assert _CAUSAL_RE.search(text) is not None
    assert _scan_qualitative_flags(text) == []


def test_sequencing_requirement_would_fail_without_hedge_guard() -> None:
    """Direct proof the M7.4.1 -> M7.4.2 ordering was load-bearing, not just good practice: the
    raw causal-connector match alone (ignoring the hedge guard `_scan_qualitative_flags` applies)
    DOES fire on these hedged sentences - confirming that shipping M7.4.2's trigger words without
    M7.4.1's hedge check in place first would have created real, new false positives."""
    hedged_examples_that_would_have_been_false_positives = [
        "Нельзя утверждать, что X привело к Y.",
        "Нет доказательств, что X вызвало Y.",
        "Поэтому нельзя сделать вывод, что X стало причиной Y.",
    ]
    for text in hedged_examples_that_would_have_been_false_positives:
        assert _CAUSAL_RE.search(text) is not None, f"expected raw match on: {text}"


# ---------------------------------------------------------------------------
# False-negative safety - genuinely unsupported causal claims using the NEW vocabulary are
# actually caught end-to-end (tests 15-16)
# ---------------------------------------------------------------------------


def test_end_to_end_genuine_unsupported_causal_claim_now_caught() -> None:
    """The exact classification-A example from the M7.4 authorization: previously invisible,
    now correctly flagged end-to-end."""
    audit = evaluate_candidate_fact_safety(
        "Company adopts AI", "Компания внедрила AI, что привело к росту прибыли.",
        "Company adopts AI", "A company announced it adopted an AI tool.", research_facts=[],
    )
    assert audit.status.value == "review"
    assert any(f.startswith("causal_connector:") for f in audit.causal_flags)


def test_end_to_end_existing_true_positive_unaffected() -> None:
    """Regression: the pre-existing causal true positive (M4/M5-era, using an original connector
    word) must remain flagged exactly as before - the new triggers are additive, not a
    replacement."""
    audit = evaluate_candidate_fact_safety(
        "Industry news", "Это означает крах всей отрасли полупроводников немедленно.",
        "Industry news", "News about the semiconductor industry.", research_facts=[],
    )
    assert audit.status.value == "review"
    assert any(f.startswith("causal_connector:") for f in audit.causal_flags)


def test_real_backtest_false_positive_active_verb_hedge_now_fixed() -> None:
    """Real false positive found via the 281-draft production backtest this milestone's own
    report requires (not hypothetical): "Данные не подтверждают, что X стала причиной Y" - the
    active verb form "не подтверждают" ("[the data] does not confirm") was not covered by the
    existing "не подтвержден\\w*" pattern (passive participle only, "не подтверждено"/"не
    подтверждена"). Found and fixed before this milestone was considered complete, per this
    project's own "never merge a known false positive" discipline."""
    text = "Данные не подтверждают, что кампания стала причиной финансового результата."
    assert _scan_qualitative_flags(text) == []
