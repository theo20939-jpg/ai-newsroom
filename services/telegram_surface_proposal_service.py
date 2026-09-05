"""SOCIAL-INTELLIGENCE-OPS-1, spec §3/§4: TelegramSurfaceProposal persistence - the ONLY place a
TelegramSurface row is ever mutated from the /surface command. Mirrors services/business_context_
proposal_service.py's own idempotent, immutable-once-final create/confirm/cancel shape exactly.

`confirm_proposal()` never runs from the parser directly - only from bot/handlers/telegram_surface
.py's own confirm callback, after an already-authorized human has pressed Confirm (spec §4's own
"never write TelegramSurface immediately from parser output" instruction)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.telegram_surface import TelegramSurfaceRole
from database.models.telegram_surface_proposal import TelegramSurfaceProposal, TelegramSurfaceProposalStatus
from services.telegram_surface_registry import upsert_surface


async def create_proposal(
    session: AsyncSession, *, chat_id: int, role: TelegramSurfaceRole, name: str, raw_instruction: str,
    created_by: int, username: str | None = None, active: bool = True, analytics_enabled: bool = False,
    parsed_structure: dict[str, Any] | None = None, telegram_chat_id: int | None = None,
    telegram_topic_id: int | None = None, telegram_message_id: int | None = None,
) -> TelegramSurfaceProposal:
    proposal = TelegramSurfaceProposal(
        chat_id=chat_id, role=role, name=name, username=username, active=active, analytics_enabled=analytics_enabled,
        raw_instruction=raw_instruction, parsed_structure=parsed_structure, created_by=created_by,
        telegram_chat_id=telegram_chat_id, telegram_topic_id=telegram_topic_id, telegram_message_id=telegram_message_id,
    )
    session.add(proposal)
    await session.commit()
    await session.refresh(proposal)
    return proposal


async def get_proposal(session: AsyncSession, proposal_id: UUID) -> TelegramSurfaceProposal | None:
    return await session.get(TelegramSurfaceProposal, proposal_id)


async def confirm_proposal(
    session: AsyncSession, proposal_id: UUID, *, decided_by: int,
) -> TelegramSurfaceProposal | None:
    """Idempotent and immutable-once-final (identical policy to services/business_context_
    proposal_service.py::confirm_proposal()): a second CONFIRM on an already-final proposal is a
    no-op returning the unchanged row - never a duplicate TelegramSurface write. Uses upsert_
    surface() so even confirming two DIFFERENT proposals for the same chat_id never creates two
    rows, only updates the one surface in place."""
    proposal = await session.get(TelegramSurfaceProposal, proposal_id)
    if proposal is None:
        return None
    if proposal.status != TelegramSurfaceProposalStatus.PENDING:
        return proposal

    surface = await upsert_surface(
        session, chat_id=proposal.chat_id, role=proposal.role, name=proposal.name, username=proposal.username,
        active=proposal.active, analytics_enabled=proposal.analytics_enabled,
    )

    proposal.status = TelegramSurfaceProposalStatus.CONFIRMED
    proposal.decided_at = datetime.now(timezone.utc)
    proposal.decided_by = decided_by
    proposal.resulting_surface_id = surface.id
    await session.commit()
    await session.refresh(proposal)
    return proposal


async def cancel_proposal(session: AsyncSession, proposal_id: UUID, *, decided_by: int) -> TelegramSurfaceProposal | None:
    """Idempotent: mirrors confirm_proposal()'s own immutable-once-final policy. Never mutates
    TelegramSurface."""
    proposal = await session.get(TelegramSurfaceProposal, proposal_id)
    if proposal is None:
        return None
    if proposal.status != TelegramSurfaceProposalStatus.PENDING:
        return proposal
    proposal.status = TelegramSurfaceProposalStatus.CANCELLED
    proposal.decided_at = datetime.now(timezone.utc)
    proposal.decided_by = decided_by
    await session.commit()
    await session.refresh(proposal)
    return proposal
