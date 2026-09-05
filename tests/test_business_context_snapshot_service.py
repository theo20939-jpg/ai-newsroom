"""NINJA Social Intelligence Foundation §15/§105: BusinessContextSnapshot determinism + claim
resolution. Real db_session, mirrors tests/test_business_context_proposal_service.py's own
conventions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.campaign import CampaignStatus, DateConfidence
from database.models.claim_policy import ClaimStatus
from database.models.strategic_directive import DirectiveStatus
from services.business_context_snapshot_service import get_business_context_snapshot
from services.campaign_service import create_campaign, update_campaign
from services.claim_policy_service import create_claim_policy
from services.product_context_service import create_product
from services.strategic_directive_service import create_directive


@pytest.mark.asyncio
async def test_snapshot_is_deterministic_for_same_state_and_time(db_session: AsyncSession) -> None:
    await create_product(db_session, slug="snap1", name="Snapshot Product 1")
    now = datetime.now(timezone.utc)

    snap1 = await get_business_context_snapshot(db_session, now=now)
    snap2 = await get_business_context_snapshot(db_session, now=now)
    assert [s.product.slug for s in snap1.products] == [s.product.slug for s in snap2.products]
    assert snap1.as_of == snap2.as_of == now


@pytest.mark.asyncio
async def test_snapshot_includes_active_campaign_with_derived_phase(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="snap2", name="Snapshot Product 2")
    now = datetime.now(timezone.utc)
    campaign = await create_campaign(
        db_session, product_id=product.id, name="Launch",
        structured_context={
            "status": "confirmed", "planned_launch_date": (now.date() + timedelta(days=2)).isoformat(),
            "date_confidence": "exact",
        },
    )
    snapshot = await get_business_context_snapshot(db_session, now=now)
    summary = next(s for s in snapshot.products if s.product.slug == "snap2")
    assert summary.active_campaign is not None
    assert summary.active_campaign.phase == "COUNTDOWN"
    assert summary.active_campaign.campaign_id == str(campaign.id)


@pytest.mark.asyncio
async def test_snapshot_excludes_cancelled_campaigns_from_active_list(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="snap3", name="Snapshot Product 3")
    now = datetime.now(timezone.utc)
    campaign = await create_campaign(db_session, product_id=product.id, name="Cancelled Launch")
    await update_campaign(db_session, campaign.id, structured_context={"status": "cancelled"})

    snapshot = await get_business_context_snapshot(db_session, now=now)
    summary = next(s for s in snapshot.products if s.product.slug == "snap3")
    assert summary.active_campaign is None


@pytest.mark.asyncio
async def test_embargoed_claim_resolves_to_approved_once_embargo_passes(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="snap4", name="Snapshot Product 4")
    now = datetime.now(timezone.utc)
    await create_claim_policy(
        db_session, product_id=product.id, claim_text="price known", status=ClaimStatus.EMBARGOED,
        embargoed_until=now - timedelta(days=1),
    )
    await create_claim_policy(
        db_session, product_id=product.id, claim_text="future price", status=ClaimStatus.EMBARGOED,
        embargoed_until=now + timedelta(days=1),
    )

    snapshot = await get_business_context_snapshot(db_session, now=now)
    approved_texts = [c.claim_text for c in snapshot.approved_claims if c.product_id == product.id]
    restricted_texts = [c.claim_text for c in snapshot.restricted_claims if c.product_id == product.id]
    assert "price known" in approved_texts
    assert "future price" in restricted_texts


@pytest.mark.asyncio
async def test_snapshot_includes_active_directives_only(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    await create_directive(
        db_session, instruction="active directive", valid_from=now - timedelta(days=1), created_by=1,
        valid_until=now + timedelta(days=1),
    )
    expired = await create_directive(
        db_session, instruction="expired directive", valid_from=now - timedelta(days=10), created_by=1,
        valid_until=now - timedelta(days=5),
    )

    snapshot = await get_business_context_snapshot(db_session, now=now)
    instructions = [d.instruction for d in snapshot.active_directives]
    assert "active directive" in instructions
    assert "expired directive" not in instructions
