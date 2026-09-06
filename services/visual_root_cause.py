"""VISUAL-DESIGN-AUTONOMY-1, spec §23-24: a light, deterministic classifier from real Art Director
output to `VisualFailureRootCause` - for COST/ROUTING EFFICIENCY only (spec §23's own "must NOT
limit creative freedom" instruction). A DESIGN_DIRECTION classification still leaves the Visual
Design Director completely free to redesign; this module never picks the creative response, only
which cheap/expensive next step is worth trying first (e.g. reselect media before spending a
second generation call).

Mirrors services/telegram_revision_router.py's own issue-code groupings (the existing, real,
already-tested revision router for the deterministic-renderer path) but expresses the spec's own
7-value root-cause taxonomy instead of that router's 5-value action taxonomy - the two modules
solve adjacent but distinct problems (this one classifies WHY a render failed for a downstream
creative-loop decision; that one decides WHAT deterministic action the renderer/media pipeline
takes) and are not merged, since the router's RevisionAction vocabulary already has real callers
that expect its own exact 5 values."""
from __future__ import annotations

from database.models.visual_design_attempt import VisualFailureRootCause
from services.telegram_art_director import ArtDirectorIssueCode

_SOURCE_MEDIA_CODES = frozenset({
    ArtDirectorIssueCode.MEDIA_LOW_QUALITY, ArtDirectorIssueCode.MEDIA_IRRELEVANT,
    ArtDirectorIssueCode.SUBJECT_CROP_BAD,
})
_GENERATION_MODEL_CODES = frozenset({ArtDirectorIssueCode.GENERATION_ARTIFACT})
_RENDERER_CODES = frozenset({
    ArtDirectorIssueCode.TEXT_OVERLAP, ArtDirectorIssueCode.TEXT_CLIPPING, ArtDirectorIssueCode.HEADLINE_OVERFLOW,
})
_OVERLAY_CODES = frozenset({
    ArtDirectorIssueCode.LOW_LOGO_CONTRAST, ArtDirectorIssueCode.LOGO_DEFORMED, ArtDirectorIssueCode.LOGO_TOO_LARGE,
    ArtDirectorIssueCode.LOGO_TOO_SMALL, ArtDirectorIssueCode.SAFE_AREA_VIOLATION,
    # VISUAL-SINGLE-BRAND-MARK-1 §11/§12: DUPLICATE_NNJ_BRAND_MARK defaults to OVERLAY here
    # (a branding/overlay-design symptom) - the fixed `_PRIORITY` order below means a co-emitted
    # GENERATION_ARTIFACT (the generation-caused variant of this same symptom - see services/
    # telegram_art_director_vision.py's own prompt instructions) still wins and correctly routes
    # to GENERATION_MODEL instead, since that check runs first.
    ArtDirectorIssueCode.DUPLICATE_NNJ_BRAND_MARK,
})
_FACTUAL_CODES = frozenset({ArtDirectorIssueCode.NUMBER_MISMATCH})
_DESIGN_DIRECTION_CODES = frozenset({
    ArtDirectorIssueCode.VISUAL_TOO_BUSY, ArtDirectorIssueCode.VISUAL_EMPTY,
    ArtDirectorIssueCode.NEWS_OVERBRANDED, ArtDirectorIssueCode.PRESENTATION_MISMATCH,
})

# Checked in this fixed priority order: a factual failure always wins (it can never be redesigned
# away), then a source-media/generation-model/renderer/overlay problem (each cheaper to fix than a
# full redesign), and only then a genuine design-direction issue.
_PRIORITY: tuple[tuple[frozenset[ArtDirectorIssueCode], VisualFailureRootCause], ...] = (
    (_FACTUAL_CODES, VisualFailureRootCause.FACTUAL),
    (_SOURCE_MEDIA_CODES, VisualFailureRootCause.SOURCE_MEDIA),
    (_GENERATION_MODEL_CODES, VisualFailureRootCause.GENERATION_MODEL),
    (_RENDERER_CODES, VisualFailureRootCause.RENDERER),
    (_OVERLAY_CODES, VisualFailureRootCause.OVERLAY),
    (_DESIGN_DIRECTION_CODES, VisualFailureRootCause.DESIGN_DIRECTION),
)


def classify_root_cause(issue_codes: list[ArtDirectorIssueCode]) -> VisualFailureRootCause:
    """Returns UNKNOWN (never a guessed classification) when no issue code matches a known
    category - e.g. a bare UNKNOWN_VISUAL_FAILURE code, or an empty list."""
    issue_set = set(issue_codes)
    for codes, root_cause in _PRIORITY:
        if issue_set & codes:
            return root_cause
    return VisualFailureRootCause.UNKNOWN
