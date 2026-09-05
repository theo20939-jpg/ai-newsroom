"""INSTAGRAM GROWTH ENGINE v2, spec §20: ObjectiveRecommendation - deterministic, evidence-aware
objective selection. Deliberately never assigns every ContentObjective at once (spec's own explicit
"do not assign all objectives simultaneously" instruction) - exactly one primary objective, an
optionally empty list of secondary ones."""
from __future__ import annotations

from dataclasses import dataclass, field

from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_objectives import ContentObjective

_CATEGORY_EDUCATION_PHASES = {"CATEGORY_EDUCATION", "PROBLEM_FRAMING", "AWARENESS"}
_CONVERSION_PHASES = {"LAUNCH", "COUNTDOWN", "FEATURE_REVEAL"}


@dataclass(frozen=True)
class ObjectiveRecommendation:
    primary_objective: ContentObjective
    secondary_objectives: list[ContentObjective] = field(default_factory=list)
    why: str = ""
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.3


def recommend_objective(
    *, opportunity: ContentOpportunity, has_multi_step_narrative: bool = False,
) -> ObjectiveRecommendation:
    """Starting-hypothesis mapping (spec §31's own "these are starting hypotheses, not permanent
    universal truth" instruction) - a real Performance Memory pass would recalibrate this over
    time, not implemented in this phase (no live Instagram performance data exists yet, spec §42)."""
    evidence = [f"source_type={opportunity.source_type.value}", f"campaign_phase={opportunity.campaign_phase!r}"]

    if opportunity.source_type == OpportunitySourceType.NEWS and opportunity.news_value >= 0.6:
        return ObjectiveRecommendation(
            primary_objective=ContentObjective.REACH, secondary_objectives=[ContentObjective.SHARES],
            why="high news_value favors reach/shares while the story is timely", evidence=evidence, confidence=0.3,
        )

    if opportunity.campaign_phase in _CONVERSION_PHASES and opportunity.product_mention_allowed:
        return ObjectiveRecommendation(
            primary_objective=ContentObjective.PRODUCT_CLICK, secondary_objectives=[ContentObjective.PROFILE_VISITS],
            why="conversion-phase campaign with product mention explicitly allowed", evidence=evidence, confidence=0.35,
        )

    if opportunity.campaign_phase in _CATEGORY_EDUCATION_PHASES or has_multi_step_narrative:
        return ObjectiveRecommendation(
            primary_objective=ContentObjective.SAVES, secondary_objectives=[ContentObjective.COMMENTS],
            why="category-education phase or multi-step narrative favors saveable/reference content",
            evidence=evidence, confidence=0.3,
        )

    return ObjectiveRecommendation(
        primary_objective=ContentObjective.BRAND, secondary_objectives=[],
        why="no strong signal for a more specific objective - brand is the safe default",
        evidence=evidence, confidence=0.15,
    )
