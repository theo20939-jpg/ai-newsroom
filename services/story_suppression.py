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
- Everything else -> False. In particular: UNCERTAIN_DELTA never suppresses ("conservative -
  false unless strong replay evidence"). UNCERTAIN_MATCH never suppresses ("false suppression is
  worse than a duplicate" - explicit, non-negotiable). STORY_UPDATE, MATERIAL_UPDATE,
  RELATED_STORY, and NEW_STORY never suppress - none of them represent a same-story item with
  nothing new to say, by definition.

Phase V2.22 correction (real production evidence, the Sainsbury's AI-scanning story): a
SEMANTIC_DUPLICATE match at the maximum possible confidence (1.0, the exact-normalized-title
short-circuit in services/story_memory.py::match_story()) with delta_classification=MINOR_DELTA
was NOT suppressed under the original policy above, even though `classify_delta()`'s own
docstring defines MINOR_DELTA as "a small number of new distinctive keywords, no material claim"
- by construction, never a reader-worthy new fact (that is exactly what MATERIAL_UPDATE exists to
flag instead). The original "MINOR_DELTA never suppresses" rule was reasoned before any real
evidence existed ("conservative - false unless strong replay evidence" - M11's replay had not run
yet); this IS that replay evidence. Scoped narrowly to SEMANTIC_DUPLICATE only, NOT
SUPPORTING_SOURCE: a SEMANTIC_DUPLICATE match is Story Memory's own strongest same-story signal
(near-identical/rehashed title), whereas SUPPORTING_SOURCE is deliberately weaker ("substantially
similar but not identical" per match_story()'s own docstring) - widening both at once would be
exactly the un-evidenced, broad suppression-policy loosening this phase's own instructions warn
against. STORY_UPDATE/MATERIAL_UPDATE/RELATED_STORY/NEW_STORY remain entirely unaffected - none
of them reach this function's suppressible-match-type gate at all.
"""
from __future__ import annotations

from services.story_confidence import HIGH
from services.story_delta_engine import CONFIRMATION_ONLY, MINOR_DELTA, NO_NEW_FACTS
from services.story_memory import SEMANTIC_DUPLICATE, SUPPORTING_SOURCE

_NO_MATERIAL_DELTA = {NO_NEW_FACTS, CONFIRMATION_ONLY}
# Phase V2.22: SEMANTIC_DUPLICATE additionally suppresses on MINOR_DELTA - see module docstring's
# own "Phase V2.22 correction" section for the real evidence. SUPPORTING_SOURCE deliberately keeps
# the original, narrower allowlist.
_NO_MATERIAL_DELTA_FOR_SEMANTIC_DUPLICATE = _NO_MATERIAL_DELTA | {MINOR_DELTA}
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
    if match_type == SEMANTIC_DUPLICATE:
        return delta_classification in _NO_MATERIAL_DELTA_FOR_SEMANTIC_DUPLICATE
    return delta_classification in _NO_MATERIAL_DELTA
