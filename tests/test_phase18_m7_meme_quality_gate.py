"""Phase 18 M7 - Meme Quality Gate tests (docs/phase18_m7_meme_quality_gate_report.md).

Pure, DB-free unit tests for services/meme_quality.py.
"""
from __future__ import annotations

from schemas.meme_concept import MemeConcept, MemeFormat
from schemas.meme_copy import MemeCopy
from schemas.meme_image import MemeImageGenerationResult, MemeImageStatus
from schemas.meme_opportunity import (
    MemeOpportunityAssessment,
    MemeOpportunityDecision,
    MemeOpportunitySignals,
)
from schemas.meme_quality import MemeQualityDecision
from schemas.meme_render import MemeRenderResult, MemeRenderStatus
from schemas.meme_safety import (
    MemeGateDecision,
    MemeOriginalityAssessment,
    MemeSafetyAssessment,
    MemeSafetyOriginalityGateResult,
)
from services.meme_quality import (
    MAX_CONCEPT_REGENERATIONS,
    MAX_IMAGE_REGENERATIONS,
    apply_regeneration_bounds,
    assess_meme_quality,
)


def _concept(**overrides) -> MemeConcept:
    base = dict(
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
        visual_punchline="A robot quietly wheels the CEO's own desk out the door mid-speech.",
        visual_style="reaction photo",
    )
    return MemeConcept(**{**base, **overrides})


def _copy(**overrides) -> MemeCopy:
    base = dict(
        top_text="AI WON'T TAKE YOUR JOB", bottom_text="SAYS GUY WHOSE JOB IS AI",
        punchline_short="The one job AI can't replace.", telegram_caption="From today's keynote.",
        editor_explanation="Plays on the irony.", alt_text="A CEO on stage pointing at a slide.",
    )
    return MemeCopy(**{**base, **overrides})


def _safety_gate(
    safety_decision: MemeGateDecision = MemeGateDecision.PASS,
    originality_decision: MemeGateDecision = MemeGateDecision.PASS,
) -> MemeSafetyOriginalityGateResult:
    safety = MemeSafetyAssessment(decision=safety_decision)
    originality = MemeOriginalityAssessment(decision=originality_decision)
    ranks = {MemeGateDecision.PASS: 0, MemeGateDecision.REVIEW: 1, MemeGateDecision.BLOCK: 2}
    gate = max((safety_decision, originality_decision), key=lambda d: ranks[d])
    return MemeSafetyOriginalityGateResult(
        policy_version="v1", gate_decision=gate, safety=safety, originality=originality,
    )


def _render(status: MemeRenderStatus = MemeRenderStatus.RENDERED, contrast_passed: bool = True,
            safe_zone_violations: list[str] | None = None) -> MemeRenderResult:
    return MemeRenderResult(
        status=status, storage_key="images/aa/aa.png" if status == MemeRenderStatus.RENDERED else None,
        contrast_passed=contrast_passed, safe_zone_violations=safe_zone_violations or [],
    )


def _image(status: MemeImageStatus = MemeImageStatus.GENERATED) -> MemeImageGenerationResult:
    return MemeImageGenerationResult(
        status=status, mode="dry_run", storage_key="images/aa/aa.png" if status == MemeImageStatus.GENERATED else None,
    )


def _opportunity(decision: MemeOpportunityDecision = MemeOpportunityDecision.MEME_READY) -> MemeOpportunityAssessment:
    signals = MemeOpportunitySignals(
        irony_contrast_score=80, audience_relatability_score=50, visual_potential_score=50,
        topic_fit_score=70, freshness_score=100, composite_score=70,
    )
    return MemeOpportunityAssessment(
        policy_version="v1", decision=decision, signals=signals, source_sufficiency="sufficient",
    )


# ---------------------------------------------------------------------------
# Precedence tree
# ---------------------------------------------------------------------------


def test_clean_everything_is_ready_for_editor() -> None:
    result = assess_meme_quality(_concept(), _copy(), _safety_gate(), _render(), _image())
    assert result.decision == MemeQualityDecision.READY_FOR_EDITOR


def test_safety_block_is_unconditional_reject() -> None:
    safety_gate = _safety_gate(safety_decision=MemeGateDecision.BLOCK)
    result = assess_meme_quality(_concept(), _copy(), safety_gate, _render(), _image())
    assert result.decision == MemeQualityDecision.REJECT
    assert "safety_originality_gate_blocked" in result.reason_codes


def test_reject_overrides_even_a_perfect_render() -> None:
    safety_gate = _safety_gate(safety_decision=MemeGateDecision.BLOCK)
    result = assess_meme_quality(
        _concept(), _copy(), safety_gate, _render(contrast_passed=True), _image(),
    )
    assert result.decision == MemeQualityDecision.REJECT


def test_opportunity_sensitive_block_is_reject() -> None:
    result = assess_meme_quality(
        _concept(), _copy(), _safety_gate(), _render(), _image(),
        opportunity=_opportunity(MemeOpportunityDecision.SENSITIVE_BLOCK),
    )
    assert result.decision == MemeQualityDecision.REJECT
    assert "opportunity_sensitive_block" in result.reason_codes


def test_image_generation_failure_recommends_regenerate_image() -> None:
    result = assess_meme_quality(
        _concept(), _copy(), _safety_gate(), _render(status=MemeRenderStatus.FAILED), _image(MemeImageStatus.FAILED),
    )
    assert result.decision == MemeQualityDecision.REGENERATE_IMAGE


def test_contrast_failure_recommends_regenerate_image() -> None:
    result = assess_meme_quality(
        _concept(), _copy(), _safety_gate(), _render(contrast_passed=False), _image(),
    )
    assert result.decision == MemeQualityDecision.REGENERATE_IMAGE


def test_safe_zone_violation_recommends_regenerate_image() -> None:
    result = assess_meme_quality(
        _concept(), _copy(), _safety_gate(), _render(safe_zone_violations=["top_text_truncated_to_fit_safe_zone"]),
        _image(),
    )
    assert result.decision == MemeQualityDecision.REGENERATE_IMAGE


def test_concept_originality_review_recommends_regenerate_concept() -> None:
    safety_gate = _safety_gate(originality_decision=MemeGateDecision.REVIEW)
    result = assess_meme_quality(_concept(), _copy(), safety_gate, _render(), _image())
    assert result.decision == MemeQualityDecision.REGENERATE_CONCEPT


def test_safety_review_recommends_review_not_regenerate() -> None:
    safety_gate = _safety_gate(safety_decision=MemeGateDecision.REVIEW)
    result = assess_meme_quality(_concept(), _copy(), safety_gate, _render(), _image())
    assert result.decision == MemeQualityDecision.REVIEW


def test_opportunity_review_recommends_review() -> None:
    result = assess_meme_quality(
        _concept(), _copy(), _safety_gate(), _render(), _image(),
        opportunity=_opportunity(MemeOpportunityDecision.REVIEW),
    )
    assert result.decision == MemeQualityDecision.REVIEW


# ---------------------------------------------------------------------------
# M7-local checks
# ---------------------------------------------------------------------------


def test_unattributed_number_in_copy_fails_factual_alignment_and_triggers_review() -> None:
    copy = _copy(top_text="500 MILLION REASONS TO WORRY")
    result = assess_meme_quality(_concept(), copy, _safety_gate(), _render(), _image())
    assert result.decision == MemeQualityDecision.REVIEW
    assert result.checks.factual_alignment is False
    assert "unattributed_number_in_copy" in result.reason_codes


def test_number_present_in_concept_grounding_passes_factual_alignment() -> None:
    concept = _concept(source_fact_links=["The company raised $500 million."])
    copy = _copy(top_text="500 MILLION RAISED")
    result = assess_meme_quality(concept, copy, _safety_gate(), _render(), _image())
    assert result.checks.factual_alignment is True


def test_too_short_punchline_triggers_review() -> None:
    copy = _copy(punchline_short="Wow yeah")
    result = assess_meme_quality(_concept(), copy, _safety_gate(), _render(), _image())
    assert result.decision == MemeQualityDecision.REVIEW
    assert result.checks.punchline_clarity is False


def test_crude_language_fails_brand_fit_and_triggers_review() -> None:
    copy = _copy(telegram_caption="What an idiot move by the CEO.")
    result = assess_meme_quality(_concept(), copy, _safety_gate(), _render(), _image())
    assert result.decision == MemeQualityDecision.REVIEW
    assert result.checks.brand_fit is False
    assert "crude_or_mean_spirited_language" in result.reason_codes


# ---------------------------------------------------------------------------
# Bounded regeneration
# ---------------------------------------------------------------------------


def test_regenerate_concept_downgrades_to_reject_once_bound_reached() -> None:
    safety_gate = _safety_gate(originality_decision=MemeGateDecision.REVIEW)
    assessment = assess_meme_quality(_concept(), _copy(), safety_gate, _render(), _image())
    assert assessment.decision == MemeQualityDecision.REGENERATE_CONCEPT

    bounded = apply_regeneration_bounds(
        assessment, concept_regeneration_count=MAX_CONCEPT_REGENERATIONS, image_regeneration_count=0,
    )
    assert bounded.decision == MemeQualityDecision.REJECT
    assert "concept_regeneration_limit_reached" in bounded.reason_codes


def test_regenerate_concept_allowed_when_under_bound() -> None:
    safety_gate = _safety_gate(originality_decision=MemeGateDecision.REVIEW)
    assessment = assess_meme_quality(_concept(), _copy(), safety_gate, _render(), _image())

    bounded = apply_regeneration_bounds(
        assessment, concept_regeneration_count=0, image_regeneration_count=0,
    )
    assert bounded.decision == MemeQualityDecision.REGENERATE_CONCEPT


def test_regenerate_image_downgrades_to_reject_once_bound_reached() -> None:
    assessment = assess_meme_quality(
        _concept(), _copy(), _safety_gate(), _render(contrast_passed=False), _image(),
    )
    assert assessment.decision == MemeQualityDecision.REGENERATE_IMAGE

    bounded = apply_regeneration_bounds(
        assessment, concept_regeneration_count=0, image_regeneration_count=MAX_IMAGE_REGENERATIONS,
    )
    assert bounded.decision == MemeQualityDecision.REJECT
    assert "image_regeneration_limit_reached" in bounded.reason_codes


def test_apply_regeneration_bounds_is_a_no_op_for_ready_for_editor() -> None:
    assessment = assess_meme_quality(_concept(), _copy(), _safety_gate(), _render(), _image())
    assert assessment.decision == MemeQualityDecision.READY_FOR_EDITOR

    bounded = apply_regeneration_bounds(
        assessment, concept_regeneration_count=MAX_CONCEPT_REGENERATIONS,
        image_regeneration_count=MAX_IMAGE_REGENERATIONS,
    )
    assert bounded.decision == MemeQualityDecision.READY_FOR_EDITOR
    assert bounded.reason_codes == assessment.reason_codes
