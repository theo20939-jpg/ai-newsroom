"""Beginner-Friendly Copywriting (Phase 17 M4): a deterministic, shadow/comparison-only plan for
how much explanation a candidate post may safely add, and how much length that explanation
realistically supports (docs/phase17_m4_beginner_friendly_copywriting_report.md).

Root cause this addresses (M3's own central finding, `docs/
phase17_m3_adaptive_length_shadow_comparison_report.md` §25): candidates consistently stopped
well short of their own `min_words` floor for `normal`/`complex` complexity, even with real
evidence available (the arXiv/MLIP case reached only 193 of its own 220-word floor despite having
9 real event_details). Root-caused (this milestone's own discovery note) to the M3 candidate
prompt's own asymmetric "stop naturally... even if short of the target" instruction, not to
`max_tokens` (real usage sat far below the cap in every case checked) or schema/parsing
truncation. M4's fix has two parts: (1) an explicit, bounded budget for beginner-friendly
explanation, so the candidate has a *positive* reason to write more, grounded in real evidence;
(2) a "safe range" that is explicitly bounded by how much real evidence actually exists (§ below),
so the target the candidate is asked to reach is one the evidence can actually support - removing
the false conflict M3's own report named between "ideal" length and real available facts.

LLM/cost boundary: `build_beginner_friendly_plan()` calls `services.editorial_brief.
build_editorial_brief()` and `services.adaptive_length.build_adaptive_length_plan()` directly (both
pure functions, zero new LLM calls) rather than depending on `editorial_brief_mode`/`adaptive_
length_mode` being on - the same "independently computable from already-persisted data" pattern
M2/M3 established. Subject/term explanations are drawn only from real evidence text or
`services.editorial_glossary`'s small, versioned, hand-reviewed glossary - never from the model's
own general knowledge (there is no LLM call in this module at all).
"""
from __future__ import annotations

import re
from typing import Any

from core.config import settings

from schemas.adaptive_length import Complexity
from schemas.beginner_friendly import (
    BEGINNER_FRIENDLY_POLICY_VERSION,
    AudienceLevel,
    BeginnerFriendlyPlan,
    JargonRisk,
    WordRange,
)
from schemas.editorial_brief import EditorialBrief, SourceSufficiency
from services.adaptive_length import build_adaptive_length_plan
from services.channel_profiles import AI_GADGETS_CHANNEL_PROFILE
from services.editorial_brief import build_editorial_brief
from services.editorial_glossary import lookup

# This channel's own already-documented audience (services/channel_profiles.py's own
# "tech-interested general readers" editorial policy, Phase 17 M2) - reused, not re-decided here.
_AUDIENCE_LEVEL = AudienceLevel.TECH_INTERESTED if "tech-interested" in AI_GADGETS_CHANNEL_PROFILE.audience else AudienceLevel.GENERAL

# Entities so widely known to a tech-interested general reader that naming them needs no
# explanation - a short, explicit, hand-reviewed list (mirrors services/channel_relevance.py's
# own _ENTITY_HINTS "no bare company name drives a decision" discipline, applied here to the
# opposite question: which names are safe to leave UNexplained).
_ASSUMED_KNOWLEDGE_ENTITIES = frozenset({
    # Mirrors services/channel_relevance.py's own already-reviewed _ENTITY_HINTS list (Phase 17
    # M2) for consistency - the same "well-known enough" judgment, reused, not re-decided here.
    "apple", "google", "microsoft", "meta", "amazon", "netflix", "samsung", "nvidia", "tsmc",
    "intel", "amd", "openai", "anthropic", "tesla", "spacex", "sony", "valve", "steam", "xbox",
    "playstation", "qualcomm", "bytedance", "tiktok", "uber", "instagram",
})
_ASSUMED_KNOWLEDGE_ACRONYMS = frozenset({"ai", "ии", "eu", "us", "uk", "ceo", "cto", "ipo", "usd", "eur", "doj"})

_ENTITY_TOKEN_RE = re.compile(r"(?<!^)(?<![.!?…]\s)\b[A-ZА-ЯЁ][a-zа-яё]{2,}\b")
_JARGON_ACRONYM_RE = re.compile(r"\b[A-Z]{2,}\b")
# A subject mention is treated as evidence-explainable when a descriptive noun sits near it in
# the same evidence string - a narrow, explicit signal, never a general relation-extraction model.
_DESCRIPTIVE_NOUN_RE = re.compile(
    r"\b(стартап|производитель|компания|разработчик|платформа|издатель|студия|фонд|"
    r"startup|maker|developer|publisher|manufacturer|platform)\w*\b", re.IGNORECASE,
)

_EVIDENCE_WORDS_PER_UNIT = 28  # a reasoned, documented starting estimate - see module docstring;
# not fit to historical outcome data (none exists yet for this exact plan), matching this
# codebase's own established precedent (docs/phase15_editorial_intelligence_discovery_report.md's
# own "reasoned, not fit" disclosure for services/editorial_scoring.py's weights).
_SAFE_RANGE_FLOOR_WORDS = 40  # never below EditorialBrief's own INSUFFICIENT-source floor.
_SAFE_RANGE_WIDTH_WORDS = 50

_THIN_SUFFICIENCY = {
    SourceSufficiency.HEADLINE_ONLY, SourceSufficiency.EMPTY,
    SourceSufficiency.CONFLICTING, SourceSufficiency.UNKNOWN,
}


def _joined_text(brief: EditorialBrief) -> str:
    parts = [brief.headline_fact or "", *brief.event_details]
    return " ".join(p for p in parts if p)


def classify_subjects_to_explain(brief: EditorialBrief) -> tuple[list[str], list[str], list[str]]:
    """Returns (subjects_to_explain, assumed_knowledge, unexplainable_subjects). A detected
    proper-noun entity is either well-known enough to skip (assumed_knowledge), has a real
    descriptive clause nearby in the evidence text (subjects_to_explain - explainable), or has
    neither (unexplainable_subjects - flagged as needing explanation but with no safe evidence to
    build one from, so the candidate must leave it unexplained, never invent a description)."""
    text = _joined_text(brief)
    entities = sorted(set(_ENTITY_TOKEN_RE.findall(text)))

    subjects_to_explain: list[str] = []
    assumed_knowledge: list[str] = []
    unexplainable: list[str] = []
    for entity in entities:
        if entity.lower() in _ASSUMED_KNOWLEDGE_ENTITIES:
            assumed_knowledge.append(entity)
            continue
        # Look for a descriptive noun within a short window around the entity mention.
        window_pattern = re.compile(
            rf"(.{{0,40}}{re.escape(entity)}.{{0,40}})", re.IGNORECASE,
        )
        match = window_pattern.search(text)
        has_descriptive_context = bool(match and _DESCRIPTIVE_NOUN_RE.search(match.group(1)))
        if has_descriptive_context:
            subjects_to_explain.append(entity)
        else:
            unexplainable.append(entity)
    return subjects_to_explain, assumed_knowledge, unexplainable


def classify_terms_to_explain(brief: EditorialBrief) -> tuple[list[str], list[str]]:
    """Returns (terms_to_explain, unexplainable_terms). A jargon acronym found in
    `services.editorial_glossary` is explainable (deterministic_definition provenance); one that
    looks like jargon (an ALLCAPS 2+-letter token) but isn't in the glossary and isn't a
    well-known acronym is flagged unexplainable - never given an invented definition."""
    text = _joined_text(brief)
    candidates = sorted(set(_JARGON_ACRONYM_RE.findall(text)))

    terms_to_explain: list[str] = []
    unexplainable: list[str] = []
    for token in candidates:
        lowered = token.lower()
        if lowered in _ASSUMED_KNOWLEDGE_ACRONYMS:
            continue
        if lookup(lowered) is not None:
            terms_to_explain.append(lowered)
        else:
            unexplainable.append(token)
    return terms_to_explain, unexplainable


def _jargon_risk(term_count: int) -> JargonRisk:
    if term_count == 0:
        return JargonRisk.LOW
    if term_count <= 2:
        return JargonRisk.MEDIUM
    return JargonRisk.HIGH


def _compute_safe_range(ideal: WordRange, evidence_units: int, complexity: Complexity) -> WordRange:
    """Pure. `safe_range` is a constrained subset of `ideal_range` - it can never exceed
    `ideal_range`'s own ceiling (schema-enforced), and is capped by how many real, distinct
    pieces of evidence actually exist. `INSUFFICIENT` complexity already reflects a thin source
    at the schema level (EditorialBrief's own 40-90 band) - safe_range equals ideal_range there
    unchanged, since there is nothing further to constrain."""
    if complexity == Complexity.INSUFFICIENT:
        return ideal
    supported_ceiling = evidence_units * _EVIDENCE_WORDS_PER_UNIT
    safe_max = max(_SAFE_RANGE_FLOOR_WORDS, min(ideal.max_words, supported_ceiling))
    safe_min = max(_SAFE_RANGE_FLOOR_WORDS, min(safe_max, safe_max - _SAFE_RANGE_WIDTH_WORDS))
    safe_target = round((safe_min + safe_max) / 2)
    return WordRange(min_words=safe_min, target_words=safe_target, max_words=safe_max)


def build_beginner_friendly_plan(
    news_event_title: str,
    news_event_content: str | None,
    research_output: dict[str, Any],
    intelligence_output: dict[str, Any],
    *,
    has_image_candidate: bool | None,
) -> BeginnerFriendlyPlan:
    """Pure. No I/O, no LLM call, deterministic: identical inputs always produce an identical
    output (idempotent by construction)."""
    brief = build_editorial_brief(news_event_title, news_event_content, research_output, intelligence_output)
    adaptive_plan = build_adaptive_length_plan(
        news_event_title, news_event_content, research_output, intelligence_output,
        has_image_candidate=has_image_candidate,
    )

    subjects_to_explain, assumed_knowledge, unexplainable_subjects = classify_subjects_to_explain(brief)
    terms_to_explain, unexplainable_terms_raw = classify_terms_to_explain(brief)
    all_unexplainable = sorted({*unexplainable_subjects, *unexplainable_terms_raw})

    explainable_count = len(subjects_to_explain) + len(terms_to_explain)
    explanation_required = (
        explainable_count > 0
        and brief.source_sufficiency not in {SourceSufficiency.EMPTY, SourceSufficiency.UNKNOWN}
    )

    reason_codes = [f"base_complexity={adaptive_plan.complexity.value}"]
    if unexplainable_subjects:
        reason_codes.append("unexplainable_subjects_present")
    if unexplainable_terms_raw:
        reason_codes.append("unexplainable_terms_present")

    evidence_units = (
        len(brief.event_details) + len(brief.why_it_matters) + len(brief.what_next)
        + len(subjects_to_explain) + len(terms_to_explain)
    )
    safe_range = _compute_safe_range(
        WordRange(
            min_words=adaptive_plan.min_words, target_words=adaptive_plan.target_words,
            max_words=adaptive_plan.max_words,
        ),
        evidence_units, adaptive_plan.complexity,
    )
    if safe_range.max_words < adaptive_plan.max_words:
        reason_codes.append(f"safe_range_constrained_by_evidence_units={evidence_units}")

    explanation_budget = min(15 * explainable_count, max(0, safe_range.target_words // 3))
    context_budget = min(20, safe_range.target_words // 4) if brief.background_context else 0

    paragraph_target = adaptive_plan.paragraph_target
    if explanation_required and paragraph_target < 2:
        paragraph_target = 2
    paragraph_target = min(paragraph_target + (1 if explanation_required else 0), 4)

    jargon_risk = _jargon_risk(len(terms_to_explain) + len(all_unexplainable))

    return BeginnerFriendlyPlan(
        policy_version=BEGINNER_FRIENDLY_POLICY_VERSION,
        audience_level=_AUDIENCE_LEVEL,
        explanation_required=explanation_required,
        subjects_to_explain=subjects_to_explain,
        terms_to_explain=terms_to_explain,
        assumed_knowledge=assumed_knowledge,
        unexplainable_terms=all_unexplainable,
        explanation_budget=explanation_budget,
        context_budget=context_budget,
        detail_target=adaptive_plan.detail_target,
        paragraph_target=paragraph_target,
        why_it_matters_required=bool(brief.why_it_matters),
        what_next_allowed=bool(brief.what_next),
        uncertainty_required=bool(brief.uncertainties) or brief.source_sufficiency in _THIN_SUFFICIENCY,
        jargon_risk=jargon_risk,
        ideal_range=WordRange(
            min_words=adaptive_plan.min_words, target_words=adaptive_plan.target_words,
            max_words=adaptive_plan.max_words,
        ),
        safe_range=safe_range,
        reason_codes=reason_codes,
        evidence_constraints=[
            "no_invented_company_description", "no_unverified_market_claims",
            "no_superlatives_without_evidence", "explanation_only_from_glossary_or_evidence",
        ],
    )


def apply_beginner_friendly_shadow(
    news_event_title: str,
    news_event_content: str | None,
    research_output: dict[str, Any],
    intelligence_output: dict[str, Any],
    has_image_candidate: bool | None,
    structured_output: dict[str, Any],
) -> dict[str, Any]:
    """Called only from `capabilities/executor.py`, only for the "copywriting" step (after
    Adaptive Length's own attach in that same step), only when `beginner_copywriting_mode !=
    "off"`. Returns `structured_output` completely unchanged when off (the default,
    byte-identical-to-pre-M4 rollback path). Purely additive merge - mirrors M1's/M2's/M3's own
    established convention exactly."""
    if settings.beginner_copywriting_mode == "off":
        return structured_output

    plan = build_beginner_friendly_plan(
        news_event_title, news_event_content, research_output, intelligence_output,
        has_image_candidate=has_image_candidate,
    )
    return {**structured_output, "beginner_friendly_plan": plan.model_dump(mode="json")}
