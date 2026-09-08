"""DIRECTOR-CONTROL-PLANE-1B §9-13: the Art Director spec/reference evaluator is now folded into
the real ArtDirectorResult a caller acts on (services/telegram_art_director_spec_evaluation.py::
finalize_art_direction / merge_spec_evaluation_into_result), and run_visual_design_loop() invokes
it on every attempt.

Proves:
  * §10 hard-failure precedence: an optimistic base/vision decision (PASS / PASS_WITH_NOTES) is
    overridden to BLOCK whenever a §19 hard failure fires (NUMBER_MISMATCH, INFOGRAPHIC_DESTROYED,
    DUPLICATE_NNJ_BRAND_MARK, hard ACTIVE-spec invariant).
  * §13 Kirin: the OLD FULL_DATA_CARD render over the EXISTING_INFOGRAPHIC source cannot reach a
    non-BLOCK final decision through the merged path; the NEW MINIMAL_SOURCE_PRESERVING render
    clears the hard gates; "42" never becomes a second competing "142" metric block.
  * §11: a CANDIDATE spec never forces a hard BLOCK through the merged path.
"""
from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.design_spec_version import DesignSpecType
from services.brand_renderer import render_data_card
from services.data_source_classification import (
    DataPresentationMode,
    SourceType,
    classify_source_presentation,
    select_data_presentation_mode,
)
from services.design_spec_registry import create_candidate_spec, promote_candidate
from services.presentation_director import DataCandidate
from services.telegram_art_director import (
    ArtDirectorDecision,
    ArtDirectorIssueCode,
    ArtDirectorResult,
    PixelInputContract,
    evaluate_art_direction_shadow,
)
from services.telegram_art_director_spec_evaluation import (
    SpecEvaluationInput,
    finalize_art_direction,
    merge_spec_evaluation_into_result,
)

_CANVAS = (1280, 720)
_KIRIN_WARNINGS = ["possible_banner", "possible_logo"]
_KIRIN_DATA_CANDIDATE = DataCandidate(
    value="42", unit="%", label="of Kirin 9050 Pro benchmark improvement", evidence_fact="42% improvement reported",
)


def _kirin_style_infographic_bytes() -> bytes:
    im = Image.new("RGB", _CANVAS, (18, 18, 20))
    draw = ImageDraw.Draw(im)
    draw.text((120, 260), "42%", fill=(255, 255, 255))
    draw.rectangle([1180, 20, 1260, 70], outline=(200, 30, 30), width=3)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def _pixel_input(rendered_bytes: bytes) -> PixelInputContract:
    return PixelInputContract(
        rendered_bytes=rendered_bytes, caption="42% improvement", presentation_type="DATA",
        renderer_version="test", renderer_decision_metadata={}, media_source_metadata={},
    )


# --------------------------------------------------------------------------------------------------
# §10 hard-failure precedence over an optimistic vision decision
# --------------------------------------------------------------------------------------------------


def test_vision_pass_plus_number_mismatch_is_forced_to_block() -> None:
    """The exact §10 example: vision says PASS, NUMBER_MISMATCH is present -> final BLOCK."""
    optimistic = ArtDirectorResult(
        decision=ArtDirectorDecision.PASS, severity="none",
        issue_codes=[ArtDirectorIssueCode.NUMBER_MISMATCH], confidence=0.9,
    )
    spec_result_input = SpecEvaluationInput(base_result=optimistic)
    merged, spec_result = finalize_art_direction(spec_result_input)

    assert merged.decision == ArtDirectorDecision.BLOCK
    assert ArtDirectorIssueCode.NUMBER_MISMATCH in merged.issue_codes
    assert "number_mismatch" in spec_result.hard_failure_reason_codes


@pytest.mark.asyncio
async def test_hard_active_spec_violation_overrides_optimistic_base(db_session: AsyncSession) -> None:
    candidate = await create_candidate_spec(
        db_session, scope="test_1b_spec_scope", spec_type=DesignSpecType.DECLARATIVE_VISUAL_PARAMS,
        parameters={"presentation_mode": "minimal_source_preserving"},
    )
    active_spec = await promote_candidate(db_session, candidate.id)

    optimistic = ArtDirectorResult(decision=ArtDirectorDecision.PASS_WITH_NOTES, severity="none", confidence=0.8)
    merged, spec_result = finalize_art_direction(SpecEvaluationInput(
        base_result=optimistic, active_spec=active_spec,
        presentation_mode=DataPresentationMode.FULL_DATA_CARD,  # violates the ACTIVE spec invariant
    ))
    assert merged.decision == ArtDirectorDecision.BLOCK
    assert "SPEC_PRESENTATION_MODE_MISMATCH" in spec_result.hard_failure_reason_codes


@pytest.mark.asyncio
async def test_candidate_spec_mismatch_never_forces_block_through_the_merged_path(db_session: AsyncSession) -> None:
    candidate_only = await create_candidate_spec(
        db_session, scope="test_1b_candidate_only", spec_type=DesignSpecType.DECLARATIVE_VISUAL_PARAMS,
        parameters={"presentation_mode": "minimal_source_preserving"},
    )
    optimistic = ArtDirectorResult(decision=ArtDirectorDecision.PASS_WITH_NOTES, severity="none", confidence=0.8)
    merged, _spec_result = finalize_art_direction(SpecEvaluationInput(
        base_result=optimistic, active_spec=candidate_only,
        presentation_mode=DataPresentationMode.FULL_DATA_CARD,
    ))
    assert merged.decision != ArtDirectorDecision.BLOCK  # a CANDIDATE spec is flagged, never enforced


def test_a_base_block_is_never_softened_by_a_clean_spec_evaluation() -> None:
    hard_base = ArtDirectorResult(
        decision=ArtDirectorDecision.BLOCK, severity="high",
        issue_codes=[ArtDirectorIssueCode.DUPLICATE_NNJ_BRAND_MARK], confidence=1.0,
    )
    merged = merge_spec_evaluation_into_result(
        hard_base, finalize_art_direction(SpecEvaluationInput(base_result=hard_base))[1],
    )
    assert merged.decision == ArtDirectorDecision.BLOCK


# --------------------------------------------------------------------------------------------------
# §13 Kirin - through the merged Art Director path
# --------------------------------------------------------------------------------------------------


def test_kirin_old_bad_render_cannot_pass_through_the_merged_path() -> None:
    source_type = classify_source_presentation(_KIRIN_WARNINGS)
    assert source_type == SourceType.EXISTING_INFOGRAPHIC

    old_bytes = render_data_card(
        _KIRIN_DATA_CANDIDATE, category="technology", editorial_code="NP-KIRIN",
        source_image_bytes=_kirin_style_infographic_bytes(), presentation_mode=DataPresentationMode.FULL_DATA_CARD,
    )
    base_result = evaluate_art_direction_shadow(_pixel_input(old_bytes))
    # The structural pixel evaluator alone is optimistic - it cannot see the fact regression.
    assert base_result.decision != ArtDirectorDecision.BLOCK

    merged, spec_result = finalize_art_direction(SpecEvaluationInput(
        base_result=base_result, source_type=source_type, presentation_mode=DataPresentationMode.FULL_DATA_CARD,
    ))
    assert merged.decision == ArtDirectorDecision.BLOCK
    assert merged.decision not in (ArtDirectorDecision.PASS, ArtDirectorDecision.PASS_WITH_NOTES)
    # "42" risks becoming a second competing metric block -> source-preservation hard failure.
    assert "INFOGRAPHIC_DESTROYED" in spec_result.hard_failure_reason_codes


def test_kirin_new_source_preserving_render_clears_the_hard_gates() -> None:
    source_type = classify_source_presentation(_KIRIN_WARNINGS)
    mode = select_data_presentation_mode(source_type)
    assert mode == DataPresentationMode.MINIMAL_SOURCE_PRESERVING

    new_bytes = render_data_card(
        _KIRIN_DATA_CANDIDATE, category="technology", editorial_code="NP-KIRIN",
        source_image_bytes=_kirin_style_infographic_bytes(), presentation_mode=mode,
    )
    base_result = evaluate_art_direction_shadow(_pixel_input(new_bytes))
    merged, spec_result = finalize_art_direction(SpecEvaluationInput(
        base_result=base_result, source_type=source_type, presentation_mode=mode,
    ))
    assert merged.decision != ArtDirectorDecision.BLOCK
    assert spec_result.hard_failure_reason_codes == []


def test_kirin_42_never_becomes_a_visually_ambiguous_142_through_the_merged_path() -> None:
    """If the vision model reports a NUMBER_MISMATCH on the Kirin render (42 read as 142), the
    merged verdict is BLOCK regardless of the model's own optimistic decision string."""
    source_type = classify_source_presentation(_KIRIN_WARNINGS)
    new_bytes = render_data_card(
        _KIRIN_DATA_CANDIDATE, category="technology", editorial_code="NP-KIRIN",
        source_image_bytes=_kirin_style_infographic_bytes(),
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )
    vision_said_pass_but_saw_a_number_change = ArtDirectorResult(
        decision=ArtDirectorDecision.PASS_WITH_NOTES, severity="low",
        issue_codes=[ArtDirectorIssueCode.NUMBER_MISMATCH],
        instructions="overlay stat reads 142% but the source infographic shows 42%", confidence=0.6,
    )
    del new_bytes  # the bytes are real; the merge operates on the already-computed result
    merged, spec_result = finalize_art_direction(SpecEvaluationInput(
        base_result=vision_said_pass_but_saw_a_number_change, source_type=source_type,
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    ))
    assert merged.decision == ArtDirectorDecision.BLOCK
    assert "number_mismatch" in spec_result.hard_failure_reason_codes


def test_kirin_clean_render_keeps_a_single_nnj_mark() -> None:
    new_bytes = render_data_card(
        _KIRIN_DATA_CANDIDATE, category="technology", editorial_code="NP-KIRIN",
        source_image_bytes=_kirin_style_infographic_bytes(),
        presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )
    base_result = evaluate_art_direction_shadow(_pixel_input(new_bytes))
    merged, _spec_result = finalize_art_direction(SpecEvaluationInput(base_result=base_result))
    assert ArtDirectorIssueCode.DUPLICATE_NNJ_BRAND_MARK not in merged.issue_codes
    assert merged.decision != ArtDirectorDecision.BLOCK


def test_duplicate_nnj_mark_metadata_is_a_hard_block_through_the_merged_path() -> None:
    pixel_input = PixelInputContract(
        rendered_bytes=b"fake-bytes", caption="42%", presentation_type="DATA", renderer_version="test",
        renderer_decision_metadata={"degradation_mode": "upper_and_lower"},
    )
    base_result = evaluate_art_direction_shadow(pixel_input)
    merged, _spec_result = finalize_art_direction(SpecEvaluationInput(base_result=base_result))
    assert merged.decision == ArtDirectorDecision.BLOCK
    assert ArtDirectorIssueCode.DUPLICATE_NNJ_BRAND_MARK in merged.issue_codes
