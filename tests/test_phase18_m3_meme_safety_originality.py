"""Phase 18 M3 - Meme Safety & Originality Gate tests (docs/
phase18_m3_meme_safety_originality_report.md).

Pure, DB-free unit tests for services/meme_safety.py. DB-dependent CapabilityExecutor wiring
(`_attach_meme_safety_originality`) is not covered here - same disclosed constraint as
tests/test_phase18_m1_meme_opportunity.py (local Postgres/Redis stack unavailable this session);
the wiring itself is a thin, try/except-wrapped call mirroring every prior hook's already-tested
shape.
"""
from __future__ import annotations

import pytest

from schemas.meme_concept import MemeConcept, MemeFormat
from schemas.meme_safety import MemeGateDecision
from services.meme_safety import (
    apply_meme_safety_originality_shadow,
    assess_meme_originality,
    assess_meme_safety,
    assess_meme_safety_and_originality,
)

_BASE_KWARGS = dict(
    premise="An AI company insists AI won't take jobs.",
    setup="The CEO reassures workers during a keynote.",
    punchline="Meanwhile the CEO's own job is the one AI can't replace.",
    humor_mechanism="self_referential_irony",
    visual_scene="A CEO on stage pointing at a slide reading 'Jobs are safe'.",
    characters_objects=["CEO", "presentation slide"],
    text_overlay_intent="Contrast reassurance with public skepticism.",
    source_fact_links=["The CEO publicly stated AI is not destroying jobs."],
    forbidden_interpretations=[],
    meme_format=MemeFormat.CLASSIC_TOP_BOTTOM,
)


def _concept(**overrides) -> MemeConcept:
    return MemeConcept(**{**_BASE_KWARGS, **overrides})


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


def test_clean_concept_passes_safety() -> None:
    result = assess_meme_safety(_concept())
    assert result.decision == MemeGateDecision.PASS


def test_sensitive_content_in_concept_text_is_hard_blocked() -> None:
    result = assess_meme_safety(_concept(
        punchline="The victim was shot during the incident, but at least it's funny.",
    ))
    assert result.decision == MemeGateDecision.BLOCK
    assert "crime_with_victim" in result.sensitivity_categories


def test_calibrated_fact_safety_fail_escalates_to_block() -> None:
    result = assess_meme_safety(_concept(), calibrated_fact_safety_status="fail")
    assert result.decision == MemeGateDecision.BLOCK
    assert "calibrated_fact_safety_fail" in result.reason_codes


def test_calibrated_fact_safety_review_escalates_to_review() -> None:
    result = assess_meme_safety(_concept(), calibrated_fact_safety_status="review")
    assert result.decision == MemeGateDecision.REVIEW


def test_self_flagged_forbidden_interpretation_escalates_to_review() -> None:
    result = assess_meme_safety(_concept(forbidden_interpretations=["Not a claim of dishonesty."]))
    assert result.decision == MemeGateDecision.REVIEW
    assert "concept_self_flagged_forbidden_interpretation" in result.reason_codes


def test_calibrated_pass_and_no_self_flag_stays_pass() -> None:
    result = assess_meme_safety(_concept(), calibrated_fact_safety_status="pass")
    assert result.decision == MemeGateDecision.PASS


# ---------------------------------------------------------------------------
# Originality
# ---------------------------------------------------------------------------


def test_original_concept_passes_originality() -> None:
    result = assess_meme_originality(_concept(), "Nvidia CEO insists AI is not destroying jobs")
    assert result.decision == MemeGateDecision.PASS


def test_known_meme_template_reference_is_blocked() -> None:
    result = assess_meme_originality(
        _concept(visual_scene="Draw this as a classic distracted boyfriend meme layout."),
        "Some unrelated headline",
    )
    assert result.decision == MemeGateDecision.BLOCK
    assert "known_meme_template_referenced" in result.reason_codes


def test_punchline_near_duplicate_of_headline_is_flagged_review() -> None:
    title = "Nvidia CEO insists AI is not destroying jobs after keynote remarks today"
    result = assess_meme_originality(_concept(punchline=title), title)
    assert result.decision == MemeGateDecision.REVIEW
    assert "punchline_near_duplicate_of_headline" in result.reason_codes


def test_short_incidental_word_overlap_does_not_trigger_duplicate_flag() -> None:
    result = assess_meme_originality(
        _concept(punchline="Meanwhile the CEO's own job is the one AI can't replace."),
        "Nvidia CEO insists AI is not destroying jobs",
    )
    assert result.decision == MemeGateDecision.PASS


# ---------------------------------------------------------------------------
# Combined gate
# ---------------------------------------------------------------------------


def test_combined_gate_takes_the_worse_of_safety_and_originality() -> None:
    result = assess_meme_safety_and_originality(
        _concept(visual_scene="A drake meme format image."), "Some headline",
    )
    assert result.gate_decision == MemeGateDecision.BLOCK
    assert result.safety.decision == MemeGateDecision.PASS
    assert result.originality.decision == MemeGateDecision.BLOCK


def test_combined_gate_all_pass_is_pass() -> None:
    result = assess_meme_safety_and_originality(_concept(), "Some unrelated headline")
    assert result.gate_decision == MemeGateDecision.PASS


# ---------------------------------------------------------------------------
# apply_meme_safety_originality_shadow - mode gating
# ---------------------------------------------------------------------------


def test_mode_off_returns_structured_output_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "meme_safety_gate_mode", "off")
    original = {"premise": "x"}
    result = apply_meme_safety_originality_shadow(original, "Title", original)
    assert result is original


def test_mode_shadow_attaches_meme_safety_originality_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "meme_safety_gate_mode", "shadow")
    concept_output = _concept().model_dump(mode="json")
    result = apply_meme_safety_originality_shadow(concept_output, "Some headline", concept_output)

    assert result["premise"] == concept_output["premise"]
    assert "meme_safety_originality" in result
    assert result["meme_safety_originality"]["schema_version"] == "v1"


def test_mode_shadow_with_malformed_concept_raises_inside_helper_not_silently_wrong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pure helper itself raises on a malformed concept (never silently degrades) - the
    executor's own `_attach_meme_safety_originality()` is what wraps this in try/except, not this
    function (mirrors every sibling `apply_*_shadow()` function's identical division of labor)."""
    from core.config import settings

    monkeypatch.setattr(settings, "meme_safety_gate_mode", "shadow")
    with pytest.raises(Exception):
        apply_meme_safety_originality_shadow({"premise": "only a premise"}, "Title", {"premise": "only a premise"})
