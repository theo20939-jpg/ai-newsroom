"""INSTAGRAM GROWTH ENGINE v2, spec §63: ContentOpportunity tests. Pure unit tests - no DB needed,
CampaignPlan is a plain dataclass here exactly like tests/test_instagram_growth_engine_foundation.py
already does for services/instagram_growth_strategist.py."""
from __future__ import annotations

import pytest

from services.campaign_planner import CampaignPlan
from services.instagram_content_opportunity import (
    ContentOpportunityValidationError,
    OpportunitySourceType,
    build_content_opportunity,
    resolve_product_mention_permission,
)


def _plan(*, status: str, phase: str | None, restricted: list[str] | None = None) -> CampaignPlan:
    return CampaignPlan(
        campaign_id="c1", product_id="p1", objective=None, phase=phase, status=status,
        date_confidence="exact", start_at=None, end_at=None, restricted_claims=restricted or [],
    )


def test_news_opportunity_requires_story_id() -> None:
    with pytest.raises(ContentOpportunityValidationError):
        build_content_opportunity(id="o1", source_type=OpportunitySourceType.NEWS)
    opp = build_content_opportunity(id="o1", source_type=OpportunitySourceType.NEWS, story_id="s1", news_value=0.9)
    assert opp.story_id == "s1"
    assert opp.news_value == 0.9
    assert opp.product_mention_allowed is False  # no campaign plan at all


def test_product_opportunity_requires_product_or_campaign_reference() -> None:
    with pytest.raises(ContentOpportunityValidationError):
        build_content_opportunity(id="o2", source_type=OpportunitySourceType.PRODUCT)
    opp = build_content_opportunity(
        id="o2", source_type=OpportunitySourceType.PRODUCT, product_id="p1",
        campaign_plan=_plan(status="confirmed", phase="LAUNCH"),
    )
    assert opp.campaign_relevance == 1.0


def test_hybrid_opportunity_requires_both_legs() -> None:
    with pytest.raises(ContentOpportunityValidationError):
        build_content_opportunity(id="o3", source_type=OpportunitySourceType.HYBRID, story_id="s1")
    with pytest.raises(ContentOpportunityValidationError):
        build_content_opportunity(id="o3", source_type=OpportunitySourceType.HYBRID, product_id="p1")
    opp = build_content_opportunity(
        id="o3", source_type=OpportunitySourceType.HYBRID, story_id="s1", product_id="p1",
        news_value=0.8, campaign_plan=_plan(status="confirmed", phase="CATEGORY_EDUCATION"),
    )
    assert opp.story_id == "s1" and opp.product_id == "p1"


def test_campaign_relevance_is_separate_dimension_from_news_value() -> None:
    """Spec §7's own Apple-eSIM/NINJA-Store example: high news value + high campaign relevance
    must NOT automatically imply product_mention_allowed."""
    opp = build_content_opportunity(
        id="o4", source_type=OpportunitySourceType.HYBRID, story_id="s1", campaign_id="c1",
        news_value=0.95, campaign_plan=_plan(status="tentative", phase="AWARENESS"),
    )
    assert opp.news_value == 0.95
    assert opp.campaign_relevance == 1.0
    assert opp.product_mention_allowed is False  # TENTATIVE status blocks it regardless of relevance


def test_restricted_claims_propagate_from_campaign_plan() -> None:
    opp = build_content_opportunity(
        id="o5", source_type=OpportunitySourceType.PRODUCT, product_id="p1",
        campaign_plan=_plan(status="confirmed", phase="LAUNCH", restricted=["exact price"]),
    )
    assert opp.restricted_claims == ["exact price"]


def test_tentative_launch_restriction_respected() -> None:
    assert resolve_product_mention_permission(
        campaign_plan=_plan(status="tentative", phase="AWARENESS"), restricted_claims=[], embargo_active=False,
    ) is False


def test_embargo_blocks_product_mention_even_if_confirmed() -> None:
    assert resolve_product_mention_permission(
        campaign_plan=_plan(status="confirmed", phase="LAUNCH"), restricted_claims=[], embargo_active=True,
    ) is False


def test_founder_directive_style_hard_block_via_cancelled_status() -> None:
    """A CANCELLED campaign must never permit a product mention regardless of any other signal -
    the closest a plain CampaignPlan gets to modeling a Founder Directive override in this module's
    own scope (the real StrategicDirective precedence lives in services/instagram_growth_strategist.py)."""
    assert resolve_product_mention_permission(
        campaign_plan=_plan(status="cancelled", phase=None), restricted_claims=[], embargo_active=False,
    ) is False


def test_confirmed_active_campaign_allows_product_mention() -> None:
    assert resolve_product_mention_permission(
        campaign_plan=_plan(status="confirmed", phase="LAUNCH"), restricted_claims=[], embargo_active=False,
    ) is True
