"""NINJA Social Intelligence Foundation, Part I §8-§11: LaunchCampaign / CampaignMilestone
persistence. Plain module-level async functions, no class - mirrors services/product_context_
service.py's own shape. Pure persistence only."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.campaign import CampaignStatus, DateConfidence, LaunchCampaign
from database.models.campaign_milestone import CampaignMilestone
from database.models.business_context_shared import Visibility

_CAMPAIGN_UPDATABLE_FIELDS = frozenset({
    "name", "objective", "status", "priority", "planned_launch_date", "date_confidence",
    "start_at", "end_at", "target_audiences", "primary_goal", "secondary_goals", "key_messages",
    "approved_claims", "restricted_claims", "required_cta", "available_assets", "embargo_at",
    "owner",
})


async def get_campaign(session: AsyncSession, campaign_id: UUID) -> LaunchCampaign | None:
    return await session.get(LaunchCampaign, campaign_id)


async def list_campaigns_for_product(session: AsyncSession, product_id: UUID) -> list[LaunchCampaign]:
    stmt = select(LaunchCampaign).where(LaunchCampaign.product_id == product_id).order_by(
        LaunchCampaign.created_at.desc()
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_active_campaigns(session: AsyncSession, *, now: datetime) -> list[LaunchCampaign]:
    """"Active" = not yet in a terminal state (spec §15's own get_active_campaigns(now) contract) -
    CANCELLED/COMPLETED are excluded; everything else (including DELAYED - a delayed campaign is
    still active, just with a stale date) is included regardless of `start_at`/`end_at`, since a
    DRAFT/TENTATIVE campaign has no dates yet and must still be visible to directors."""
    stmt = select(LaunchCampaign).where(
        LaunchCampaign.status.notin_([CampaignStatus.CANCELLED, CampaignStatus.COMPLETED])
    ).order_by(LaunchCampaign.priority.asc())
    return list((await session.execute(stmt)).scalars().all())


async def create_campaign(
    session: AsyncSession, *, product_id: UUID, name: str, structured_context: dict[str, Any] | None = None,
) -> LaunchCampaign:
    campaign = LaunchCampaign(product_id=product_id, name=name)
    if structured_context:
        _apply_campaign_fields(campaign, structured_context)
    session.add(campaign)
    await session.commit()
    await session.refresh(campaign)
    return campaign


def _apply_campaign_fields(campaign: LaunchCampaign, structured_context: dict[str, Any]) -> None:
    for field, value in structured_context.items():
        if field not in _CAMPAIGN_UPDATABLE_FIELDS:
            continue
        if field == "status" and isinstance(value, str):
            value = CampaignStatus(value)
        elif field == "date_confidence" and isinstance(value, str):
            value = DateConfidence(value)
        elif field == "planned_launch_date" and isinstance(value, str):
            value = date.fromisoformat(value)
        setattr(campaign, field, value)


async def update_campaign(
    session: AsyncSession, campaign_id: UUID, *, structured_context: dict[str, Any],
) -> LaunchCampaign | None:
    """Applies an allowlisted field update onto an existing campaign - the ONLY path
    services/business_context_proposal_service.py::confirm_proposal() uses to mutate a campaign,
    always from an already-confirmed human decision (spec §10's DELAYED/CANCELLED transitions flow
    through this exact function, never a bespoke status-only setter)."""
    campaign = await session.get(LaunchCampaign, campaign_id)
    if campaign is None:
        return None
    _apply_campaign_fields(campaign, structured_context)
    await session.commit()
    await session.refresh(campaign)
    return campaign


async def create_milestone(
    session: AsyncSession, *, product_id: UUID, title: str, milestone_at: datetime,
    campaign_id: UUID | None = None, type: str | None = None, description: str | None = None,
    importance: int = 100, visibility: Visibility = Visibility.INTERNAL_ONLY,
    publicity_allowed: bool = False, asset_preparation_allowed: bool = False,
) -> CampaignMilestone:
    milestone = CampaignMilestone(
        product_id=product_id, campaign_id=campaign_id, type=type, title=title,
        description=description, milestone_at=milestone_at, importance=importance,
        visibility=visibility, publicity_allowed=publicity_allowed,
        asset_preparation_allowed=asset_preparation_allowed,
    )
    session.add(milestone)
    await session.commit()
    await session.refresh(milestone)
    return milestone


async def list_upcoming_milestones(
    session: AsyncSession, *, now: datetime, days: int = 30,
) -> list[CampaignMilestone]:
    stmt = select(CampaignMilestone).where(
        CampaignMilestone.milestone_at >= now, CampaignMilestone.milestone_at <= now + timedelta(days=days),
    ).order_by(CampaignMilestone.milestone_at.asc())
    return list((await session.execute(stmt)).scalars().all())
