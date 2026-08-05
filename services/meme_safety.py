"""Meme Safety & Originality Gate (Phase 18 M3): deterministic, shadow-only review of a
generated `MemeConcept` (docs/phase18_m0_meme_discovery_report.md §4.3, docs/
phase18_m3_meme_safety_originality_report.md).

LLM/cost boundary: zero LLM Gateway calls, zero network calls - a pure function of the concept's
own text plus, optionally, the source NewsEvent title and an already-computed calibrated Fact
Safety status (Phase 15/17's own `services.fact_safety_calibration.calibrate_fact_safety` output -
reused as an input signal, never recomputed here).

Safety reuses `services.meme_opportunity.detect_sensitive_categories()` - the exact same lexicon
M1 scans the source NewsEvent with, applied here to the *generated concept's own text* instead
(a concept can introduce risky framing even when the underlying story itself was clean - the two
scans are complementary, not redundant, and must never drift into two different lexicons).

Originality is necessarily narrow (docs/phase18_m0_meme_discovery_report.md §8 risk 3, a
disclosed permanent limitation): with no external "meme database" to compare against, this module
can only detect (a) the concept explicitly naming/describing a specific, well-known existing meme
template, and (b) the concept's punchline being a near-restatement of the news headline rather
than an original creative transformation. It cannot detect similarity to memes already circulating
elsewhere on the internet.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from core.config import settings
from schemas.meme_concept import MemeConcept
from schemas.meme_safety import (
    MEME_SAFETY_SCHEMA_VERSION,
    MemeGateDecision,
    MemeOriginalityAssessment,
    MemeSafetyAssessment,
    MemeSafetyOriginalityGateResult,
)
from services.meme_opportunity import detect_sensitive_categories

POLICY_VERSION = "v1"

# Disclosed-incomplete list of widely-recognized meme templates (module docstring's own limit) -
# a concept that names/describes one of these is not an original editorial creation, it is a
# reskin of an existing format. English-dominant (internet meme-template names are used in
# English even in Russian-language contexts far more often than they are translated).
_KNOWN_MEME_TEMPLATES = frozenset({
    "distracted boyfriend", "drake meme", "drakeposting", "galaxy brain", "expanding brain",
    "this is fine dog", "this is fine meme", "woman yelling at cat", "stonks meme",
    "surprised pikachu", "hide the pain harold", "change my mind meme", "one does not simply",
    "success kid", "doge meme", "grumpy cat", "pepe the frog", "wojak", "npc meme",
    "spongebob mocking", "bernie sanders mittens",
})


def _compile_template_pattern() -> re.Pattern[str]:
    alternation = "|".join(re.escape(t) for t in sorted(_KNOWN_MEME_TEMPLATES, key=len, reverse=True))
    return re.compile(rf"\b(?:{alternation})\b", re.IGNORECASE)


_TEMPLATE_PATTERN = _compile_template_pattern()
_WORD_RE = re.compile(r"[\w']+", re.UNICODE)


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _concept_text(concept: MemeConcept) -> str:
    return _normalize(
        " ".join([
            concept.premise, concept.setup, concept.punchline, concept.humor_mechanism,
            concept.visual_scene, concept.text_overlay_intent,
            " ".join(concept.characters_objects), " ".join(concept.forbidden_interpretations),
        ])
    ).lower()


def _token_overlap_ratio(a: str, b: str) -> float:
    tokens_a = {t.lower() for t in _WORD_RE.findall(a)}
    tokens_b = {t.lower() for t in _WORD_RE.findall(b)}
    if not tokens_a or not tokens_b:
        return 0.0
    overlap = len(tokens_a & tokens_b)
    return overlap / min(len(tokens_a), len(tokens_b))


def assess_meme_safety(
    concept: MemeConcept, *, calibrated_fact_safety_status: str | None = None,
) -> MemeSafetyAssessment:
    """Pure, deterministic. Sensitivity match in the concept's own text is a hard BLOCK,
    regardless of anything else (mirrors services.fact_safety's own precedence). A calibrated
    Fact Safety "fail" status escalates to BLOCK (the concept is built on a claim Phase 15/17's
    own calibrated audit could not resolve as safe); "review" escalates to at least REVIEW. The
    concept's own `forbidden_interpretations` being non-empty is itself informative (the model
    disclosed a risk) but is deliberately never enough on its own to BLOCK - only to REVIEW - so a
    well-behaved concept that correctly flags a mild risk is not penalized for the disclosure."""
    text = _concept_text(concept)
    sensitivity_categories, evidence = detect_sensitive_categories(text)
    reason_codes: list[str] = []

    if sensitivity_categories:
        reason_codes.extend(f"concept_sensitive_category:{c}" for c in sensitivity_categories)
        return MemeSafetyAssessment(
            decision=MemeGateDecision.BLOCK,
            sensitivity_categories=sensitivity_categories,
            reason_codes=reason_codes,
            evidence=evidence,
        )

    if calibrated_fact_safety_status == "fail":
        reason_codes.append("calibrated_fact_safety_fail")
        return MemeSafetyAssessment(
            decision=MemeGateDecision.BLOCK, sensitivity_categories=[], reason_codes=reason_codes, evidence=evidence,
        )

    decision = MemeGateDecision.PASS
    if calibrated_fact_safety_status == "review":
        decision = MemeGateDecision.REVIEW
        reason_codes.append("calibrated_fact_safety_review")
    if concept.forbidden_interpretations:
        decision = MemeGateDecision.REVIEW
        reason_codes.append("concept_self_flagged_forbidden_interpretation")

    return MemeSafetyAssessment(
        decision=decision, sensitivity_categories=[], reason_codes=reason_codes, evidence=evidence,
    )


def assess_meme_originality(concept: MemeConcept, news_event_title: str) -> MemeOriginalityAssessment:
    """Pure, deterministic. See module docstring for the disclosed scope limit - this can only
    catch a named-template reskin or a headline-restated-as-punchline, never similarity to an
    unknown external meme."""
    text = _concept_text(concept)
    template_matches = sorted({m.group(0).lower() for m in _TEMPLATE_PATTERN.finditer(text)})
    if template_matches:
        return MemeOriginalityAssessment(
            decision=MemeGateDecision.BLOCK,
            reason_codes=["known_meme_template_referenced"],
            evidence=[f"known_template:{t}" for t in template_matches],
        )

    overlap = _token_overlap_ratio(concept.punchline, news_event_title)
    if overlap >= 0.8:
        return MemeOriginalityAssessment(
            decision=MemeGateDecision.REVIEW,
            reason_codes=["punchline_near_duplicate_of_headline"],
            evidence=[f"token_overlap_ratio:{overlap:.2f}"],
        )

    return MemeOriginalityAssessment(decision=MemeGateDecision.PASS, reason_codes=[], evidence=[])


def assess_meme_safety_and_originality(
    concept: MemeConcept, news_event_title: str, *, calibrated_fact_safety_status: str | None = None,
) -> MemeSafetyOriginalityGateResult:
    safety = assess_meme_safety(concept, calibrated_fact_safety_status=calibrated_fact_safety_status)
    originality = assess_meme_originality(concept, news_event_title)

    _RANK = {MemeGateDecision.PASS: 0, MemeGateDecision.REVIEW: 1, MemeGateDecision.BLOCK: 2}
    gate_decision = max((safety.decision, originality.decision), key=lambda d: _RANK[d])

    return MemeSafetyOriginalityGateResult(
        schema_version=MEME_SAFETY_SCHEMA_VERSION,
        policy_version=POLICY_VERSION,
        gate_decision=gate_decision,
        safety=safety,
        originality=originality,
    )


def apply_meme_safety_originality_shadow(
    concept_output: dict[str, Any], news_event_title: str, structured_output: dict[str, Any],
    *, calibrated_fact_safety_status: str | None = None,
) -> dict[str, Any]:
    """Called only from `capabilities/executor.py`, only for the "meme_concept" step, only after
    `MemeConceptCapability`'s own call already succeeded. Returns `structured_output` completely
    unchanged when `meme_safety_gate_mode == "off"` (the default, byte-identical rollback path) -
    mirrors `services.meme_opportunity.apply_meme_opportunity_shadow()`'s own established merge
    convention exactly: purely additive, a single `"meme_safety_originality"` key."""
    if settings.meme_safety_gate_mode == "off":
        return structured_output

    concept = MemeConcept.model_validate(concept_output)
    result = assess_meme_safety_and_originality(
        concept, news_event_title, calibrated_fact_safety_status=calibrated_fact_safety_status,
    )
    return {**structured_output, "meme_safety_originality": result.model_dump(mode="json")}
