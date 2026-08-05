"""Meme Quality Gate (Phase 18 M7): the single pre-preview decision combining every upstream
signal into one of READY_FOR_EDITOR / REVIEW / REGENERATE_CONCEPT / REGENERATE_IMAGE / REJECT
(docs/phase18_m7_meme_quality_gate_report.md).

Zero LLM/network calls - a pure function combining already-computed results: M1's
`MemeOpportunityAssessment` (optional - may not exist for every call site), M3's
`MemeSafetyOriginalityGateResult`, M6's `MemeRenderResult` (plus M5's `MemeImageGenerationResult`
for the underlying image status), and two new, narrow, deterministic checks this milestone adds
itself (factual alignment, brand fit) that no prior milestone covers.

Precedence (brief's own listed dimensions, evaluated worst-first, mirroring every prior gate's
"hard signal wins regardless" discipline):
1. A BLOCK from M3's safety/originality gate, or a SENSITIVE_BLOCK from M1, is an unconditional
   REJECT - no combination of good scores anywhere else overrides it.
2. A failed image/render status, or a failed contrast/safe-zone check, recommends
   REGENERATE_IMAGE - a rendering-level problem, fixable by a new image.
3. A REVIEW-level *originality* signal (M3's originality check runs against the concept's own
   punchline, not the final copy - a near-duplicate-of-headline concept cannot be fixed by
   rewriting the copy alone) recommends REGENERATE_CONCEPT.
4. A REVIEW-level *safety* or *opportunity* signal, or a failed M7-local check (factual
   alignment/punchline clarity/brand fit), recommends REVIEW - never silently auto-approved.
5. Only when every dimension is clean does the gate return READY_FOR_EDITOR.

Bounded regeneration (brief's own explicit "не делай бесконечных loops" requirement):
`apply_regeneration_bounds()` is a required second step, not optional - it downgrades a
REGENERATE_CONCEPT/REGENERATE_IMAGE recommendation to REJECT once the relevant attempt count
(caller-supplied, from `database.models.meme_candidate.MemeCandidate.concept_regeneration_count`/
`image_regeneration_count`) has already reached its fixed ceiling. `assess_meme_quality()` itself
never loops, never retries, never regenerates anything - it only recommends.
"""
from __future__ import annotations

import re
import unicodedata

from schemas.meme_concept import MemeConcept
from schemas.meme_copy import MemeCopy
from schemas.meme_image import MemeImageGenerationResult, MemeImageStatus
from schemas.meme_opportunity import MemeOpportunityAssessment, MemeOpportunityDecision
from schemas.meme_quality import MemeQualityAssessment, MemeQualityChecks, MemeQualityDecision
from schemas.meme_render import MemeRenderResult, MemeRenderStatus
from schemas.meme_safety import MemeGateDecision, MemeSafetyOriginalityGateResult

POLICY_VERSION = "v1"

MAX_CONCEPT_REGENERATIONS = 1
MAX_IMAGE_REGENERATIONS = 1

_MIN_PUNCHLINE_WORDS = 3
_NUMBER_RE = re.compile(r"\d[\d,.\s]*\d|\d")

# Disclosed-incomplete coarse blocklist (mirrors services/meme_safety.py's own "disclosed
# incomplete list" precedent for the known-meme-template check) - a real, testable signal for
# obviously crude/mean-spirited language, never a general toxicity classifier.
_CRUDE_LANGUAGE_MARKERS = frozenset({
    "idiot", "moron", "stupid", "shut up", "loser", "pathetic", "kill yourself",
})


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split()).lower()


def _extract_numbers(text: str) -> set[str]:
    return {m.group(0).strip() for m in _NUMBER_RE.finditer(text)}


def _check_factual_alignment(concept: MemeConcept, copy: MemeCopy) -> tuple[bool, list[str]]:
    """Coarse, deterministic: every number appearing in the on-image copy text must already
    appear somewhere in the concept's own grounding text (premise/setup/punchline/
    source_fact_links) - catches an outright fabricated statistic being introduced at the
    copywriting stage, never a subtler factual drift (module docstring's own disclosed scope)."""
    concept_text = " ".join([
        concept.premise, concept.setup, concept.punchline, " ".join(concept.source_fact_links),
    ])
    concept_numbers = _extract_numbers(concept_text)
    copy_text = " ".join(filter(None, [copy.top_text, copy.bottom_text, copy.punchline_short]))
    copy_numbers = _extract_numbers(copy_text)

    unattributed = copy_numbers - concept_numbers
    if unattributed:
        return False, ["unattributed_number_in_copy"]
    return True, []


def _check_punchline_clarity(copy: MemeCopy) -> bool:
    return len(copy.punchline_short.split()) >= _MIN_PUNCHLINE_WORDS


def _check_brand_fit(copy: MemeCopy) -> tuple[bool, list[str]]:
    text = _normalize(" ".join(filter(None, [
        copy.top_text, copy.bottom_text, copy.punchline_short, copy.telegram_caption,
    ])))
    hits = [marker for marker in _CRUDE_LANGUAGE_MARKERS if marker in text]
    if hits:
        return False, ["crude_or_mean_spirited_language"]
    return True, []


def assess_meme_quality(
    concept: MemeConcept,
    copy: MemeCopy,
    safety_gate: MemeSafetyOriginalityGateResult,
    render: MemeRenderResult,
    image: MemeImageGenerationResult,
    *,
    opportunity: MemeOpportunityAssessment | None = None,
) -> MemeQualityAssessment:
    reason_codes: list[str] = []

    # --- hard, unconditional signals first ---
    if safety_gate.gate_decision == MemeGateDecision.BLOCK:
        reason_codes.append("safety_originality_gate_blocked")
        return _result(MemeQualityDecision.REJECT, concept, copy, safety_gate, render, image, reason_codes)
    if opportunity is not None and opportunity.decision == MemeOpportunityDecision.SENSITIVE_BLOCK:
        reason_codes.append("opportunity_sensitive_block")
        return _result(MemeQualityDecision.REJECT, concept, copy, safety_gate, render, image, reason_codes)

    # --- image/render failure -> recommend a new image ---
    if image.status == MemeImageStatus.FAILED or render.status == MemeRenderStatus.FAILED:
        reason_codes.append("image_or_render_failed")
        return _result(MemeQualityDecision.REGENERATE_IMAGE, concept, copy, safety_gate, render, image, reason_codes)
    if not render.contrast_passed or render.safe_zone_violations:
        reason_codes.append("render_contrast_or_safe_zone_failed")
        return _result(MemeQualityDecision.REGENERATE_IMAGE, concept, copy, safety_gate, render, image, reason_codes)

    # --- concept-level originality failure -> a new concept, not just new copy, is needed
    # (M3's originality check runs against the concept's own punchline, not the final copy - a
    # near-duplicate-of-headline concept cannot be fixed by rewriting the copy alone). ---
    if safety_gate.originality.decision == MemeGateDecision.REVIEW:
        reason_codes.append("concept_originality_review")
        return _result(
            MemeQualityDecision.REGENERATE_CONCEPT, concept, copy, safety_gate, render, image, reason_codes,
        )

    # --- M7-local checks ---
    factual_ok, factual_reasons = _check_factual_alignment(concept, copy)
    punchline_ok = _check_punchline_clarity(copy)
    brand_ok, brand_reasons = _check_brand_fit(copy)
    reason_codes.extend(factual_reasons)
    reason_codes.extend(brand_reasons)
    if not punchline_ok:
        reason_codes.append("punchline_too_short_to_be_clear")

    # --- soft (review-level) signals ---
    if safety_gate.gate_decision == MemeGateDecision.REVIEW:
        reason_codes.append("safety_originality_gate_review")
    if opportunity is not None and opportunity.decision == MemeOpportunityDecision.REVIEW:
        reason_codes.append("opportunity_review")

    review_triggered = (
        safety_gate.gate_decision == MemeGateDecision.REVIEW
        or (opportunity is not None and opportunity.decision == MemeOpportunityDecision.REVIEW)
        or not factual_ok
        or not punchline_ok
        or not brand_ok
    )
    if review_triggered:
        return _result(MemeQualityDecision.REVIEW, concept, copy, safety_gate, render, image, reason_codes)

    return _result(MemeQualityDecision.READY_FOR_EDITOR, concept, copy, safety_gate, render, image, reason_codes)


def _result(
    decision: MemeQualityDecision,
    concept: MemeConcept,
    copy: MemeCopy,
    safety_gate: MemeSafetyOriginalityGateResult,
    render: MemeRenderResult,
    image: MemeImageGenerationResult,
    reason_codes: list[str],
) -> MemeQualityAssessment:
    factual_ok, _ = _check_factual_alignment(concept, copy)
    brand_ok, _ = _check_brand_fit(copy)
    checks = MemeQualityChecks(
        factual_alignment=factual_ok,
        punchline_clarity=_check_punchline_clarity(copy),
        readability=render.contrast_passed and not render.safe_zone_violations,
        originality=safety_gate.originality.decision == MemeGateDecision.PASS,
        brand_fit=brand_ok,
        meme_safety=safety_gate.safety.decision == MemeGateDecision.PASS,
        visual_quality=image.status == MemeImageStatus.GENERATED and render.status == MemeRenderStatus.RENDERED,
        mobile_friendliness=not render.safe_zone_violations,
    )
    return MemeQualityAssessment(
        policy_version=POLICY_VERSION, decision=decision, checks=checks, reason_codes=reason_codes,
    )


def apply_regeneration_bounds(
    assessment: MemeQualityAssessment, *, concept_regeneration_count: int, image_regeneration_count: int,
) -> MemeQualityAssessment:
    """Required second step (module docstring) - never call `assess_meme_quality()`'s own
    recommendation directly as a final decision without passing it through this function first.
    Downgrades to REJECT once the relevant bound is already exhausted; otherwise returns
    `assessment` completely unchanged (identity-preserving, so a caller that never regenerates
    anything sees byte-identical behavior)."""
    if (
        assessment.decision == MemeQualityDecision.REGENERATE_CONCEPT
        and concept_regeneration_count >= MAX_CONCEPT_REGENERATIONS
    ):
        return MemeQualityAssessment(
            policy_version=assessment.policy_version,
            decision=MemeQualityDecision.REJECT,
            checks=assessment.checks,
            reason_codes=[*assessment.reason_codes, "concept_regeneration_limit_reached"],
        )
    if (
        assessment.decision == MemeQualityDecision.REGENERATE_IMAGE
        and image_regeneration_count >= MAX_IMAGE_REGENERATIONS
    ):
        return MemeQualityAssessment(
            policy_version=assessment.policy_version,
            decision=MemeQualityDecision.REJECT,
            checks=assessment.checks,
            reason_codes=[*assessment.reason_codes, "image_regeneration_limit_reached"],
        )
    return assessment
