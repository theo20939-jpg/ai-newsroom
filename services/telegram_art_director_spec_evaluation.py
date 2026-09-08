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
     governs the exact same source-preservation safety property as #4, never a soft preference.

DESIGN-SPEC-ENFORCEMENT-1 §3-8: SPEC_MATCH is no longer limited to the `presentation_mode`
invariant. When a structured `RenderEvidence` (services/render_evidence.py - values REPLAYED from
the renderer's own deterministic helpers, never LLM-estimated) is supplied AND the spec is
actually in force (ACTIVE / FROZEN), `_evaluate_spec_match()` now compares every applicable
declared parameter (`font_size_min`/`max`, `max_line_count`, `safe_margin_frac`, `logo_zone`,
`placement_zone`/`metric_placement`, `scrim_treatment`, `source_image_treatment`) field-by-field
and emits a SPECIFIC reason code per mismatch (§6) with a hard/soft classification (§7). A field
the renderer cannot truthfully measure (`RenderEvidence` value `NOT_MEASURED`) is skipped for that
render - it never makes the whole dimension NOT_APPLICABLE (§4). CANDIDATE specs keep the
pre-existing behavior (only the `presentation_mode` flag, never hard, never field enforcement) -
§17: a candidate must never change current production acceptance."""
from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass, field

from database.models.design_reference_asset import DesignReferenceAsset
from database.models.design_spec_version import DesignSpecStatus, DesignSpecVersion
from services.data_source_classification import DataPresentationMode, SourceType
from services.render_evidence import NOT_MEASURED, RenderEvidence
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
    # DESIGN-SPEC-ENFORCEMENT-1 addendum §3: an ACTIVE spec exists and at least one declared field
    # WAS verified, but at least one other applicable declared field could not be measured for this
    # render (a legacy renderer gap, e.g. NEWS `placement_zone`). Not a failure - the Founder can
    # see exactly which fields were checked (`checked_fields`) and which were not
    # (`not_measured_fields`). Whole-dimension NOT_APPLICABLE stays reserved for "no applicable /
    # measurable declared field at all".
    PARTIAL_EVIDENCE = "partial_evidence"


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
    # DESIGN-SPEC-ENFORCEMENT-1 addendum §3: for SPEC_MATCH, exactly which declared spec fields
    # were verified against RenderEvidence this render, and which applicable ones could not be
    # measured. Empty for every other dimension.
    checked_fields: list[str] = field(default_factory=list)
    not_measured_fields: list[str] = field(default_factory=list)


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
    # DESIGN-SPEC-ENFORCEMENT-1 §3: structured, renderer-truthful metadata about the FINAL render
    # (services/render_evidence.py). When present AND the active spec is in force, SPEC_MATCH
    # verifies the render against the spec's declarative layout/typography parameters field-by-
    # field. Absent (every pre-existing caller) -> SPEC_MATCH keeps its `presentation_mode`-only
    # behavior, byte-identical to before this phase.
    render_evidence: RenderEvidence | None = None


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


# DESIGN-SPEC-ENFORCEMENT-1 §8: the founder telegram_* specs declare safe_margin_frac=0.019, a
# 3-decimal rounding of the renderer's own locked _SAFE_INSET_FRAC (24/1280 = 0.01875). The
# floor comparison allows this much slack so that exact constant never reads as a violation of the
# value it was rounded from.
_SAFE_MARGIN_TOLERANCE = 1e-3


@dataclass(frozen=True)
class _FieldCheck:
    """One declared-parameter vs RenderEvidence comparison outcome.

    - `measured=True`, `ok=True`  -> the field was verified and conforms (goes to checked_fields).
    - `measured=True`, `ok=False` -> the field was verified and MISMATCHES (a real FAIL).
    - `measured=False`, `applicable=True`  -> the spec declares it, it DOES apply to this render,
      but the (legacy) renderer cannot expose it -> goes to not_measured_fields -> PARTIAL_EVIDENCE.
    - `measured=False`, `applicable=False` -> the render mode makes the field genuinely inapplicable
      (e.g. font size in MINIMAL_SOURCE_PRESERVING) -> recorded only as a note, never PARTIAL."""

    field: str
    measured: bool
    ok: bool
    reason_code: str = ""
    hard: bool = False
    detail: str = ""
    applicable: bool = True


def _param_value(raw: object) -> str | None:
    """A declared parameter as a plain comparable string. `parameters` is stored JSON, so a value
    is already a str/int/float; a defensive `getattr(., "value", .)` also unwraps an enum if a
    caller ever passes one."""
    if raw is None:
        return None
    unwrapped = raw.value if hasattr(raw, "value") else raw  # type: ignore[attr-defined]
    return str(unwrapped)


def _measured_number(evidence: RenderEvidence, name: str) -> float | None:
    value = getattr(evidence, name, NOT_MEASURED)
    return float(value) if isinstance(value, (int, float)) else None


def _measured_text(evidence: RenderEvidence, name: str) -> str | None:
    value = getattr(evidence, name, NOT_MEASURED)
    return value if isinstance(value, str) else None


def _compare_spec_fields(parameters: dict, evidence: RenderEvidence) -> list[_FieldCheck]:
    """§5/§6/§7: compare each applicable declared parameter against the renderer-truthful
    RenderEvidence, one specific reason code per mismatch. A parameter the spec does not declare
    (None) is skipped; an evidence value of NOT_MEASURED is skipped (recorded `measured=False`),
    never a fail. Hard/soft per §7: source information destroyed (recompose over a preserve spec),
    DATA line/metric layout causing factual ambiguity (max_line_count exceeded), and >1 brand mark
    are hard; placement/scrim/font/margin drift is soft (REWORK)."""
    checks: list[_FieldCheck] = []
    na_fields = evidence.not_applicable_fields

    def _unmeasured(label: str, evidence_attr: str, why: str) -> _FieldCheck:
        # applicable=False iff the renderer POSITIVELY marked this evidence field inapplicable for
        # this render (addendum §3) - those never make SPEC_MATCH PARTIAL_EVIDENCE.
        return _FieldCheck(
            label, measured=False, ok=True, applicable=evidence_attr not in na_fields,
            detail=evidence.notes.get(evidence_attr, why),
        )

    # --- typography: primary stat font within [min, max] -------------------------------------
    font_min = parameters.get("font_size_min")
    font_max = parameters.get("font_size_max")
    if font_min is not None or font_max is not None:
        size = _measured_number(evidence, "primary_font_size")
        if size is None:
            checks.append(_unmeasured("font_size", "primary_font_size", "no primary stat typography rendered / not measurable"))
        else:
            lo_ok = font_min is None or size >= font_min
            hi_ok = font_max is None or size <= font_max
            if lo_ok and hi_ok:
                checks.append(_FieldCheck("font_size", True, True, detail=f"primary_font_size={size:g} within [{font_min}, {font_max}]"))
            else:
                checks.append(_FieldCheck(
                    "font_size", True, False, reason_code="SPEC_FONT_SIZE_OUT_OF_RANGE", hard=False,
                    detail=f"primary_font_size={size:g} outside the spec range [{font_min}, {font_max}].",
                ))

    # --- max line count (DATA stat descriptor) --------------------------------------------------
    max_lines = parameters.get("max_line_count")
    if max_lines is not None:
        lines = _measured_number(evidence, "actual_line_count")
        if lines is None:
            checks.append(_unmeasured("max_line_count", "actual_line_count", "line count not measurable for this render"))
        elif lines <= max_lines:
            checks.append(_FieldCheck("max_line_count", True, True, detail=f"actual_line_count={lines:g} <= {max_lines}"))
        else:
            checks.append(_FieldCheck(
                "max_line_count", True, False, reason_code="SPEC_MAX_LINE_COUNT_EXCEEDED", hard=True,
                detail=(
                    f"actual_line_count={lines:g} exceeds the spec max {max_lines} - "
                    "extra descriptor lines crowd the primary metric and create factual-layout ambiguity (§7)."
                ),
            ))

    # --- safe margin as a FLOOR --------------------------------------------------------------
    spec_margin = parameters.get("safe_margin_frac")
    if spec_margin is not None:
        actual_margin = _measured_number(evidence, "safe_margin_frac")
        if actual_margin is None:
            checks.append(_unmeasured("safe_margin_frac", "safe_margin_frac", "renderer inset not measurable"))
        elif actual_margin >= spec_margin - _SAFE_MARGIN_TOLERANCE:
            checks.append(_FieldCheck(
                "safe_margin_frac", True, True,
                detail=f"actual inset {actual_margin:g} >= spec floor {spec_margin} (± {_SAFE_MARGIN_TOLERANCE})",
            ))
        else:
            checks.append(_FieldCheck(
                "safe_margin_frac", True, False, reason_code="SPEC_SAFE_MARGIN_VIOLATION", hard=False,
                detail=(
                    f"actual edge inset {actual_margin:g} is below the spec's minimum safe "
                    f"margin {spec_margin} - content sits closer to the frame edge than the spec allows."
                ),
            ))

    # --- logo zone -------------------------------------------------------------------------
    _zone_check(checks, _unmeasured, "logo_zone", parameters.get("logo_zone"), _measured_text(evidence, "logo_zone"), "SPEC_LOGO_ZONE_MISMATCH")
    # --- primary accent / stat placement zone --------------------------------------------------
    spec_placement = parameters.get("placement_zone")
    if spec_placement is None:
        spec_placement = parameters.get("metric_placement")
    _zone_check(checks, _unmeasured, "placement_zone", spec_placement, _measured_text(evidence, "placement_zone"), "SPEC_PLACEMENT_ZONE_MISMATCH")

    # --- scrim treatment -----------------------------------------------------------------------
    spec_scrim = _param_value(parameters.get("scrim_treatment"))
    if spec_scrim is not None:
        actual_scrim = _measured_text(evidence, "scrim_treatment")
        if actual_scrim is None:
            checks.append(_unmeasured("scrim_treatment", "scrim_treatment", "scrim treatment not measurable"))
        elif actual_scrim == spec_scrim:
            checks.append(_FieldCheck("scrim_treatment", True, True, detail=f"scrim_treatment={spec_scrim}"))
        else:
            checks.append(_FieldCheck(
                "scrim_treatment", True, False, reason_code="SPEC_SCRIM_MISMATCH", hard=False,
                detail=f"spec requires scrim_treatment={spec_scrim!r} but the render used {actual_scrim!r}.",
            ))

    # --- source image treatment --------------------------------------------------------------
    spec_source = _param_value(parameters.get("source_image_treatment"))
    if spec_source is not None:
        actual_source = _measured_text(evidence, "source_image_treatment")
        if actual_source is None:
            checks.append(_unmeasured("source_image_treatment", "source_image_treatment", "source treatment not measurable"))
        elif actual_source == spec_source:
            checks.append(_FieldCheck("source_image_treatment", True, True, detail=f"source_image_treatment={spec_source}"))
        else:
            # §7: destroying source information (an AI recompose where the spec wants the real
            # source preserved) is HARD; a mechanical aspect crop-to-canvas is a soft REWORK.
            destroys = spec_source == "preserve" and actual_source == "recompose"
            checks.append(_FieldCheck(
                "source_image_treatment", True, False, reason_code="SPEC_SOURCE_TREATMENT_MISMATCH", hard=destroys,
                detail=(
                    f"spec requires source_image_treatment={spec_source!r} but the render used "
                    f"{actual_source!r}"
                    + (" - the real source was recomposed/regenerated, destroying its own information (§7 hard)." if destroys
                       else " - a mechanical fit that may drop edge content (soft REWORK).")
                ),
            ))

    # --- single brand mark contract (not a declared param - always enforced when measured) ----
    logo_count = _measured_number(evidence, "logo_count")
    if logo_count is not None and logo_count > 1:
        checks.append(_FieldCheck(
            "logo_count", True, False, reason_code=ArtDirectorIssueCode.DUPLICATE_NNJ_BRAND_MARK.value, hard=True,
            detail=f"the render placed {logo_count:g} canonical NNJ marks - exactly one is the contract (§7 hard).",
        ))

    return checks


def _zone_check(
    checks: list[_FieldCheck], unmeasured: Callable[[str, str, str], _FieldCheck],
    field_name: str, spec_raw: object, evidence_zone: str | None, reason_code: str,
) -> None:
    spec_zone = _param_value(spec_raw)
    if spec_zone is None:
        return
    if evidence_zone is None:
        checks.append(unmeasured(field_name, field_name, f"{field_name} not measurable for this render"))
    elif evidence_zone == spec_zone:
        checks.append(_FieldCheck(field_name, True, True, detail=f"{field_name}={spec_zone}"))
    else:
        checks.append(_FieldCheck(
            field_name, True, False, reason_code=reason_code, hard=False,
            detail=f"spec requires {field_name}={spec_zone!r} but the render placed it {evidence_zone!r}.",
        ))


def _evaluate_spec_match(
    active_spec: DesignSpecVersion | None,
    presentation_mode: DataPresentationMode | None,
    render_evidence: RenderEvidence | None = None,
) -> DimensionEvaluation:
    if active_spec is None or not active_spec.parameters:
        return DimensionEvaluation(
            dimension=ArtDirectorDimension.SPEC_MATCH, status=DimensionStatus.NOT_APPLICABLE,
            rationale="No active Design Spec with declared parameters for this scope.",
        )

    parameters = active_spec.parameters
    in_force = active_spec.status in (DesignSpecStatus.ACTIVE, DesignSpecStatus.FROZEN)

    reason_codes: list[str] = []
    rationale_parts: list[str] = []
    checked_fields: list[str] = []       # declared spec fields verified this render (pass OR fail)
    not_measured_fields: list[str] = []  # declared + applicable, but the legacy renderer can't expose it
    any_hard = False
    any_fail = False

    # --- (1) presentation_mode invariant - pre-existing behavior, preserved exactly ------------
    spec_mode = parameters.get("presentation_mode")
    if spec_mode is not None:
        actual_mode = presentation_mode.value if presentation_mode is not None else None
        if actual_mode == spec_mode:
            checked_fields.append("presentation_mode")
            rationale_parts.append(f"Render honors the active spec's own presentation_mode={spec_mode}.")
        else:
            any_fail = True
            checked_fields.append("presentation_mode")
            hard = in_force
            any_hard = any_hard or hard
            reason_codes.append("SPEC_PRESENTATION_MODE_MISMATCH")
            rationale_parts.append(
                f"Spec requires presentation_mode={spec_mode!r} but this render used {actual_mode!r}."
                + ("" if hard else " Spec is not yet in force (CANDIDATE) - flagged, not enforced.")
            )

    # --- (2) field-by-field declarative comparison (DESIGN-SPEC-ENFORCEMENT-1 §5-8) -----------
    # §17: only an ACTIVE / FROZEN spec enforces production results. A CANDIDATE keeps the
    # presentation_mode-only behavior above (soft, never hard) and never reaches field enforcement.
    if render_evidence is not None and in_force:
        for check in _compare_spec_fields(parameters, render_evidence):
            if not check.measured:
                if check.applicable:
                    not_measured_fields.append(check.field)
                    rationale_parts.append(f"{check.field}: NOT_MEASURED - applicable but the renderer cannot expose it ({check.detail}).")
                else:
                    rationale_parts.append(f"{check.field}: not applicable to this render ({check.detail}).")
                continue
            checked_fields.append(check.field)
            if check.ok:
                continue
            any_fail = True
            any_hard = any_hard or check.hard
            if check.reason_code and check.reason_code not in reason_codes:
                reason_codes.append(check.reason_code)
            rationale_parts.append(f"{check.field}: {check.detail}")
    elif render_evidence is not None and not in_force:
        rationale_parts.append(
            "RenderEvidence supplied but the spec is CANDIDATE - field-by-field enforcement is "
            "reserved for ACTIVE/FROZEN specs (§17); only the presentation_mode flag applies."
        )

    scope_ctx = f"Design Spec (scope={active_spec.scope}, version={active_spec.version}, status={active_spec.status.value})"
    verified_summary = (
        f" [verified: {', '.join(checked_fields) or 'none'}"
        + (f"; not measurable: {', '.join(not_measured_fields)}" if not_measured_fields else "")
        + "]"
    )

    if any_fail:
        return DimensionEvaluation(
            dimension=ArtDirectorDimension.SPEC_MATCH, status=DimensionStatus.FAIL,
            reason_codes=reason_codes, hard_failure=any_hard,
            rationale=f"{scope_ctx}: " + " ".join(rationale_parts) + verified_summary,
            checked_fields=checked_fields, not_measured_fields=not_measured_fields,
        )
    if checked_fields and not_measured_fields:
        # addendum §3: real evidence for some fields, a genuine gap for others -> PARTIAL_EVIDENCE,
        # never whole-dimension NOT_APPLICABLE.
        return DimensionEvaluation(
            dimension=ArtDirectorDimension.SPEC_MATCH, status=DimensionStatus.PARTIAL_EVIDENCE,
            rationale=f"{scope_ctx}: " + " ".join(rationale_parts) + verified_summary,
            checked_fields=checked_fields, not_measured_fields=not_measured_fields,
        )
    if checked_fields:
        return DimensionEvaluation(
            dimension=ArtDirectorDimension.SPEC_MATCH, status=DimensionStatus.PASS,
            rationale=f"{scope_ctx}: " + (" ".join(rationale_parts) or "render conforms to every applicable declared parameter.") + verified_summary,
            checked_fields=checked_fields, not_measured_fields=not_measured_fields,
        )
    # Spec declares parameters, but NONE was applicable/measurable for this render (e.g.
    # presentation_mode unset AND no RenderEvidence; or every declared field is not applicable to
    # this render mode). addendum §3: only THIS case yields whole-dimension NOT_APPLICABLE.
    detail = " ".join(rationale_parts) if rationale_parts else "no applicable/measurable declared parameter for this render."
    return DimensionEvaluation(
        dimension=ArtDirectorDimension.SPEC_MATCH, status=DimensionStatus.NOT_APPLICABLE,
        rationale=f"{scope_ctx}: {detail}",
        not_measured_fields=not_measured_fields,
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
        _evaluate_spec_match(
            evaluation_input.active_spec, evaluation_input.presentation_mode, evaluation_input.render_evidence,
        ),
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
    # addendum §3: surface which ACTIVE-spec fields were verified vs. could not be measured, so the
    # Founder sees the coverage of a PARTIAL_EVIDENCE SPEC_MATCH on the merged result too.
    partial = next(
        (d for d in spec_result.dimensions
         if d.dimension is ArtDirectorDimension.SPEC_MATCH and d.status is DimensionStatus.PARTIAL_EVIDENCE),
        None,
    )
    if partial is not None:
        instructions = (
            f"{instructions} SPEC_MATCH partial evidence - verified: "
            f"{', '.join(partial.checked_fields) or 'none'}; not measurable: "
            f"{', '.join(partial.not_measured_fields)}."
        ).strip()
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
