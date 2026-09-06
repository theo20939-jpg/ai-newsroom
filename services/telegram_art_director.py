"""NINJA Social Intelligence Foundation, Part III §44-46: Telegram Art Director - SHADOW ONLY
(spec §48/§111, no visual veto wired anywhere). Evaluates the ACTUAL final render, not template
metadata alone (spec §44) - `PixelInputContract` requires real rendered bytes or WYSIWYG-faithful
preview bytes, mirroring the exact "byte-identical to publish" contract already proven in the
FinalPostReview pipeline (services/final_post_review_notifier.py).

CRITICAL (spec §46): must never classify a deliberate safe no-overlay decision as a failure merely
because a logo/mark is absent - `renderer_decision_metadata` carries the real safety-scoring
outcome (services/brand_renderer.py's own `MasterNewsBrandingDecision`/`DataSignaturePlan` shape,
passed through as a plain dict here to avoid a new cross-module coupling) and this function checks
it BEFORE ever raising a missing-mark issue.

SOCIAL-INTELLIGENCE-PRELAUNCH-1A §17: explicitly evaluated and NOT wired with SocialLaunchContext.
This module is a pixel-level QC gate against the ACTUAL rendered bytes (overflow/clipping/contrast/
overlap) - whether the account is cold-start/pre-launch/live has no bearing on any of those checks;
a headline that overflows overflows the same way on post #1 as on post #10,000. The launch-stage
reasoning this phase adds lives entirely upstream, in services/visual_design_director.py's own
VisualDirectorContext.launch_context_summary (spec §16) - the Art Director evaluates what was
actually produced, never why it was requested."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class ArtDirectorIssueCode(str, enum.Enum):
    """Spec §45's own extensible taxonomy - not exhaustive by design (module docstring)."""

    HEADLINE_OVERFLOW = "headline_overflow"
    TEXT_OVERLAP = "text_overlap"
    TEXT_CLIPPING = "text_clipping"
    LOW_LOGO_CONTRAST = "low_logo_contrast"
    LOGO_DEFORMED = "logo_deformed"
    LOGO_TOO_LARGE = "logo_too_large"
    LOGO_TOO_SMALL = "logo_too_small"
    SUBJECT_CROP_BAD = "subject_crop_bad"
    SAFE_AREA_VIOLATION = "safe_area_violation"
    GENERATION_ARTIFACT = "generation_artifact"
    NUMBER_MISMATCH = "number_mismatch"
    NEWS_OVERBRANDED = "news_overbranded"
    MEDIA_LOW_QUALITY = "media_low_quality"
    MEDIA_IRRELEVANT = "media_irrelevant"
    PRESENTATION_MISMATCH = "presentation_mismatch"
    VISUAL_TOO_BUSY = "visual_too_busy"
    VISUAL_EMPTY = "visual_empty"
    UNKNOWN_VISUAL_FAILURE = "unknown_visual_failure"


class ArtDirectorDecision(str, enum.Enum):
    PASS = "pass"
    PASS_WITH_NOTES = "pass_with_notes"
    REWORK = "rework"
    BLOCK = "block"


@dataclass(frozen=True)
class PixelInputContract:
    """Spec §44's own required input shape. `rendered_bytes` should be the real final render or a
    byte-identical WYSIWYG preview (never template metadata alone)."""

    rendered_bytes: bytes
    caption: str
    presentation_type: str
    renderer_version: str | None
    renderer_decision_metadata: dict[str, Any] = field(default_factory=dict)
    media_source_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtDirectorResult:
    decision: ArtDirectorDecision
    severity: str
    issue_codes: list[ArtDirectorIssueCode] = field(default_factory=list)
    action: str = ""
    instructions: str = ""
    confidence: float = 0.3


def renderer_reports_safe_degradation(renderer_decision_metadata: dict[str, Any]) -> bool:
    """Recognizes the real production shape (services/brand_renderer.py): a `DataSignaturePlan`
    with `tier == "none"`, or a `MasterNewsBrandingDecision` where a component's own `placement`
    is `"omitted"` - both are DELIBERATE safety-scoring outcomes, never a rendering bug. Accepts
    a plain dict (not the real dataclass types) to avoid a new services/brand_renderer.py
    import coupling from this module - a future phase may tighten this to the real types once an
    actual caller exists to prove the integration."""
    tier = renderer_decision_metadata.get("tier")
    if tier == "none":
        return True
    placement = renderer_decision_metadata.get("placement")
    if placement in ("omitted", "OMITTED"):
        return True
    for component in ("upper_mark", "lower_signature"):
        sub = renderer_decision_metadata.get(component)
        if isinstance(sub, dict) and sub.get("placement") in ("omitted", "OMITTED"):
            return True
    return False


def evaluate_art_direction_shadow(pixel_input: PixelInputContract) -> ArtDirectorResult:
    """Deterministic, structural checks only in this phase (no real vision/pixel-analysis model
    wired yet - a future phase's own explicit job, per spec §44's "either actual rendered bytes...
    or faithful final preview bytes" input requirement being satisfied here, without yet
    implementing the analysis that would consume them). Proves the contract + the §46 safety-
    degradation exception; does not fabricate a real quality judgment from bytes alone."""
    if not pixel_input.rendered_bytes:
        return ArtDirectorResult(
            decision=ArtDirectorDecision.BLOCK, severity="high",
            issue_codes=[ArtDirectorIssueCode.VISUAL_EMPTY], action="RERENDER",
            instructions="No rendered bytes provided - cannot evaluate an empty render.", confidence=1.0,
        )

    if renderer_reports_safe_degradation(pixel_input.renderer_decision_metadata):
        # §46: never flag this as a failure - a deliberate, already-safety-scored decision.
        return ArtDirectorResult(
            decision=ArtDirectorDecision.PASS, severity="none", issue_codes=[],
            action="", instructions="Safe degradation (no visible brand mark) - not a failure.",
            confidence=0.9,
        )

    return ArtDirectorResult(
        decision=ArtDirectorDecision.PASS_WITH_NOTES, severity="low", issue_codes=[],
        action="", instructions="No structural checks failed (shadow evaluator - no real pixel analysis yet).",
        confidence=0.2,
    )
