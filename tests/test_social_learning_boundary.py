"""SOCIAL-INTELLIGENCE-PRELAUNCH-1 §41: is_eligible_for_first_party_learning() - old VPN posts
before the learning boundary must never contaminate PULSE performance evidence."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from database.models.social_launch_context import (
    HistoricalContentPolicy,
    LaunchDateStatus,
    LaunchState,
    LearningBaselinePolicy,
    SocialLaunchContext,
    SocialLaunchPlatform,
)
from services.social_learning_boundary import is_eligible_for_first_party_learning

_NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)


def _context(**overrides) -> SocialLaunchContext:
    defaults = dict(
        platform=SocialLaunchPlatform.TELEGRAM, version=1, target_identity="NINJA PULSE",
        current_identity="NINJA VPN", launch_state=LaunchState.TRANSITION, planned_launch_at=None,
        launch_date_status=LaunchDateStatus.TENTATIVE, learning_start_at=_NOW,
        baseline_policy=LearningBaselinePolicy.FROM_FIRST_POST_AFTER_LAUNCH,
        historical_content_policy=HistoricalContentPolicy.LEGACY_CONTEXT_ONLY,
        raw_instruction="test", confirmed_structure={}, created_by=1,
    )
    defaults.update(overrides)
    return SocialLaunchContext(**defaults)


def test_no_launch_context_means_nothing_is_eligible() -> None:
    """Fail-safe: with no context ever configured, no boundary has ever been established."""
    assert is_eligible_for_first_party_learning(published_at=_NOW, launch_context=None) is False


def test_old_vpn_post_before_learning_boundary_is_excluded() -> None:
    context = _context(learning_start_at=_NOW)
    old_post = _NOW - timedelta(days=30)
    assert is_eligible_for_first_party_learning(published_at=old_post, launch_context=context) is False


def test_post_after_learning_boundary_is_eligible() -> None:
    context = _context(learning_start_at=_NOW)
    new_post = _NOW + timedelta(hours=1)
    assert is_eligible_for_first_party_learning(published_at=new_post, launch_context=context) is True


def test_no_learning_start_at_yet_excludes_every_post() -> None:
    """learning_start_at is NULL until the real boundary event actually happens - a post
    published even far in the future is still ineligible if learning has not started."""
    context = _context(learning_start_at=None)
    future_post = _NOW + timedelta(days=365)
    assert is_eligible_for_first_party_learning(published_at=future_post, launch_context=context) is False


def test_include_in_learning_policy_bypasses_the_boundary() -> None:
    """The one deliberate escape hatch (spec §8) - a platform with no meaningful pre/post-launch
    distinction at all. Old posts are eligible even with no learning_start_at set."""
    context = _context(historical_content_policy=HistoricalContentPolicy.INCLUDE_IN_LEARNING, learning_start_at=None)
    old_post = _NOW - timedelta(days=365)
    assert is_eligible_for_first_party_learning(published_at=old_post, launch_context=context) is True


def test_legacy_context_only_never_lets_a_pre_boundary_post_count_regardless_of_how_old() -> None:
    """spec §7: legacy VPN posts may remain visible as history elsewhere, but this function must
    never return True for them under LEGACY_CONTEXT_ONLY, no matter how the boundary is framed."""
    context = _context(historical_content_policy=HistoricalContentPolicy.LEGACY_CONTEXT_ONLY, learning_start_at=_NOW)
    for days_before in (1, 30, 365, 3650):
        old_post = _NOW - timedelta(days=days_before)
        assert is_eligible_for_first_party_learning(published_at=old_post, launch_context=context) is False
