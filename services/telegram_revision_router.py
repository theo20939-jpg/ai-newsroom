"""NINJA Social Intelligence Foundation, Part III §47: RevisionRouter. Feature-flagged off
(telegram_revision_router_enabled=False, core/config.py) - not wired into any automatic path.
Max 2 automated revision rounds (spec §47's own explicit ceiling) - never an infinite loop."""
from __future__ import annotations

import enum

from services.telegram_art_director import ArtDirectorDecision, ArtDirectorResult, ArtDirectorIssueCode

MAX_REVISION_ROUNDS = 2

_MEDIA_ISSUE_CODES = frozenset({
    ArtDirectorIssueCode.MEDIA_LOW_QUALITY, ArtDirectorIssueCode.MEDIA_IRRELEVANT,
    ArtDirectorIssueCode.SUBJECT_CROP_BAD,
})
_PRESENTATION_ISSUE_CODES = frozenset({ArtDirectorIssueCode.PRESENTATION_MISMATCH})


class RevisionAction(str, enum.Enum):
    RERENDER = "rerender"
    RESELECT_MEDIA = "reselect_media"
    REDRAW = "redraw"
    REQUEST_PRESENTATION_REVIEW = "request_presentation_review"
    HUMAN_REVIEW = "human_review"


def route_revision(result: ArtDirectorResult, *, attempt_count: int) -> RevisionAction:
    """`attempt_count` is the number of automated revision rounds ALREADY attempted for this same
    render (0 on the first evaluation) - once it reaches `MAX_REVISION_ROUNDS`, always routes to
    HUMAN_REVIEW regardless of the Art Director's own decision, never looping further."""
    if attempt_count >= MAX_REVISION_ROUNDS:
        return RevisionAction.HUMAN_REVIEW
    if result.decision == ArtDirectorDecision.PASS:
        return RevisionAction.HUMAN_REVIEW  # nothing to route - caller should not have called this
    if result.decision == ArtDirectorDecision.BLOCK:
        return RevisionAction.HUMAN_REVIEW

    issue_set = set(result.issue_codes)
    if issue_set & _PRESENTATION_ISSUE_CODES:
        return RevisionAction.REQUEST_PRESENTATION_REVIEW
    if issue_set & _MEDIA_ISSUE_CODES:
        return RevisionAction.RESELECT_MEDIA
    if ArtDirectorIssueCode.GENERATION_ARTIFACT in issue_set:
        return RevisionAction.REDRAW
    if issue_set:
        return RevisionAction.RERENDER
    return RevisionAction.HUMAN_REVIEW
