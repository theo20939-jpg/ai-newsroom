"""Editorial Brief (Phase 17 M1): a deterministic, shadow-only editorial plan built from data
already available at the "intelligence" workflow step (docs/
phase17_m1_editorial_brief_shadow_report.md).

Root cause this addresses (docs/phase17_m0_output_quality_discovery_report.md §13 items 1/3):
`CopywritingCapability` never sees `NewsEvent.content`, only Research's already-paraphrased
`facts`, and no step anywhere computes an explicit length/structure/completeness target before
generation. This module does not fix that yet (M1 is shadow-only, §19 of the M0 report: "do not
wire this into Copywriting in M1") - it only measures what a brief *would* look like, so M2-M6
can be calibrated against real data instead of guesses.

LLM/cost boundary (M1's own explicit requirement - zero new production API cost): every
content-bearing field here is built from data the "intelligence" step already has for free -
`NewsEventSnapshot` (title/content/summary/url/category) plus `step_results["research"]`
(`facts`/`confidence`/`gaps`) and the just-computed `intelligence` output
(`significance`/`angle`/`audience_relevance`/`recommendation`). Two fields structurally cannot be
filled this way - `subject_explanation`/`background_context` require pretrained world knowledge
an LLM would have to supply, which is exactly the kind of second paid call M1 is forbidden from
adding - so both are always left empty/`None` here, tagged `unavailable`, never fabricated from
whatever text happens to be on hand. Likewise `difference_or_change` requires storyline memory
that does not exist before M7+ and is always left `None`, tagged `unavailable`.

Split, mirroring `services/fact_safety.py`'s own established shape: pure, fully unit-testable
classification/assembly functions (no I/O, no LLM, no DB), plus one thin `apply_editorial_
brief_shadow()` integration function that is the only piece `capabilities/executor.py` calls.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from core.config import settings
from schemas.editorial_brief import (
    EditorialBrief,
    EvidenceSource,
    FieldConfidence,
    FieldProvenance,
    RecommendedFormat,
    SourceSufficiency,
    TargetWordRange,
)

_WORD_RE = re.compile(r"\S+")
_SENTENCE_SPLIT_RE = re.compile(r"[.!?…]+(?:\s|$)")
_NUMBER_RE = re.compile(r"\d[\d,.\s]*\d|\d")
_CURRENCY_RE = re.compile(r"[$€£₽¥]|\b(?:млн|млрд|тыс|USD|EUR|RUB)\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_PERCENT_RE = re.compile(r"\d+([.,]\d+)?\s*%")
_CAPITALIZED_TOKEN_RE = re.compile(r"(?<!^)(?<![.!?…]\s)\b[A-ZА-ЯЁ][a-zа-яё]{2,}\b")

# M5.3-style narrow, explicit keyword list (services/fact_safety.py's own precedent) - a real,
# testable signal for "Research itself flagged disagreement," never a general sentiment/NLI
# classifier. An unlisted synonym simply never triggers CONFLICTING - costs a missed case, never
# risks inventing one.
_CONFLICT_KEYWORDS = (
    "conflict", "contradict", "discrepan", "inconsistent", "disput",
    "противореч", "несоответств", "расхожден",
)

# Below this many words, source content is treated as headline-only even if not a literal
# duplicate of the title - calibrated against docs/phase17_m0_output_quality_discovery_report.md
# §10's real examples ("Comments", "Is that good?", bare-title RSS teasers all sit under 10 words).
_HEADLINE_ONLY_WORD_CEILING = 12
# Below this, content exists and isn't a title-duplicate, but is too thin to call SUFFICIENT.
_PARTIAL_WORD_FLOOR = 30
_PARTIAL_CONCRETE_DETAIL_FLOOR = 1
# SUFFICIENT content this long/detailed can support an EXPLAINER-length brief instead of just
# STANDARD_NEWS - source-driven, not category-driven (M0 §4's own "category has almost no effect
# on length" finding argues against branching on category here).
_EXPLAINER_WORD_FLOOR = 120
_EXPLAINER_SENTENCE_FLOOR = 5

# docs/phase17_m0_output_quality_discovery_report.md §15's own four bands, unchanged here -
# M1 only computes/persists these, never applies them to Copywriting (that is M3's job).
_RANGE_SHORT_UPDATE = TargetWordRange(min_words=90, max_words=140)  # "Simple"
_RANGE_STANDARD_NEWS = TargetWordRange(min_words=140, max_words=220)  # "Normal"
_RANGE_EXPLAINER = TargetWordRange(min_words=220, max_words=320)  # "Complex"
_RANGE_FOLLOW_UP = TargetWordRange(min_words=180, max_words=300)  # "Follow-up" - unreachable in M1
# Below the "Simple" floor, deliberately: §10/§15 - "do not force artificial expansion" of a
# thin/conflicting source. Anchored a little above the real historical median (33 words, M0 §4)
# to allow a slightly fuller honest answer without demanding the 90-word Simple floor no thin
# source can responsibly reach.
_RANGE_INSUFFICIENT = TargetWordRange(min_words=40, max_words=90)
_RANGE_REJECT = TargetWordRange(min_words=0, max_words=0)


def _word_count(text: str | None) -> int:
    if not text:
        return 0
    return len(_WORD_RE.findall(text))


def _sentence_count(text: str | None) -> int:
    if not text or not text.strip():
        return 0
    parts = [p for p in _SENTENCE_SPLIT_RE.split(text.strip()) if p.strip()]
    return max(1, len(parts))


def _concrete_details_count(text: str | None) -> int:
    if not text:
        return 0
    count = 0
    count += len(_NUMBER_RE.findall(text))
    count += len(_CURRENCY_RE.findall(text))
    count += len(_YEAR_RE.findall(text))
    count += len(_PERCENT_RE.findall(text))
    count += len(set(_CAPITALIZED_TOKEN_RE.findall(text)))
    return count


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = item.strip() if isinstance(item, str) else ""
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _has_conflict_signal(research_gaps: list[str]) -> bool:
    return any(keyword in gap.lower() for gap in research_gaps for keyword in _CONFLICT_KEYWORDS)


class _SourceAssessment:
    """Internal, not part of the public schema - the raw signals `classify_source_sufficiency()`
    computed, reused by `recommend_format_and_range()` so both stay consistent without
    recomputing word/sentence counts twice."""

    __slots__ = ("sufficiency", "reason_codes", "word_count", "sentence_count", "concrete_details")

    def __init__(
        self, sufficiency: SourceSufficiency, reason_codes: list[str],
        word_count: int, sentence_count: int, concrete_details: int,
    ) -> None:
        self.sufficiency = sufficiency
        self.reason_codes = reason_codes
        self.word_count = word_count
        self.sentence_count = sentence_count
        self.concrete_details = concrete_details


def classify_source_sufficiency(
    title: str, content: str | None, research_facts: list[str], research_gaps: list[str],
) -> _SourceAssessment:
    """Pure, deterministic. Never treats raw length as automatically sufficient (docs/
    phase17_m0_output_quality_discovery_report.md §10's own explicit warning) - a headline
    repeated verbatim in a longer wrapper is still HEADLINE_ONLY."""
    if not title or not title.strip():
        return _SourceAssessment(SourceSufficiency.UNKNOWN, ["missing_title"], 0, 0, 0)

    if _has_conflict_signal(research_gaps):
        return _SourceAssessment(
            SourceSufficiency.CONFLICTING, ["research_flagged_conflict"],
            _word_count(content), _sentence_count(content), _concrete_details_count(content),
        )

    content_stripped = (content or "").strip()
    if not content_stripped:
        if research_facts:
            return _SourceAssessment(SourceSufficiency.PARTIAL, ["no_content", "research_facts_available"], 0, 0, 0)
        return _SourceAssessment(SourceSufficiency.EMPTY, ["no_content", "no_research_facts"], 0, 0, 0)

    norm_title = _normalize(title)
    norm_content = _normalize(content_stripped)
    if norm_content == norm_title:
        return _SourceAssessment(SourceSufficiency.HEADLINE_ONLY, ["content_equals_title"], 0, 0, 0)
    if norm_content.startswith(norm_title) and (len(norm_content) - len(norm_title)) < 20:
        return _SourceAssessment(SourceSufficiency.HEADLINE_ONLY, ["content_is_title_plus_suffix"], 0, 0, 0)

    word_count = _word_count(content_stripped)
    sentence_count = _sentence_count(content_stripped)
    concrete_details = _concrete_details_count(content_stripped)
    reason_codes = [f"word_count={word_count}", f"sentence_count={sentence_count}", f"concrete_details={concrete_details}"]

    if word_count < _HEADLINE_ONLY_WORD_CEILING:
        return _SourceAssessment(
            SourceSufficiency.HEADLINE_ONLY, reason_codes + ["content_too_short"],
            word_count, sentence_count, concrete_details,
        )
    if word_count < _PARTIAL_WORD_FLOOR or concrete_details < _PARTIAL_CONCRETE_DETAIL_FLOOR:
        return _SourceAssessment(
            SourceSufficiency.PARTIAL, reason_codes + ["below_sufficient_threshold"],
            word_count, sentence_count, concrete_details,
        )
    return _SourceAssessment(
        SourceSufficiency.SUFFICIENT, reason_codes, word_count, sentence_count, concrete_details,
    )


def recommend_format_and_range(assessment: _SourceAssessment) -> tuple[RecommendedFormat, TargetWordRange, list[str]]:
    """Pure, deterministic. `reject_candidate` reflects source-material insufficiency only -
    never channel/topic relevance, which stays entirely out of scope for M1/this function (docs/
    phase17_m0_output_quality_discovery_report.md §11's "must not conflate" warning)."""
    sufficiency = assessment.sufficiency
    if sufficiency == SourceSufficiency.EMPTY:
        return RecommendedFormat.REJECT_CANDIDATE, _RANGE_REJECT, ["no_content_no_facts"]
    if sufficiency == SourceSufficiency.UNKNOWN:
        return RecommendedFormat.REJECT_CANDIDATE, _RANGE_REJECT, ["sufficiency_unknown"]
    if sufficiency == SourceSufficiency.HEADLINE_ONLY:
        return RecommendedFormat.INSUFFICIENT_SOURCE, _RANGE_INSUFFICIENT, ["headline_only_do_not_expand"]
    if sufficiency == SourceSufficiency.CONFLICTING:
        return RecommendedFormat.INSUFFICIENT_SOURCE, _RANGE_INSUFFICIENT, ["conflicting_evidence_needs_review"]
    if sufficiency == SourceSufficiency.PARTIAL:
        return RecommendedFormat.SHORT_UPDATE, _RANGE_SHORT_UPDATE, ["partial_source_short_update"]
    # SUFFICIENT
    if assessment.word_count >= _EXPLAINER_WORD_FLOOR or assessment.sentence_count >= _EXPLAINER_SENTENCE_FLOOR:
        return RecommendedFormat.EXPLAINER, _RANGE_EXPLAINER, ["rich_source_explainer"]
    return RecommendedFormat.STANDARD_NEWS, _RANGE_STANDARD_NEWS, ["sufficient_source_standard_news"]


def build_editorial_brief(
    news_event_title: str,
    news_event_content: str | None,
    research_output: dict[str, Any],
    intelligence_output: dict[str, Any],
) -> EditorialBrief:
    """Pure. No I/O, no LLM call, deterministic: identical inputs always produce an identical
    output (idempotent by construction - re-running the same task's "intelligence" step, e.g. on
    retry, produces byte-identical brief content)."""
    research_facts = _dedupe_preserve_order(
        [f for f in research_output.get("facts", []) if isinstance(f, str)]
        if isinstance(research_output.get("facts"), list) else []
    )
    research_gaps = _dedupe_preserve_order(
        [g for g in research_output.get("gaps", []) if isinstance(g, str)]
        if isinstance(research_output.get("gaps"), list) else []
    )

    assessment = classify_source_sufficiency(news_event_title, news_event_content, research_facts, research_gaps)
    recommended_format, target_word_range, format_reason_codes = recommend_format_and_range(assessment)

    evidence_notes: dict[str, FieldProvenance] = {}

    # headline_fact: a pick, never a generation - facts[0] when Research produced anything,
    # otherwise the title verbatim (docs §14's own table).
    if research_facts:
        headline_fact: str | None = research_facts[0]
        evidence_notes["headline_fact"] = FieldProvenance(
            confidence=FieldConfidence.CONFIRMED, source="research", reason_codes=["research_facts_0"],
        )
    else:
        headline_fact = news_event_title
        evidence_notes["headline_fact"] = FieldProvenance(
            confidence=FieldConfidence.CONFIRMED, source="news_event", reason_codes=["fallback_to_title"],
        )

    # event_details: Research's own facts, deduped - never re-derived from raw content (Research
    # already did that extraction; re-parsing news_event_content here would risk disagreeing
    # with Research's own already-recorded judgment of what the facts are).
    event_details = research_facts
    evidence_notes["event_details"] = FieldProvenance(
        confidence=FieldConfidence.CONFIRMED if research_facts else FieldConfidence.UNKNOWN,
        source="research" if research_facts else "none",
        reason_codes=[] if research_facts else ["no_research_facts"],
    )

    # subject_explanation/background_context/difference_or_change: structurally unavailable
    # without a new LLM call or storyline memory - never fabricated (module docstring).
    evidence_notes["subject_explanation"] = FieldProvenance(
        confidence=FieldConfidence.UNAVAILABLE, source="none", reason_codes=["requires_llm_not_available_in_m1"],
    )
    evidence_notes["background_context"] = FieldProvenance(
        confidence=FieldConfidence.UNAVAILABLE, source="none", reason_codes=["requires_llm_not_available_in_m1"],
    )
    evidence_notes["difference_or_change"] = FieldProvenance(
        confidence=FieldConfidence.UNAVAILABLE, source="none", reason_codes=["no_storyline_memory_m1"],
    )

    # why_it_matters: Intelligence's own significance/angle judgments, already produced upstream
    # (this "intelligence" step's own just-computed output) - surfaced, not re-generated.
    significance = intelligence_output.get("significance")
    angle = intelligence_output.get("angle")
    why_it_matters = [v.strip() for v in (significance, angle) if isinstance(v, str) and v.strip()]
    evidence_notes["why_it_matters"] = FieldProvenance(
        confidence=FieldConfidence.CONFIRMED if why_it_matters else FieldConfidence.UNKNOWN,
        source="intelligence",
        reason_codes=[] if why_it_matters else ["significance_and_angle_empty"],
    )

    # what_next: Intelligence's own recommendation only - deliberately NOT Research's gaps
    # (those describe missing information, tracked separately in `uncertainties`; conflating
    # "what we don't know" with "what happens next" would blur two different concepts).
    recommendation = intelligence_output.get("recommendation")
    what_next = [recommendation.strip()] if isinstance(recommendation, str) and recommendation.strip() else []
    evidence_notes["what_next"] = FieldProvenance(
        confidence=FieldConfidence.CONFIRMED if what_next else FieldConfidence.UNKNOWN,
        source="intelligence",
        reason_codes=[] if what_next else ["recommendation_empty"],
    )

    # uncertainties: Research's own gaps directly (docs §14: "already exists, just unused"),
    # plus an honest, fixed meta-note when the source itself is thin/conflicting/unknown - a
    # statement about this brief's own confidence, not a claim about the news event, so it
    # carries no fabrication risk.
    uncertainties = list(research_gaps)
    thin_source_states = {
        SourceSufficiency.HEADLINE_ONLY, SourceSufficiency.EMPTY,
        SourceSufficiency.CONFLICTING, SourceSufficiency.UNKNOWN,
    }
    added_thin_source_note = False
    if assessment.sufficiency in thin_source_states:
        uncertainties.append(
            "Source material is limited (source_sufficiency="
            f"{assessment.sufficiency.value}); most specifics are unconfirmed."
        )
        added_thin_source_note = True
    uncertainties_confidence: FieldConfidence
    uncertainties_source: EvidenceSource
    if research_gaps:
        uncertainties_confidence, uncertainties_source = FieldConfidence.CONFIRMED, "research"
    elif added_thin_source_note:
        uncertainties_confidence, uncertainties_source = FieldConfidence.INFERRED, "derived"
    else:
        uncertainties_confidence, uncertainties_source = FieldConfidence.UNKNOWN, "none"
    evidence_notes["uncertainties"] = FieldProvenance(
        confidence=uncertainties_confidence, source=uncertainties_source,
        reason_codes=["research_gaps"] if research_gaps else [],
    )

    evidence_notes["recommended_format"] = FieldProvenance(
        confidence=FieldConfidence.INFERRED, source="derived", reason_codes=format_reason_codes,
    )
    evidence_notes["target_word_range"] = FieldProvenance(
        confidence=FieldConfidence.INFERRED, source="derived", reason_codes=format_reason_codes,
    )
    evidence_notes["source_sufficiency"] = FieldProvenance(
        confidence=FieldConfidence.INFERRED, source="derived", reason_codes=assessment.reason_codes,
    )

    return EditorialBrief(
        headline_fact=headline_fact,
        subject_explanation=None,
        event_details=event_details,
        background_context=[],
        difference_or_change=None,
        why_it_matters=why_it_matters,
        what_next=what_next,
        uncertainties=uncertainties,
        recommended_format=recommended_format,
        target_word_range=target_word_range,
        source_sufficiency=assessment.sufficiency,
        source_sufficiency_reason_codes=assessment.reason_codes,
        evidence_notes=evidence_notes,
    )


_CONTENT_BEARING_FIELDS = (
    "headline_fact", "subject_explanation", "event_details", "background_context",
    "difference_or_change", "why_it_matters", "what_next", "uncertainties",
)


def populated_field_count(brief: EditorialBrief) -> int:
    """Count of the 8 content-bearing fields (docs §14's table, excluding the always-populated
    classification fields `recommended_format`/`target_word_range`/`source_sufficiency`) that
    ended up non-empty - a coarse "how much did we actually manage to say" signal for logging."""
    return sum(1 for name in _CONTENT_BEARING_FIELDS if getattr(brief, name))


def apply_editorial_brief_shadow(
    news_event_title: str,
    news_event_content: str | None,
    research_output: dict[str, Any],
    structured_output: dict[str, Any],
) -> dict[str, Any]:
    """Called only from `capabilities/executor.py`, only for the "intelligence" step, only after
    IntelligenceCapability's own call (or a reused prior result) already succeeded.
    `structured_output` IS Intelligence's own just-produced output - used both as the brief's
    `intelligence_output` input and as the base dict this merges into, mirroring `services.
    fact_safety.apply_fact_safety()`'s own established merge convention exactly.

    Returns `structured_output` completely unchanged when `editorial_brief_mode == "off"` (the
    default, byte-identical-to-pre-M1 rollback path). This function itself never raises for
    well-formed input - `capabilities/executor.py` additionally wraps the call site in a
    try/except (matching `_attach_image_intelligence()`'s own "must not affect delivery"
    discipline) so even an unexpected error here can never fail the "intelligence" step.
    """
    if settings.editorial_brief_mode == "off":
        return structured_output

    brief = build_editorial_brief(news_event_title, news_event_content, research_output, structured_output)
    return {**structured_output, "editorial_brief": brief.model_dump(mode="json")}
