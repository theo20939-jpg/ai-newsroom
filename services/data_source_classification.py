"""DIRECTOR-CONTROL-PLANE-1 §23-26: source-presentation classification for the DATA renderer - the
real fix for the Kirin 9050 Pro regression (source infographic already showing "42%", the old
DATA renderer composited a SECOND, competing stat block on top, producing a visually confusing/
ambiguous "142%"-reading result). Deterministic, structural-signal-only (spec §24's own "vision-
assisted as appropriate" is a real future extension point - not implemented here given no live
caller needs the extra Gateway cost/latency yet; this module's own `classify_source_presentation()`
is exactly where such a call would be added later, without changing its return contract).

Reuses ONLY already-computed signals (schemas/image_candidate.py::QualitySignals, persisted onto
EditorialImageCandidate.warnings by the existing Phase 16 M3/M9 image-intelligence pipeline) -
never a new ML model, never OCR. Returns UNKNOWN (never a fabricated confident guess) whenever the
existing signal set is not conclusive - spec §41's own "do not require OCR-heavy production logic
if a safer structured source-fact path exists" instruction."""
from __future__ import annotations

import enum


class SourceType(str, enum.Enum):
    PHOTO = "photo"
    PRODUCT_PHOTO = "product_photo"
    SCREENSHOT = "screenshot"
    EXISTING_INFOGRAPHIC = "existing_infographic"
    DOCUMENT = "document"
    CHART = "chart"
    UNKNOWN = "unknown"


class DataPresentationMode(str, enum.Enum):
    """Spec §25's own three modes - reused verbatim by schemas/declarative_visual_parameters.py::
    PresentationMode, this is the one real definition."""

    FULL_DATA_CARD = "full_data_card"
    MINIMAL_SOURCE_PRESERVING = "minimal_source_preserving"
    NO_OVERLAY_SAFETY = "no_overlay_safety"


def classify_source_presentation(warnings: list[str] | None) -> SourceType:
    """`warnings` is `EditorialImageCandidate.warnings` verbatim - the exact same field worker/
    content_cycle.py::assess_recomposition_source_risk() already reads (its own
    _RECOMPOSITION_RISK_WARNINGS frozenset, reused here as the same trusted vocabulary, never a
    second competing signal list).

    `possible_branded_screenshot` alone -> SCREENSHOT (a UI capture, not a designed infographic).
    `possible_banner` + `possible_logo` together -> EXISTING_INFOGRAPHIC (the strongest available
    structural proxy for "this photo IS a pre-made graphic that already carries its own text/brand
    hierarchy", since a banner-shaped image that also carries an embedded logo is exactly the shape
    a product/press infographic takes - both signals already exist, no new detector). `possible_
    banner` alone (no embedded logo) -> DOCUMENT (a plain banner/slide, still text-heavy enough to
    warrant caution, but without the stronger infographic signal). Everything else -> UNKNOWN,
    never a guessed PHOTO/PRODUCT_PHOTO/CHART with no real supporting evidence."""
    warning_set = set(warnings or [])
    if "possible_branded_screenshot" in warning_set:
        return SourceType.SCREENSHOT
    if "possible_banner" in warning_set and "possible_logo" in warning_set:
        return SourceType.EXISTING_INFOGRAPHIC
    if "possible_banner" in warning_set:
        return SourceType.DOCUMENT
    return SourceType.UNKNOWN


def select_data_presentation_mode(source_type: SourceType) -> DataPresentationMode:
    """Spec §25's own required default: EXISTING_INFOGRAPHIC prefers MINIMAL_SOURCE_PRESERVING
    unless a Design Spec explicitly permits reconstruction (no such override exists in this phase -
    services/brand_renderer.py::render_data_card()'s own `presentation_mode` parameter is the only
    way to force FULL_DATA_CARD, and no caller does so for an EXISTING_INFOGRAPHIC source yet).
    Every other source type keeps today's existing FULL_DATA_CARD behavior unchanged - this
    function never regresses a PHOTO/PRODUCT_PHOTO/UNKNOWN source's own already-correct treatment."""
    if source_type == SourceType.EXISTING_INFOGRAPHIC:
        return DataPresentationMode.MINIMAL_SOURCE_PRESERVING
    return DataPresentationMode.FULL_DATA_CARD
