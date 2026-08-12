"""Phase 20 M7/M10: confidence bands for a Story Memory match.

Separated from `services/story_memory.py::MatchResult.confidence` deliberately - that field's
meaning is outcome-dependent (for `STORY_UPDATE`/`SUPPORTING_SOURCE`/`SEMANTIC_DUPLICATE`/
`UNCERTAIN_MATCH` it equals the raw `combined` score; for `NEW_STORY` it is `1 - combined`
("how confident this is genuinely new"); for `RELATED_STORY` it is the entity-overlap floor, a
different scale entirely). A confidence *band*, by contrast, only ever answers one question - "how
strong is the evidence that this is the same story?" - and is therefore only meaningful for the
four outcomes where a same-story match was actually being evaluated. Callers must not call this
for `NEW_STORY`/`RELATED_STORY` results.
"""
from __future__ import annotations

# Deliberately reuses services/story_memory.py's own outcome-threshold constants as the STARTING
# band boundaries (Phase 20 plan §18: "reuse today's 0.35/0.65 split as the initial HIGH/MEDIUM
# boundary hypothesis... expect these to move once real data exists"). A separate, independently
# tunable confidence-band threshold pair should be introduced once M11's historical replay
# recommends different boundaries; duplicating the numbers here before that would only invite
# drift between two copies of the same guess.
from services.story_memory import _HIGH_THRESHOLD as _BAND_HIGH_MIN
from services.story_memory import _LOW_THRESHOLD as _BAND_MEDIUM_MIN

HIGH = "high"
MEDIUM = "medium"
LOW = "low"


def compute_confidence_band(combined_score: float) -> str:
    """Pure. `combined_score` is the raw `combined` value `score_candidate()` produced for this
    match - equivalently, `MatchResult.confidence` for any of the four same-story-evaluation
    outcomes (`STORY_UPDATE`, `SUPPORTING_SOURCE`, `SEMANTIC_DUPLICATE`, `UNCERTAIN_MATCH`), where
    `confidence` is passed through as `combined` unmodified - see match_story()'s own return
    statements."""
    if combined_score >= _BAND_HIGH_MIN:
        return HIGH
    if combined_score >= _BAND_MEDIUM_MIN:
        return MEDIUM
    return LOW
