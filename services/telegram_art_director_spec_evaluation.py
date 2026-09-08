"""DIRECTOR-CONTROL-PLANE-1A §15-21: activates the Design Spec Registry + Design Reference
Registry into REAL Art Director evaluation - closing Gap B (the largest remaining gap from
DIRECTOR-CONTROL-PLANE-1's own honest PARTIAL verdict: these registries existed as storage, never
consumed by any evaluation).

Architecture note: this module does NOT re-run pixel analysis - `services/telegram_art_director.py::
evaluate_art_direction_shadow()` (deterministic structural checks) and `services/telegram_art_
director_vision.py::evaluate_art_direction_vision()` (real vision call) remain the ONE place actual
pixels are inspected, exactly as before this phase. This module takes that already-computed
`ArtDirectorResult` PLUS the real Design Spec/Reference/source-classification context and produces
the full §18 structured multi-dimension verdict - never a second, competing pixel evaluator.

§18's required dimensions: FACT_SAFETY, SPEC_MATCH, REFERENCE_MATCH, SOURCE_PRESERVATION,
TYPOGRAPHY, LAYOUT, BRANDING, VISUAL_QUALITY - every dimension gets an explicit PASS/FAIL/
NOT_APPLICABLE status, reason_codes, and a plain-text rationale (never silently omitted).

§19's hard-failure rules (a render can never receive an overall PASS/PASS_WITH_NOTES when any of
these fire, regardless of what any other dimension or the underlying vision model's own `decision`
field says):
  1. FACT_SAFETY: a key metric changed or became ambiguous (ArtDirectorIssueCode.NUMBER_MISMATCH,
     or a FULL_DATA_CARD render composited over an EXISTING_INFOGRAPHIC source - the exact Kirin
     9050 Pro "42% -> 142%" regression services/data_source_classification.py's own module
     docstring describes).
  2. TYPOGRAPHY: text clipping that changes meaning (ArtDirectorIssueCode.TEXT_CLIPPING).
  3. BRANDING: a duplicate NNJ mark, structurally detected OR model-drawn
     (ArtDirectorIssueCode.DUPLICATE_NNJ_BRAND_MARK) - this is also this module's own honest
     coverage of §19's "fake branding" trigger: a generation model drawing a second/fake NNJ mark
     into the scene IS a duplicate-mark case (services/visual_root_cause.py already distinguishes
     the renderer-side vs model-drawn origin) - no second, competing "fake branding" code exists in
     services/telegram_art_director.py's own taxonomy, and inventing one here would fork that
     taxonomy rather than reuse it.
  4. SOURCE_PRESERVATION: an EXISTING_INFOGRAPHIC source rendered with anything other than
     MINIMAL_SOURCE_PRESERVING/NO_OVERLAY_SAFETY (the infographic's own already-printed information
     was destroyed/risked being overpainted).
  5. SPEC_MATCH: an ACTIVE (not merely CANDIDATE) Design Spec's own `presentation_mode` parameter
     was not honored - the one Design Spec field this phase treats as a hard invariant, since it
     governs the exact same source-preservation safety property as #4, never a soft preference."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field

from database.models.design_reference_asset import DesignReferenceAsset
from database.models.design_spec_version import DesignSpecStatus, DesignSpecVersion
from services.data_source_classification import DataPresentationMode, SourceType
from services.telegram_art_director import ArtDirectorDecision, ArtDirectorIssueCode, ArtDirectorResult

_SOURCE_PRESERVING_MODES = frozenset({
    DataPresentationMode.MINIMAL_SOURCE_PRESERVING.value, DataPresentationMode.NO_OVERLAY_SAFETY.value,
})


class ArtDirectorDimension(str, enum.Enum):
    FACT_SAFETY = "fact_safety"
    SPEC_MATCH = "spec_match"
    REFERENCE_MATCH = "reference_match"
    SOURCE_PRESERVATION = "source_preservation"
    TYPOGRAPHY = "typography"
    LAYOUT = "layout"
    BRANDING = "branding"
    VISUAL_QUALITY = "visual_quality"


class DimensionStatus(str, enum.Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class DimensionEvaluation:
    dimension: ArtDirectorDimension
    status: DimensionStatus
    reason_codes: list[str] = field(default_factory=list)
    rationale: str = ""
    # §19: whether THIS specific failure is one of the hard-failure triggers (never true when
    # status is not FAIL). Hardness is a property of the specific issue, not the whole dimension -
    # e.g. TYPOGRAPHY fails hard on TEXT_CLIPPING but only soft (REWORK-worthy) on HEADLINE_OVERFLOW/
    # TEXT_OVERLAP; SPEC_MATCH fails hard only when the mismatched spec is ACTIVE/FROZEN (a real,
    # in-force invariant), never for a CANDIDATE spec that was never promoted.
    hard_failure: bool = False


@dataclass(frozen=True)
class SpecEvaluationInput:
    """Every field here is either already computed by the existing pixel evaluators
    (`base_result`) or a real, already-persisted row this phase's registries provide - never a
    fabricated value. `active_spec`/`approved_references`/`rejected_references` are read-only
    inputs; nothing in this module ever calls `promote_candidate()`/`upsert_asset()` (spec §22's
    own "no auto-promotion" requirement - this evaluator has no write path at all)."""

    base_result: ArtDirectorResult
    active_spec: DesignSpecVersion | None = None
    approved_references: list[DesignReferenceAsset] = field(default_factory=list)
    rejected_references: list[DesignReferenceAsset] = field(default_factory=list)
    source_type: SourceType | None = None
    presentation_mode: DataPresentationMode | None = None


@dataclass(frozen=True)
class SpecEvaluationResult:
    overall_decision: ArtDirectorDecision
    dimensions: list[DimensionEvaluation]
    hard_failure_reason_codes: list[str] = field(default_factory=list)

    def dimension_status(self, dimension: ArtDirectorDimension) -> DimensionStatus:
        for evaluation in self.dimensions:
            if evaluation.dimension is dimension:
                return evaluation.status
        return DimensionStatus.NOT_APPLICABLE


def _evaluate_fact_safety(base_result: ArtDirectorResult) -> DimensionEvaluation:
    if ArtDirectorIssueCode.NUMBER_MISMATCH in base_result.issue_codes:
        return DimensionEvaluation(
            dimension=ArtDirectorDimension.FACT_SAFETY, status=DimensionStatus.FAIL,
            reason_codes=[ArtDirectorIssueCode.NUMBER_MISMATCH.value], hard_failure=True,
            rationale="A key factual metric was changed or made ambiguous by this render.",
        )
    return DimensionEvaluation(
        dimension=ArtDirectorDimension.FACT_SAFETY, status=DimensionStatus.PASS,
        rationale="No factual-metric-changing issue detected in the underlying pixel evaluation.",
    )


def _evaluate_source_preservation(
    source_type: SourceType | None, presentation_mode: DataPresentationMode | None,
) -> DimensionEvaluation:
    if source_type is None:
        return DimensionEvaluation(
            dimension=ArtDirectorDimension.SOURCE_PRESERVATION, status=DimensionStatus.NOT_APPLICABLE,
            rationale="No source classification supplied - not a source-derived render.",
        )
    if source_type != SourceType.EXISTING_INFOGRAPHIC:
        return DimensionEvaluation(
            dimension=ArtDirectorDimension.SOURCE_PRESERVATION, status=DimensionStatus.NOT_APPLICABLE,
            rationale=f"source_type={source_type.value} is not a pre-made infographic - no source information to preserve.",
        )
    mode_value = presentation_mode.value if presentation_mode is not None else None
    if mode_value in _SOURCE_PRESERVING_MODES:
        return DimensionEvaluation(
            dimension=ArtDirectorDimension.SOURCE_PRESERVATION, status=DimensionStatus.PASS,
            rationale=f"presentation_mode={mode_value} preserves the source infographic's own already-printed information.",
        )
    return DimensionEvaluation(
        dimension=ArtDirectorDimension.SOURCE_PRESERVATION, status=DimensionStatus.FAIL,
        reason_codes=["INFOGRAPHIC_DESTROYED"], hard_failure=True,
        rationale=(
            f"source_type=existing_infographic rendered with presentation_mode="
            f"{mode_value or 'unknown'} - a second competing stat block risks overpainting or "
            "duplicating the source's own printed metric (the Kirin 9050 Pro regression pattern)."
        ),
    )


def _evaluate_spec_match(
    active_spec: DesignSpecVersion | None, presentation_mode: DataPresentationMode | None,
) -> DimensionEvaluation:
    if active_spec is None or not active_spec.parameters:
        return DimensionEvaluation(
            dimension=ArtDirectorDimension.SPEC_MATCH, status=DimensionStatus.NOT_APPLICABLE,
            rationale="No active Design Spec with declared parameters for this scope.",
        )
    spec_mode = active_spec.parameters.get("presentation_mode")
    if spec_mode is None:
        return DimensionEvaluation(
            dimension=ArtDirectorDimension.SPEC_MATCH, status=DimensionStatus.NOT_APPLICABLE,
            rationale="Active Design Spec does not declare a presentation_mode invariant.",
        )
    actual_mode = presentation_mode.value if presentation_mode is not None else None
    if actual_mode == spec_mode:
        return DimensionEvaluation(
            dimension=ArtDirectorDimension.SPEC_MATCH, status=DimensionStatus.PASS,
            rationale=f"Render honors the active spec's own presentation_mode={spec_mode}.",
        )
    # §19's own "hard spec invariant" trigger: a mismatch only forces a hard failure when the spec
    # is actually IN FORCE (ACTIVE, or FROZEN when no ACTIVE spec exists for this scope - both are
    # what services/design_spec_registry.py::get_active_or_frozen_spec() returns as authoritative).
    # A CANDIDATE spec was never promoted (services/design_spec_registry.py's own module docstring:
    # promote_candidate() is never called automatically) and must never gain enforcement power
    # merely by being passed in here.
    hard = active_spec.status in (DesignSpecStatus.ACTIVE, DesignSpecStatus.FROZEN)
    rationale = (
        f"Design Spec (scope={active_spec.scope}, version={active_spec.version}, status={active_spec.status.value}) "
        f"requires presentation_mode={spec_mode!r} but this render used {actual_mode!r}."
        + (" This is a hard, in-force spec invariant." if hard else " Spec is not yet in force (CANDIDATE) - flagged, not enforced.")
    )
    return DimensionEvaluation(
        dimension=ArtDirectorDimension.SPEC_MATCH, status=DimensionStatus.FAIL,
        reason_codes=["SPEC_PRESENTATION_MODE_MISMATCH"], hard_failure=hard, rationale=rationale,
    )


def _evaluate_reference_match(
    approved_references: list[DesignReferenceAsset], rejected_references: list[DesignReferenceAsset],
    presentation_mode: DataPresentationMode | None,
) -> DimensionEvaluation:
    """Structural, never a pixel/embedding comparison (no such capability exists in this codebase -
    spec §21's own proof requirement is that a DIFFERENT reference/spec CONTEXT changes this
    dimension's result, not that this module performs real computer-vision matching). A rejected
    reference whose own notes name the SAME presentation_mode this render used is treated as "this
    render repeats a pattern already rejected before" - the one honest structural signal available;
    absent that, the presence of any approved reference for this platform/presentation_type scope
    is treated as "a design precedent exists to match against"."""
    actual_mode = presentation_mode.value if presentation_mode is not None else None
    if actual_mode is not None:
        for rejected in rejected_references:
            if rejected.notes and actual_mode in rejected.notes:
                return DimensionEvaluation(
                    dimension=ArtDirectorDimension.REFERENCE_MATCH, status=DimensionStatus.FAIL,
                    reason_codes=["MATCHES_REJECTED_REFERENCE"],
                    rationale=f"This render's own presentation_mode={actual_mode} matches a previously REJECTED reference ({rejected.asset_path}).",
                )
    if approved_references:
        return DimensionEvaluation(
            dimension=ArtDirectorDimension.REFERENCE_MATCH, status=DimensionStatus.PASS,
            rationale=f"{len(approved_references)} approved reference(s) exist for this scope; no rejected pattern matched.",
        )
    return DimensionEvaluation(
        dimension=ArtDirectorDimension.REFERENCE_MATCH, status=DimensionStatus.NOT_APPLICABLE,
        rationale="No approved reference exists for this platform/presentation_type scope to match against.",
    )


def _evaluate_typography(base_result: ArtDirectorResult) -> DimensionEvaluation:
    # §19: TEXT_CLIPPING specifically ("text clipping that changes meaning") is a hard failure;
    # HEADLINE_OVERFLOW/TEXT_OVERLAP are real defects worth a REWORK but not an automatic BLOCK -
    # neither necessarily changes what the text MEANS, only how it looks.
    hard_codes = {code for code in base_result.issue_codes if code == ArtDirectorIssueCode.TEXT_CLIPPING}
    soft_codes = {
        code for code in base_result.issue_codes
        if code in (ArtDirectorIssueCode.HEADLINE_OVERFLOW, ArtDirectorIssueCode.TEXT_OVERLAP)
    }
    if hard_codes or soft_codes:
        return DimensionEvaluation(
            dimension=ArtDirectorDimension.TYPOGRAPHY, status=DimensionStatus.FAIL,
            reason_codes=[c.value for c in (hard_codes | soft_codes)], hard_failure=bool(hard_codes),
            rationale="Text clipping/overflow/overlap detected in the underlying pixel evaluation.",
        )
    return DimensionEvaluation(dimension=ArtDirectorDimension.TYPOGRAPHY, status=DimensionStatus.PASS)


def _evaluate_layout(base_result: ArtDirectorResult) -> DimensionEvaluation:
    layout_codes = {
        code for code in base_result.issue_codes
        if code in (ArtDirectorIssueCode.SAFE_AREA_VIOLATION, ArtDirectorIssueCode.SUBJECT_CROP_BAD, ArtDirectorIssueCode.VISUAL_TOO_BUSY)
    }
    if layout_codes:
        return DimensionEvaluation(
            dimension=ArtDirectorDimension.LAYOUT, status=DimensionStatus.FAIL,
            reason_codes=[c.value for c in layout_codes],
            rationale="A layout/composition issue was detected in the underlying pixel evaluation.",
        )
    return DimensionEvaluation(dimension=ArtDirectorDimension.LAYOUT, status=DimensionStatus.PASS)


def _evaluate_branding(base_result: ArtDirectorResult) -> DimensionEvaluation:
    # §19: DUPLICATE_NNJ_BRAND_MARK (structurally detected OR model-drawn "fake branding", per this
    # module's own docstring) is a hard failure; every other branding issue is real but soft.
    hard_codes = {code for code in base_result.issue_codes if code == ArtDirectorIssueCode.DUPLICATE_NNJ_BRAND_MARK}
    soft_codes = {
        code for code in base_result.issue_codes
        if code in (
            ArtDirectorIssueCode.LOW_LOGO_CONTRAST, ArtDirectorIssueCode.LOGO_DEFORMED,
            ArtDirectorIssueCode.LOGO_TOO_LARGE, ArtDirectorIssueCode.LOGO_TOO_SMALL, ArtDirectorIssueCode.NEWS_OVERBRANDED,
        )
    }
    if hard_codes or soft_codes:
        return DimensionEvaluation(
            dimension=ArtDirectorDimension.BRANDING, status=DimensionStatus.FAIL,
            reason_codes=[c.value for c in (hard_codes | soft_codes)], hard_failure=bool(hard_codes),
            rationale="A branding issue (including a possible duplicate/fake NNJ mark) was detected.",
        )
    return DimensionEvaluation(dimension=ArtDirectorDimension.BRANDING, status=DimensionStatus.PASS)


def _evaluate_visual_quality(base_result: ArtDirectorResult) -> DimensionEvaluation:
    quality_codes = {
        code for code in base_result.issue_codes
        if code in (
            ArtDirectorIssueCode.GENERATION_ARTIFACT, ArtDirectorIssueCode.MEDIA_LOW_QUALITY,
            ArtDirectorIssueCode.MEDIA_IRRELEVANT, ArtDirectorIssueCode.PRESENTATION_MISMATCH,
            ArtDirectorIssueCode.VISUAL_EMPTY, ArtDirectorIssueCode.UNKNOWN_VISUAL_FAILURE,
        )
    }
    if quality_codes:
        return DimensionEvaluation(
            dimension=ArtDirectorDimension.VISUAL_QUALITY, status=DimensionStatus.FAIL,
            reason_codes=[c.value for c in quality_codes],
            rationale="A generation/media-quality issue was detected in the underlying pixel evaluation.",
        )
    return DimensionEvaluation(dimension=ArtDirectorDimension.VISUAL_QUALITY, status=DimensionStatus.PASS)


def evaluate_against_spec_and_references(evaluation_input: SpecEvaluationInput) -> SpecEvaluationResult:
    """The one function this phase adds to make Design Spec/Reference rows real evaluation inputs
    (spec §15's own explicit gap). Never re-evaluates pixels itself - `evaluation_input.base_result`
    must already come from `evaluate_art_direction_shadow()`/`evaluate_art_direction_vision()`."""
    dimensions = [
        _evaluate_fact_safety(evaluation_input.base_result),
        _evaluate_spec_match(evaluation_input.active_spec, evaluation_input.presentation_mode),
        _evaluate_reference_match(
            evaluation_input.approved_references, evaluation_input.rejected_references, evaluation_input.presentation_mode,
        ),
        _evaluate_source_preservation(evaluation_input.source_type, evaluation_input.presentation_mode),
        _evaluate_typography(evaluation_input.base_result),
        _evaluate_layout(evaluation_input.base_result),
        _evaluate_branding(evaluation_input.base_result),
        _evaluate_visual_quality(evaluation_input.base_result),
    ]

    hard_failures = [
        reason_code
        for dim_eval in dimensions if dim_eval.hard_failure
        for reason_code in (dim_eval.reason_codes or [dim_eval.dimension.value])
    ]

    if hard_failures:
        # §19: never PASS/PASS_WITH_NOTES on a hard failure, regardless of the base pixel
        # evaluator's own decision - BLOCK is the correct action for every hard-failure category
        # listed in this module's own docstring (each is either a renderer/finalization defect or
        # a genuine fact-safety violation, never something a human REWORK retry would fix by luck).
        return SpecEvaluationResult(overall_decision=ArtDirectorDecision.BLOCK, dimensions=dimensions, hard_failure_reason_codes=hard_failures)

    soft_failure = any(dim_eval.status is DimensionStatus.FAIL for dim_eval in dimensions)
    if soft_failure:
        overall = ArtDirectorDecision.REWORK if evaluation_input.base_result.decision != ArtDirectorDecision.BLOCK else evaluation_input.base_result.decision
        return SpecEvaluationResult(overall_decision=overall, dimensions=dimensions)

    # No dimension failed - never upgrade a base decision the pixel evaluator already reached
    # (e.g. BLOCK from a structural check this module does not re-derive); otherwise preserve it.
    return SpecEvaluationResult(overall_decision=evaluation_input.base_result.decision, dimensions=dimensions)


# DIRECTOR-CONTROL-PLANE-1B §9-10: the composed Art Director verdict. Callers that consume a plain
# ArtDirectorResult (services/visual_design_loop.py's own art-director step) get the base pixel
# result AND the Design Spec / reference / source-classification evaluation merged into ONE result.
_DECISION_STRICTNESS = {
    ArtDirectorDecision.PASS: 0, ArtDirectorDecision.PASS_WITH_NOTES: 1,
    ArtDirectorDecision.REWORK: 2, ArtDirectorDecision.BLOCK: 3,
}


def _merge_issue_codes(
    base_result: ArtDirectorResult, spec_result: SpecEvaluationResult,
) -> list[ArtDirectorIssueCode]:
    """Base pixel issue codes, plus any spec-dimension reason code that is itself a real
    ArtDirectorIssueCode (e.g. FACT_SAFETY -> NUMBER_MISMATCH). Spec-only codes that have no
    ArtDirectorIssueCode member (SPEC_PRESENTATION_MODE_MISMATCH, MATCHES_REJECTED_REFERENCE,
    INFOGRAPHIC_DESTROYED) are carried in the merged result's `instructions` instead, never
    silently dropped."""
    codes = list(base_result.issue_codes)
    for dim_eval in spec_result.dimensions:
        if dim_eval.status is not DimensionStatus.FAIL:
            continue
        for raw in dim_eval.reason_codes:
            try:
                mapped = ArtDirectorIssueCode(raw)
            except ValueError:
                continue
            if mapped not in codes:
                codes.append(mapped)
    return codes


def merge_spec_evaluation_into_result(
    base_result: ArtDirectorResult, spec_result: SpecEvaluationResult,
) -> ArtDirectorResult:
    """§10 hard-failure precedence: a §19 hard failure (wrong/ambiguous key metric, infographic
    destroyed, duplicate/fake NNJ mark, meaning-changing clipping, hard ACTIVE-spec invariant
    violation) ALWAYS yields BLOCK - it can never be downgraded by an optimistic vision decision.
    Otherwise the STRICTER of the base decision and the spec `overall_decision` wins (a spec/
    reference soft mismatch can push PASS -> REWORK, but a base BLOCK is never softened)."""
    merged_codes = _merge_issue_codes(base_result, spec_result)

    if spec_result.hard_failure_reason_codes:
        hard = "; ".join(spec_result.hard_failure_reason_codes)
        instructions = f"Hard art-direction failure ({hard})."
        if base_result.instructions:
            instructions = f"{instructions} {base_result.instructions}"
        return ArtDirectorResult(
            decision=ArtDirectorDecision.BLOCK, severity="high", issue_codes=merged_codes,
            action="HUMAN_REVIEW", instructions=instructions, confidence=max(base_result.confidence, 0.9),
        )

    if _DECISION_STRICTNESS[base_result.decision] >= _DECISION_STRICTNESS[spec_result.overall_decision]:
        final_decision = base_result.decision
    else:
        final_decision = spec_result.overall_decision

    soft_notes = [
        code
        for dim_eval in spec_result.dimensions if dim_eval.status is DimensionStatus.FAIL
        for code in dim_eval.reason_codes
    ]
    instructions = base_result.instructions
    if soft_notes:
        joined = "; ".join(sorted(set(soft_notes)))
        instructions = f"{instructions} spec/reference notes: {joined}".strip()
    return ArtDirectorResult(
        decision=final_decision, severity=base_result.severity, issue_codes=merged_codes,
        action=base_result.action, instructions=instructions, confidence=base_result.confidence,
    )


def finalize_art_direction(evaluation_input: SpecEvaluationInput) -> tuple[ArtDirectorResult, SpecEvaluationResult]:
    """Convenience: run `evaluate_against_spec_and_references()` and fold it back into a single
    ArtDirectorResult in one call. Returns both so a caller that wants the per-dimension detail
    (a console, a test) still has it. The pixel evaluation itself must already have happened -
    `evaluation_input.base_result` is its output."""
    spec_result = evaluate_against_spec_and_references(evaluation_input)
    return merge_spec_evaluation_into_result(evaluation_input.base_result, spec_result), spec_result
