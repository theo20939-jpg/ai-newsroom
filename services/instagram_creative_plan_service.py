"""INSTAGRAM-GROWTH-3, item 6: CreativePlan/CreativeDraft persistence. AI creative output is a
PROPOSAL, never a business fact - `status` never auto-flips to APPROVED anywhere in this module;
`approve_draft()` is the one explicit, human-triggered call that does it (and, in turn, marks the
owning plan APPROVED - a plan is approved once ONE of its drafts is)."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_creative_plan import (
    CreativeDraftStatus,
    CreativePlanStatus,
    InstagramCreativeDraft,
    InstagramCreativePlan,
)


async def create_creative_plan(
    session: AsyncSession, *, content_opportunity_id: str, objective: str, format: str,
    campaign_id: UUID | None = None, product_id: UUID | None = None, series_id: UUID | None = None,
    hook_family: str | None = None, business_context_version: str | None = None,
    campaign_state_snapshot: str | None = None,
) -> InstagramCreativePlan:
    plan = InstagramCreativePlan(
        content_opportunity_id=content_opportunity_id, objective=objective, format=format, campaign_id=campaign_id,
        product_id=product_id, series_id=series_id, hook_family=hook_family,
        business_context_version=business_context_version, campaign_state_snapshot=campaign_state_snapshot,
    )
    session.add(plan)
    await session.commit()
    await session.refresh(plan)
    return plan


async def get_creative_plan(session: AsyncSession, plan_id: UUID) -> InstagramCreativePlan | None:
    return await session.get(InstagramCreativePlan, plan_id)


async def create_creative_draft(
    session: AsyncSession, *, creative_plan_id: UUID, format: str, payload: dict, generated_at: datetime,
    approved_claims: list[str] | None = None, restricted_claims: list[str] | None = None,
    evidence_used: list[str] | None = None, ai_model: str | None = None, ai_capability: str | None = None,
    ai_cost_usd: float | None = None,
) -> InstagramCreativeDraft:
    draft = InstagramCreativeDraft(
        creative_plan_id=creative_plan_id, format=format, payload=payload, generated_at=generated_at,
        approved_claims=approved_claims or [], restricted_claims=restricted_claims or [],
        evidence_used=evidence_used or [], ai_model=ai_model, ai_capability=ai_capability, ai_cost_usd=ai_cost_usd,
    )
    session.add(draft)
    await session.commit()
    await session.refresh(draft)
    return draft


async def list_drafts_for_plan(session: AsyncSession, creative_plan_id: UUID) -> list[InstagramCreativeDraft]:
    stmt = select(InstagramCreativeDraft).where(InstagramCreativeDraft.creative_plan_id == creative_plan_id)
    return list((await session.execute(stmt)).scalars().all())


async def approve_draft(session: AsyncSession, draft_id: UUID) -> InstagramCreativeDraft:
    draft = await session.get(InstagramCreativeDraft, draft_id)
    if draft is None:
        raise ValueError(f"no InstagramCreativeDraft with id={draft_id}")
    draft.status = CreativeDraftStatus.APPROVED

    plan = await session.get(InstagramCreativePlan, draft.creative_plan_id)
    if plan is not None:
        plan.status = CreativePlanStatus.APPROVED

    await session.commit()
    await session.refresh(draft)
    return draft


async def reject_draft(session: AsyncSession, draft_id: UUID, *, reason: str) -> InstagramCreativeDraft:
    draft = await session.get(InstagramCreativeDraft, draft_id)
    if draft is None:
        raise ValueError(f"no InstagramCreativeDraft with id={draft_id}")
    draft.status = CreativeDraftStatus.REJECTED
    draft.rejection_reason = reason
    await session.commit()
    await session.refresh(draft)
    return draft
