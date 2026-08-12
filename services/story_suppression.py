"""Phase 20 M7: duplicate/supporting-source suppression PROPOSAL layer.

Computes `would_suppress: bool` per event x story match - a shadow-only recommendation. Nothing
in this codebase reads this value to change real selection/scoring/publishing behavior this phase
(see tests/test_story_suppression_isolation.py, M10, for the AST-based proof).

Exact policy (Phase 20 Checkpoint-1-approval message, verbatim intent):
- SEMANTIC_DUPLICATE, confidence_band == HIGH, delta_classification in {NO_NEW_FACTS,
  CONFIRMATION_ONLY} -> True. A same-story rehash with nothing new to say.
- SUPPORTING_SOURCE, confidence_band == HIGH, delta_classification in {NO_NEW_FACTS,
  CONFIRMATION_ONLY} -> True. "Attach-evidence-only" semantics: worth recording as another
  corroborating source under the same Story, not worth a separate reader-facing item.
- Everything else -> False. In particular: MINOR_DELTA and UNCERTAIN_DELTA never suppress
  ("conservative - false unless strong replay evidence"; M11's replay has not run, so the
  conservative default is the only defensible one right now). UNCERTAIN_MATCH never suppresses
  ("false suppression is worse than a duplicate" - explicit, non-negotiable). STORY_UPDATE,
  MATERIAL_UPDATE, RELATED_STORY, and NEW_STORY never suppress - none of them represent a
  same-story item with nothing new to say, by definition.
"""
from __future__ import annotations

from services.story_confidence import HIGH
from services.story_delta_engine import CONFIRMATION_ONLY, NO_NEW_FACTS
from services.story_memory import SEMANTIC_DUPLICATE, SUPPORTING_SOURCE

_NO_MATERIAL_DELTA = {NO_NEW_FACTS, CONFIRMATION_ONLY}
_SUPPRESSIBLE_MATCH_TYPES = {SEMANTIC_DUPLICATE, SUPPORTING_SOURCE}


def compute_would_suppress(*, match_type: str, confidence_band: str, delta_classification: str) -> bool:
    """Pure. `match_type` is a services.story_memory outcome constant, `confidence_band` a
    services.story_confidence band constant, `delta_classification` a
    services.story_delta_engine classification constant - all three already independently
    computed by the caller before this function is ever reached."""
    if match_type not in _SUPPRESSIBLE_MATCH_TYPES:
        return False
    if confidence_band != HIGH:
        return False
    return delta_classification in _NO_MATERIAL_DELTA
