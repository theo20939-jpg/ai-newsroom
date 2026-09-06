"""SOCIAL-INTELLIGENCE-PRELAUNCH-1 §12/§13/§14: SocialLaunchProposal persistence + the ONLY place
a SocialLaunchContext row is ever written from a Telegram command. Mirrors services/
telegram_surface_proposal_service.py's own propose->confirm/cancel shape exactly.

`confirm_proposal()` is the sole function that turns a proposal into a real SocialLaunchContext
row - it NEVER runs from the parser directly (same "never let an LLM self-confirm its own proposed
mutation" discipline services/business_context_proposal_service.py already established), only from
bot/handlers/launch.py's own confirm callback, after an already-authorized FOUNDER has pressed
Confirm."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.social_launch_context import (
    HistoricalContentPolicy,
    LaunchDateStatus,
    LaunchState,
    LearningBaselinePolicy,
    SocialLaunchPlatform,
)
from database.models.social_launch_proposal import SocialLaunchProposal, SocialLaunchProposalStatus
from services.social_launch_context_service import create_next_version, get_current_context


async def create_proposal(
    session: AsyncSession, *, platform: SocialLaunchPlatform, raw_instruction: str,
    parsed_structure: dict[str, Any], created_by: int, telegram_chat_id: int | None = None,
    telegram_topic_id: int | None = None, telegram_message_id: int | None = None,
) -> SocialLaunchProposal:
    proposal = SocialLaunchProposal(
        platform=platform, raw_instruction=raw_instruction, parsed_structure=parsed_structure,
        created_by=created_by, telegram_chat_id=telegram_chat_id, telegram_topic_id=telegram_topic_id,
        telegram_message_id=telegram_message_id,
    )
    session.add(proposal)
    await session.commit()
    await session.refresh(proposal)
    return proposal


async def get_proposal(session: AsyncSession, proposal_id: UUID) -> SocialLaunchProposal | None:
    return await session.get(SocialLaunchProposal, proposal_id)


async def confirm_proposal(
    session: AsyncSession, proposal_id: UUID, *, decided_by: int,
) -> SocialLaunchProposal | None:
    """Idempotent and immutable-once-final, byte-for-byte the same policy services/
    telegram_surface_proposal_service.py::confirm_proposal() already established. Carries
    `learning_start_at` FORWARD UNCHANGED from the previous version for this platform (spec §5's
    own "existing advisory plans become stale and are regenerated" instruction is about advisory
    plans, never about silently resetting an already-established real learning boundary) - a new
    /launch instruction can change strategy fields, never retroactively erase a real event
    timestamp that already happened."""
    proposal = await session.get(SocialLaunchProposal, proposal_id)
    if proposal is None:
        return None
    if proposal.status != SocialLaunchProposalStatus.PENDING:
        return proposal

    structure = proposal.parsed_structure or {}
    previous = await get_current_context(session, proposal.platform)

    planned_launch_at: datetime | None = None
    raw_date = structure.get("planned_launch_at")
    if raw_date:
        parsed = datetime.fromisoformat(raw_date)
        planned_launch_at = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)

    context = await create_next_version(
        session, platform=proposal.platform,
        target_identity=structure.get("target_identity") or (previous.target_identity if previous else "NINJA PULSE"),
        current_identity=structure.get("current_identity", previous.current_identity if previous else None),
        launch_state=LaunchState(structure["launch_state"]) if structure.get("launch_state") else (
            previous.launch_state if previous else LaunchState.PRE_LAUNCH
        ),
        planned_launch_at=planned_launch_at if raw_date else (previous.planned_launch_at if previous else None),
        launch_date_status=LaunchDateStatus(structure["launch_date_status"]) if structure.get("launch_date_status") else (
            previous.launch_date_status if previous else LaunchDateStatus.UNSCHEDULED
        ),
        baseline_policy=LearningBaselinePolicy(structure["baseline_policy"]) if structure.get("baseline_policy") else (
            previous.baseline_policy if previous else LearningBaselinePolicy.FROM_FIRST_PUBLICATION
        ),
        historical_content_policy=(
            HistoricalContentPolicy(structure["historical_content_policy"]) if structure.get("historical_content_policy")
            else (previous.historical_content_policy if previous else HistoricalContentPolicy.LEGACY_CONTEXT_ONLY)
        ),
        raw_instruction=proposal.raw_instruction, confirmed_structure=structure, created_by=decided_by,
        learning_start_at=previous.learning_start_at if previous else None,
        campaign_id=previous.campaign_id if previous else None, surface_id=previous.surface_id if previous else None,
    )

    proposal.status = SocialLaunchProposalStatus.CONFIRMED
    proposal.decided_at = datetime.now(timezone.utc)
    proposal.decided_by = decided_by
    proposal.resulting_context_id = context.id
    await session.commit()
    await session.refresh(proposal)
    return proposal


async def cancel_proposal(session: AsyncSession, proposal_id: UUID, *, decided_by: int) -> SocialLaunchProposal | None:
    proposal = await session.get(SocialLaunchProposal, proposal_id)
    if proposal is None:
        return None
    if proposal.status != SocialLaunchProposalStatus.PENDING:
        return proposal
    proposal.status = SocialLaunchProposalStatus.CANCELLED
    proposal.decided_at = datetime.now(timezone.utc)
    proposal.decided_by = decided_by
    await session.commit()
    await session.refresh(proposal)
    return proposal
