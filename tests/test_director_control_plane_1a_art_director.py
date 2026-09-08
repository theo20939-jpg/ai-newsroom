"""DIRECTOR-CONTROL-PLANE-1A §20/§21/§36/§38: Gap B - the full Kirin 9050 Pro Director-path
regression through the NEW services/telegram_art_director_spec_evaluation.py, plus the required
proof that the SAME final image with a DIFFERENT applicable spec/reference context produces a
DIFFERENT SPEC_MATCH/REFERENCE_MATCH result (references/specs are real inputs, not stored
metadata)."""
from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.design_reference_asset import DesignReferenceRole
from database.models.design_spec_version import DesignSpecType
from services.brand_renderer import render_data_card
from services.data_source_classification import (
    DataPresentationMode,
    SourceType,
    classify_source_presentation,
    select_data_presentation_mode,
)
from services.design_reference_registry import upsert_asset
from services.design_spec_registry import create_candidate_spec, promote_candidate
from services.presentation_director import DataCandidate
from services.telegram_art_director import ArtDirectorDecision, PixelInputContract, evaluate_art_direction_shadow
from services.telegram_art_director_spec_evaluation import (
    ArtDirectorDimension,
    DimensionStatus,
    SpecEvaluationInput,
    evaluate_against_spec_and_references,
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


class TestKirinDirectorPathRegression:
    """§20: full end-to-end Director-path proof - the OLD FULL_DATA_CARD render (against an
    EXISTING_INFOGRAPHIC source) must never receive an overall PASS, and the NEW
    MINIMAL_SOURCE_PRESERVING render must PASS on FACT_SAFETY/SOURCE_PRESERVATION."""

    def test_old_full_data_card_render_over_infographic_source_is_never_pass(self) -> None:
        source_type = classify_source_presentation(_KIRIN_WARNINGS)
        assert source_type == SourceType.EXISTING_INFOGRAPHIC

        old_bytes = render_data_card(
            _KIRIN_DATA_CANDIDATE, category="technology", editorial_code="NP-KIRIN",
            source_image_bytes=_kirin_style_infographic_bytes(), presentation_mode=DataPresentationMode.FULL_DATA_CARD,
        )
        base_result = evaluate_art_direction_shadow(_pixel_input(old_bytes))

        result = evaluate_against_spec_and_references(SpecEvaluationInput(
            base_result=base_result, source_type=source_type, presentation_mode=DataPresentationMode.FULL_DATA_CARD,
        ))

        assert result.dimension_status(ArtDirectorDimension.SOURCE_PRESERVATION) is DimensionStatus.FAIL
        assert result.overall_decision != ArtDirectorDecision.PASS
        assert result.overall_decision != ArtDirectorDecision.PASS_WITH_NOTES
        assert result.overall_decision == ArtDirectorDecision.BLOCK

    def test_new_minimal_source_preserving_render_passes_fact_safety_and_source_preservation(self) -> None:
        source_type = classify_source_presentation(_KIRIN_WARNINGS)
        recommended_mode = select_data_presentation_mode(source_type)
        assert recommended_mode == DataPresentationMode.MINIMAL_SOURCE_PRESERVING

        new_bytes = render_data_card(
            _KIRIN_DATA_CANDIDATE, category="technology", editorial_code="NP-KIRIN",
            source_image_bytes=_kirin_style_infographic_bytes(), presentation_mode=recommended_mode,
        )
        base_result = evaluate_art_direction_shadow(_pixel_input(new_bytes))

        result = evaluate_against_spec_and_references(SpecEvaluationInput(
            base_result=base_result, source_type=source_type, presentation_mode=recommended_mode,
        ))

        assert result.dimension_status(ArtDirectorDimension.FACT_SAFETY) is DimensionStatus.PASS
        assert result.dimension_status(ArtDirectorDimension.SOURCE_PRESERVATION) is DimensionStatus.PASS
        assert result.overall_decision != ArtDirectorDecision.BLOCK

    @pytest.mark.asyncio
    async def test_spec_match_is_consistent_with_the_active_spec(self, db_session: AsyncSession) -> None:
        """§20's own "SPEC_MATCH consistent with the active spec" requirement."""
        candidate = await create_candidate_spec(
            db_session, scope="test_kirin_data_scope", spec_type=DesignSpecType.DECLARATIVE_VISUAL_PARAMS,
            parameters={"presentation_mode": "minimal_source_preserving"},
        )
        active_spec = await promote_candidate(db_session, candidate.id)

        source_type = classify_source_presentation(_KIRIN_WARNINGS)
        source_bytes = _kirin_style_infographic_bytes()

        old_bytes = render_data_card(
            _KIRIN_DATA_CANDIDATE, category="technology", editorial_code="NP-KIRIN",
            source_image_bytes=source_bytes, presentation_mode=DataPresentationMode.FULL_DATA_CARD,
        )
        old_result = evaluate_against_spec_and_references(SpecEvaluationInput(
            base_result=evaluate_art_direction_shadow(_pixel_input(old_bytes)), active_spec=active_spec,
            source_type=source_type, presentation_mode=DataPresentationMode.FULL_DATA_CARD,
        ))
        assert old_result.dimension_status(ArtDirectorDimension.SPEC_MATCH) is DimensionStatus.FAIL
        assert old_result.overall_decision == ArtDirectorDecision.BLOCK

        new_bytes = render_data_card(
            _KIRIN_DATA_CANDIDATE, category="technology", editorial_code="NP-KIRIN",
            source_image_bytes=source_bytes, presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
        )
        new_result = evaluate_against_spec_and_references(SpecEvaluationInput(
            base_result=evaluate_art_direction_shadow(_pixel_input(new_bytes)), active_spec=active_spec,
            source_type=source_type, presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
        ))
        assert new_result.dimension_status(ArtDirectorDimension.SPEC_MATCH) is DimensionStatus.PASS

    @pytest.mark.asyncio
    async def test_candidate_spec_mismatch_is_flagged_but_never_enforced_as_hard(self, db_session: AsyncSession) -> None:
        """A CANDIDATE spec was never promoted (services/design_spec_registry.py's own module
        docstring: promote_candidate() is never called automatically) - it must never gain
        enforcement power merely by being passed into evaluation. Only an ACTIVE/FROZEN spec (what
        get_active_or_frozen_spec() actually returns as authoritative) can trigger a hard BLOCK."""
        candidate_only = await create_candidate_spec(
            db_session, scope="test_candidate_only_scope", spec_type=DesignSpecType.DECLARATIVE_VISUAL_PARAMS,
            parameters={"presentation_mode": "minimal_source_preserving"},
        )
        rendered_bytes = render_data_card(
            _KIRIN_DATA_CANDIDATE, category="technology", editorial_code="NP-KIRIN",
            source_image_bytes=_kirin_style_infographic_bytes(), presentation_mode=DataPresentationMode.FULL_DATA_CARD,
        )
        base_result = evaluate_art_direction_shadow(_pixel_input(rendered_bytes))
        result = evaluate_against_spec_and_references(SpecEvaluationInput(
            base_result=base_result, active_spec=candidate_only, presentation_mode=DataPresentationMode.FULL_DATA_CARD,
        ))
        assert result.dimension_status(ArtDirectorDimension.SPEC_MATCH) is DimensionStatus.FAIL
        assert result.overall_decision != ArtDirectorDecision.BLOCK


class TestSameImageDifferentContextProducesDifferentResult:
    """§21's own required proof: the SAME final image, with a DIFFERENT applicable spec/reference
    context, must produce a DIFFERENT SPEC_MATCH/REFERENCE_MATCH result."""

    @pytest.mark.asyncio
    async def test_same_image_different_active_spec_changes_spec_match(self, db_session: AsyncSession) -> None:
        rendered_bytes = render_data_card(
            _KIRIN_DATA_CANDIDATE, category="technology", editorial_code="NP-KIRIN",
            source_image_bytes=_kirin_style_infographic_bytes(), presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
        )
        base_result = evaluate_art_direction_shadow(_pixel_input(rendered_bytes))

        candidate = await create_candidate_spec(
            db_session, scope="test_same_image_scope", spec_type=DesignSpecType.DECLARATIVE_VISUAL_PARAMS,
            parameters={"presentation_mode": "full_data_card"},
        )
        conflicting_spec = await promote_candidate(db_session, candidate.id)

        result_no_spec = evaluate_against_spec_and_references(SpecEvaluationInput(
            base_result=base_result, active_spec=None, presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
        ))
        result_conflicting_spec = evaluate_against_spec_and_references(SpecEvaluationInput(
            base_result=base_result, active_spec=conflicting_spec, presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
        ))

        assert result_no_spec.dimension_status(ArtDirectorDimension.SPEC_MATCH) is DimensionStatus.NOT_APPLICABLE
        assert result_conflicting_spec.dimension_status(ArtDirectorDimension.SPEC_MATCH) is DimensionStatus.FAIL
        assert result_no_spec.overall_decision != result_conflicting_spec.overall_decision

    @pytest.mark.asyncio
    async def test_same_image_different_reference_set_changes_reference_match(self, db_session: AsyncSession) -> None:
        rendered_bytes = render_data_card(
            _KIRIN_DATA_CANDIDATE, category="technology", editorial_code="NP-KIRIN",
            source_image_bytes=_kirin_style_infographic_bytes(), presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
        )
        base_result = evaluate_art_direction_shadow(_pixel_input(rendered_bytes))

        result_no_references = evaluate_against_spec_and_references(SpecEvaluationInput(base_result=base_result))
        assert result_no_references.dimension_status(ArtDirectorDimension.REFERENCE_MATCH) is DimensionStatus.NOT_APPLICABLE

        approved = await upsert_asset(
            db_session, asset_path="assets/brand/newsroom_visuals/v1/references/test_same_image_approved.png",
            reference_role=DesignReferenceRole.APPROVED_REFERENCE, platform="telegram", presentation_type="DATA",
        )
        result_with_approved = evaluate_against_spec_and_references(SpecEvaluationInput(
            base_result=base_result, approved_references=[approved],
        ))
        assert result_with_approved.dimension_status(ArtDirectorDimension.REFERENCE_MATCH) is DimensionStatus.PASS
        assert result_no_references.dimension_status(ArtDirectorDimension.REFERENCE_MATCH) != result_with_approved.dimension_status(ArtDirectorDimension.REFERENCE_MATCH)

        rejected = await upsert_asset(
            db_session, asset_path="assets/brand/newsroom_visuals/v1/references/test_same_image_rejected.png",
            reference_role=DesignReferenceRole.REJECTED_REFERENCE, platform="telegram", presentation_type="DATA",
            notes="rejected because minimal_source_preserving crops too aggressively on portrait sources",
        )
        result_with_rejected = evaluate_against_spec_and_references(SpecEvaluationInput(
            base_result=base_result, approved_references=[approved], rejected_references=[rejected],
            presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
        ))
        assert result_with_rejected.dimension_status(ArtDirectorDimension.REFERENCE_MATCH) is DimensionStatus.FAIL
        assert result_with_rejected.dimension_status(ArtDirectorDimension.REFERENCE_MATCH) != result_with_approved.dimension_status(ArtDirectorDimension.REFERENCE_MATCH)


class TestNoClippingAndOneNnjMark:
    """§38's own required "no clipping, one NNJ mark" proof at the structured-dimension level."""

    def test_clean_render_passes_typography_and_branding(self) -> None:
        rendered_bytes = render_data_card(
            _KIRIN_DATA_CANDIDATE, category="technology", editorial_code="NP-KIRIN",
            source_image_bytes=_kirin_style_infographic_bytes(), presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
        )
        base_result = evaluate_art_direction_shadow(_pixel_input(rendered_bytes))
        result = evaluate_against_spec_and_references(SpecEvaluationInput(base_result=base_result))
        assert result.dimension_status(ArtDirectorDimension.TYPOGRAPHY) is DimensionStatus.PASS
        assert result.dimension_status(ArtDirectorDimension.BRANDING) is DimensionStatus.PASS

    def test_duplicate_nnj_mark_is_a_hard_branding_failure(self) -> None:
        pixel_input = PixelInputContract(
            rendered_bytes=b"fake-bytes", caption="42%", presentation_type="DATA", renderer_version="test",
            renderer_decision_metadata={"degradation_mode": "upper_and_lower"},
        )
        base_result = evaluate_art_direction_shadow(pixel_input)
        result = evaluate_against_spec_and_references(SpecEvaluationInput(base_result=base_result))
        assert result.dimension_status(ArtDirectorDimension.BRANDING) is DimensionStatus.FAIL
        assert result.overall_decision == ArtDirectorDecision.BLOCK
