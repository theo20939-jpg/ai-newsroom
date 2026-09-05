"""INSTAGRAM GROWTH ENGINE v2, spec §72: Growth Strategist safety tests - Founder Directive
precedence must always win over a Growth-favorable signal (restricted claim never promoted, embargo
precedence)."""
from __future__ import annotations

from datetime import datetime, timezone

from database.models.strategic_directive import DirectiveStatus, StrategicDirective
from services.campaign_planner import CampaignPlan
from services.instagram_content_opportunity import OpportunitySourceType, build_content_opportunity
from services.instagram_growth_strategist import (
    OpportunityContext,
    apply_founder_directive_precedence,
    directive_blocks_product,
    generate_growth_strategy,
)


def _directive(**overrides: object) -> StrategicDirective:
    defaults: dict[str, object] = dict(
        priority=10, valid_from=datetime.now(timezone.utc), instruction="Store пока не продвигаем.",
        products=["store"], platforms=[], status=DirectiveStatus.ACTIVE,
    )
    defaults.update(overrides)
    return StrategicDirective(**defaults)  # type: ignore[arg-type]


def _confirmed_plan(campaign_id: str = "c1") -> CampaignPlan:
    return CampaignPlan(
        campaign_id=campaign_id, product_id="p1", objective=None, phase="LAUNCH", status="confirmed",
        date_confidence="exact", start_at=None, end_at=None,
    )


def test_directive_blocks_scoped_product_only() -> None:
    directives = [_directive(products=["store"])]
    assert directive_blocks_product(directives, product_slug="store")
    assert not directive_blocks_product(directives, product_slug="vpn")


def test_directive_with_empty_scope_blocks_every_product() -> None:
    directives = [_directive(products=[], platforms=[])]
    assert directive_blocks_product(directives, product_slug="anything")


def test_expired_or_cancelled_directive_does_not_block() -> None:
    directives = [_directive(status=DirectiveStatus.SUPERSEDED)]
    assert not directive_blocks_product(directives, product_slug="store")


def test_founder_directive_overrides_confirmed_campaign_product_mention() -> None:
    """Spec §37/§58's own explicit example: growth data / campaign status alone would allow a
    product mention, but an active Founder Directive still wins."""
    opportunity = build_content_opportunity(
        id="o1", source_type=OpportunitySourceType.PRODUCT, product_id="p1", campaign_plan=_confirmed_plan(),
    )
    assert opportunity.product_mention_allowed is True  # campaign alone would allow it

    resolved, notes = apply_founder_directive_precedence(
        [OpportunityContext(opportunity=opportunity, product_slug="store")], [_directive(products=["store"])],
    )
    assert resolved[0].product_mention_allowed is False
    assert notes and "store" in notes[0]


def test_directive_does_not_affect_unrelated_product() -> None:
    opportunity = build_content_opportunity(
        id="o2", source_type=OpportunitySourceType.PRODUCT, product_id="p2", campaign_plan=_confirmed_plan(),
    )
    resolved, notes = apply_founder_directive_precedence(
        [OpportunityContext(opportunity=opportunity, product_slug="vpn")], [_directive(products=["store"])],
    )
    assert resolved[0].product_mention_allowed is True
    assert notes == []


def test_restricted_claim_never_promoted_by_growth_strategy() -> None:
    """A restricted claim propagated onto an opportunity must survive into the strategy's own
    output unchanged - generate_growth_strategy() never clears/waters down restricted_claims."""
    plan = CampaignPlan(
        campaign_id="c1", product_id="p1", objective=None, phase="LAUNCH", status="confirmed",
        date_confidence="exact", start_at=None, end_at=None, restricted_claims=["exact price"],
    )
    opportunity = build_content_opportunity(id="o3", source_type=OpportunitySourceType.PRODUCT, product_id="p1", campaign_plan=plan)
    strategy = generate_growth_strategy(opportunity_contexts=[OpportunityContext(opportunity=opportunity, product_slug="store")])
    assert strategy.priority_opportunities[0].restricted_claims == ["exact price"]


def test_embargo_still_active_surfaces_as_a_risk() -> None:
    opportunity = build_content_opportunity(
        id="o4", source_type=OpportunitySourceType.PRODUCT, product_id="p1", campaign_plan=_confirmed_plan(),
        embargo_active=True,
    )
    strategy = generate_growth_strategy(opportunity_contexts=[OpportunityContext(opportunity=opportunity)])
    assert any("embargo" in r for r in strategy.risks)


def test_growth_strategy_never_assigns_every_objective_at_once() -> None:
    opportunities = [
        build_content_opportunity(id=f"o{i}", source_type=OpportunitySourceType.NEWS, story_id=f"s{i}", news_value=0.9)
        for i in range(3)
    ]
    strategy = generate_growth_strategy(opportunity_contexts=[OpportunityContext(opportunity=o) for o in opportunities])
    assert len(strategy.objective_mix) < 8  # never all ContentObjective values represented for 3 similar opportunities
