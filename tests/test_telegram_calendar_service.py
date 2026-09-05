"""SOCIAL-INTELLIGENCE-OPS-1, spec §61: Telegram Content Calendar tests - mirrors
tests/test_instagram_calendar_service.py's own conventions against the separate Telegram model."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.campaign import CampaignStatus
from database.models.telegram_content_calendar_item import TelegramCalendarItemStatus, TelegramContentRole
from services.campaign_service import create_campaign, update_campaign
from services.product_context_service import create_product
from services.telegram_calendar_service import (
    UnsafeCalendarAssumptionError,
    create_calendar_item,
    invalidate_items_for_campaign_change,
    invalidate_items_for_claim_change,
    list_calendar_items,
    reschedule_calendar_item,
)


@pytest.mark.asyncio
async def test_active_item_is_created_and_listed(db_session: AsyncSession) -> None:
    item = await create_calendar_item(
        db_session, planned_at=datetime.now(timezone.utc), objective="reach", content_role=TelegramContentRole.NEWS,
    )
    assert item.status == TelegramCalendarItemStatus.ACTIVE
    items = await list_calendar_items(db_session)
    assert any(i.id == item.id for i in items)


@pytest.mark.asyncio
async def test_tentative_launch_blocks_hard_countdown_assumptions(db_session: AsyncSession) -> None:
    with pytest.raises(UnsafeCalendarAssumptionError):
        await create_calendar_item(
            db_session, planned_at=datetime.now(timezone.utc), objective="reach", content_role=TelegramContentRole.CAMPAIGN,
            depends_on_campaign_phase="COUNTDOWN", planned_against_campaign_status="tentative",
        )


@pytest.mark.asyncio
async def test_delay_invalidates_dependent_item_but_not_generic_category_item(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="tgcala", name="TG Calendar Product A")
    campaign = await create_campaign(
        db_session, product_id=product.id, name="Launch",
        structured_context={"status": "confirmed", "planned_launch_date": (datetime.now(timezone.utc).date() + timedelta(days=2)).isoformat(), "date_confidence": "exact"},
    )
    countdown = await create_calendar_item(
        db_session, planned_at=datetime.now(timezone.utc), objective="reach", content_role=TelegramContentRole.CAMPAIGN,
        campaign_id=campaign.id, depends_on_campaign_phase="LAUNCH", planned_against_campaign_status="confirmed",
        planned_against_campaign_phase="LAUNCH",
    )
    generic = await create_calendar_item(
        db_session, planned_at=datetime.now(timezone.utc), objective="brand", content_role=TelegramContentRole.EVERGREEN,
        campaign_id=campaign.id, depends_on_campaign_phase=None,
    )
    await update_campaign(db_session, campaign.id, structured_context={"status": "delayed"})
    changed = await invalidate_items_for_campaign_change(
        db_session, campaign_id=campaign.id, new_status=CampaignStatus.DELAYED, new_phase="AWARENESS", reason="delayed",
    )
    changed_ids = {i.id for i in changed}
    assert countdown.id in changed_ids
    assert generic.id not in changed_ids

    items = await list_calendar_items(db_session, campaign_id=campaign.id)
    by_id = {i.id: i for i in items}
    assert by_id[countdown.id].status == TelegramCalendarItemStatus.INVALIDATED
    assert by_id[generic.id].status == TelegramCalendarItemStatus.ACTIVE


@pytest.mark.asyncio
async def test_cancel_invalidates_campaign_items(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="tgcalb", name="TG Calendar Product B")
    campaign = await create_campaign(db_session, product_id=product.id, name="Launch B")
    await update_campaign(db_session, campaign.id, structured_context={"status": "confirmed", "planned_launch_date": (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat(), "date_confidence": "exact"})
    item = await create_calendar_item(
        db_session, planned_at=datetime.now(timezone.utc), objective="product_click", content_role=TelegramContentRole.CAMPAIGN,
        campaign_id=campaign.id, depends_on_campaign_phase="LAUNCH", planned_against_campaign_status="confirmed", planned_against_campaign_phase="LAUNCH",
    )
    await update_campaign(db_session, campaign.id, structured_context={"status": "cancelled"})
    changed = await invalidate_items_for_campaign_change(
        db_session, campaign_id=campaign.id, new_status=CampaignStatus.CANCELLED, new_phase=None, reason="cancelled",
    )
    assert item.id in {i.id for i in changed}


@pytest.mark.asyncio
async def test_rescheduled_item_shown(db_session: AsyncSession) -> None:
    item = await create_calendar_item(
        db_session, planned_at=datetime.now(timezone.utc), objective="reach", content_role=TelegramContentRole.NEWS,
    )
    new_time = datetime.now(timezone.utc) + timedelta(days=3)
    rescheduled = await reschedule_calendar_item(db_session, item.id, new_planned_at=new_time, reason="moved")
    assert rescheduled.status == TelegramCalendarItemStatus.RESCHEDULED
    assert rescheduled.planned_at == new_time


@pytest.mark.asyncio
async def test_claim_policy_change_marks_stale(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="tgcalc", name="TG Calendar Product C")
    item = await create_calendar_item(
        db_session, planned_at=datetime.now(timezone.utc), objective="product_click", content_role=TelegramContentRole.CAMPAIGN,
        product_id=product.id,
    )
    changed = await invalidate_items_for_claim_change(db_session, product_id=product.id, reason="new restricted claim")
    assert item.id in {i.id for i in changed}
    refreshed = await list_calendar_items(db_session)
    assert next(i for i in refreshed if i.id == item.id).status == TelegramCalendarItemStatus.STALE


@pytest.mark.asyncio
async def test_duplicate_invalidation_is_idempotent(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="tgcald", name="TG Calendar Product D")
    campaign = await create_campaign(db_session, product_id=product.id, name="Launch D")
    item = await create_calendar_item(
        db_session, planned_at=datetime.now(timezone.utc), objective="reach", content_role=TelegramContentRole.CAMPAIGN,
        campaign_id=campaign.id, depends_on_campaign_phase="COUNTDOWN", planned_against_campaign_status="confirmed", planned_against_campaign_phase="COUNTDOWN",
    )
    first = await invalidate_items_for_campaign_change(db_session, campaign_id=campaign.id, new_status=CampaignStatus.CANCELLED, new_phase=None, reason="cancelled")
    second = await invalidate_items_for_campaign_change(db_session, campaign_id=campaign.id, new_status=CampaignStatus.CANCELLED, new_phase=None, reason="cancelled again")
    assert item.id in {i.id for i in first}
    assert second == []
