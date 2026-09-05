"""INSTAGRAM-GROWTH-3, item 1: semantic SUPPLEMENT layer over the accepted, deterministic
services/instagram_trend_matching.py. Every function here:

1. calls the accepted deterministic matcher FIRST (unchanged, never bypassed) - lexical/entity
   evidence is always computed and always retained in the result;
2. THEN, only if a gateway/prompt_repository is supplied, asks
   services/instagram_semantic_matching.py::evaluate_semantic_relatedness() whether the two
   subjects are related in substance;
3. fails soft to the deterministic-only result if the AI call is unavailable for any reason
   (no gateway supplied, prompt missing, Gateway error, malformed output) - `semantic_available`
   tells a caller which case happened, `matched`/`confidence` are NEVER solely AI-derived.

No single magic relevance score: `topic_overlap`/`entity_overlap` (lexical) and
`semantic_relatedness` (semantic) are always reported as separate numbers, never averaged into one
opaque score."""
from __future__ import annotations

from dataclasses import replace

from integrations.llm_gateway.protocol import LLMGateway
from integrations.prompts.protocol import PromptRepository
from services.campaign_planner import CampaignPlan
from services.instagram_semantic_matching import SemanticMatchResult, evaluate_semantic_relatedness
from services.instagram_trend_matching import (
    StoryMatchInput,
    TrendCampaignMatch,
    TrendNewsMatch,
    match_trend_to_campaign,
    match_trend_to_story,
)
from services.instagram_trend_radar import Trend

# A semantic verdict alone can upgrade a lexically-unmatched pair to "matched" only above this
# floor - low-confidence semantic guesses never silently flip a rejection into a match.
_SEMANTIC_MATCH_THRESHOLD = 0.6


async def _run_semantic(
    gateway: LLMGateway | None, prompt_repository: PromptRepository | None, *,
    subject_a: str, subject_b: str, context_a: str, context_b: str,
) -> SemanticMatchResult:
    if gateway is None or prompt_repository is None:
        return SemanticMatchResult(available=False, unavailable_reason="no gateway/prompt_repository supplied")
    return await evaluate_semantic_relatedness(
        gateway, prompt_repository, subject_a=subject_a, subject_b=subject_b, context_a=context_a, context_b=context_b,
    )


async def match_trend_to_story_with_semantics(
    trend: Trend, story: StoryMatchInput, *, gateway: LLMGateway | None = None,
    prompt_repository: PromptRepository | None = None,
) -> TrendNewsMatch:
    baseline = match_trend_to_story(trend, story)
    semantic = await _run_semantic(
        gateway, prompt_repository, subject_a=trend.topic, subject_b=story.title,
        context_a=trend.format or "", context_b=", ".join([*story.entities, *story.keywords]),
    )
    if not semantic.available:
        return baseline

    upgraded_matched = baseline.matched or (
        baseline.lifecycle_favorable and not baseline.risks
        and bool(semantic.is_related) and (semantic.relatedness or 0.0) >= _SEMANTIC_MATCH_THRESHOLD
    )
    evidence = [
        *baseline.evidence,
        f"semantic_relatedness={semantic.relatedness:.2f}" if semantic.relatedness is not None else "semantic_relatedness=unknown",
        f"semantic_rationale={semantic.rationale!r}",
    ]
    confidence = baseline.confidence
    if upgraded_matched and not baseline.matched:
        confidence = round(max(confidence, min(0.5, (semantic.relatedness or 0.0) * 0.6)), 3)

    return replace(
        baseline, matched=upgraded_matched, evidence=evidence, confidence=confidence,
        semantic_available=True, semantic_relatedness=semantic.relatedness, semantic_rationale=semantic.rationale,
    )


async def match_trend_to_campaign_with_semantics(
    trend: Trend, campaign_plan: CampaignPlan, *, campaign_theme: str = "", gateway: LLMGateway | None = None,
    prompt_repository: PromptRepository | None = None,
) -> TrendCampaignMatch:
    baseline = match_trend_to_campaign(trend, campaign_plan)
    semantic = await _run_semantic(
        gateway, prompt_repository, subject_a=trend.topic, subject_b=campaign_theme or campaign_plan.phase or "",
        context_a=trend.format or "", context_b="; ".join(campaign_plan.key_messages),
    )
    if not semantic.available:
        return baseline

    upgraded_matched = baseline.matched or (
        baseline.brand_fit_ok and campaign_plan.phase is not None
        and bool(semantic.is_related) and (semantic.relatedness or 0.0) >= _SEMANTIC_MATCH_THRESHOLD
    )
    evidence = [
        *baseline.evidence,
        f"semantic_relatedness={semantic.relatedness:.2f}" if semantic.relatedness is not None else "semantic_relatedness=unknown",
        f"semantic_rationale={semantic.rationale!r}",
    ]
    confidence = baseline.confidence
    if upgraded_matched and not baseline.matched:
        confidence = round(max(confidence, min(0.5, (semantic.relatedness or 0.0) * 0.6)), 3)

    return replace(
        baseline, matched=upgraded_matched, evidence=evidence, confidence=confidence,
        semantic_available=True, semantic_relatedness=semantic.relatedness, semantic_rationale=semantic.rationale,
    )
