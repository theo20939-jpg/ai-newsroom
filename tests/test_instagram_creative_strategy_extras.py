"""INSTAGRAM GROWTH ENGINE v2: CreativeConcept, Stories Strategy, Objective Selection, and
Original Format Lab tests (spec §26/§29/§32/§20)."""
from __future__ import annotations

import pytest

from services.instagram_content_opportunity import OpportunitySourceType, build_content_opportunity
from services.instagram_creative_concept import CreativeConcept
from services.instagram_format_director import ClaimViolationError, ContentFormat
from services.instagram_hook_intelligence import Hook, HookFamily
from services.instagram_objective_selection import recommend_objective
from services.instagram_objectives import ContentObjective
from services.instagram_original_format_lab import OriginalFormatExperiment, OriginalFormatStatus
from services.instagram_stories_strategy import StoryAmplificationPlan, StoryRole, StorySlide


def _hook() -> Hook:
    return Hook(family=HookFamily.CURIOSITY_GAP, mechanic="withhold the answer until slide 3")


def test_creative_concept_rejects_restricted_claim_in_narrative() -> None:
    with pytest.raises(ClaimViolationError):
        CreativeConcept(
            id="cc1", objective=ContentObjective.SAVES, target_audience="a", core_insight="insight",
            angle="Only $99 per month!", hook=_hook(), format=ContentFormat.CAROUSEL,
            restricted_claims=["$99"],
        )


def test_creative_concept_allows_approved_claim() -> None:
    concept = CreativeConcept(
        id="cc2", objective=ContentObjective.SAVES, target_audience="a", core_insight="insight",
        angle="multiple AI models inside", hook=_hook(), format=ContentFormat.CAROUSEL,
        approved_claims=["multiple AI models"],
    )
    assert concept.approved_claims == ["multiple AI models"]


def test_story_amplification_plan_requires_at_least_one_slide() -> None:
    with pytest.raises(ValueError):
        StoryAmplificationPlan(objective="reach", sequence=[])
    plan = StoryAmplificationPlan(
        objective="reach", sequence=[StorySlide(role=StoryRole.TEASER, content="coming soon")],
    )
    assert plan.sequence[0].role == StoryRole.TEASER


def test_objective_recommendation_is_not_all_objectives_at_once() -> None:
    opportunity = build_content_opportunity(id="o1", source_type=OpportunitySourceType.NEWS, story_id="s1", news_value=0.9)
    recommendation = recommend_objective(opportunity=opportunity)
    assert recommendation.primary_objective == ContentObjective.REACH
    assert ContentObjective.REACH not in recommendation.secondary_objectives
    assert len(recommendation.secondary_objectives) < len(list(ContentObjective))


def test_original_format_experiment_starts_draft() -> None:
    experiment = OriginalFormatExperiment(
        idea="split-screen comparison reel", novelty_hypothesis="h", intentional_difference="d",
        target_objective="reach", target_audience="a", format="reel", test_conditions="t",
        success_criteria="s", evaluation_window="7d",
    )
    assert experiment.status == OriginalFormatStatus.DRAFT


def test_original_format_experiment_terminal_status_requires_result() -> None:
    with pytest.raises(ValueError):
        OriginalFormatExperiment(
            idea="x", novelty_hypothesis="h", intentional_difference="d", target_objective="reach",
            target_audience="a", format="reel", test_conditions="t", success_criteria="s",
            evaluation_window="7d", status=OriginalFormatStatus.ADOPTED,
        )
