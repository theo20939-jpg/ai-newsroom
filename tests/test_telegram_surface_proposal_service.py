"""SOCIAL-INTELLIGENCE-OPS-1, spec §58: /surface proposal confirm/cancel tests - idempotency,
never writing TelegramSurface before confirmation."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.telegram_surface import TelegramSurfaceRole
from database.models.telegram_surface_proposal import TelegramSurfaceProposalStatus
from services.telegram_surface_proposal_service import cancel_proposal, confirm_proposal, create_proposal
from services.telegram_surface_registry import get_surface_by_chat_id, list_surfaces


@pytest.mark.asyncio
async def test_proposal_does_not_write_surface_until_confirmed(db_session: AsyncSession) -> None:
    await create_proposal(
        db_session, chat_id=-1005555555555, role=TelegramSurfaceRole.PUBLIC_NEWS_CHANNEL, name="NINJA PULSE",
        raw_instruction="raw text", created_by=1, analytics_enabled=True,
    )
    assert await list_surfaces(db_session) == []


@pytest.mark.asyncio
async def test_confirm_creates_the_surface(db_session: AsyncSession) -> None:
    proposal = await create_proposal(
        db_session, chat_id=-1006666666666, role=TelegramSurfaceRole.PUBLIC_NEWS_CHANNEL, name="NINJA PULSE",
        raw_instruction="raw text", created_by=1, analytics_enabled=True,
    )
    confirmed = await confirm_proposal(db_session, proposal.id, decided_by=1)
    assert confirmed is not None
    assert confirmed.status == TelegramSurfaceProposalStatus.CONFIRMED
    surface = await get_surface_by_chat_id(db_session, -1006666666666)
    assert surface is not None
    assert surface.analytics_enabled is True


@pytest.mark.asyncio
async def test_repeated_confirm_is_idempotent(db_session: AsyncSession) -> None:
    proposal = await create_proposal(
        db_session, chat_id=-1007777777777, role=TelegramSurfaceRole.PUBLIC_GAMING_CHANNEL, name="NINJA Games",
        raw_instruction="raw", created_by=1,
    )
    first = await confirm_proposal(db_session, proposal.id, decided_by=1)
    second = await confirm_proposal(db_session, proposal.id, decided_by=1)
    assert first is not None and second is not None
    assert first.resulting_surface_id == second.resulting_surface_id
    surfaces = [s for s in await list_surfaces(db_session) if s.chat_id == -1007777777777]
    assert len(surfaces) == 1  # never duplicated


@pytest.mark.asyncio
async def test_confirming_two_proposals_for_the_same_chat_updates_not_duplicates(db_session: AsyncSession) -> None:
    first_proposal = await create_proposal(
        db_session, chat_id=-1008888888888, role=TelegramSurfaceRole.OTHER, name="Unclassified",
        raw_instruction="raw1", created_by=1,
    )
    await confirm_proposal(db_session, first_proposal.id, decided_by=1)

    second_proposal = await create_proposal(
        db_session, chat_id=-1008888888888, role=TelegramSurfaceRole.PUBLIC_PRODUCT_CHANNEL, name="NINJA Store",
        raw_instruction="raw2", created_by=1, analytics_enabled=True,
    )
    await confirm_proposal(db_session, second_proposal.id, decided_by=1)

    surfaces = [s for s in await list_surfaces(db_session) if s.chat_id == -1008888888888]
    assert len(surfaces) == 1
    assert surfaces[0].role == TelegramSurfaceRole.PUBLIC_PRODUCT_CHANNEL
    assert surfaces[0].analytics_enabled is True


@pytest.mark.asyncio
async def test_cancel_never_writes_a_surface(db_session: AsyncSession) -> None:
    proposal = await create_proposal(
        db_session, chat_id=-1009999999998, role=TelegramSurfaceRole.PUBLIC_NEWS_CHANNEL, name="x",
        raw_instruction="raw", created_by=1,
    )
    cancelled = await cancel_proposal(db_session, proposal.id, decided_by=1)
    assert cancelled is not None
    assert cancelled.status == TelegramSurfaceProposalStatus.CANCELLED
    assert await get_surface_by_chat_id(db_session, -1009999999998) is None


@pytest.mark.asyncio
async def test_confirm_after_cancel_is_a_noop(db_session: AsyncSession) -> None:
    proposal = await create_proposal(
        db_session, chat_id=-1009999999997, role=TelegramSurfaceRole.PUBLIC_NEWS_CHANNEL, name="x",
        raw_instruction="raw", created_by=1,
    )
    await cancel_proposal(db_session, proposal.id, decided_by=1)
    result = await confirm_proposal(db_session, proposal.id, decided_by=1)
    assert result is not None
    assert result.status == TelegramSurfaceProposalStatus.CANCELLED
    assert await get_surface_by_chat_id(db_session, -1009999999997) is None
