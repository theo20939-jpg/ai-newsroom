"""Adaptive Length (Phase 17 M3): a deterministic, shadow/comparison-only length and structure
plan for one NewsEvent (docs/phase17_m3_adaptive_length_shadow_comparison_report.md).

Root cause this addresses (docs/phase17_m0_output_quality_discovery_report.md §13 item 3): no
step anywhere computes an explicit length/structure target before generation - `prompts/
copywriting/v3.yaml` only says "suitable for a short social post," and the only real length
enforcement is `bot/formatting.py`'s post-hoc, delivery-time shrink-to-fit. This module does not
change that (M3 is shadow/comparison-only - production `CopywritingCapability` is completely
untouched); it only computes what a length target *should* be, calibrated against real Telegram
constraints and Phase 17 M1's own `EditorialBrief`, so M4+ can decide whether/how to apply it.

LLM/cost boundary: `build_adaptive_length_plan()` calls `services.editorial_brief.
build_editorial_brief()` directly (a pure function, zero new LLM call) rather than depending on
`editorial_brief_mode` being `"shadow"` - the same "each M-milestone independently computable from
already-persisted data" pattern M2 established for `classify_source_sufficiency()`. Zero LLM
Gateway calls, zero network calls, zero DB queries live anywhere in this module.

Split, mirroring `services/editorial_brief.py`'s/`services/channel_relevance.py`'s own shape:
pure classification/assembly functions, plus one thin `apply_adaptive_length_shadow()`
integration function that is the only piece `capabilities/executor.py` calls.
"""
from __future__ import annotations

import re
from typing import Any

from core.config import settings
from schemas.adaptive_length import (
    ADAPTIVE_LENGTH_POLICY_VERSION,
    AdaptiveLengthPlan,
    Complexity,
    DeliveryMode,
    LengthConfidence,
    PlanSection,
)
from schemas.editorial_brief import EditorialBrief, RecommendedFormat, SourceSufficiency
from services.editorial_brief import build_editorial_brief

# Calibrated against docs/phase17_m0_output_quality_discovery_report.md §15's real corpus
# measurement ("median real body is 248 characters... ~7.5 chars/word in this Cyrillic-heavy
# corpus") - reused unchanged for consistency across the whole Phase 17 arc, not re-derived.
_CHARS_PER_WORD = 7.5

# docs/phase17_m0_output_quality_discovery_report.md §15's own four bands, recalibrated here with
# an explicit target (this report's own contribution - M0 only gave min/max) roughly at the
# lower third of each band, matching the same report's own finding that current real output
# clusters far below every band's ceiling - a target near the floor is a realistic near-term
# goal, not the band's own maximum.
_WORD_RANGES: dict[Complexity, tuple[int, int, int]] = {  # (min, target, max)
    Complexity.SIMPLE: (90, 115, 140),
    Complexity.NORMAL: (140, 180, 220),
    Complexity.COMPLEX: (220, 270, 320),
    Complexity.FOLLOW_UP: (180, 230, 300),  # unreachable in M3 - no storyline memory (§ below)
    Complexity.INSUFFICIENT: (40, 65, 90),  # mirrors EditorialBrief's own INSUFFICIENT_SOURCE range
}

_PARAGRAPH_TARGET: dict[Complexity, int] = {
    Complexity.SIMPLE: 1, Complexity.NORMAL: 2, Complexity.COMPLEX: 3,
    Complexity.FOLLOW_UP: 2, Complexity.INSUFFICIENT: 1,
}

# Real, measured Telegram-side reserve (docs/phase17_m3_adaptive_length_shadow_comparison_report.md
# §12): header emoji+category+date (~39 chars) + NewsEvent.title (real DB max observed: 120 chars
# across 2000 rows, p95/p99 118/119 - suspiciously exactly capped, likely truncated upstream, but
# taken as the real ceiling either way) + a "\n\n" separator (2) + draft title wrapped in <b></b>
# (real max observed 84 chars + 7 markup = 91) + a "\n\n" separator (2) + a "\n\n" separator before
# hashtags (2) + hashtags line (real max observed 83 chars) = 39+120+2+91+2+2+83 = 339, rounded up
# for HTML-escaping expansion (&/</> can each grow) and future-headline headroom.
_TELEGRAM_RESERVE_CHARS = 360

_REGULATION_KEYWORDS = frozenset({
    "antitrust", "regulation", "lawsuit", "court", "investigation", "fine", "закон",
    "регулирован", "суд", "иск", "штраф", "расследование", "антимонопольн",
})
_JARGON_TOKEN_RE = re.compile(r"\b[A-Z]{3,}\b")
_ENTITY_TOKEN_RE = re.compile(r"(?<!^)(?<![.!?…]\s)\b[A-ZА-ЯЁ][a-zа-яё]{2,}\b")

_THIN_SUFFICIENCY = {
    SourceSufficiency.HEADLINE_ONLY, SourceSufficiency.EMPTY,
    SourceSufficiency.CONFLICTING, SourceSufficiency.UNKNOWN,
}


def _joined_evidence_text(brief: EditorialBrief) -> str:
    parts = [brief.headline_fact or "", *brief.event_details, *brief.why_it_matters, *brief.what_next]
    return " ".join(p for p in parts if p)


def determine_complexity(brief: EditorialBrief) -> tuple[Complexity, list[str]]:
    """Pure, deterministic. Source sufficiency always wins over richness signals (M3's own
    "length never outranks Fact Safety" rule, applied here as "thin source always caps
    complexity, regardless of how many enrichment signals look present") - a thin source cannot
    be scored COMPLEX no matter how many entities/keywords happen to match."""
    if brief.source_sufficiency in _THIN_SUFFICIENCY:
        return Complexity.INSUFFICIENT, ["thin_source_forces_insufficient"]

    base_by_format: dict[RecommendedFormat, Complexity] = {
        RecommendedFormat.SHORT_UPDATE: Complexity.SIMPLE,
        RecommendedFormat.STANDARD_NEWS: Complexity.NORMAL,
        RecommendedFormat.EXPLAINER: Complexity.COMPLEX,
        RecommendedFormat.FOLLOW_UP: Complexity.FOLLOW_UP,
        RecommendedFormat.INSUFFICIENT_SOURCE: Complexity.INSUFFICIENT,
        RecommendedFormat.REJECT_CANDIDATE: Complexity.INSUFFICIENT,
    }
    base = base_by_format[brief.recommended_format]
    reason_codes = [f"base_from_recommended_format={brief.recommended_format.value}"]
    if base in (Complexity.INSUFFICIENT, Complexity.FOLLOW_UP):
        return base, reason_codes

    text = _joined_evidence_text(brief)
    entities = set(_ENTITY_TOKEN_RE.findall(text))
    jargon_count = len(_JARGON_TOKEN_RE.findall(text))
    has_regulation_signal = any(kw in text.lower() for kw in _REGULATION_KEYWORDS)

    enrichment_score = 0
    if brief.why_it_matters:
        enrichment_score += 1
        reason_codes.append("why_it_matters_present")
    if brief.what_next:
        enrichment_score += 1
        reason_codes.append("what_next_present")
    if has_regulation_signal:
        enrichment_score += 1
        reason_codes.append("regulation_legal_signal")
    if jargon_count >= 2:
        enrichment_score += 1
        reason_codes.append("technical_jargon_signal")
    if len(entities) >= 3:
        enrichment_score += 1
        reason_codes.append("multi_party_entities")

    if base == Complexity.SIMPLE and enrichment_score >= 3:
        reason_codes.append("enriched_signals_upgrade_simple_to_normal")
        return Complexity.NORMAL, reason_codes
    if base == Complexity.NORMAL and enrichment_score >= 4:
        reason_codes.append("enriched_signals_upgrade_normal_to_complex")
        return Complexity.COMPLEX, reason_codes
    return base, reason_codes


def _word_range_for(complexity: Complexity, source_sufficiency: SourceSufficiency) -> tuple[int, int, int, list[str], list[str]]:
    """Returns (min, target, max, reason_codes, safety_constraints). PARTIAL sufficiency lowers
    the target toward the floor without changing min/max - M3's own "не требовать заполнения
    отсутствующего контекста... явно запретить раздувание текста" rule - never an artificial
    minimum for a thin source (INSUFFICIENT's own band already reflects that)."""
    min_words, target_words, max_words = _WORD_RANGES[complexity]
    reason_codes: list[str] = []
    safety_constraints: list[str] = []

    if source_sufficiency == SourceSufficiency.PARTIAL and complexity != Complexity.INSUFFICIENT:
        lowered_target = min_words + round((target_words - min_words) * 0.5)
        reason_codes.append(f"partial_source_target_lowered_from_{target_words}_to_{lowered_target}")
        safety_constraints.append("no_padding_partial_source")
        target_words = lowered_target

    if source_sufficiency == SourceSufficiency.CONFLICTING:
        safety_constraints.append("do_not_amplify_conflicting_claims")
    if source_sufficiency == SourceSufficiency.EMPTY:
        safety_constraints.append("empty_source_skip_comparison_candidate")

    return min_words, target_words, max_words, reason_codes, safety_constraints


def determine_delivery(
    target_words: int, max_words: int, has_image_candidate: bool | None,
) -> tuple[DeliveryMode, int, list[str]]:
    """Pure, deterministic. `has_image_candidate=None` means Image Intelligence has not run
    (mode off, or this plan is built before that step) - `DeliveryMode.UNKNOWN`, and the smaller
    (photo-caption-sized) budget is used defensively, never the larger text budget, so a later
    reader is never told more room exists than might actually be safe.

    A candidate that would not fit a photo caption at its own *target* length recommends
    TEXT_MESSAGE outright (never a shrunk word range to force-fit a caption) - M0 §15's own
    "make has-image an input... so a genuinely complex story is allowed to drop the image rather
    than truncate the text" recommendation, resolved here as a concrete product decision."""
    from bot.formatting import SAFE_LIMIT
    from bot.image_preview_formatting import CAPTION_SAFE_LIMIT

    reason_codes: list[str] = []
    target_chars = target_words * _CHARS_PER_WORD

    if has_image_candidate is None:
        reason_codes.append("delivery_mode_unknown_conservative_budget")
        return DeliveryMode.UNKNOWN, CAPTION_SAFE_LIMIT - _TELEGRAM_RESERVE_CHARS, reason_codes

    if has_image_candidate and target_chars + _TELEGRAM_RESERVE_CHARS <= CAPTION_SAFE_LIMIT:
        reason_codes.append("fits_photo_caption_at_target")
        return DeliveryMode.PHOTO_CAPTION, CAPTION_SAFE_LIMIT - _TELEGRAM_RESERVE_CHARS, reason_codes

    if has_image_candidate:
        reason_codes.append("exceeds_photo_caption_recommend_text_over_truncation")
    else:
        reason_codes.append("no_image_candidate")
    return DeliveryMode.TEXT_MESSAGE, SAFE_LIMIT - _TELEGRAM_RESERVE_CHARS, reason_codes


def _plan_sections(brief: EditorialBrief, complexity: Complexity) -> tuple[list[PlanSection], list[PlanSection], list[PlanSection]]:
    """Every section beyond HEADLINE/LEAD is only ever required/optional when the brief actually
    has real evidence for it - never fabricated to fill a template slot (M3's own "natural
    structure, not a mechanical checklist" rule). `subject_explanation`/`background_context` are
    always empty in the current EditorialBrief (Phase 17 M1's own LLM/cost boundary - see
    services/editorial_brief.py) and therefore always land in `omitted`, never `required`, today -
    a structurally guaranteed non-fabrication property, not a coincidence."""
    has_details = bool(brief.event_details)
    has_subject = bool(brief.subject_explanation)
    has_background = bool(brief.background_context)
    has_why = bool(brief.why_it_matters)
    has_next = bool(brief.what_next)
    has_uncertainty = bool(brief.uncertainties)

    required = [PlanSection.LEAD]
    optional: list[PlanSection] = []
    omitted: list[PlanSection] = []

    def _place(section: PlanSection, available: bool, tier: str) -> None:
        if not available:
            omitted.append(section)
        elif tier == "required":
            required.append(section)
        else:
            optional.append(section)

    if complexity == Complexity.INSUFFICIENT:
        _place(PlanSection.EVENT_DETAILS, has_details, "optional")
        _place(PlanSection.UNCERTAINTY_NOTE, has_uncertainty, "optional")
        omitted.extend([PlanSection.SUBJECT_EXPLANATION, PlanSection.BACKGROUND_CONTEXT, PlanSection.WHY_IT_MATTERS, PlanSection.WHAT_NEXT])
    elif complexity == Complexity.SIMPLE:
        _place(PlanSection.EVENT_DETAILS, has_details, "optional")
        _place(PlanSection.WHY_IT_MATTERS, has_why, "optional")
        omitted.extend([PlanSection.SUBJECT_EXPLANATION, PlanSection.BACKGROUND_CONTEXT, PlanSection.WHAT_NEXT])
        _place(PlanSection.UNCERTAINTY_NOTE, has_uncertainty, "optional")
    elif complexity == Complexity.NORMAL:
        _place(PlanSection.EVENT_DETAILS, has_details, "required")
        _place(PlanSection.SUBJECT_EXPLANATION, has_subject, "optional")
        _place(PlanSection.BACKGROUND_CONTEXT, has_background, "optional")
        _place(PlanSection.WHY_IT_MATTERS, has_why, "optional")
        _place(PlanSection.WHAT_NEXT, has_next, "optional")
        _place(PlanSection.UNCERTAINTY_NOTE, has_uncertainty, "optional")
    elif complexity == Complexity.COMPLEX:
        _place(PlanSection.EVENT_DETAILS, has_details, "required")
        _place(PlanSection.WHY_IT_MATTERS, has_why, "required")
        _place(PlanSection.SUBJECT_EXPLANATION, has_subject, "optional")
        _place(PlanSection.BACKGROUND_CONTEXT, has_background, "optional")
        _place(PlanSection.WHAT_NEXT, has_next, "optional")
        _place(PlanSection.UNCERTAINTY_NOTE, has_uncertainty, "optional")
    else:  # FOLLOW_UP - unreachable in M3, defined for schema completeness only
        _place(PlanSection.WHAT_NEXT, has_next, "required")
        _place(PlanSection.EVENT_DETAILS, has_details, "optional")
        _place(PlanSection.WHY_IT_MATTERS, has_why, "optional")
        omitted.extend([PlanSection.SUBJECT_EXPLANATION, PlanSection.BACKGROUND_CONTEXT])
        _place(PlanSection.UNCERTAINTY_NOTE, has_uncertainty, "optional")

    return required, optional, omitted


def _plan_confidence(brief: EditorialBrief, complexity: Complexity) -> LengthConfidence:
    if complexity == Complexity.INSUFFICIENT:
        return LengthConfidence.LOW
    if brief.source_sufficiency == SourceSufficiency.SUFFICIENT and len(brief.event_details) >= 2:
        return LengthConfidence.HIGH
    return LengthConfidence.MEDIUM


def build_adaptive_length_plan(
    news_event_title: str,
    news_event_content: str | None,
    research_output: dict[str, Any],
    intelligence_output: dict[str, Any],
    *,
    has_image_candidate: bool | None,
) -> AdaptiveLengthPlan:
    """Pure. No I/O, no LLM call, deterministic: identical inputs always produce an identical
    output (idempotent by construction)."""
    brief = build_editorial_brief(news_event_title, news_event_content, research_output, intelligence_output)
    complexity, complexity_reason_codes = determine_complexity(brief)
    min_words, target_words, max_words, range_reason_codes, safety_constraints = _word_range_for(
        complexity, brief.source_sufficiency,
    )
    delivery_mode, hard_character_limit, delivery_reason_codes = determine_delivery(
        target_words, max_words, has_image_candidate,
    )
    required_sections, optional_sections, omitted_sections = _plan_sections(brief, complexity)
    detail_target = min(len(brief.event_details), {
        Complexity.SIMPLE: 2, Complexity.NORMAL: 4, Complexity.COMPLEX: 6,
        Complexity.FOLLOW_UP: 4, Complexity.INSUFFICIENT: 1,
    }[complexity])

    if brief.source_sufficiency in _THIN_SUFFICIENCY:
        safety_constraints.append("no_fabrication_thin_source")
        safety_constraints.append("do_not_repeat_single_idea_to_reach_length")

    return AdaptiveLengthPlan(
        policy_version=ADAPTIVE_LENGTH_POLICY_VERSION,
        recommended_format=brief.recommended_format,
        complexity=complexity,
        source_sufficiency=brief.source_sufficiency,
        min_words=min_words,
        target_words=target_words,
        max_words=max_words,
        hard_character_limit=round(hard_character_limit),
        delivery_mode=delivery_mode,
        paragraph_target=_PARAGRAPH_TARGET[complexity],
        detail_target=detail_target,
        required_sections=required_sections,
        optional_sections=optional_sections,
        omitted_sections=omitted_sections,
        reason_codes=[*complexity_reason_codes, *range_reason_codes, *delivery_reason_codes],
        confidence=_plan_confidence(brief, complexity),
        safety_constraints=safety_constraints,
    )


def apply_adaptive_length_shadow(
    news_event_title: str,
    news_event_content: str | None,
    research_output: dict[str, Any],
    intelligence_output: dict[str, Any],
    has_image_candidate: bool | None,
    structured_output: dict[str, Any],
) -> dict[str, Any]:
    """Called only from `capabilities/executor.py`, only for the "copywriting" step (after Image
    Intelligence's own attach in that same step, so `has_image_candidate` reflects real data),
    only when `adaptive_length_mode != "off"`. Returns `structured_output` completely unchanged
    when off (the default, byte-identical-to-pre-M3 rollback path). Purely additive merge -
    mirrors `apply_editorial_brief_shadow()`'s/`apply_channel_relevance_shadow()`'s own
    established convention exactly."""
    if settings.adaptive_length_mode == "off":
        return structured_output

    plan = build_adaptive_length_plan(
        news_event_title, news_event_content, research_output, intelligence_output,
        has_image_candidate=has_image_candidate,
    )
    return {**structured_output, "adaptive_length_plan": plan.model_dump(mode="json")}
