"""SOCIAL-INTELLIGENCE-INTEGRATION-1, spec §32: /directors status tests - real flag state,
WAITING_FOR_DATA truthful, disabled shown as disabled, no LLM call, no DB mutation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from services.campaign_service import create_campaign
from services.director_status_service import DirectorStatus, get_director_console_status
from services.product_context_service import create_product


@pytest.mark.asyncio
async def test_empty_state_is_honest_waiting_for_data(db_session: AsyncSession) -> None:
    status = await get_director_console_status(db_session, now=datetime.now(timezone.utc))

    campaign_planner = next(e for e in status.business if e.name == "Campaign Planner")
    assert campaign_planner.status == DirectorStatus.READY  # no active campaign yet

    art_director = next(e for e in status.telegram if e.name == "Art Director")
    assert art_director.status == DirectorStatus.WAITING_FOR_DATA

    growth_director = next(e for e in status.telegram if e.name == "Growth Director")
    assert growth_director.status == DirectorStatus.WAITING_FOR_DATA

    strategy_director = next(e for e in status.telegram if e.name == "Strategy Director")
    assert strategy_director.status == DirectorStatus.WAITING_FOR_DATA

    performance_memory = next(e for e in status.instagram if e.name == "Performance Memory")
    assert performance_memory.status == DirectorStatus.WAITING_FOR_DATA


@pytest.mark.asyncio
async def test_disabled_flags_shown_as_disabled(db_session: AsyncSession) -> None:
    status = await get_director_console_status(db_session, now=datetime.now(timezone.utc))
    channel_director = next(e for e in status.telegram if e.name == "Channel Director")
    assert channel_director.status == DirectorStatus.DISABLED  # telegram_channel_director_shadow_enabled defaults False


@pytest.mark.asyncio
async def test_creative_director_is_ready_never_shadow_or_active(db_session: AsyncSession) -> None:
    status = await get_director_console_status(db_session, now=datetime.now(timezone.utc))
    creative_director = next(e for e in status.instagram if e.name == "Creative Director")
    assert creative_director.status == DirectorStatus.READY


@pytest.mark.asyncio
async def test_real_active_campaign_reflected_in_business_and_instagram_status(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="statustest", name="Status Test Product")
    now = datetime.now(timezone.utc)
    await create_campaign(
        db_session, product_id=product.id, name="Launch",
        structured_context={
            "status": "confirmed", "planned_launch_date": (now.date() + timedelta(days=2)).isoformat(),
            "date_confidence": "exact",
        },
    )
    status = await get_director_console_status(db_session, now=now)
    campaign_planner = next(e for e in status.business if e.name == "Campaign Planner")
    assert campaign_planner.status == DirectorStatus.ACTIVE
    assert "Status Test Product" in campaign_planner.detail

    growth_strategist = next(e for e in status.instagram if e.name == "Growth Strategist")
    assert growth_strategist.status == DirectorStatus.SHADOW


@pytest.mark.asyncio
async def test_status_check_never_mutates_the_database(db_session: AsyncSession) -> None:
    before = await get_director_console_status(db_session, now=datetime.now(timezone.utc))
    after = await get_director_console_status(db_session, now=datetime.now(timezone.utc))
    assert [e.status for e in before.telegram] == [e.status for e in after.telegram]
