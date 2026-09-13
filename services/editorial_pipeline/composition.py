"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 (S9/S17): composition planning.

`decide_data_composition_strategy()` implements S9's own explicit, ordered precedence for DATA:

    1. truthful real series exists                                -> DATA_WITH_GRAPH
    2. no real graph but a suitable truthful source/researched image exists -> DATA_WITH_SOURCE_IMAGE
    3. neither                                                      -> DATA_TYPOGRAPHIC

"Truthful" is load-bearing (S9's own "never fabricate a graph"): a series only counts when it came
from `StructuredDataContent.series` (itself only ever populated from a real `DataCandidate.series`,
which the renderer/presentation_director layer never invents - see services/presentation_director.py's
own `DataCandidate.series` docstring: "the renderer NEVER invents [it]... plotted verbatim"), and a
source image only counts when `MediaSelectionResult.selected` is set AND its subject-match
classification is not MISMATCH (a mismatched or missing selection is exactly "no suitable image",
never silently treated as one).

`build_composition_plan()` assembles the platform-neutral `CompositionPlan` (S17) - it makes ONLY
the format/strategy/photo-input/media-group/caption-position/branding decisions; it never touches
pixels, never calls a renderer, and never re-decides anything a QualityGateResult has already ruled
on. The actual renderer (services/brand_renderer.py, services/nnj_master_news_overlay.py - both
Founder-approved and frozen, S18) is invoked by the platform adapter (platforms/telegram.py), not
here and not by this module's own callers directly - S17's own "renderer does only layout/
typography/crop/brand treatment/drawing" boundary.
"""
from __future__ import annotations

from services.editorial_pipeline.contracts import (
    CompositionPlan,
    DataCompositionStrategy,
    MediaSelectionResult,
    PresentationFormat,
    StructuredDataContent,
    SubjectMatchClassification,
)


def decide_data_composition_strategy(
    *, structured_data: StructuredDataContent | None, media_selection: MediaSelectionResult | None,
) -> DataCompositionStrategy:
    if structured_data is not None and structured_data.series:
        return DataCompositionStrategy.DATA_WITH_GRAPH
    if media_selection is not None and media_selection.selected is not None:
        subject_match = media_selection.selected.subject_match
        if subject_match is None or subject_match.subject_match != SubjectMatchClassification.MISMATCH:
            return DataCompositionStrategy.DATA_WITH_SOURCE_IMAGE
    return DataCompositionStrategy.DATA_TYPOGRAPHIC


def build_composition_plan(
    *, presentation_format: PresentationFormat, structured_data: StructuredDataContent | None,
    media_selection: MediaSelectionResult | None, caption_position: str = "BELOW",
    branding_strength: str = "STANDARD",
) -> CompositionPlan:
    """`photo_input`/`media_group_items` are left unresolved here (None / empty) - platform
    adapters populate them from `media_selection.selected` in their own platform-native shape (a
    Telegram `BufferedInputFile`/cached file_id vs. an Instagram-native asset reference), matching
    S17's own platform-neutral discipline for this contract."""
    data_strategy = (
        decide_data_composition_strategy(structured_data=structured_data, media_selection=media_selection)
        if presentation_format == PresentationFormat.DATA else None
    )
    return CompositionPlan(
        presentation_format=presentation_format, data_strategy=data_strategy, photo_input=None,
        media_group_items=(), caption_position=caption_position, branding_strength=branding_strength,  # type: ignore[arg-type]
    )
