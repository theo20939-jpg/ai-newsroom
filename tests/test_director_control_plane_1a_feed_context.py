"""DIRECTOR-CONTROL-PLANE-1A §35: real feed-context tests for both Telegram
(services/telegram_feed_window.py) and Instagram (services/instagram_feed_context.py +
services/instagram_connection_readiness.py) - proves the legacy-vs-learning-eligible separation is
real, the bounded window is honestly empty when no surface/account is registered, and that no
fabricated "connected" state is ever produced without a real account row / real posts."""
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
from services.instagram_connection_readiness import (
    InstagramReadinessState,
    account_readiness_summary,
    resolve_instagram_readiness_state,
)
from services.instagram_feed_context import build_instagram_feed_context
from services.platform_account_context import PlatformAccountContext
from services.telegram_feed_window import build_telegram_feed_window

_NOW = datetime(2026, 9, 8, tzinfo=timezone.utc)


def _launch_context(learning_start_at: datetime | None) -> SocialLaunchContext:
    return SocialLaunchContext(
        platform=SocialLaunchPlatform.TELEGRAM, version=1, launch_state=LaunchState.LIVE,
        launch_date_status=LaunchDateStatus.CONFIRMED, planned_launch_at=None,
        learning_start_at=learning_start_at,
        baseline_policy=LearningBaselinePolicy.FROM_EXPLICIT_DATE,
        historical_content_policy=HistoricalContentPolicy.LEGACY_CONTEXT_ONLY,
        current_identity="NINJA VPN", target_identity="NINJA PULSE",
        raw_instruction="test", confirmed_structure={}, created_by=1,
    )


class TestTelegramFeedWindow:
    def test_no_surface_registered_returns_honestly_empty_window(self) -> None:
        window = build_telegram_feed_window(None, launch_context=None)
        assert window.surface_registered is False
        assert window.posts == []
        assert window.learning_eligible_posts == []

    def test_legacy_posts_are_read_context_eligible_but_never_learning_eligible(self) -> None:
        learning_start = _NOW - timedelta(days=10)
        raw = {
            "recent_posts": [
                {
                    "message_id": 1, "date": (learning_start - timedelta(days=30)).isoformat(),
                    "media_type": "photo", "text_length": 40, "views": 1000, "reactions_total": 5, "forwards": 1,
                },
                {
                    "message_id": 2, "date": (learning_start + timedelta(days=1)).isoformat(),
                    "media_type": "photo", "text_length": 60, "views": 500, "reactions_total": 10, "forwards": 2,
                },
            ],
        }
        window = build_telegram_feed_window(raw, launch_context=_launch_context(learning_start))
        assert window.surface_registered is True
        assert len(window.posts) == 2
        legacy_post, new_post = window.posts
        assert legacy_post.is_legacy is True
        assert legacy_post.read_context_eligible is True
        assert legacy_post.performance_learning_eligible is False
        assert new_post.is_legacy is False
        assert new_post.performance_learning_eligible is True
        assert window.legacy_posts == [legacy_post]
        assert window.learning_eligible_posts == [new_post]

    def test_bounded_window_never_exceeds_fetched_posts(self) -> None:
        raw = {
            "recent_posts": [
                {"message_id": i, "date": _NOW.isoformat(), "media_type": "photo", "text_length": 10}
                for i in range(30)
            ],
        }
        window = build_telegram_feed_window(raw, launch_context=None)
        assert len(window.posts) == 30

    def test_media_type_distribution_is_a_real_bounded_count(self) -> None:
        raw = {
            "recent_posts": [
                {"message_id": 1, "date": _NOW.isoformat(), "media_type": "photo", "text_length": 10},
                {"message_id": 2, "date": _NOW.isoformat(), "media_type": "photo", "text_length": 10},
                {"message_id": 3, "date": _NOW.isoformat(), "media_type": "video", "text_length": 10},
            ],
        }
        window = build_telegram_feed_window(raw, launch_context=None)
        assert window.media_type_distribution == {"photo": 2, "video": 1}


def _account_context(*, connection_state: str) -> PlatformAccountContext:
    return PlatformAccountContext(
        platform="instagram", canonical_account_id=None, surface_role=None, display_name=None,
        username=None, profile_description=None, avatar_reference=None, launch_state=None,
        connection_state=connection_state,
    )


class TestInstagramReadiness:
    def test_not_configured_when_graph_api_not_configured(self) -> None:
        state = resolve_instagram_readiness_state(_account_context(connection_state="connection_required"))
        assert state is InstagramReadinessState.NOT_CONFIGURED

    def test_not_configured_when_account_row_missing(self) -> None:
        state = resolve_instagram_readiness_state(_account_context(connection_state="not_registered"))
        assert state is InstagramReadinessState.NOT_CONFIGURED

    def test_not_configured_when_account_row_never_connected(self) -> None:
        state = resolve_instagram_readiness_state(_account_context(connection_state="not_connected"))
        assert state is InstagramReadinessState.NOT_CONFIGURED

    def test_error_state_is_reported_honestly(self) -> None:
        state = resolve_instagram_readiness_state(_account_context(connection_state="error"))
        assert state is InstagramReadinessState.ERROR

    def test_connected_only_when_real_account_row_says_so(self) -> None:
        state = resolve_instagram_readiness_state(_account_context(connection_state="registered"))
        assert state is InstagramReadinessState.CONNECTED

    def test_account_readiness_summary_never_claims_first_party_baseline_when_not_connected(self) -> None:
        summary = account_readiness_summary(_account_context(connection_state="connection_required"))
        assert summary["readiness_state"] == "NOT_CONFIGURED"
        assert summary["account_state"] == "PRE_LAUNCH"
        assert summary["first_party_baseline"] == "NONE"
        assert summary["connection_required"] is True


class TestInstagramFeedContext:
    def test_no_credentials_returns_honestly_empty_context(self) -> None:
        context = build_instagram_feed_context(
            None, readiness_state=InstagramReadinessState.NOT_CONFIGURED, launch_context=None,
        )
        assert context.posts == []
        assert context.readiness_state is InstagramReadinessState.NOT_CONFIGURED

    def test_connected_mock_feed_supplies_real_shaped_posts_with_legacy_split(self) -> None:
        learning_start = _NOW - timedelta(days=5)
        raw_media = [
            {
                "media_id": "m1", "timestamp": (learning_start - timedelta(days=20)).isoformat(),
                "media_type": "IMAGE", "caption_length": 30, "like_count": 100, "comment_count": 4,
            },
            {
                "media_id": "m2", "timestamp": (learning_start + timedelta(days=2)).isoformat(),
                "media_type": "IMAGE", "caption_length": 20, "like_count": 200, "comment_count": 8,
            },
        ]
        context = build_instagram_feed_context(
            raw_media, readiness_state=InstagramReadinessState.CONNECTED,
            launch_context=_launch_context(learning_start),
        )
        assert len(context.posts) == 2
        assert len(context.legacy_posts) == 1
        assert len(context.learning_eligible_posts) == 1
        assert context.media_type_distribution == {"IMAGE": 2}
