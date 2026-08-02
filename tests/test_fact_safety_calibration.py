"""Phase 17 M5 - Fact Safety calibration layer tests (docs/
phase17_m5_editorial_completeness_gate_shadow_report.md).

Pure unit tests only (no DB, no LLM). Covers the calibration layer's own suppression rules and,
critically, the false-negative-safety regression fixtures (this milestone's own explicit priority:
never trade a false negative for a false positive reduction) - each fixture asserts a genuinely
unsupported claim STAYS flagged after calibration.
"""
from __future__ import annotations

from schemas.candidate_fact_safety import AuditSeverity, CandidateFactSafetyAudit, FactSafetyStatus
from services.fact_safety_calibration import calibrate_fact_safety

_SOURCE_TITLE = "United Microelectronics Corporation expands Singapore plant"
_SOURCE_CONTENT = (
    "United Microelectronics Corporation (UMC) said its board approved a phased expansion plan. "
    "The company will expand cleanroom capacity in Singapore and build a new plant in Tainan, Taiwan."
)
_RESEARCH_FACTS = [
    "Netflix заплатила 500 миллионов долларов за продление прав на «Ходячие мертвецы».",
]


def _audit(**overrides) -> CandidateFactSafetyAudit:
    defaults = dict(
        status=FactSafetyStatus.REVIEW, supported_claim_count=1, severity=AuditSeverity.LOW,
    )
    defaults.update(overrides)
    return CandidateFactSafetyAudit(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Suppression rules (36-39, 42-43, 52)
# ---------------------------------------------------------------------------


def test_russian_inflection_suppressed_correctly() -> None:
    audit = _audit(
        status=FactSafetyStatus.FAIL, severity=AuditSeverity.HIGH,
        entity_flags=["unsupported:Ходячих мертвецов"], unsupported_claim_flags=["unsupported:Ходячих мертвецов"],
    )
    calibrated = calibrate_fact_safety(
        audit, draft_title="t", news_event_title="Netflix pays for streaming rights",
        news_event_content=None, research_facts=_RESEARCH_FACTS,
    )
    assert calibrated.calibrated_status != FactSafetyStatus.FAIL
    reasons = {sf.reason_code for sf in calibrated.suppressed_false_positive_flags}
    assert "russian_inflection_or_quote_match" in reasons


def test_quoted_title_matching() -> None:
    audit = _audit(
        status=FactSafetyStatus.REVIEW, entity_flags=['unsupported:«Ходячие мертвецы»'],
    )
    calibrated = calibrate_fact_safety(
        audit, draft_title="t", news_event_title="x", news_event_content=None,
        research_facts=_RESEARCH_FACTS,
    )
    assert calibrated.calibrated_status == FactSafetyStatus.PASS
    assert calibrated.suppressed_false_positive_flags


def test_corporation_suffix_suppression() -> None:
    audit = _audit(
        status=FactSafetyStatus.FAIL, severity=AuditSeverity.HIGH,
        definition_flags=["unsupported_definition: Corporation"],
    )
    calibrated = calibrate_fact_safety(
        audit, draft_title="t", news_event_title=_SOURCE_TITLE, news_event_content=_SOURCE_CONTENT,
        research_facts=[],
    )
    assert calibrated.calibrated_status != FactSafetyStatus.FAIL
    reasons = {sf.reason_code for sf in calibrated.suppressed_false_positive_flags}
    assert "definition_fragment_of_supported_entity" in reasons


def test_hedge_phrase_not_treated_as_unsupported_forecast() -> None:
    audit = _audit(
        status=FactSafetyStatus.REVIEW,
        causal_flags=["causal_connector: Говорить об этом как об установленном факте оснований нет"],
    )
    calibrated = calibrate_fact_safety(
        audit, draft_title="t", news_event_title="x", news_event_content=None, research_facts=[],
    )
    assert not calibrated.unresolved_flags
    reasons = {sf.reason_code for sf in calibrated.suppressed_false_positive_flags}
    assert "hedge_language_misclassified" in reasons


def test_confirmed_what_next_retained() -> None:
    """A forecast sentence naming only already-evidenced facts (a confirmed synthesis, not an
    invented prediction) is suppressed - the exact real M4.1 pattern
    (docs/phase17_m4_1_reasoning_budget_fix_report.md §11, UMC "will expand in two locations")."""
    audit = _audit(
        status=FactSafetyStatus.REVIEW,
        causal_flags=["unhedged_forecast: Инфраструктура будет развиваться в Singapore и Tainan"],
    )
    calibrated = calibrate_fact_safety(
        audit, draft_title="t", news_event_title=_SOURCE_TITLE, news_event_content=_SOURCE_CONTENT,
        research_facts=[],
    )
    assert not calibrated.unresolved_flags
    reasons = {sf.reason_code for sf in calibrated.suppressed_false_positive_flags}
    assert reasons & {"qualitative_synthesis_no_new_checkable_claim", "confirmed_fact_synthesis"}


def test_unsupported_future_claim_still_flagged() -> None:
    """False-negative safety: a forecast naming a NEW, unevidenced number must stay flagged."""
    audit = _audit(
        status=FactSafetyStatus.REVIEW,
        causal_flags=["unhedged_forecast: Прибыль компании будет 40% в следующем квартале"],
    )
    calibrated = calibrate_fact_safety(
        audit, draft_title="t", news_event_title=_SOURCE_TITLE, news_event_content=_SOURCE_CONTENT,
        research_facts=[],
    )
    assert calibrated.unresolved_flags
    assert not calibrated.suppressed_false_positive_flags


def test_regex_fragment_false_positive_suppressed() -> None:
    audit = _audit(
        status=FactSafetyStatus.FAIL, severity=AuditSeverity.HIGH,
        definition_flags=["unsupported_definition: Horowitz"],
    )
    calibrated = calibrate_fact_safety(
        audit, draft_title="t", news_event_title="Andreessen Horowitz backs new AI startup",
        news_event_content=None, research_facts=[],
    )
    assert calibrated.calibrated_status != FactSafetyStatus.FAIL
    reasons = {sf.reason_code for sf in calibrated.suppressed_false_positive_flags}
    assert "definition_fragment_of_supported_entity" in reasons


def test_product_version_matching() -> None:
    audit = _audit(status=FactSafetyStatus.REVIEW, entity_flags=["unsupported:GPT-4"])
    calibrated = calibrate_fact_safety(
        audit, draft_title="t", news_event_title="OpenAI releases GPT-4 update",
        news_event_content=None, research_facts=[],
    )
    assert calibrated.calibrated_status == FactSafetyStatus.PASS


def test_suppression_reason_codes() -> None:
    audit = _audit(
        status=FactSafetyStatus.FAIL, severity=AuditSeverity.HIGH,
        entity_flags=["unsupported:Ходячих мертвецов"],
        definition_flags=["unsupported_definition: Corporation"],
    )
    calibrated = calibrate_fact_safety(
        audit, draft_title="t", news_event_title=_SOURCE_TITLE, news_event_content=_SOURCE_CONTENT,
        research_facts=_RESEARCH_FACTS,
    )
    assert calibrated.suppressed_false_positive_flags
    for suppressed in calibrated.suppressed_false_positive_flags:
        assert suppressed.reason_code
        assert suppressed.flag


# ---------------------------------------------------------------------------
# False-negative-safety regression fixtures (41, 44-51, 53-54)
# ---------------------------------------------------------------------------


def test_unsupported_number_retained() -> None:
    audit = _audit(status=FactSafetyStatus.REVIEW, numeric_flags=["unsupported:$9,999,999"])
    calibrated = calibrate_fact_safety(
        audit, draft_title="t", news_event_title=_SOURCE_TITLE, news_event_content=_SOURCE_CONTENT,
        research_facts=[],
    )
    assert "unsupported:$9,999,999" in calibrated.true_positive_flags
    assert calibrated.calibrated_status == FactSafetyStatus.FAIL


def test_unsupported_percentage_retained() -> None:
    audit = _audit(status=FactSafetyStatus.REVIEW, numeric_flags=["unsupported:87%"])
    calibrated = calibrate_fact_safety(
        audit, draft_title="t", news_event_title=_SOURCE_TITLE, news_event_content=_SOURCE_CONTENT,
        research_facts=[],
    )
    assert "unsupported:87%" in calibrated.true_positive_flags


def test_unsupported_date_retained() -> None:
    audit = _audit(status=FactSafetyStatus.REVIEW, numeric_flags=["unsupported:2031-01-01"])
    calibrated = calibrate_fact_safety(
        audit, draft_title="t", news_event_title=_SOURCE_TITLE, news_event_content=_SOURCE_CONTENT,
        research_facts=[],
    )
    assert "unsupported:2031-01-01" in calibrated.true_positive_flags


def test_unsupported_entity_retained() -> None:
    audit = _audit(status=FactSafetyStatus.REVIEW, entity_flags=["unsupported:Quantum Dynamics Labs"])
    calibrated = calibrate_fact_safety(
        audit, draft_title="Quantum Dynamics Labs unveils device", news_event_title=_SOURCE_TITLE,
        news_event_content=_SOURCE_CONTENT, research_facts=[],
    )
    assert "unsupported:Quantum Dynamics Labs" in calibrated.true_positive_flags
    # Matches the raw audit's own established design: an unsupported *entity* claim alone (even a
    # central one) is REVIEW-tier, never FAIL - only money/percentage/date/quote/definition escalate.
    assert calibrated.calibrated_status == FactSafetyStatus.REVIEW


def test_unsupported_company_description_retained() -> None:
    audit = _audit(status=FactSafetyStatus.REVIEW, entity_flags=["unsupported:ведущий мировой разработчик чипов"])
    calibrated = calibrate_fact_safety(
        audit, draft_title="t", news_event_title=_SOURCE_TITLE, news_event_content=_SOURCE_CONTENT,
        research_facts=[],
    )
    assert "unsupported:ведущий мировой разработчик чипов" in calibrated.true_positive_flags


def test_unsupported_causal_claim_retained() -> None:
    audit = _audit(
        status=FactSafetyStatus.REVIEW,
        causal_flags=["causal_connector: Это означает крах всей отрасли полупроводников немедленно"],
    )
    calibrated = calibrate_fact_safety(
        audit, draft_title="t", news_event_title=_SOURCE_TITLE, news_event_content=_SOURCE_CONTENT,
        research_facts=[],
    )
    assert calibrated.unresolved_flags
    assert calibrated.calibrated_status == FactSafetyStatus.REVIEW


def test_unsupported_definition_retained() -> None:
    audit = _audit(
        status=FactSafetyStatus.FAIL, severity=AuditSeverity.HIGH,
        definition_flags=["unsupported_definition: Cryptozoology"],
    )
    calibrated = calibrate_fact_safety(
        audit, draft_title="t", news_event_title=_SOURCE_TITLE, news_event_content=_SOURCE_CONTENT,
        research_facts=[],
    )
    assert calibrated.calibrated_status == FactSafetyStatus.FAIL
    assert "unsupported_definition: Cryptozoology" in calibrated.true_positive_flags


def test_market_leader_claim_retained() -> None:
    audit = _audit(
        status=FactSafetyStatus.REVIEW,
        causal_flags=["market_claim: Компания является безоговорочным лидером рынка чипов"],
    )
    calibrated = calibrate_fact_safety(
        audit, draft_title="t", news_event_title=_SOURCE_TITLE, news_event_content=_SOURCE_CONTENT,
        research_facts=[],
    )
    assert calibrated.unresolved_flags
    assert not calibrated.suppressed_false_positive_flags


def test_unresolved_flags_preserved() -> None:
    audit = _audit(
        status=FactSafetyStatus.REVIEW,
        causal_flags=["superlative_claim: Это самый революционный продукт в истории индустрии"],
    )
    calibrated = calibrate_fact_safety(
        audit, draft_title="t", news_event_title=_SOURCE_TITLE, news_event_content=_SOURCE_CONTENT,
        research_facts=[],
    )
    assert calibrated.unresolved_flags == ["superlative_claim: Это самый революционный продукт в истории индустрии"]
    assert calibrated.human_review_required is True


def test_true_positive_retention() -> None:
    audit = _audit(
        status=FactSafetyStatus.REVIEW,
        numeric_flags=["unsupported:$1"], entity_flags=["unsupported:Nonexistent Corp Name"],
    )
    calibrated = calibrate_fact_safety(
        audit, draft_title="t", news_event_title=_SOURCE_TITLE, news_event_content=_SOURCE_CONTENT,
        research_facts=[],
    )
    assert "unsupported:$1" in calibrated.true_positive_flags
    assert "unsupported:Nonexistent Corp Name" in calibrated.true_positive_flags
    assert len(calibrated.true_positive_flags) == 2


def test_raw_status_preserved_alongside_calibrated() -> None:
    audit = _audit(status=FactSafetyStatus.FAIL, severity=AuditSeverity.HIGH, definition_flags=["unsupported_definition: Corporation"])
    calibrated = calibrate_fact_safety(
        audit, draft_title="t", news_event_title=_SOURCE_TITLE, news_event_content=_SOURCE_CONTENT,
        research_facts=[],
    )
    assert calibrated.raw_audit_status == FactSafetyStatus.FAIL
    assert calibrated.calibrated_status != calibrated.raw_audit_status
