"""Phase 17 M7.1 - Fact Safety calibration implementation tests (docs/
phase17_m7_1_fact_safety_calibration_report.md, discovery: docs/
phase17_m7_fact_safety_calibration_discovery.md).

Two scoped changes only, per M7.1's own explicit authorization:
(A) Stage 2 candidate generation now also computes `services.fact_safety_calibration.
calibrate_fact_safety()` alongside the existing raw `CandidateFactSafetyAudit`, storing both
separately - never overwriting the raw result.
(B) `трлн`/`trillion` added to `services.fact_safety`'s money-magnitude table - a coverage gap
found incidentally during M7 discovery (a trillion-scale claim was previously invisible to Fact
Safety entirely).

No other Fact Safety logic changed - entity matching, causal detection, and the money-without-
currency normalization gap (M7 discovery's own class #1) are all explicitly out of scope here and
untouched. This file pins that: real money-format regression cases are re-asserted, and the known,
disclosed limitation that a *currency-less* trillion-scale quantity still fails to normalize (same
pre-existing gap as the million/billion case) is itself tested and documented, not silently left
undiscovered.
"""
import pytest

from services.candidate_fact_safety import evaluate_candidate_fact_safety
from services.fact_safety import _normalize_money, extract_claims
from services.fact_safety_calibration import calibrate_fact_safety

# ---------------------------------------------------------------------------
# Fix B - трлн/trillion magnitude detection (tests 1-3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("$2.8 trillion", ("USD", 2_800_000_000_000.0)),
        ("$2,8 трлн", ("USD", 2_800_000_000_000.0)),
        ("2.8 trillion dollars", ("USD", 2_800_000_000_000.0)),
        ("2,8 трлн долларов", ("USD", 2_800_000_000_000.0)),
        ("€1.5 trillion", ("EUR", 1_500_000_000_000.0)),
    ],
)
def test_trillion_scale_quantities_with_currency_are_detected(text: str, expected) -> None:
    assert _normalize_money(text) == expected


def test_trillion_claim_is_extracted_where_it_previously_was_not() -> None:
    """Before M7.1, "2,8 трлн параметров" was invisible to extract_claims() entirely (docs/
    phase17_m7_fact_safety_calibration_discovery.md §1b) - now it is extracted (as a `money`-typed
    claim, matching how million/billion claims are already typed)."""
    claims = extract_claims("Модель содержит 2,8 трлн параметров.")
    assert claims["money"] == ["2,8 трлн"]


def test_trillion_claim_without_currency_still_fails_to_normalize_known_disclosed_gap() -> None:
    """Disclosed, not silently left broken: a bare trillion-scale quantity with no currency word
    still cannot resolve via `_normalize_money()`, for the exact same reason a bare million-scale
    quantity ("320,7 млн") could not (M7 discovery class #1) - that root-cause fix is explicitly
    OUT OF SCOPE for M7.1. This test exists so a future reader sees this is a known limitation,
    not an oversight, and so any future fix to the currency-requirement logic has an explicit
    regression pin to update rather than silently changing behavior here."""
    assert _normalize_money("2,8 трлн") is None


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
        ("1,700,000", None),  # no currency signal at all - correctly unresolvable, unchanged
    ],
)
def test_existing_money_normalization_unchanged_after_trillion_addition(text: str, expected) -> None:
    """Exact regression pin of tests/test_fact_safety.py::test_money_normalization_formats' own
    parametrization - re-asserted here to prove trillion/трлн addition changed nothing about how
    million/billion/thousand/bare-number cases already resolved."""
    assert _normalize_money(text) == expected


def test_fabricated_trillion_claim_with_currency_not_in_evidence_is_still_flagged() -> None:
    """False-negative safety (M7.1's own explicit requirement): a fabricated trillion-scale claim
    that includes a currency (and therefore CAN normalize) must still be caught as unsupported when
    it does not match any evidence - trillion detection must never accidentally become a new way to
    smuggle an unchecked large-number claim through."""
    audit = evaluate_candidate_fact_safety(
        "Company raises huge round",
        "The company raised $9.4 trillion in its latest funding round.",
        "Company raises funding", "The company raised $10 million in its latest funding round.",
        research_facts=[],
    )
    assert audit.status.value == "fail"
    assert any("9.4 trillion" in f or "9,4 trillion" in f for f in audit.numeric_flags)


# ---------------------------------------------------------------------------
# Fix A - Stage 2 calibration wiring: raw preserved, calibrated computed separately (tests 6-9)
# ---------------------------------------------------------------------------

_847618CD_RESEARCH_FACTS = [
    "В конце июля исследовательская команда Bottleneck Labs опубликовала отчет об эксперименте с автономным ИИ-агентом.",
    "Агенту на модели GPT-5.6 Sol на 24 часа предоставили настоящий бизнес: действующее iOS-приложение, банковский счет с реальными деньгами и компьютер с полным доступом.",
    "Агента звали Saul.",
    "За 24 часа Saul использовал 320,7 млн входных токенов и выполнил 1129 вызовов инструментов.",
    "За время эксперимента агент привлек пять новых пользователей.",
    "Агент не заработал денег.",
    "Со счета ушло $99,50: баланс снизился с $350 до $250,50.",
    "Общая стоимость бизнеса снизилась на $447.",
]
# The real, persisted NewsEvent.title (not the baseline production draft's own title, which reads
# differently - "Автономный ИИ-агент протестировал реальный бизнес — и ушёл в минус" - the two are
# easy to conflate but evaluate_candidate_fact_safety()/calibrate_fact_safety() both take the real
# event title specifically).
_847618CD_EVENT_TITLE = "ИИ-агенту дали задачу спасти реальный бизнес. Он врал, спамил и ушел в минус"
_847618CD_CANDIDATE_TITLE = "Автономный ИИ-агент за сутки привлек пять пользователей, но не заработал денег"
_847618CD_CANDIDATE_BODY = (
    "В конце июля исследовательская команда Bottleneck Labs опубликовала отчет об эксперименте с "
    "автономным ИИ-агентом. Агент Saul работал на модели GPT-5.6 Sol и получил на 24 часа доступ к "
    "настоящему бизнесу: действующему iOS-приложению, банковскому счету с реальными деньгами и "
    "компьютеру с полным доступом.\n\n"
    "За время теста Saul привлек пять новых пользователей, но не заработал денег. Он использовал "
    "320,7 млн входных токенов и выполнил 1129 вызовов инструментов. Со счета ушло $99,50: баланс "
    "снизился с $350 до $250,50. Кроме того, общая стоимость бизнеса уменьшилась на $447.\n\n"
    "При этом представленный фрагмент не подтверждает конкретные утверждения о лжи или спаме, "
    "вынесенные в заголовок. Поэтому по этим данным нельзя однозначно утверждать, что именно "
    "потерпело неудачу — агент или сам эксперимент."
)
# The event's real, persisted NewsEvent.content (fetched read-only from the database once while
# writing this test, then hardcoded here as a fixture - never re-fetched at test time, no DB
# session in this file). Reproduced verbatim, including its raw HTML, because entity/money
# extraction is sensitive to exact wording - an invented placeholder body was tried first and
# produced different flags than the real recorded run, so this pins the real text specifically.
_847618CD_EVENT_CONTENT = (
    '<img src="https://habrastorage.org/getpro/habr/upload_files/dff/660/c2d/'
    'dff660c2dedb25d9e1ad1f3893948707.jpg" /><p>В конце июля исследовательская команда Bottleneck '
    'Labs опубликовала&nbsp;<a href="https://www.bottlenecklabs.com/blog/autonomously-run-businesses" '
    'rel="noopener noreferrer nofollow">отчет</a>&nbsp;о необычном эксперименте: агенту на GPT-5.6 '
    'Sol на сутки отдали настоящий бизнес — живое iOS-приложение, банковский счет с реальными '
    'деньгами и компьютер с полным доступом. Исследователи сформулировали вопрос просто: способен '
    'ли агент на передовой модели, получив полный инструментарий предпринимателя, добиться '
    'измеримых бизнес-результатов? За 24 часа агент по имени Saul сжег 320,7 млн входных токенов, '
    'сделал 1129 вызовов инструментов, привлек пять новых пользователей и не заработал ни доллара. '
    'Живых денег со счета утекло $99,50 (баланс просел с $350 до $250,50), а общая стоимость '
    'бизнеса упала на $447. Впрочем, чем дальше читаешь отчет, тем меньше уверенности, кто здесь '
    'провалился — агент или сам эксперимент.</p> <a href="https://habr.com/ru/articles/1065830/'
    '?utm_campaign=1065830&amp;utm_source=habrahabr&amp;utm_medium=rss#habracut">Читать далее</a>'
)


def test_847618cd_raw_audit_still_fail_high_unchanged() -> None:
    """The raw, uncalibrated audit result must be byte-for-byte identical to what M7 discovery
    already found and disclosed - M7.1 must never change raw detection behavior, only add a
    separate calibrated view alongside it."""
    raw = evaluate_candidate_fact_safety(
        _847618CD_CANDIDATE_TITLE, _847618CD_CANDIDATE_BODY, _847618CD_EVENT_TITLE,
        _847618CD_EVENT_CONTENT, _847618CD_RESEARCH_FACTS,
    )
    assert raw.status.value == "fail"
    assert raw.severity.value == "high"
    assert any(f.startswith("unsupported:320,7") for f in raw.numeric_flags)


def test_847618cd_calibrated_status_improves_via_existing_suppression_rule() -> None:
    """The numeric false positive (320.7 million tokens, verbatim in research_facts) is suppressed
    by calibration's own already-existing `russian_inflection_or_quote_match` rule - status
    improves from FAIL/high to REVIEW, without any new suppression rule being written in M7.1."""
    raw = evaluate_candidate_fact_safety(
        _847618CD_CANDIDATE_TITLE, _847618CD_CANDIDATE_BODY, _847618CD_EVENT_TITLE,
        _847618CD_EVENT_CONTENT, _847618CD_RESEARCH_FACTS,
    )
    calibrated = calibrate_fact_safety(
        raw, draft_title=_847618CD_CANDIDATE_TITLE, news_event_title=_847618CD_EVENT_TITLE,
        news_event_content=_847618CD_EVENT_CONTENT, research_facts=_847618CD_RESEARCH_FACTS,
    )
    assert calibrated.raw_audit_status == raw.status
    assert calibrated.calibrated_status.value == "review"
    assert any(
        s.flag.startswith("unsupported:320,7") and s.reason_code == "russian_inflection_or_quote_match"
        for s in calibrated.suppressed_false_positive_flags
    )


def test_847618cd_entity_and_causal_flags_survive_calibration_known_remaining_issue() -> None:
    """Documents, with a real regression pin, that calibration alone does NOT fully resolve
    847618cd: the two entity flags (M7 discovery class #2 - out of scope for M7.1) remain
    true_positive, and the causal flag (class #3 - also out of scope) remains unresolved. This is
    the exact "known remaining issue" M7.1's own report discloses, not an unexpected result."""
    raw = evaluate_candidate_fact_safety(
        _847618CD_CANDIDATE_TITLE, _847618CD_CANDIDATE_BODY, _847618CD_EVENT_TITLE,
        _847618CD_EVENT_CONTENT, _847618CD_RESEARCH_FACTS,
    )
    calibrated = calibrate_fact_safety(
        raw, draft_title=_847618CD_CANDIDATE_TITLE, news_event_title=_847618CD_EVENT_TITLE,
        news_event_content=_847618CD_EVENT_CONTENT, research_facts=_847618CD_RESEARCH_FACTS,
    )
    assert any(f.startswith("unsupported:Автономный") for f in calibrated.true_positive_flags)
    assert any(f.startswith("unsupported:Агент") for f in calibrated.true_positive_flags)
    assert any(f.startswith("causal_connector:") for f in calibrated.unresolved_flags)


def test_raw_and_calibrated_are_independently_computed_never_one_derived_by_mutating_the_other() -> None:
    """Structural guard: calling calibrate_fact_safety() must never mutate the raw
    CandidateFactSafetyAudit object it was given (both are frozen Pydantic models, but this test
    pins the behavioral guarantee directly, not just the type system)."""
    raw = evaluate_candidate_fact_safety(
        _847618CD_CANDIDATE_TITLE, _847618CD_CANDIDATE_BODY, _847618CD_EVENT_TITLE,
        _847618CD_EVENT_CONTENT, _847618CD_RESEARCH_FACTS,
    )
    raw_dump_before = raw.model_dump(mode="json")
    calibrate_fact_safety(
        raw, draft_title=_847618CD_CANDIDATE_TITLE, news_event_title=_847618CD_EVENT_TITLE,
        news_event_content=_847618CD_EVENT_CONTENT, research_facts=_847618CD_RESEARCH_FACTS,
    )
    assert raw.model_dump(mode="json") == raw_dump_before
