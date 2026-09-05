"""INSTAGRAM-GROWTH-3, item 6/19: CreativePlan/CreativeDraft persistence tests - AI output is a
proposal, never auto-approved."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_creative_plan import CreativeDraftStatus, CreativePlanStatus
from services.instagram_creative_plan_service import (
    approve_draft,
    create_creative_draft,
    create_creative_plan,
    list_drafts_for_plan,
    reject_draft,
)


@pytest.mark.asyncio
async def test_creative_plan_starts_proposed(db_session: AsyncSession) -> None:
    plan = await create_creative_plan(
        db_session, content_opportunity_id="opp-1", objective="reach", format="reel",
    )
    assert plan.status == CreativePlanStatus.PROPOSED


@pytest.mark.asyncio
async def test_creative_draft_never_auto_approves(db_session: AsyncSession) -> None:
    plan = await create_creative_plan(db_session, content_opportunity_id="opp-2", objective="reach", format="single")
    draft = await create_creative_draft(
        db_session, creative_plan_id=plan.id, format="single", payload={"creative_angle": "a"},
        generated_at=datetime.now(timezone.utc), evidence_used=["fact 1"],
    )
    assert draft.status == CreativeDraftStatus.PROPOSED
    refreshed_plan = await create_creative_plan(db_session, content_opportunity_id="opp-3", objective="reach", format="single")
    assert refreshed_plan.status == CreativePlanStatus.PROPOSED  # unrelated plan untouched


@pytest.mark.asyncio
async def test_approving_a_draft_also_approves_its_plan(db_session: AsyncSession) -> None:
    plan = await create_creative_plan(db_session, content_opportunity_id="opp-4", objective="saves", format="carousel")
    draft = await create_creative_draft(
        db_session, creative_plan_id=plan.id, format="carousel", payload={"slides": []},
        generated_at=datetime.now(timezone.utc),
    )
    approved = await approve_draft(db_session, draft.id)
    assert approved.status == CreativeDraftStatus.APPROVED

    from services.instagram_creative_plan_service import get_creative_plan
    refreshed = await get_creative_plan(db_session, plan.id)
    assert refreshed is not None
    assert refreshed.status == CreativePlanStatus.APPROVED


@pytest.mark.asyncio
async def test_rejecting_a_draft_records_reason(db_session: AsyncSession) -> None:
    plan = await create_creative_plan(db_session, content_opportunity_id="opp-5", objective="reach", format="reel")
    draft = await create_creative_draft(
        db_session, creative_plan_id=plan.id, format="reel", payload={"hook": "h"},
        generated_at=datetime.now(timezone.utc),
    )
    rejected = await reject_draft(db_session, draft.id, reason="restricted claim leaked")
    assert rejected.status == CreativeDraftStatus.REJECTED
    assert rejected.rejection_reason == "restricted claim leaked"


@pytest.mark.asyncio
async def test_multiple_drafts_can_be_listed_per_plan(db_session: AsyncSession) -> None:
    plan = await create_creative_plan(db_session, content_opportunity_id="opp-6", objective="reach", format="reel")
    await create_creative_draft(db_session, creative_plan_id=plan.id, format="reel", payload={"v": 1}, generated_at=datetime.now(timezone.utc))
    await create_creative_draft(db_session, creative_plan_id=plan.id, format="reel", payload={"v": 2}, generated_at=datetime.now(timezone.utc))
    drafts = await list_drafts_for_plan(db_session, plan.id)
    assert len(drafts) == 2
