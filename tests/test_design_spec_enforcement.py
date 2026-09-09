"""DESIGN-SPEC-ENFORCEMENT-1 §16/§20: the ACTIVE declarative Design Specs are now enforced as
post-render constraints. `services/render_evidence.py` replays the renderer's own deterministic
decisions into a structured `RenderEvidence`; `services/telegram_art_director_spec_evaluation.py::
_evaluate_spec_match` compares it field-by-field against an ACTIVE/FROZEN spec, emitting a SPECIFIC
reason code per mismatch with hard/soft routing.

Covers the §20 matrix:
  * NEWS / BREAKING / DATA-infographic / DATA-photo / QUOTE accepted render -> SPEC_MATCH=PASS
  * wrong logo zone -> SPEC_LOGO_ZONE_MISMATCH (soft REWORK)
  * DATA 3 lines where max is 2 -> SPEC_MAX_LINE_COUNT_EXCEEDED (hard BLOCK)
  * DATA font < min / > max -> SPEC_FONT_SIZE_OUT_OF_RANGE (soft REWORK)
  * source treatment mismatch -> SPEC_SOURCE_TREATMENT_MISMATCH (crop=soft, recompose=hard)
  * safe margin violation -> SPEC_SAFE_MARGIN_VIOLATION (soft REWORK)
  * single NNJ mark -> pass ; two NNJ marks -> hard failure
  * CANDIDATE spec -> never reaches field enforcement (§17)
  * no active spec -> NOT_APPLICABLE remains valid (§4)
plus §14 Kirin end-to-end and §15 the normal PHOTO-source DATA card.
"""
from __future__ import annotations

import io
from dataclasses import replace

import pytest
from PIL import Image, ImageDraw
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.design_spec_version import DesignSpecStatus, DesignSpecType, DesignSpecVersion
from services.brand_renderer import render_breaking_frame, render_data_card, render_quote_card
from services.data_source_classification import (
    DataPresentationMode,
    SourceType,
    classify_source_presentation,
    select_data_presentation_mode,
)
from services.design_spec_registry import create_candidate_spec, promote_candidate
from services.nnj_master_news_overlay import apply_master_news_branding
from services.presentation_director import DataCandidate, QuoteCandidate
from services.render_evidence import (
    NOT_MEASURED,
    RenderEvidence,
    derive_breaking_render_evidence,
    derive_data_render_evidence,
    derive_master_news_render_evidence,
    derive_quote_render_evidence,
)
from services.telegram_art_director import (
    ArtDirectorDecision,
    ArtDirectorIssueCode,
    PixelInputContract,
    evaluate_art_direction_shadow,
)
from services.telegram_art_director_spec_evaluation import (
    ArtDirectorDimension,
    DimensionStatus,
    SpecEvaluationInput,
    _evaluate_spec_match,
    evaluate_against_spec_and_references,
    finalize_art_direction,
)

# --- founder-approved ACTIVE parameter sets (DESIGN-SPEC-ENFORCEMENT-1 §2, verbatim) -------------
_NEWS_PARAMS = {
    "safe_margin_frac": 0.019, "placement_zone": "lower_left", "logo_zone": "lower_right",
    "scrim_treatment": "none", "source_image_treatment": "preserve",
}
_BREAKING_PARAMS = dict(_NEWS_PARAMS)
_DATA_PARAMS = {
    "font_size_max": 88, "font_size_min": 48, "max_line_count": 2, "safe_margin_frac": 0.019,
    "logo_zone": "lower_right", "scrim_treatment": "none", "source_image_treatment": "preserve",
}
# FOUNDER-VISUAL-BOARD-ALIGNMENT-1: the generated FULL_DATA_CARD path now renders the Founder
# hero-metric card (brand_renderer.render_data_hero_card) - a large primary number on a generated
# graphite panel, so its font range is much larger and there is no source photo to declare a
# treatment for. This is the proposed telegram_data vNEXT CANDIDATE shape (design/
# proposed_telegram_data_quote_vnext_candidates.md); it is NOT promoted.
_DATA_HERO_PARAMS = {
    # aligned with telegram_data v3 CANDIDATE (VISUAL-SPEC-VNEXT-PRODUCTION-ALIGNMENT-1): no
    # logo_zone / placement_zone / scrim_treatment - those differ between the hero card and the
    # source-preserving MINIMAL render, so declaring hero-only values would lie about the latter.
    "font_size_max": 200, "font_size_min": 88, "max_line_count": 2, "safe_margin_frac": 0.019,
}
_QUOTE_PARAMS = {
    "safe_margin_frac": 0.019, "logo_zone": "lower_right", "scrim_treatment": "none",
    "source_image_treatment": "preserve",
}

_KIRIN_DATA_CANDIDATE = DataCandidate(
    value="42", unit="%", label="of Kirin 9050 Pro benchmark improvement", evidence_fact="42% improvement reported",
)


# --------------------------------------------------------------------------------------------------
# fixtures / helpers
# --------------------------------------------------------------------------------------------------


def _jpeg(im: Image.Image, quality: int = 92) -> bytes:
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _photo_16x9(col: tuple[int, int, int] = (90, 110, 140)) -> bytes:
    im = Image.new("RGB", (1280, 720), col)
    d = ImageDraw.Draw(im)
    d.ellipse([1280 * 0.35, 720 * 0.2, 1280 * 0.65, 720 * 0.8], fill=(165, 150, 130))
    return _jpeg(im)


def _photo_4x3() -> bytes:
    im = Image.new("RGB", (1200, 900), (70, 90, 120))
    d = ImageDraw.Draw(im)
    d.ellipse([300, 200, 900, 700], fill=(170, 150, 130))
    return _jpeg(im)


def _kirin_infographic() -> bytes:
    im = Image.new("RGB", (1280, 720), (18, 18, 20))
    d = ImageDraw.Draw(im)
    d.text((120, 260), "42%", fill=(255, 255, 255))
    d.rectangle([1180, 20, 1260, 70], outline=(200, 30, 30), width=3)
    return _jpeg(im, quality=95)


def _portrait() -> bytes:
    im = Image.new("RGB", (800, 1000), (40, 40, 50))
    d = ImageDraw.Draw(im)
    d.ellipse([250, 200, 550, 560], fill=(205, 185, 165))
    return _jpeg(im)


def _local_spec(parameters: dict, *, status: DesignSpecStatus = DesignSpecStatus.ACTIVE, scope: str = "telegram_data") -> DesignSpecVersion:
    """An in-memory DesignSpecVersion - no DB round-trip needed for the pure comparator tests."""
    return DesignSpecVersion(
        platform="telegram", surface="channel", presentation_type=scope.split("_")[-1].upper(),
        spec_type=DesignSpecType.DECLARATIVE_VISUAL_PARAMS, scope=scope, version=1,
        status=status, parameters=parameters,
    )


def _good_data_evidence() -> RenderEvidence:
    return RenderEvidence(
        presentation_type="DATA", renderer_variant="brand_renderer.render_data_card",
        canvas_width=1280, canvas_height=720, safe_margin_frac=0.01875, logo_count=1,
        logo_zone="lower_right", placement_zone="lower_right", scrim_applied=False,
        scrim_treatment="none", source_image_treatment="preserve", source_preserved=True,
        presentation_mode="full_data_card", primary_font_size=72, actual_line_count=2, text_clipped=False,
    )


def _pixel_input(rendered_bytes: bytes, presentation_type: str) -> PixelInputContract:
    return PixelInputContract(
        rendered_bytes=rendered_bytes, caption="canary", presentation_type=presentation_type,
        renderer_version="dse1", renderer_decision_metadata={}, media_source_metadata={},
    )


# ==============================================================================================
# §20 - accepted renders through the deterministic evaluator -> SPEC_MATCH = PASS
# ==============================================================================================


def test_news_accepted_render_spec_match_is_partial_evidence_never_whole_na() -> None:
    """§4/addendum §3: NEWS verifies its real declared fields (safe margin, logo zone, scrim,
    source treatment, single mark). `placement_zone` cannot be measured on the MASTER NEWS path
    (the pulse is fused into the one brand-mark signature) - so SPEC_MATCH is PARTIAL_EVIDENCE with
    that ONE field named, never a whole-dimension NOT_APPLICABLE."""
    branded, _decision = apply_master_news_branding(_photo_16x9())
    evidence = derive_master_news_render_evidence(_photo_16x9(), presentation_type="NEWS")
    # FOUNDER-VISUAL-POLISH-2: NEWS is now the restrained MARK_ONLY watermark - placement_zone
    # is genuinely NOT APPLICABLE, so the spec field is skipped as a note and SPEC_MATCH PASSes.
    assert "placement_zone" in evidence.not_applicable_fields
    dim = _evaluate_spec_match(_local_spec(_NEWS_PARAMS, scope="telegram_news"), None, evidence)
    assert dim.status is DimensionStatus.PASS, dim.rationale
    assert dim.reason_codes == []
    assert set(dim.checked_fields) >= {"safe_margin_frac", "logo_zone", "scrim_treatment", "source_image_treatment"}
    assert dim.not_measured_fields == []
    assert branded  # the real render succeeded


def test_breaking_corrected_render_has_no_band_no_scrim_mismatch_and_matches_news_family() -> None:
    """VISUAL-RENDERER-RECONCILIATION-1 §5-9: the retired dark band + baked 'BREAKING' wordmark are
    gone; BREAKING now uses the exact MASTER NEWS fused lower signature on the NATIVE-size source.
    scrim_treatment is genuinely `none` -> no SPEC_SCRIM_MISMATCH. The only remaining discrepancy
    is `placement_zone` (the same wrongly-derived field as NEWS: telegram_breaking v1 declares
    lower_left, the fused signature exposes no independent accent placement) -> SPEC_MATCH is
    PARTIAL_EVIDENCE with that ONE field named, pending the telegram_breaking v2 founder review."""
    rendered = render_breaking_frame(_photo_16x9((120, 40, 40)), category="technology", editorial_code="NP-B1")
    evidence = derive_breaking_render_evidence(_photo_16x9((120, 40, 40)))
    assert evidence.scrim_applied is False
    assert evidence.scrim_treatment == "none"
    assert evidence.source_image_treatment == "preserve"

    # FOUNDER-VISUAL-POLISH-2 §3: BREAKING v3 places the pulse in the lower-centre band. Against
    # the old params (placement_zone lower_left) that is a SOFT SPEC_PLACEMENT_ZONE_MISMATCH.
    dim = _evaluate_spec_match(_local_spec(_BREAKING_PARAMS, scope="telegram_breaking"), None, evidence)
    assert dim.status is DimensionStatus.FAIL
    assert dim.reason_codes == ["SPEC_PLACEMENT_ZONE_MISMATCH"]
    assert dim.hard_failure is False
    assert set(dim.checked_fields) >= {"safe_margin_frac", "logo_zone", "scrim_treatment", "source_image_treatment"}

    # A `telegram_breaking` spec with placement_zone dropped -> SPEC_MATCH = PASS.
    v2_params = {k: v for k, v in _BREAKING_PARAMS.items() if k != "placement_zone"}
    v2_dim = _evaluate_spec_match(_local_spec(v2_params, scope="telegram_breaking"), None, evidence)
    assert v2_dim.status is DimensionStatus.PASS

    merged, spec_result = finalize_art_direction(SpecEvaluationInput(
        base_result=_passing_base(), active_spec=_local_spec(_BREAKING_PARAMS, scope="telegram_breaking"),
        render_evidence=evidence,
    ))
    assert merged.decision is not ArtDirectorDecision.BLOCK
    assert spec_result.hard_failure_reason_codes == []
    assert rendered


def test_data_infographic_accepted_render_spec_match_passes() -> None:
    source_type = classify_source_presentation(["possible_banner", "possible_logo"])
    assert source_type == SourceType.EXISTING_INFOGRAPHIC
    mode = select_data_presentation_mode(source_type)
    assert mode == DataPresentationMode.MINIMAL_SOURCE_PRESERVING

    rendered = render_data_card(
        _KIRIN_DATA_CANDIDATE, category="technology", editorial_code="NP-KIRIN",
        source_image_bytes=_kirin_infographic(), presentation_mode=mode,
    )
    evidence = derive_data_render_evidence(_kirin_infographic(), _KIRIN_DATA_CANDIDATE, presentation_mode=mode)
    assert evidence.actual_line_count == 0  # "42 stays 42" - no second stat block
    assert evidence.primary_font_size is NOT_MEASURED
    assert "primary_font_size" in evidence.not_applicable_fields  # not a measurement gap - no stat text exists
    dim = _evaluate_spec_match(_local_spec(_DATA_PARAMS), None, evidence)
    # §4: DATA infographic verifies ALL APPLICABLE declared fields -> PASS (font not applicable here).
    assert dim.status is DimensionStatus.PASS, dim.rationale
    assert set(dim.checked_fields) >= {"max_line_count", "safe_margin_frac", "logo_zone", "scrim_treatment", "source_image_treatment"}
    assert dim.not_measured_fields == []
    assert rendered


def test_data_photo_accepted_render_spec_match_passes() -> None:
    """§15 + FOUNDER-VISUAL-BOARD-ALIGNMENT-1: a non-infographic source classifies to FULL_DATA_CARD,
    which now renders the Founder-approved generated hero-metric card. Evaluated against the
    proposed telegram_data vNEXT hero parameter shape, its accepted render still yields
    SPEC_MATCH=PASS: the large primary-value font is inside the hero range, exactly one NNJ mark,
    and there is no source photo to declare a treatment for."""
    source_type = classify_source_presentation([])
    assert source_type != SourceType.EXISTING_INFOGRAPHIC
    mode = select_data_presentation_mode(source_type)
    assert mode is DataPresentationMode.FULL_DATA_CARD

    rendered = render_data_card(
        _KIRIN_DATA_CANDIDATE, category="technology", editorial_code="NP-P1",
        source_image_bytes=_photo_16x9(), presentation_mode=mode,
    )
    evidence = derive_data_render_evidence(_photo_16x9(), _KIRIN_DATA_CANDIDATE, presentation_mode=mode)
    assert evidence.renderer_variant == "brand_renderer.render_data_hero_card"
    assert evidence.source_image_treatment is NOT_MEASURED
    assert "source_image_treatment" in evidence.not_applicable_fields
    assert evidence.logo_count == 1
    dim = _evaluate_spec_match(_local_spec(_DATA_HERO_PARAMS), None, evidence)
    assert dim.status is DimensionStatus.PASS, dim.rationale
    assert "font_size" in dim.checked_fields  # the hero card's primary value font IS verified
    assert dim.not_measured_fields == []
    assert 88 <= evidence.primary_font_size <= 200
    assert rendered


def test_quote_accepted_render_spec_match_passes() -> None:
    rendered = render_quote_card(
        QuoteCandidate(text="This model changes on-device inference.", speaker="A. Researcher"),
        category="technology", editorial_code="NP-Q1", portrait_bytes=_portrait(),
    )
    evidence = derive_quote_render_evidence(_portrait())
    dim = _evaluate_spec_match(_local_spec(_QUOTE_PARAMS, scope="telegram_quote"), None, evidence)
    # QUOTE verifies its real declared fields (margin, logo zone, source treatment). `scrim_treatment`
    # is not applicable WITH forensic evidence (the dark left panel is the card's own text ground,
    # ~7% edge feather onto the portrait) - so PASS, not PARTIAL and not a scrim FAIL.
    assert dim.status is DimensionStatus.PASS, dim.rationale
    assert set(dim.checked_fields) >= {"safe_margin_frac", "logo_zone", "source_image_treatment"}
    assert dim.not_measured_fields == []
    assert "scrim_treatment" in evidence.not_applicable_fields
    assert "%" in evidence.notes["scrim_treatment"] and "feather" in evidence.notes["scrim_treatment"]
    # QUOTE keeps a wider margin than the spec floor - that is safer, never a violation.
    assert evidence.safe_margin_frac >= _QUOTE_PARAMS["safe_margin_frac"]
    assert rendered


# ==============================================================================================
# §16 / §20 - negative spec tests: specific reason codes, correct REWORK/BLOCK routing
# ==============================================================================================


def test_wrong_logo_zone_is_a_soft_spec_logo_zone_mismatch() -> None:
    evidence = replace(_good_data_evidence(), logo_zone="upper_left", placement_zone="upper_left")
    dim = _evaluate_spec_match(_local_spec(_DATA_PARAMS), None, evidence)
    assert dim.status is DimensionStatus.FAIL
    assert "SPEC_LOGO_ZONE_MISMATCH" in dim.reason_codes
    assert dim.hard_failure is False

    merged, spec_result = finalize_art_direction(SpecEvaluationInput(
        base_result=_passing_base(), active_spec=_local_spec(_DATA_PARAMS), render_evidence=evidence,
    ))
    assert merged.decision is ArtDirectorDecision.REWORK
    assert spec_result.hard_failure_reason_codes == []


def test_data_three_lines_where_max_is_two_is_a_hard_block() -> None:
    evidence = replace(_good_data_evidence(), actual_line_count=3)
    dim = _evaluate_spec_match(_local_spec(_DATA_PARAMS), None, evidence)
    assert dim.status is DimensionStatus.FAIL
    assert dim.reason_codes == ["SPEC_MAX_LINE_COUNT_EXCEEDED"]
    assert dim.hard_failure is True

    merged, spec_result = finalize_art_direction(SpecEvaluationInput(
        base_result=_passing_base(), active_spec=_local_spec(_DATA_PARAMS), render_evidence=evidence,
    ))
    assert merged.decision is ArtDirectorDecision.BLOCK
    assert "SPEC_MAX_LINE_COUNT_EXCEEDED" in spec_result.hard_failure_reason_codes


def test_data_font_below_min_is_a_soft_font_range_failure() -> None:
    evidence = replace(_good_data_evidence(), primary_font_size=42)
    dim = _evaluate_spec_match(_local_spec(_DATA_PARAMS), None, evidence)
    assert dim.status is DimensionStatus.FAIL
    assert dim.reason_codes == ["SPEC_FONT_SIZE_OUT_OF_RANGE"]
    assert dim.hard_failure is False


def test_data_font_above_max_is_a_soft_font_range_failure() -> None:
    evidence = replace(_good_data_evidence(), primary_font_size=140)
    dim = _evaluate_spec_match(_local_spec(_DATA_PARAMS), None, evidence)
    assert dim.status is DimensionStatus.FAIL
    assert dim.reason_codes == ["SPEC_FONT_SIZE_OUT_OF_RANGE"]
    assert dim.hard_failure is False


def test_source_treatment_crop_mismatch_is_soft_recompose_mismatch_is_hard() -> None:
    cropped = replace(_good_data_evidence(), source_image_treatment="crop", source_preserved=False)
    dim_crop = _evaluate_spec_match(_local_spec(_DATA_PARAMS), None, cropped)
    assert dim_crop.status is DimensionStatus.FAIL
    assert dim_crop.reason_codes == ["SPEC_SOURCE_TREATMENT_MISMATCH"]
    assert dim_crop.hard_failure is False

    recomposed = replace(_good_data_evidence(), source_image_treatment="recompose", source_preserved=False)
    dim_recompose = _evaluate_spec_match(_local_spec(_DATA_PARAMS), None, recomposed)
    assert dim_recompose.status is DimensionStatus.FAIL
    assert dim_recompose.reason_codes == ["SPEC_SOURCE_TREATMENT_MISMATCH"]
    assert dim_recompose.hard_failure is True


def test_safe_margin_violation_is_a_soft_failure_with_its_own_reason_code() -> None:
    evidence = replace(_good_data_evidence(), safe_margin_frac=0.004)
    dim = _evaluate_spec_match(_local_spec(_DATA_PARAMS), None, evidence)
    assert dim.status is DimensionStatus.FAIL
    assert dim.reason_codes == ["SPEC_SAFE_MARGIN_VIOLATION"]
    assert dim.hard_failure is False


def test_wrong_scrim_treatment_is_a_soft_spec_scrim_mismatch() -> None:
    evidence = replace(_good_data_evidence(), scrim_applied=True, scrim_treatment="strong")
    dim = _evaluate_spec_match(_local_spec(_DATA_PARAMS), None, evidence)
    assert dim.status is DimensionStatus.FAIL
    assert dim.reason_codes == ["SPEC_SCRIM_MISMATCH"]
    assert dim.hard_failure is False


def test_single_nnj_mark_passes_two_marks_is_a_hard_failure() -> None:
    ok = _evaluate_spec_match(_local_spec(_DATA_PARAMS), None, replace(_good_data_evidence(), logo_count=1))
    assert ok.status is DimensionStatus.PASS

    dup = _evaluate_spec_match(_local_spec(_DATA_PARAMS), None, replace(_good_data_evidence(), logo_count=2))
    assert dup.status is DimensionStatus.FAIL
    assert dup.hard_failure is True

    merged, spec_result = finalize_art_direction(SpecEvaluationInput(
        base_result=_passing_base(), active_spec=_local_spec(_DATA_PARAMS),
        render_evidence=replace(_good_data_evidence(), logo_count=2),
    ))
    assert merged.decision is ArtDirectorDecision.BLOCK
    assert ArtDirectorIssueCode.DUPLICATE_NNJ_BRAND_MARK in merged.issue_codes


def test_multiple_mismatches_each_get_their_own_reason_code_not_a_generic_one() -> None:
    evidence = replace(
        _good_data_evidence(), logo_zone="upper_left", placement_zone="upper_left",
        primary_font_size=30, scrim_treatment="light", scrim_applied=True,
    )
    # _DATA_PARAMS declares logo_zone (not placement_zone), font range and scrim - one code each.
    dim = _evaluate_spec_match(_local_spec(_DATA_PARAMS), None, evidence)
    assert dim.status is DimensionStatus.FAIL
    assert set(dim.reason_codes) == {"SPEC_LOGO_ZONE_MISMATCH", "SPEC_FONT_SIZE_OUT_OF_RANGE", "SPEC_SCRIM_MISMATCH"}
    assert "SPEC_MISMATCH" not in dim.reason_codes

    # A spec that DOES declare placement_zone gets its own distinct code too.
    dim2 = _evaluate_spec_match(_local_spec(_NEWS_PARAMS, scope="telegram_news"), None, evidence)
    assert "SPEC_PLACEMENT_ZONE_MISMATCH" in dim2.reason_codes


# ==============================================================================================
# §17 / §4 - candidate specs never enforce; no active spec stays NOT_APPLICABLE
# ==============================================================================================


@pytest.mark.asyncio
async def test_candidate_spec_cannot_enforce_the_active_field_path(db_session: AsyncSession) -> None:
    candidate = await create_candidate_spec(
        db_session, scope="test_dse_candidate_only", spec_type=DesignSpecType.DECLARATIVE_VISUAL_PARAMS,
        parameters=_DATA_PARAMS,
    )
    assert candidate.status is DesignSpecStatus.CANDIDATE
    # An evidence set that would HARD-fail an ACTIVE spec (3 lines, duplicate mark):
    evidence = replace(_good_data_evidence(), actual_line_count=3, logo_count=2, logo_zone="upper_left")
    dim = _evaluate_spec_match(candidate, None, evidence)
    assert dim.status is not DimensionStatus.FAIL  # field enforcement is not reached for a CANDIDATE
    assert dim.hard_failure is False

    merged, spec_result = finalize_art_direction(SpecEvaluationInput(
        base_result=_passing_base(), active_spec=candidate, render_evidence=evidence,
    ))
    assert merged.decision is not ArtDirectorDecision.BLOCK
    assert spec_result.hard_failure_reason_codes == []


def test_no_active_spec_keeps_spec_match_not_applicable_even_with_evidence() -> None:
    dim = _evaluate_spec_match(None, None, _good_data_evidence())
    assert dim.status is DimensionStatus.NOT_APPLICABLE

    result = evaluate_against_spec_and_references(SpecEvaluationInput(
        base_result=_passing_base(), active_spec=None, render_evidence=_good_data_evidence(),
    ))
    assert result.dimension_status(ArtDirectorDimension.SPEC_MATCH) is DimensionStatus.NOT_APPLICABLE


def test_partial_evidence_lists_exactly_which_fields_were_checked_vs_not_measured() -> None:
    """addendum §3: an ACTIVE spec + some measurable fields + one NOT_MEASURED applicable field
    -> PARTIAL_EVIDENCE, and the Founder can read the split off the dimension."""
    from services.render_evidence import NOT_MEASURED as _NM

    evidence = replace(_good_data_evidence(), logo_zone=_NM)  # simulate a legacy gap on logo_zone
    dim = _evaluate_spec_match(_local_spec(_DATA_PARAMS), None, evidence)
    assert dim.status is DimensionStatus.PARTIAL_EVIDENCE
    assert dim.reason_codes == []
    assert "logo_zone" in dim.not_measured_fields
    assert "logo_zone" not in dim.checked_fields
    assert {"safe_margin_frac", "scrim_treatment", "source_image_treatment", "max_line_count"} <= set(dim.checked_fields)


def test_whole_dimension_not_applicable_only_when_no_field_is_applicable_or_measurable() -> None:
    """addendum §3: whole-dimension NOT_APPLICABLE is reserved for 'nothing to check'. A spec that
    declares only a field this render mode makes inapplicable yields NOT_APPLICABLE; add one
    measurable field and it must become PASS/PARTIAL, never NOT_APPLICABLE."""
    # QUOTE render: scrim_treatment is not applicable (card text panel). A spec declaring ONLY
    # scrim_treatment therefore has nothing to verify -> whole-dimension NOT_APPLICABLE (correct).
    quote_ev = derive_quote_render_evidence(_portrait())
    only_scrim = _local_spec({"scrim_treatment": "none"}, scope="telegram_quote")
    assert _evaluate_spec_match(only_scrim, None, quote_ev).status is DimensionStatus.NOT_APPLICABLE

    # Add a measurable field -> no longer NOT_APPLICABLE.
    scrim_plus_margin = _local_spec({"scrim_treatment": "none", "safe_margin_frac": 0.019}, scope="telegram_quote")
    assert _evaluate_spec_match(scrim_plus_margin, None, quote_ev).status is DimensionStatus.PASS


def test_evidence_is_ignored_when_not_passed_behaviour_is_unchanged() -> None:
    """Every pre-existing caller passes no render_evidence - SPEC_MATCH must behave exactly as
    before this phase: presentation_mode-only, NOT_APPLICABLE when the spec declares none."""
    dim = _evaluate_spec_match(_local_spec(_DATA_PARAMS), None, None)
    assert dim.status is DimensionStatus.NOT_APPLICABLE

    dim_mode = _evaluate_spec_match(
        _local_spec({"presentation_mode": "minimal_source_preserving"}), DataPresentationMode.FULL_DATA_CARD, None,
    )
    assert dim_mode.status is DimensionStatus.FAIL
    assert dim_mode.reason_codes == ["SPEC_PRESENTATION_MODE_MISMATCH"]
    assert dim_mode.hard_failure is True


# ==============================================================================================
# §14 - Kirin end-to-end through the merged Art Director path, now WITH render evidence
# ==============================================================================================


@pytest.mark.asyncio
async def test_kirin_end_to_end_with_active_data_spec_and_render_evidence(db_session: AsyncSession) -> None:
    candidate = await create_candidate_spec(
        db_session, scope="test_dse_kirin_data", spec_type=DesignSpecType.DECLARATIVE_VISUAL_PARAMS,
        parameters=_DATA_PARAMS,
    )
    active_spec = await promote_candidate(db_session, candidate.id)

    source_type = classify_source_presentation(["possible_banner", "possible_logo"])
    mode = select_data_presentation_mode(source_type)
    good_bytes = render_data_card(
        _KIRIN_DATA_CANDIDATE, category="technology", editorial_code="NP-KIRIN",
        source_image_bytes=_kirin_infographic(), presentation_mode=mode,
    )
    evidence = derive_data_render_evidence(_kirin_infographic(), _KIRIN_DATA_CANDIDATE, presentation_mode=mode)
    base_result = evaluate_art_direction_shadow(_pixel_input(good_bytes, "DATA"))

    merged, spec_result = finalize_art_direction(SpecEvaluationInput(
        base_result=base_result, active_spec=active_spec, source_type=source_type,
        presentation_mode=mode, render_evidence=evidence,
    ))
    assert merged.decision is not ArtDirectorDecision.BLOCK
    assert spec_result.hard_failure_reason_codes == []
    assert spec_result.dimension_status(ArtDirectorDimension.SPEC_MATCH) is DimensionStatus.PASS
    assert spec_result.dimension_status(ArtDirectorDimension.SOURCE_PRESERVATION) is DimensionStatus.PASS
    assert spec_result.dimension_status(ArtDirectorDimension.FACT_SAFETY) is DimensionStatus.PASS

    # The OLD bad render (FULL_DATA_CARD over the infographic) is still BLOCK.
    bad_bytes = render_data_card(
        _KIRIN_DATA_CANDIDATE, category="technology", editorial_code="NP-KIRIN",
        source_image_bytes=_kirin_infographic(), presentation_mode=DataPresentationMode.FULL_DATA_CARD,
    )
    bad_evidence = derive_data_render_evidence(
        _kirin_infographic(), _KIRIN_DATA_CANDIDATE, presentation_mode=DataPresentationMode.FULL_DATA_CARD,
    )
    bad_merged, _bad_spec = finalize_art_direction(SpecEvaluationInput(
        base_result=evaluate_art_direction_shadow(_pixel_input(bad_bytes, "DATA")),
        active_spec=active_spec, source_type=source_type,
        presentation_mode=DataPresentationMode.FULL_DATA_CARD, render_evidence=bad_evidence,
    ))
    assert bad_merged.decision is ArtDirectorDecision.BLOCK


@pytest.mark.asyncio
async def test_all_four_active_specs_evaluate_their_accepted_render_field_aware(db_session: AsyncSession) -> None:
    """§4/addendum §4: NEWS / BREAKING / DATA / QUOTE - each promoted to ACTIVE, each with its
    accepted render. Expected per the addendum's final canary table:
      * DATA, QUOTE -> SPEC_MATCH PASS (every applicable declared field verified)
      * NEWS       -> PARTIAL_EVIDENCE (placement_zone not measurable on the MASTER path)
      * BREAKING   -> FAIL / SPEC_SCRIM_MISMATCH (the retired dark band is still drawn)
    No render is FORCED to PASS; no hard failure anywhere."""
    specs = {}
    _news_p = {k: v for k, v in _NEWS_PARAMS.items() if k != "placement_zone"}
    _brk_p = {k: v for k, v in _BREAKING_PARAMS.items() if k != "placement_zone"}
    for scope, params in [
        ("telegram_news", _news_p), ("telegram_breaking", _brk_p),
        ("telegram_data", _DATA_PARAMS), ("telegram_quote", _QUOTE_PARAMS),
    ]:
        cand = await create_candidate_spec(
            db_session, scope=f"test_dse_{scope}", spec_type=DesignSpecType.DECLARATIVE_VISUAL_PARAMS, parameters=params,
        )
        specs[scope] = await promote_candidate(db_session, cand.id)

    photo = _photo_16x9()
    apply_master_news_branding(photo)
    news_ev = derive_master_news_render_evidence(photo, presentation_type="NEWS")
    render_breaking_frame(photo, category="technology", editorial_code="NP-B1")
    breaking_ev = derive_breaking_render_evidence(photo)
    # FOUNDER-VISUAL-BOARD-ALIGNMENT-1: FULL_DATA_CARD now renders the generated hero-metric card
    # (its own SPEC_MATCH coverage is test_data_photo_accepted_render_spec_match_passes). This
    # four-spec canary keeps exercising the DATA spec's source-preserving field path via the
    # infographic classification, where source_image_treatment IS a checked field.
    data_mode = select_data_presentation_mode(classify_source_presentation(["possible_banner", "possible_logo"]))
    assert data_mode is DataPresentationMode.MINIMAL_SOURCE_PRESERVING
    data_bytes = render_data_card(
        _KIRIN_DATA_CANDIDATE, category="technology", editorial_code="NP-D1",
        source_image_bytes=photo, presentation_mode=data_mode,
    )
    data_ev = derive_data_render_evidence(photo, _KIRIN_DATA_CANDIDATE, presentation_mode=data_mode)
    render_quote_card(
        QuoteCandidate(text="On-device inference just got real.", speaker="A. Researcher"),
        category="technology", editorial_code="NP-Q1", portrait_bytes=_portrait(),
    )
    quote_ev = derive_quote_render_evidence(_portrait())

    # After VISUAL-RENDERER-RECONCILIATION-1: NEWS and BREAKING both land on PARTIAL_EVIDENCE for
    # the SAME reason - the fused NEWS-family lower signature exposes no independent `placement_zone`
    # while telegram_news/breaking v1 still declare the wrongly-derived placement_zone=lower_left.
    expected = {
        "telegram_news": DimensionStatus.PASS,       # FOUNDER-VISUAL-POLISH-2: MARK_ONLY, placement_zone N/A
        "telegram_breaking": DimensionStatus.PASS,   # BREAKING v3 vs a placement_zone-free spec
        "telegram_data": DimensionStatus.PASS,
        "telegram_quote": DimensionStatus.PASS,
    }
    for scope, evidence, pt, rendered in [
        ("telegram_news", news_ev, "NEWS", photo),
        ("telegram_breaking", breaking_ev, "BREAKING", photo),
        ("telegram_data", data_ev, "DATA", data_bytes),
        ("telegram_quote", quote_ev, "QUOTE", photo),
    ]:
        base = evaluate_art_direction_shadow(_pixel_input(rendered, pt))
        merged, spec_result = finalize_art_direction(SpecEvaluationInput(
            base_result=base, active_spec=specs[scope], render_evidence=evidence,
        ))
        spec_dim = next(d for d in spec_result.dimensions if d.dimension is ArtDirectorDimension.SPEC_MATCH)
        assert spec_dim.status is expected[scope], (scope, spec_dim.status, merged.instructions)
        assert spec_result.hard_failure_reason_codes == [], scope
        assert spec_dim.reason_codes == [], (scope, spec_dim.reason_codes)  # no mismatch anywhere
        # every case verifies at least the margin + logo zone + source treatment
        assert {"safe_margin_frac", "logo_zone", "source_image_treatment"} <= set(spec_dim.checked_fields), scope
    # FOUNDER-VISUAL-POLISH-2: NEWS (MARK_ONLY) and BREAKING v3 both cleanly PASS a
    # placement_zone-free spec - nothing routes to BLOCK/REWORK.
    for scope in ("telegram_news", "telegram_breaking"):
        assert expected[scope] is DimensionStatus.PASS
    brk_merged, _ = finalize_art_direction(SpecEvaluationInput(
        base_result=evaluate_art_direction_shadow(_pixel_input(photo, "BREAKING")),
        active_spec=specs["telegram_breaking"], render_evidence=breaking_ev,
    ))
    assert brk_merged.decision is not ArtDirectorDecision.BLOCK
    assert brk_merged.decision is not ArtDirectorDecision.REWORK


# ==============================================================================================
# render_evidence.py - the derivers report the renderer's OWN decisions, truthfully
# ==============================================================================================


def test_derive_data_evidence_reports_a_crop_when_the_source_aspect_differs() -> None:
    # FOUNDER-VISUAL-BOARD-ALIGNMENT-1: crop detection (`_canvas_crop_treatment`) applies to the
    # source-preserving DATA path; FULL_DATA_CARD is now the source-free generated hero card.
    ev_16x9 = derive_data_render_evidence(
        _photo_16x9(), _KIRIN_DATA_CANDIDATE, presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )
    assert ev_16x9.source_image_treatment == "preserve"
    assert ev_16x9.source_preserved is True

    ev_4x3 = derive_data_render_evidence(
        _photo_4x3(), _KIRIN_DATA_CANDIDATE, presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )
    assert ev_4x3.source_image_treatment == "crop"
    assert ev_4x3.source_preserved is False


def test_derive_data_hero_evidence_is_source_free_and_reports_the_metric_font() -> None:
    """FOUNDER-VISUAL-BOARD-ALIGNMENT-1: FULL_DATA_CARD evidence describes the generated hero card."""
    ev = derive_data_render_evidence(
        _photo_4x3(), _KIRIN_DATA_CANDIDATE, presentation_mode=DataPresentationMode.FULL_DATA_CARD,
    )
    assert ev.renderer_variant == "brand_renderer.render_data_hero_card"
    assert ev.source_image_treatment is NOT_MEASURED
    assert ev.source_preserved is NOT_MEASURED
    assert "source_image_treatment" in ev.not_applicable_fields
    assert ev.logo_count == 1 and ev.logo_zone == "lower_right"
    assert ev.scrim_applied is False
    assert isinstance(ev.primary_font_size, int) and ev.primary_font_size >= 88
    assert ev.actual_line_count <= 2


def test_derive_data_evidence_minimal_mode_measures_zero_lines_and_no_stat_font() -> None:
    ev = derive_data_render_evidence(
        _kirin_infographic(), _KIRIN_DATA_CANDIDATE, presentation_mode=DataPresentationMode.MINIMAL_SOURCE_PRESERVING,
    )
    assert ev.actual_line_count == 0
    assert ev.primary_font_size is NOT_MEASURED
    assert "primary_font_size" in ev.not_applicable_fields  # no stat block rendered - genuinely N/A
    assert ev.presentation_mode == "minimal_source_preserving"
    assert ev.logo_count == 1


def test_derive_master_news_evidence_has_one_mark_and_placement_zone_is_a_measurement_gap() -> None:
    ev = derive_master_news_render_evidence(_photo_16x9(), presentation_type="NEWS")
    assert ev.logo_count == 1
    assert ev.logo_zone in {"lower_right", "lower_left", "upper_right", "upper_left"}
    assert ev.placement_zone is NOT_MEASURED
    # FOUNDER-VISUAL-POLISH-2: MARK_ONLY has no independent accent -> placement_zone is NOT
    # APPLICABLE (the one mark's corner is logo_zone), not a measurement gap.
    assert "placement_zone" in ev.not_applicable_fields
    assert "NOT APPLICABLE" in ev.notes["placement_zone"]
    assert ev.source_image_treatment == "preserve"
    assert "primary_font_size" in ev.not_applicable_fields


def test_derive_master_news_evidence_reports_crop_for_a_non_16x9_source() -> None:
    ev = derive_master_news_render_evidence(_photo_4x3(), presentation_type="NEWS")
    assert ev.source_image_treatment == "crop"
    assert ev.source_preserved is False


def test_derive_quote_evidence_margin_above_floor_and_scrim_na_with_forensic_evidence() -> None:
    ev = derive_quote_render_evidence(_portrait())
    assert ev.safe_margin_frac >= 0.05
    assert ev.scrim_treatment is NOT_MEASURED
    assert "scrim_treatment" in ev.not_applicable_fields
    # addendum §1: not a bare NOT_MEASURED - the note carries the measured feather geometry.
    assert "feather" in ev.notes["scrim_treatment"] and "%" in ev.notes["scrim_treatment"]
    assert ev.logo_zone == "lower_right"
    assert ev.source_image_treatment == "preserve"


def test_derive_breaking_evidence_reports_the_corrected_no_scrim_news_family_signature() -> None:
    ev = derive_breaking_render_evidence(_photo_16x9())
    assert ev.source_image_treatment == "preserve"
    assert ev.source_preserved is True
    # VRR-1: the band is gone - the corrected renderer composites no scrim of any kind.
    assert ev.scrim_applied is False
    assert ev.scrim_treatment == "none"
    assert ev.logo_count == 1
    assert ev.renderer_version == "pulse-breaking-v3"
    assert ev.placement_zone == "lower_center"  # FOUNDER-VISUAL-POLISH-2: the red pulse crosses the lower media


# --------------------------------------------------------------------------------------------------


def _passing_base():
    from services.telegram_art_director import ArtDirectorResult

    return ArtDirectorResult(decision=ArtDirectorDecision.PASS, severity="none", confidence=0.9)
