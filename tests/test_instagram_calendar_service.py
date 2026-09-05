"""INSTAGRAM GROWTH ENGINE v2, spec §70: Dynamic Calendar tests. Real db_session, mirrors
tests/test_business_context_snapshot_service.py's own conventions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.campaign import CampaignStatus
from database.models.instagram_calendar_item import CalendarItemStatus
from services.campaign_service import create_campaign, update_campaign
from services.instagram_calendar_service import (
    UnsafeCalendarAssumptionError,
    create_calendar_item,
    invalidate_items_for_campaign_change,
    invalidate_items_for_claim_change,
    list_calendar_items,
)
from services.product_context_service import create_product


@pytest.mark.asyncio
async def test_confirmed_launch_countdown_item_can_be_created(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="cal1", name="Calendar Product 1")
    campaign = await create_campaign(
        db_session, product_id=product.id, name="Launch",
        structured_context={"status": "confirmed", "planned_launch_date": (datetime.now(timezone.utc).date() + timedelta(days=2)).isoformat(), "date_confidence": "exact"},
    )
    item = await create_calendar_item(
        db_session, planned_at=datetime.now(timezone.utc), objective="reach", format="reel",
        campaign_id=campaign.id, product_id=product.id, depends_on_campaign_phase="COUNTDOWN",
        planned_against_campaign_status="confirmed", planned_against_campaign_phase="COUNTDOWN",
    )
    assert item.status == CalendarItemStatus.ACTIVE


@pytest.mark.asyncio
async def test_tentative_launch_blocks_hard_countdown_assumptions(db_session: AsyncSession) -> None:
    with pytest.raises(UnsafeCalendarAssumptionError):
        await create_calendar_item(
            db_session, planned_at=datetime.now(timezone.utc), objective="reach", format="reel",
            depends_on_campaign_phase="COUNTDOWN", planned_against_campaign_status="tentative",
        )


@pytest.mark.asyncio
async def test_delay_invalidates_countdown_and_launch_items_but_not_generic_awareness(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="cal2", name="Calendar Product 2")
    campaign = await create_campaign(
        db_session, product_id=product.id, name="Launch 2",
        structured_context={"status": "confirmed", "planned_launch_date": (datetime.now(timezone.utc).date() + timedelta(days=2)).isoformat(), "date_confidence": "exact"},
    )
    countdown = await create_calendar_item(
        db_session, planned_at=datetime.now(timezone.utc), objective="reach", format="reel", campaign_id=campaign.id,
        depends_on_campaign_phase="COUNTDOWN", planned_against_campaign_status="confirmed", planned_against_campaign_phase="COUNTDOWN",
    )
    launch = await create_calendar_item(
        db_session, planned_at=datetime.now(timezone.utc), objective="product_click", format="single", campaign_id=campaign.id,
        depends_on_campaign_phase="LAUNCH", planned_against_campaign_status="confirmed", planned_against_campaign_phase="LAUNCH",
    )
    awareness = await create_calendar_item(
        db_session, planned_at=datetime.now(timezone.utc), objective="brand", format="carousel", campaign_id=campaign.id,
        depends_on_campaign_phase=None, planned_against_campaign_status="confirmed", planned_against_campaign_phase="AWARENESS",
    )

    await update_campaign(db_session, campaign.id, structured_context={"status": "delayed"})
    changed = await invalidate_items_for_campaign_change(
        db_session, campaign_id=campaign.id, new_status=CampaignStatus.DELAYED, new_phase="AWARENESS",
        reason="launch delayed - no new date yet",
    )
    changed_ids = {item.id for item in changed}
    assert countdown.id in changed_ids
    assert launch.id in changed_ids
    assert awareness.id not in changed_ids

    items = await list_calendar_items(db_session, campaign_id=campaign.id)
    by_id = {item.id: item for item in items}
    assert by_id[countdown.id].status == CalendarItemStatus.INVALIDATED
    assert by_id[launch.id].status == CalendarItemStatus.INVALIDATED
    assert by_id[awareness.id].status == CalendarItemStatus.ACTIVE


@pytest.mark.asyncio
async def test_cancel_invalidates_launch_content(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="cal3", name="Calendar Product 3")
    campaign = await create_campaign(db_session, product_id=product.id, name="Launch 3")
    await update_campaign(db_session, campaign.id, structured_context={"status": "confirmed", "planned_launch_date": (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat(), "date_confidence": "exact"})
    launch_item = await create_calendar_item(
        db_session, planned_at=datetime.now(timezone.utc), objective="product_click", format="single", campaign_id=campaign.id,
        depends_on_campaign_phase="LAUNCH", planned_against_campaign_status="confirmed", planned_against_campaign_phase="LAUNCH",
    )
    await update_campaign(db_session, campaign.id, structured_context={"status": "cancelled"})
    changed = await invalidate_items_for_campaign_change(
        db_session, campaign_id=campaign.id, new_status=CampaignStatus.CANCELLED, new_phase=None, reason="campaign cancelled",
    )
    assert launch_item.id in {item.id for item in changed}


@pytest.mark.asyncio
async def test_duplicate_invalidation_is_idempotent(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="cal4", name="Calendar Product 4")
    campaign = await create_campaign(db_session, product_id=product.id, name="Launch 4")
    item = await create_calendar_item(
        db_session, planned_at=datetime.now(timezone.utc), objective="reach", format="reel", campaign_id=campaign.id,
        depends_on_campaign_phase="COUNTDOWN", planned_against_campaign_status="confirmed", planned_against_campaign_phase="COUNTDOWN",
    )
    first_pass = await invalidate_items_for_campaign_change(
        db_session, campaign_id=campaign.id, new_status=CampaignStatus.CANCELLED, new_phase=None, reason="cancelled",
    )
    second_pass = await invalidate_items_for_campaign_change(
        db_session, campaign_id=campaign.id, new_status=CampaignStatus.CANCELLED, new_phase=None, reason="cancelled again",
    )
    assert item.id in {i.id for i in first_pass}
    assert second_pass == []  # already INVALIDATED - not re-touched


@pytest.mark.asyncio
async def test_claim_policy_change_marks_affected_content_stale(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="cal5", name="Calendar Product 5")
    item = await create_calendar_item(
        db_session, planned_at=datetime.now(timezone.utc), objective="product_click", format="single", product_id=product.id,
    )
    changed = await invalidate_items_for_claim_change(db_session, product_id=product.id, reason="new restricted claim added")
    assert item.id in {i.id for i in changed}
    refreshed = await list_calendar_items(db_session)
    assert next(i for i in refreshed if i.id == item.id).status == CalendarItemStatus.STALE


@pytest.mark.asyncio
async def test_business_context_version_is_stored_on_calendar_item(db_session: AsyncSession) -> None:
    item = await create_calendar_item(
        db_session, planned_at=datetime.now(timezone.utc), objective="reach", format="reel",
        planned_against_campaign_status="confirmed", planned_against_campaign_phase="LAUNCH",
    )
    assert item.planned_against_campaign_status == "confirmed"
    assert item.planned_against_campaign_phase == "LAUNCH"
