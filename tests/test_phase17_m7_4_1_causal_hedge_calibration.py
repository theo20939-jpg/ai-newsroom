"""Phase 17 M7.4.1 - hedge-aware causal detection tests (docs/
phase17_m7_4_1_causal_hedge_calibration_report.md, discovery: docs/
phase17_m7_4_causal_calibration_discovery.md).

Scope: hedge-awareness ONLY - no new causal vocabulary (that is M7.4.2, sequenced after this).
`_CAUSAL_RE`'s trigger word list is unchanged; what changed is that a sentence matching it is now
also checked against a widened epistemic-limitation pattern, at the raw-detector level (mirroring
`_FORECAST_RE`'s own pre-existing "and not _HEDGE_RE.search(sentence)" pattern, which the causal
check never had until now), plus a matching widened pattern in the calibration layer for defense
in depth / for any `causal_flags` list constructed directly rather than produced by the raw
detector.
"""
from services.candidate_fact_safety import (
    _CAUSAL_RE,
    _EPISTEMIC_LIMITATION_RE,
    evaluate_candidate_fact_safety,
    _scan_qualitative_flags,
)
from services.fact_safety_calibration import calibrate_fact_safety
from schemas.candidate_fact_safety import AuditSeverity, CandidateFactSafetyAudit, FactSafetyStatus

# ---------------------------------------------------------------------------
# Direct detector tests - must NOT flag (the 5 required examples, tests 1-5)
# ---------------------------------------------------------------------------


def test_must_not_flag_nelzya_utverzhdat() -> None:
    assert _scan_qualitative_flags("Нельзя утверждать, что X привело к Y.") == []


def test_must_not_flag_neyasno_li() -> None:
    assert _scan_qualitative_flags("Неясно, привело ли X к Y.") == []


def test_must_not_flag_net_dokazatelstv() -> None:
    assert _scan_qualitative_flags("Нет доказательств, что X вызвало Y.") == []


def test_must_not_flag_neizvestno_li() -> None:
    assert _scan_qualitative_flags(
        "По данным компании, неизвестно, повлияло ли X на Y."
    ) == []


def test_must_not_flag_poetomu_nelzya_sdelat_vyvod() -> None:
    """The one example that WAS an active, reproducible false positive before this milestone
    ("Поэтому" is an existing `_CAUSAL_RE` trigger word) - verified fixed."""
    assert _CAUSAL_RE.search("Поэтому нельзя сделать вывод, что X стало причиной Y.") is not None
    assert _scan_qualitative_flags("Поэтому нельзя сделать вывод, что X стало причиной Y.") == []


# ---------------------------------------------------------------------------
# Must remain detectable once M7.4.2 adds the missing vocabulary - explicitly OUT OF SCOPE for
# M7.4.1 itself (no new causal trigger words added here), pinned as a documented non-goal so a
# future reader does not mistake the absence of a flag for a bug (tests 6-8)
# ---------------------------------------------------------------------------


def test_privelo_vyzvalo_stalo_prichinoi_now_detectable_see_m7_4_2() -> None:
    """UPDATED for M7.4.2 (docs/phase17_m7_4_2_causal_trigger_expansion_report.md): this test
    originally pinned "X привело к Y"/"X вызвало снижение"/"Это стало причиной роста" as NOT
    detectable, since M7.4.1 deliberately added no causal vocabulary. M7.4.2 has since added
    exactly these triggers (sequenced strictly after M7.4.1's hedge-awareness fix, per M7.4
    discovery's own explicit requirement) - see `tests/test_phase17_m7_4_2_causal_trigger_
    expansion.py` for the full, now-passing positive detection tests. This placeholder is kept
    only so a reader following this file's own history does not need to guess where the
    "not yet detectable" claim went."""
    assert _CAUSAL_RE.search("X привело к Y.") is not None
    assert _CAUSAL_RE.search("X вызвало снижение.") is not None
    assert _CAUSAL_RE.search("Это стало причиной роста.") is not None


# ---------------------------------------------------------------------------
# False-negative safety - a genuine unhedged causal claim using EXISTING vocabulary must still
# be caught (tests 9-10)
# ---------------------------------------------------------------------------


def test_existing_true_positive_still_flagged_eto_oznachaet() -> None:
    """Exact regression pin of the existing calibration-layer fixture
    (tests/test_fact_safety_calibration.py::test_unsupported_causal_claim_retained) - re-asserted
    here at the raw-detector level: a genuine unhedged causal assertion using an EXISTING trigger
    word, with no hedge language anywhere in the sentence, must remain flagged."""
    text = "Это означает крах всей отрасли полупроводников немедленно."
    expected_sentence = text.rstrip(".")  # the sentence splitter strips trailing punctuation
    assert _scan_qualitative_flags(text) == [f"causal_connector: {expected_sentence}"]


def test_existing_true_positive_still_flagged_end_to_end() -> None:
    audit = evaluate_candidate_fact_safety(
        "Company statement", "Это означает крах всей отрасли полупроводников немедленно.",
        "Company statement", "A company made a statement today.", research_facts=[],
    )
    assert audit.status.value == "review"
    assert any(f.startswith("causal_connector:") for f in audit.causal_flags)


# ---------------------------------------------------------------------------
# Widened epistemic-limitation pattern - direct regex tests (tests 11-16)
# ---------------------------------------------------------------------------


def test_epistemic_limitation_tolerates_intervening_adverb() -> None:
    """The real, previously-disclosed-but-unfixed `847618cd` gap: "нельзя утвержда*" required
    tight adjacency; "нельзя ОДНОЗНАЧНО утверждать" (one intervening adverb) now matches too."""
    assert _EPISTEMIC_LIMITATION_RE.search("нельзя однозначно утверждать") is not None
    assert _EPISTEMIC_LIMITATION_RE.search("нельзя утверждать") is not None


def test_epistemic_limitation_new_standalone_triggers() -> None:
    for phrase in ["неясно", "непонятно", "неизвестно"]:
        assert _EPISTEMIC_LIMITATION_RE.search(phrase) is not None, phrase


def test_epistemic_limitation_net_dokazatelstv_variants() -> None:
    for phrase in ["нет доказательств", "нет оснований", "нет подтверждения"]:
        assert _EPISTEMIC_LIMITATION_RE.search(phrase) is not None, phrase


def test_epistemic_limitation_nelzya_sdelat_vyvod() -> None:
    assert _EPISTEMIC_LIMITATION_RE.search("нельзя сделать вывод") is not None
    assert _EPISTEMIC_LIMITATION_RE.search("нельзя точно сделать вывод") is not None


def test_epistemic_limitation_existing_phrase_unchanged() -> None:
    """Exact regression pin: the pre-existing suppression case must still match after widening."""
    assert _EPISTEMIC_LIMITATION_RE.search(
        "Говорить об этом как об установленном факте оснований нет"
    ) is not None


def test_epistemic_limitation_does_not_match_unrelated_text() -> None:
    """False-positive-of-the-fix safety: the widened pattern must not spuriously match ordinary,
    unrelated causal text with none of these markers."""
    assert _EPISTEMIC_LIMITATION_RE.search("Компания объявила о росте прибыли.") is None
    assert _EPISTEMIC_LIMITATION_RE.search("Это означает крах всей отрасли.") is None


# ---------------------------------------------------------------------------
# Calibration-layer parity - the second, independent copy stays in sync (tests 17-18)
# ---------------------------------------------------------------------------


def _audit(**causal_flags_kwargs) -> CandidateFactSafetyAudit:
    return CandidateFactSafetyAudit(
        status=FactSafetyStatus.REVIEW, severity=AuditSeverity.LOW,
        supported_claim_count=1, unsupported_claim_flags=[], numeric_flags=[], entity_flags=[],
        definition_flags=[], reason_codes=[], **causal_flags_kwargs,
    )


def test_calibration_layer_suppresses_widened_phrases_directly_constructed() -> None:
    """A `causal_flags` list constructed directly (not via the raw detector - matching every
    existing calibration test's own convention) must also be suppressed by the widened
    calibration-layer pattern, confirming the two independent copies stay in sync."""
    audit = _audit(causal_flags=["causal_connector: Поэтому нельзя сделать вывод, что X стало причиной Y"])
    calibrated = calibrate_fact_safety(
        audit, draft_title="t", news_event_title="x", news_event_content=None, research_facts=[],
    )
    assert not calibrated.unresolved_flags
    reasons = {sf.reason_code for sf in calibrated.suppressed_false_positive_flags}
    assert "hedge_language_misclassified" in reasons


def test_calibration_layer_still_retains_genuine_causal_claim() -> None:
    """Exact regression pin of the existing test_unsupported_causal_claim_retained fixture -
    re-asserted here to confirm the widened pattern did not accidentally start suppressing it."""
    audit = _audit(causal_flags=["causal_connector: Это означает крах всей отрасли полупроводников немедленно"])
    calibrated = calibrate_fact_safety(
        audit, draft_title="t", news_event_title="x", news_event_content=None, research_facts=[],
    )
    assert calibrated.unresolved_flags
    assert not calibrated.suppressed_false_positive_flags


# ---------------------------------------------------------------------------
# End-to-end: the real 847618cd case fully resolves (test 19)
# ---------------------------------------------------------------------------


def test_end_to_end_hedged_causal_sentence_reaches_pass() -> None:
    """A minimal, synthetic version of the real 847618cd pattern - a candidate whose only
    otherwise-flaggable content is a hedge sentence opening with an existing causal-connector
    trigger word must now reach a full PASS."""
    audit = evaluate_candidate_fact_safety(
        "Experiment result unclear",
        "Поэтому нельзя однозначно утверждать, что именно привело к такому результату.",
        "Experiment result unclear", "An experiment produced an unclear result.",
        research_facts=[],
    )
    assert audit.status.value == "pass"
    assert audit.causal_flags == []
