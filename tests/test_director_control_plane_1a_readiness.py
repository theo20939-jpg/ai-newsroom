"""DIRECTOR-CONTROL-PLANE-1A §26/§27: the two required readiness tests.

§26 - Telegram-surface-registration-readiness: the real NINJA VPN -> NINJA PULSE transition
scenario - feed readable, old posts context-visible, old performance learning excluded.

§27 - Instagram-connection-readiness: must PASS without any real credentials configured (this test
environment has none) - proves the adapter/config/capability-detection/context-wiring/secret-safe
behavior are all real and implemented, never a fabricated connected state."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.social_launch_context import (
    HistoricalContentPolicy,
    LaunchDateStatus,
    LaunchState,
    LearningBaselinePolicy,
    SocialLaunchContext,
    SocialLaunchPlatform,
)
from services import instagram_graph_adapter
from services.instagram_connection_readiness import InstagramReadinessState, account_readiness_summary, resolve_instagram_readiness_state
from services.instagram_graph_adapter import InstagramNotConnectedError
from services.platform_account_context import build_instagram_account_context
from services.telegram_feed_window import build_telegram_feed_window

_LAUNCH_START = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _transition_launch_context() -> SocialLaunchContext:
    return SocialLaunchContext(
        platform=SocialLaunchPlatform.TELEGRAM, version=1, launch_state=LaunchState.LIVE,
        launch_date_status=LaunchDateStatus.CONFIRMED, planned_launch_at=None,
        learning_start_at=_LAUNCH_START, baseline_policy=LearningBaselinePolicy.FROM_EXPLICIT_DATE,
        historical_content_policy=HistoricalContentPolicy.LEGACY_CONTEXT_ONLY,
        current_identity="NINJA VPN", target_identity="NINJA PULSE",
        raw_instruction="test", confirmed_structure={}, created_by=1,
    )


class TestTelegramSurfaceRegistrationReadiness:
    """§26's own real NINJA VPN -> NINJA PULSE transition scenario."""

    def test_unregistered_surface_is_honestly_empty_never_fabricated(self) -> None:
        window = build_telegram_feed_window(None, launch_context=None)
        assert window.surface_registered is False
        assert window.posts == []

    def test_old_vpn_era_posts_are_readable_as_transition_context(self) -> None:
        """Legacy NINJA VPN-era posts must be READ_CONTEXT_ELIGIBLE (spec §10's own "understand
        what the current audience already saw" allowance) even though they can never feed
        performance learning."""
        raw = {
            "recent_posts": [
                {
                    "message_id": 100, "date": (_LAUNCH_START - timedelta(days=90)).isoformat(),
                    "media_type": "photo", "text_length": 80,
                },
            ],
        }
        window = build_telegram_feed_window(raw, launch_context=_transition_launch_context())
        assert len(window.posts) == 1
        vpn_era_post = window.posts[0]
        assert vpn_era_post.is_legacy is True
        assert vpn_era_post.read_context_eligible is True

    def test_old_vpn_era_posts_never_feed_performance_learning(self) -> None:
        raw = {
            "recent_posts": [
                {
                    "message_id": 100, "date": (_LAUNCH_START - timedelta(days=90)).isoformat(),
                    "media_type": "photo", "text_length": 80,
                },
            ],
        }
        window = build_telegram_feed_window(raw, launch_context=_transition_launch_context())
        assert window.learning_eligible_posts == []
        assert window.legacy_posts == window.posts

    def test_new_pulse_era_posts_are_performance_learning_eligible(self) -> None:
        raw = {
            "recent_posts": [
                {
                    "message_id": 200, "date": (_LAUNCH_START + timedelta(days=5)).isoformat(),
                    "media_type": "photo", "text_length": 80,
                },
            ],
        }
        window = build_telegram_feed_window(raw, launch_context=_transition_launch_context())
        assert len(window.learning_eligible_posts) == 1
        assert window.legacy_posts == []

    def test_mixed_transition_feed_correctly_splits_legacy_from_eligible(self) -> None:
        """The realistic transition-window shape: some VPN-era history still in the recent window,
        alongside the first real PULSE-era posts - both readable, only the new ones learning-eligible."""
        raw = {
            "recent_posts": [
                {"message_id": 100, "date": (_LAUNCH_START - timedelta(days=30)).isoformat(), "media_type": "photo", "text_length": 50},
                {"message_id": 101, "date": (_LAUNCH_START - timedelta(days=10)).isoformat(), "media_type": "photo", "text_length": 60},
                {"message_id": 200, "date": (_LAUNCH_START + timedelta(days=1)).isoformat(), "media_type": "video", "text_length": 40},
                {"message_id": 201, "date": (_LAUNCH_START + timedelta(days=3)).isoformat(), "media_type": "photo", "text_length": 45},
            ],
        }
        window = build_telegram_feed_window(raw, launch_context=_transition_launch_context())
        assert len(window.posts) == 4
        assert all(p.read_context_eligible for p in window.posts)
        assert len(window.legacy_posts) == 2
        assert len(window.learning_eligible_posts) == 2


class TestInstagramConnectionReadiness:
    """§27: must PASS with zero real Instagram credentials configured - proves the adapter/config/
    capability-detection/context-wiring/secret-safe layers are real, not stubs."""

    def test_not_configured_in_this_environment(self) -> None:
        assert instagram_graph_adapter.is_configured() is False

    @pytest.mark.asyncio
    async def test_fetch_calls_raise_not_connected_never_a_fabricated_result(self) -> None:
        with pytest.raises(InstagramNotConnectedError):
            await instagram_graph_adapter.fetch_profile_snapshot()
        with pytest.raises(InstagramNotConnectedError):
            await instagram_graph_adapter.fetch_recent_media()
        with pytest.raises(InstagramNotConnectedError):
            await instagram_graph_adapter.fetch_media_insights("m1")

    @pytest.mark.asyncio
    async def test_context_wiring_never_fabricates_a_connected_account(self, db_session: AsyncSession) -> None:
        now = datetime(2026, 9, 8, tzinfo=timezone.utc)
        context = await build_instagram_account_context(db_session, now=now)
        assert context.canonical_account_id is None
        readiness_state = resolve_instagram_readiness_state(context)
        assert readiness_state is InstagramReadinessState.NOT_CONFIGURED

        summary = account_readiness_summary(context)
        assert summary["readiness_state"] == "NOT_CONFIGURED"
        assert summary["account_state"] == "PRE_LAUNCH"
        assert summary["first_party_baseline"] == "NONE"
        assert summary["connection_required"] is True

    def test_secret_token_value_never_leaks_through_readiness_reporting(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Even if a real token WERE configured, resolve_instagram_readiness_state()/
        account_readiness_summary() must never surface the raw secret value anywhere in their
        output - they only ever report the boolean/state derived from it."""
        monkeypatch.setattr(settings, "instagram_access_token", SecretStr("super-secret-token-value"))
        monkeypatch.setattr(settings, "instagram_business_account_id", "17800000000000000")
        assert instagram_graph_adapter.is_configured() is True

        from services.platform_account_context import PlatformAccountContext
        context = PlatformAccountContext(
            platform="instagram", canonical_account_id="17800000000000000", surface_role=None,
            display_name=None, username=None, profile_description=None, avatar_reference=None,
            launch_state=None, connection_state="not_connected",
        )
        summary = account_readiness_summary(context)
        assert "super-secret-token-value" not in str(summary)
        assert "super-secret-token-value" not in str(context)
