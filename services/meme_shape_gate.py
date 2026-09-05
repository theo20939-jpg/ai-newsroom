"""Meme Shape Gate (MEME-PROD-4): a cheap, deterministic pre-filter run INSIDE `capabilities/
meme_concept_capability.py::MemeConceptCapability.execute()`, before the structured concept output
is accepted, to catch the pipeline's own confirmed failure mode - a concept that reads as an
"editorial illustration explaining the news" rather than an actual meme.

Deliberately narrow and disclosed, mirroring `services/meme_safety.py::assess_meme_originality()`'s
own "originality is necessarily narrow" precedent exactly: this is a DETERMINISTIC SUPPLEMENT, not
the semantic judge. The brief's own instruction is explicit - "Do NOT use brittle keyword-only
detection as the primary gate... A deterministic heuristic may supplement, not replace, semantic
evaluation." The real semantic correction is the LLM's own one-shot rewrite
(`_build_shape_correction_request()` in the capability module, mirroring `capabilities/
scoring_capability.py`'s own §10 correction-retry shape byte-for-byte) - this module only decides
WHETHER to spend that one bounded retry, using the same token_overlap_ratio-based restatement
signal `meme_safety.py` already established for its own headline-restatement check (same threshold,
same reused idea, applied to a different field pair).

Zero LLM/network calls. Zero cost. Operates on the capability's own raw `structured_output` dict
(not a validated `MemeConcept`) - this module runs at the capability layer, where every other
floor-validation in this codebase (`_floor_validate()` in both `meme_concept_capability.py` and
`scoring_capability.py`) already deals in plain dicts, never a parsed Pydantic model; `services/
meme_safety.py`'s own use of a real `MemeConcept` reflects that it runs one layer later, in the
orchestrator, AFTER `MemeConcept.model_validate()` - a different layer, a different established
convention, both internally consistent."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_WORD_RE = re.compile(r"[\w']+", re.UNICODE)

# Same restatement-detection threshold services/meme_safety.py::assess_meme_originality() already
# uses for punchline-vs-headline overlap - reused, not re-derived, for the same underlying
# question ("did the model just restate X instead of transforming it").
_RESTATEMENT_OVERLAP_THRESHOLD = 0.8


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _token_overlap_ratio(a: str, b: str) -> float:
    """Byte-for-byte the same formula services/meme_safety.py::_token_overlap_ratio() already
    established - duplicated locally per this codebase's own established per-module-private-
    helper convention (that function is module-private there too)."""
    tokens_a = {t.lower() for t in _WORD_RE.findall(a)}
    tokens_b = {t.lower() for t in _WORD_RE.findall(b)}
    if not tokens_a or not tokens_b:
        return 0.0
    overlap = len(tokens_a & tokens_b)
    return overlap / min(len(tokens_a), len(tokens_b))


@dataclass(frozen=True)
class MemeShapeAssessment:
    """`risk_reason` is `None` exactly when the concept passes this pre-filter - mirrors this
    codebase's own "verdict plus evidence, never a bare boolean" convention (e.g.
    `services.meme_safety.MemeOriginalityAssessment`'s own `reason_codes`)."""

    risk_reason: str | None
    evidence: str | None = None


def assess_meme_shape_risk(
    *, visual_scene: str, visual_punchline: str, premise: str,
) -> MemeShapeAssessment:
    """Flags exactly two narrow, disclosed failure shapes - never a general "is this funny"
    judgment (that is what the LLM correction retry itself is for, per module docstring):

    1. `visual_punchline` is empty/whitespace-only - the model didn't articulate a distinct visual
       joke at all (a schema `min_length=1` violation would already catch a truly empty string;
       this also catches whitespace-only, which passes that length check).
    2. `visual_punchline` is a near-restatement of `visual_scene` or of the news `premise`
       (token-overlap >= 0.8, either direction) - the strongest available deterministic signal
       that the model filled the field with a copy of the scene/news rather than a distinct joke,
       the exact confirmed production failure shape (chip-price scene = chip-price "punchline")."""
    punchline_norm = _normalize(visual_punchline)
    if not punchline_norm.strip():
        return MemeShapeAssessment(risk_reason="visual_punchline_empty")

    scene_overlap = _token_overlap_ratio(punchline_norm, _normalize(visual_scene))
    if scene_overlap >= _RESTATEMENT_OVERLAP_THRESHOLD:
        return MemeShapeAssessment(
            risk_reason="visual_punchline_restates_visual_scene",
            evidence=f"token_overlap_ratio:{scene_overlap:.2f}",
        )

    premise_overlap = _token_overlap_ratio(punchline_norm, _normalize(premise))
    if premise_overlap >= _RESTATEMENT_OVERLAP_THRESHOLD:
        return MemeShapeAssessment(
            risk_reason="visual_punchline_restates_news_premise",
            evidence=f"token_overlap_ratio:{premise_overlap:.2f}",
        )

    return MemeShapeAssessment(risk_reason=None)
