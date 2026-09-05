"""NINJA Social Intelligence Foundation, Part I §15: BusinessContextSnapshot - the single,
compact, consumption-oriented read directors use instead of re-reading raw history. Deterministic,
zero LLM calls (spec §104): pure querying + `services/campaign_planner.py` phase derivation."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.campaign import LaunchCampaign
from database.models.campaign_milestone import CampaignMilestone
from database.models.claim_policy import ClaimPolicy, ClaimStatus
from database.models.product import Product
from database.models.strategic_directive import StrategicDirective
from services.campaign_planner import CampaignPlan, build_campaign_plan
from services.campaign_service import list_active_campaigns, list_upcoming_milestones
from services.claim_policy_service import get_claim_policy
from services.product_context_service import list_products
from services.strategic_directive_service import list_active_directives


@dataclass(frozen=True)
class ProductSummary:
    product: Product
    active_campaign: CampaignPlan | None


@dataclass(frozen=True)
class BusinessContextSnapshot:
    as_of: datetime
    products: list[ProductSummary] = field(default_factory=list)
    active_campaigns: list[CampaignPlan] = field(default_factory=list)
    upcoming_milestones: list[CampaignMilestone] = field(default_factory=list)
    active_directives: list[StrategicDirective] = field(default_factory=list)
    approved_claims: list[ClaimPolicy] = field(default_factory=list)
    restricted_claims: list[ClaimPolicy] = field(default_factory=list)
    source_version_ids: list[str] = field(default_factory=list)


async def get_active_campaigns(session: AsyncSession, *, now: datetime) -> list[LaunchCampaign]:
    return await list_active_campaigns(session, now=now)


async def get_upcoming_milestones(
    session: AsyncSession, *, now: datetime, days: int = 30,
) -> list[CampaignMilestone]:
    return await list_upcoming_milestones(session, now=now, days=days)


async def get_active_directives(session: AsyncSession, *, now: datetime) -> list[StrategicDirective]:
    return await list_active_directives(session, now=now)


async def get_product_claim_policy(
    session: AsyncSession, product_id: UUID, *, now: datetime,
) -> list[ClaimPolicy]:
    return await get_claim_policy(session, product_id, now=now)


async def get_business_context_snapshot(session: AsyncSession, *, now: datetime) -> BusinessContextSnapshot:
    """Assembles the full compact snapshot in one call - the one function bot/business_context_
    formatting.py::render_status()/directors are expected to call, never several ad hoc queries."""
    products = await list_products(session)
    active_campaigns_rows = await get_active_campaigns(session, now=now)
    campaigns_by_product: dict[UUID, LaunchCampaign] = {}
    for campaign in active_campaigns_rows:
        # First (highest-priority, since list_active_campaigns orders by priority ascending) active
        # campaign per product wins - a product is not expected to run two simultaneous campaigns
        # in this phase's own scope.
        campaigns_by_product.setdefault(campaign.product_id, campaign)

    product_summaries: list[ProductSummary] = []
    approved: list[ClaimPolicy] = []
    restricted: list[ClaimPolicy] = []
    for product in products:
        matched_campaign = campaigns_by_product.get(product.id)
        plan = build_campaign_plan(matched_campaign, now=now) if matched_campaign is not None else None
        product_summaries.append(ProductSummary(product=product, active_campaign=plan))

        claims = await get_product_claim_policy(session, product.id, now=now)
        for claim in claims:
            # APPROVED (including an embargo that has already passed - get_claim_policy() already
            # resolved that) goes in `approved`; RESTRICTED and a still-active EMBARGOED claim both
            # go in `restricted` - a director must treat "not yet public" the same cautious way
            # regardless of which of the two produced it.
            (approved if claim.status == ClaimStatus.APPROVED else restricted).append(claim)

    active_campaign_plans = [build_campaign_plan(c, now=now) for c in active_campaigns_rows]
    milestones = await get_upcoming_milestones(session, now=now)
    directives = await get_active_directives(session, now=now)

    return BusinessContextSnapshot(
        as_of=now, products=product_summaries, active_campaigns=active_campaign_plans,
        upcoming_milestones=milestones, active_directives=directives,
        approved_claims=approved, restricted_claims=restricted,
    )
