"""Phase 19 M3: pure, tier-1 unit tests for services.editorial_planning_safety - no DB, no
network, no LLM.
"""
from services.editorial_planning_safety import (
    check_grounding_supported,
    check_no_competitive_claims,
    check_quote_exists_in_evidence,
    check_what_remains_unknown_present,
    evaluate_plan_safety,
)


def _plan(**overrides) -> dict:
    base = {
        "central_fact": "The company raised five million dollars in a seed funding round.",
        "what_is_new": "A new funding round.", "why_it_matters": "It funds their next product.",
        "headline_emphasis": "Funding round", "opening_emphasis": "The company raised funds.",
        "what_remains_unknown": None, "verified_quote_text": None,
    }
    base.update(overrides)
    return base


def test_grounding_supported_when_central_fact_overlaps_evidence() -> None:
    evidence = "The company announced today that it raised five million dollars in a seed round."
    assert check_grounding_supported(_plan(), evidence) is True


def test_grounding_not_supported_when_central_fact_shares_no_vocabulary() -> None:
    evidence = "A completely unrelated topic about weather patterns in another country entirely."
    assert check_grounding_supported(_plan(), evidence) is False


def test_grounding_check_passes_when_evidence_is_empty() -> None:
    """No evidence to ground against (e.g. HEADLINE_ONLY) - not this check's job to fail."""
    assert check_grounding_supported(_plan(), "") is True


def test_grounding_check_fails_on_missing_central_fact() -> None:
    assert check_grounding_supported(_plan(central_fact=""), "some evidence text here") is False


def test_no_competitive_claims_passes_on_neutral_text() -> None:
    assert check_no_competitive_claims(_plan()) is True


def test_no_competitive_claims_fails_on_superlative() -> None:
    assert check_no_competitive_claims(_plan(why_it_matters="This is revolutionary and unmatched.")) is False


def test_no_competitive_claims_fails_on_competitive_phrase() -> None:
    assert check_no_competitive_claims(_plan(central_fact="Our product outperforms the competition.")) is False


def test_quote_exists_check_passes_when_quote_is_none() -> None:
    assert check_quote_exists_in_evidence(_plan(verified_quote_text=None), [], "any evidence") is True


def test_quote_exists_check_passes_when_verbatim_in_evidence() -> None:
    evidence = 'The CEO said, "We are excited about this launch," during the call.'
    plan = _plan(verified_quote_text="We are excited about this launch")
    assert check_quote_exists_in_evidence(plan, [], evidence) is True


def test_quote_exists_check_fails_when_not_present_anywhere() -> None:
    plan = _plan(verified_quote_text="This exact phrase never appears in any source")
    assert check_quote_exists_in_evidence(plan, [], "Unrelated evidence text entirely.") is False


def test_quote_exists_check_checks_candidates_list_too() -> None:
    plan = _plan(verified_quote_text="a specific verbatim quotation here")
    candidates = ['Someone said "a specific verbatim quotation here" once.']
    assert check_quote_exists_in_evidence(plan, candidates, "unrelated fallback text") is True


def test_what_remains_unknown_present_check() -> None:
    assert check_what_remains_unknown_present(_plan()) is True
    assert check_what_remains_unknown_present({}) is False


def test_evaluate_plan_safety_all_pass() -> None:
    evidence = "The company announced it raised five million dollars in a seed funding round today."
    report = evaluate_plan_safety(_plan(), evidence_text=evidence)
    assert report.passed is True
    assert report.failed_checks == []


def test_evaluate_plan_safety_reports_multiple_failures() -> None:
    plan = _plan(
        central_fact="Totally unrelated fabricated content sharing no vocabulary at all.",
        why_it_matters="This is revolutionary and unmatched.",
    )
    del plan["what_remains_unknown"]
    report = evaluate_plan_safety(plan, evidence_text="Some real evidence about a funding round.")
    assert report.passed is False
    assert "grounding_supported" in report.failed_checks
    assert "no_competitive_claims" in report.failed_checks
    assert "what_remains_unknown_present" in report.failed_checks
