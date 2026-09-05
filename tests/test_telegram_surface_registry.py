"""SOCIAL-INTELLIGENCE-INTEGRATION-1, spec §37: Telegram Surface Registry tests."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.telegram_surface import TelegramSurfaceRole
from services.telegram_surface_registry import (
    create_surface,
    list_public_analytics_surfaces,
    list_surfaces,
    owned_surface_is_public_and_analytics_enabled,
)


@pytest.mark.asyncio
async def test_internal_editorial_excluded_from_audience_learning(db_session: AsyncSession) -> None:
    await create_surface(
        db_session, chat_id=-1001111111111, role=TelegramSurfaceRole.INTERNAL_EDITORIAL,
        name="NNJ Newsroom (internal)", analytics_enabled=True, active=True,
    )
    public_surfaces = await list_public_analytics_surfaces(db_session)
    assert public_surfaces == []


@pytest.mark.asyncio
async def test_public_news_channel_can_be_analytics_enabled(db_session: AsyncSession) -> None:
    await create_surface(
        db_session, chat_id=-1002222222222, role=TelegramSurfaceRole.PUBLIC_NEWS_CHANNEL,
        name="NINJA PULSE", analytics_enabled=True, active=True,
    )
    public_surfaces = await list_public_analytics_surfaces(db_session)
    assert len(public_surfaces) == 1
    assert public_surfaces[0].role == TelegramSurfaceRole.PUBLIC_NEWS_CHANNEL


@pytest.mark.asyncio
async def test_public_surface_not_analytics_enabled_is_excluded(db_session: AsyncSession) -> None:
    await create_surface(
        db_session, chat_id=-1003333333333, role=TelegramSurfaceRole.PUBLIC_GAMING_CHANNEL,
        name="NINJA Games", analytics_enabled=False, active=True,
    )
    assert await list_public_analytics_surfaces(db_session) == []


@pytest.mark.asyncio
async def test_inactive_public_surface_is_excluded(db_session: AsyncSession) -> None:
    await create_surface(
        db_session, chat_id=-1004444444444, role=TelegramSurfaceRole.PUBLIC_PRODUCT_CHANNEL,
        name="NINJA Store", analytics_enabled=True, active=False,
    )
    assert await list_public_analytics_surfaces(db_session) == []


@pytest.mark.asyncio
async def test_no_surface_configured_fails_safe(db_session: AsyncSession) -> None:
    """No hardcoded NINJA PULSE ID exists anywhere - an unconfigured registry must fail safe
    (False), never assume the owned channel is public."""
    assert await owned_surface_is_public_and_analytics_enabled(db_session) is False
    assert await list_surfaces(db_session) == []
