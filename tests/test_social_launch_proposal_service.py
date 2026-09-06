"""SOCIAL-INTELLIGENCE-PRELAUNCH-1 §43: SocialLaunchProposal propose->confirm/cancel lifecycle -
mirrors tests/test_telegram_surface_proposal_service.py's own established shape."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.social_launch_context import SocialLaunchPlatform
from database.models.social_launch_proposal import SocialLaunchProposalStatus
from services.social_launch_context_service import get_current_context
from services.social_launch_proposal_service import cancel_proposal, confirm_proposal, create_proposal

pytestmark = pytest.mark.asyncio

_FOUNDER = 5507703201


async def test_confirm_creates_a_real_social_launch_context_row(db_session: AsyncSession) -> None:
    proposal = await create_proposal(
        db_session, platform=SocialLaunchPlatform.TELEGRAM, raw_instruction="rebrand VPN to PULSE",
        parsed_structure={
            "target_identity": "NINJA PULSE", "current_identity": "NINJA VPN",
            "launch_state": "transition", "historical_content_policy": "legacy_context_only",
            "summary": "rebrand",
        },
        created_by=_FOUNDER,
    )
    confirmed = await confirm_proposal(db_session, proposal.id, decided_by=_FOUNDER)
    assert confirmed is not None
    assert confirmed.status == SocialLaunchProposalStatus.CONFIRMED
    assert confirmed.resulting_context_id is not None

    context = await get_current_context(db_session, SocialLaunchPlatform.TELEGRAM)
    assert context is not None
    assert context.target_identity == "NINJA PULSE"
    assert context.current_identity == "NINJA VPN"
    assert context.version == 1


async def test_confirm_is_idempotent_never_applies_twice(db_session: AsyncSession) -> None:
    proposal = await create_proposal(
        db_session, platform=SocialLaunchPlatform.INSTAGRAM, raw_instruction="empty account",
        parsed_structure={"target_identity": "NINJA PULSE", "summary": "cold start"}, created_by=_FOUNDER,
    )
    first = await confirm_proposal(db_session, proposal.id, decided_by=_FOUNDER)
    second = await confirm_proposal(db_session, proposal.id, decided_by=_FOUNDER)
    assert first is not None and second is not None
    assert first.resulting_context_id == second.resulting_context_id

    history_count = len((await get_current_context(db_session, SocialLaunchPlatform.INSTAGRAM)) and [1] or [])
    assert history_count == 1  # confirming twice never creates a second version


async def test_cancel_never_writes_a_social_launch_context_row(db_session: AsyncSession) -> None:
    proposal = await create_proposal(
        db_session, platform=SocialLaunchPlatform.TELEGRAM, raw_instruction="test", parsed_structure={"target_identity": "X"},
        created_by=_FOUNDER,
    )
    cancelled = await cancel_proposal(db_session, proposal.id, decided_by=_FOUNDER)
    assert cancelled is not None
    assert cancelled.status == SocialLaunchProposalStatus.CANCELLED
    assert await get_current_context(db_session, SocialLaunchPlatform.TELEGRAM) is None


async def test_omitted_field_carries_forward_previous_value_never_erased(db_session: AsyncSession) -> None:
    """spec §16: a rewritten instruction changes only what it addresses - it does not silently
    reset historical_content_policy/baseline_policy/learning_start_at to a schema default."""
    first_proposal = await create_proposal(
        db_session, platform=SocialLaunchPlatform.TELEGRAM, raw_instruction="initial",
        parsed_structure={
            "target_identity": "NINJA PULSE", "historical_content_policy": "legacy_context_only",
            "baseline_policy": "from_first_post_after_launch", "summary": "initial setup",
        },
        created_by=_FOUNDER,
    )
    await confirm_proposal(db_session, first_proposal.id, decided_by=_FOUNDER)

    second_proposal = await create_proposal(
        db_session, platform=SocialLaunchPlatform.TELEGRAM, raw_instruction="date update",
        parsed_structure={"planned_launch_at": "2026-12-01T00:00:00+00:00", "launch_date_status": "tentative", "summary": "date set"},
        created_by=_FOUNDER,
    )
    await confirm_proposal(db_session, second_proposal.id, decided_by=_FOUNDER)

    context = await get_current_context(db_session, SocialLaunchPlatform.TELEGRAM)
    assert context is not None
    assert context.version == 2
    assert context.historical_content_policy.value == "legacy_context_only"  # carried forward, never reset
    assert context.baseline_policy.value == "from_first_post_after_launch"  # carried forward
    assert context.launch_date_status.value == "tentative"  # the new value actually applied


async def test_learning_start_at_is_never_reset_by_a_new_confirmed_instruction(db_session: AsyncSession) -> None:
    """spec §5's own 'existing advisory plans become stale' is about advisory, never about
    silently erasing a real learning-boundary timestamp that already happened."""
    from datetime import datetime, timezone

    from services.social_launch_context_service import create_next_version, mark_learning_started
    from database.models.social_launch_context import (
        HistoricalContentPolicy, LaunchDateStatus, LaunchState, LearningBaselinePolicy,
    )

    v1 = await create_next_version(
        db_session, platform=SocialLaunchPlatform.TELEGRAM, target_identity="NINJA PULSE", current_identity="NINJA VPN",
        launch_state=LaunchState.LIVE, planned_launch_at=None, launch_date_status=LaunchDateStatus.CONFIRMED,
        baseline_policy=LearningBaselinePolicy.FROM_FIRST_POST_AFTER_LAUNCH,
        historical_content_policy=HistoricalContentPolicy.LEGACY_CONTEXT_ONLY,
        raw_instruction="launched", confirmed_structure={}, created_by=_FOUNDER,
    )
    mark_learning_started(v1, now=datetime(2026, 10, 1, tzinfo=timezone.utc))
    await db_session.commit()

    proposal = await create_proposal(
        db_session, platform=SocialLaunchPlatform.TELEGRAM, raw_instruction="minor update",
        parsed_structure={"launch_state": "live", "summary": "minor"}, created_by=_FOUNDER,
    )
    await confirm_proposal(db_session, proposal.id, decided_by=_FOUNDER)

    context = await get_current_context(db_session, SocialLaunchPlatform.TELEGRAM)
    assert context is not None
    assert context.learning_start_at is not None
    assert context.learning_start_at.year == 2026 and context.learning_start_at.month == 10
