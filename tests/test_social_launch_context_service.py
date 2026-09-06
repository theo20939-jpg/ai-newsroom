"""SOCIAL-INTELLIGENCE-PRELAUNCH-1 §41/§42/§46: SocialLaunchContextService - versioning,
staleness fingerprint, and cold-start/empty-account handling."""
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.social_launch_context import (
    HistoricalContentPolicy,
    LaunchDateStatus,
    LaunchState,
    LearningBaselinePolicy,
    SocialLaunchPlatform,
)
from services.social_launch_context_service import (
    compute_launch_context_fingerprint,
    create_next_version,
    describe_launch_context_for_creative,
    get_current_context,
    is_prelaunch_or_transition,
    list_history,
)

pytestmark = pytest.mark.asyncio


async def _create(session: AsyncSession, *, platform: SocialLaunchPlatform, **overrides: Any):
    defaults: dict[str, Any] = dict(
        target_identity="NINJA PULSE", current_identity=None, launch_state=LaunchState.PRE_LAUNCH,
        planned_launch_at=None, launch_date_status=LaunchDateStatus.UNSCHEDULED,
        baseline_policy=LearningBaselinePolicy.FROM_FIRST_PUBLICATION,
        historical_content_policy=HistoricalContentPolicy.LEGACY_CONTEXT_ONLY,
        raw_instruction="test instruction", confirmed_structure={"summary": "test"}, created_by=5507703201,
    )
    defaults.update(overrides)
    return await create_next_version(session, platform=platform, **defaults)


async def test_no_context_yet_is_a_valid_cold_start_state(db_session: AsyncSession) -> None:
    """spec §42: zero posts / zero context is valid, never an error state."""
    context = await get_current_context(db_session, SocialLaunchPlatform.INSTAGRAM)
    assert context is None
    assert is_prelaunch_or_transition(context) is True


async def test_confirming_a_new_instruction_creates_a_new_version_never_overwrites(db_session: AsyncSession) -> None:
    """spec §43: history/versioning preserved."""
    v1 = await _create(db_session, platform=SocialLaunchPlatform.TELEGRAM, current_identity="NINJA VPN")
    assert v1.version == 1

    v2 = await _create(db_session, platform=SocialLaunchPlatform.TELEGRAM, current_identity="NINJA VPN (rebrand in progress)")
    assert v2.version == 2
    assert v2.id != v1.id

    current = await get_current_context(db_session, SocialLaunchPlatform.TELEGRAM)
    assert current is not None
    assert current.id == v2.id

    history = await list_history(db_session, SocialLaunchPlatform.TELEGRAM)
    assert [h.version for h in history] == [2, 1]
    assert history[1].current_identity == "NINJA VPN"  # v1 preserved unchanged, never overwritten


async def test_platforms_are_independent(db_session: AsyncSession) -> None:
    await _create(db_session, platform=SocialLaunchPlatform.TELEGRAM)
    instagram_context = await get_current_context(db_session, SocialLaunchPlatform.INSTAGRAM)
    assert instagram_context is None  # Telegram's own version history never leaks into Instagram


async def test_fingerprint_changes_when_launch_state_changes(db_session: AsyncSession) -> None:
    v1 = await _create(db_session, platform=SocialLaunchPlatform.TELEGRAM, launch_state=LaunchState.PRE_LAUNCH)
    v2 = await _create(db_session, platform=SocialLaunchPlatform.TELEGRAM, launch_state=LaunchState.TRANSITION)
    assert compute_launch_context_fingerprint(v1) != compute_launch_context_fingerprint(v2)


async def test_fingerprint_is_stable_for_identical_content() -> None:
    from database.models.social_launch_context import SocialLaunchContext
    import uuid
    from datetime import datetime, timezone

    kwargs = dict(
        id=uuid.uuid4(), platform=SocialLaunchPlatform.TELEGRAM, version=1, target_identity="NINJA PULSE",
        current_identity="NINJA VPN", launch_state=LaunchState.TRANSITION, planned_launch_at=None,
        launch_date_status=LaunchDateStatus.TENTATIVE, learning_start_at=None,
        baseline_policy=LearningBaselinePolicy.FROM_FIRST_POST_AFTER_LAUNCH,
        historical_content_policy=HistoricalContentPolicy.LEGACY_CONTEXT_ONLY,
        raw_instruction="x", confirmed_structure={}, created_by=1, created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    a = SocialLaunchContext(**kwargs)
    b = SocialLaunchContext(**{**kwargs, "id": uuid.uuid4()})  # different row id, same content
    assert compute_launch_context_fingerprint(a) == compute_launch_context_fingerprint(b)


async def test_none_context_fingerprint_is_none() -> None:
    assert compute_launch_context_fingerprint(None) is None


async def test_describe_launch_context_for_creative_is_empty_for_no_context_or_live(db_session: AsyncSession) -> None:
    """SOCIAL-INTELLIGENCE-PRELAUNCH-1A §7: an established (LIVE) or unconfigured platform gets no
    injected launch framing at all - the empty string is CreativeDirectorInput.launch_context_note's
    own default, so every existing caller stays byte-for-byte unaffected."""
    assert describe_launch_context_for_creative(None) == ""
    live_context = await _create(db_session, platform=SocialLaunchPlatform.INSTAGRAM, launch_state=LaunchState.LIVE)
    assert describe_launch_context_for_creative(live_context) == ""


async def test_describe_launch_context_for_creative_distinguishes_pre_launch_from_transition(db_session: AsyncSession) -> None:
    """PRE_LAUNCH and TRANSITION are real, distinct states (spec §7) - a rebrand-in-progress
    account gets framing about the OLD identity too, a brand-new account does not (it has none)."""
    pre_launch = await _create(db_session, platform=SocialLaunchPlatform.INSTAGRAM, launch_state=LaunchState.PRE_LAUNCH)
    pre_launch_text = describe_launch_context_for_creative(pre_launch)
    assert "NINJA PULSE" in pre_launch_text
    assert "zero follower familiarity" in pre_launch_text

    transition = await _create(
        db_session, platform=SocialLaunchPlatform.TELEGRAM, launch_state=LaunchState.TRANSITION,
        current_identity="NINJA VPN news",
    )
    transition_text = describe_launch_context_for_creative(transition)
    assert "NINJA VPN news" in transition_text
    assert "NINJA PULSE" in transition_text
    assert "transitioning" in transition_text
