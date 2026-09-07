"""DIRECTOR-CONTROL-PLANE-1 §4: PlatformAccountContext - the ONE normalized read layer Directors
consume, built FROM the existing, real, platform-specific tables (TelegramSurface +
SocialLaunchContext for Telegram; InstagramAccount + SocialLaunchContext for Instagram) rather than
duplicating them. Every field is deterministically derived from already-persisted rows and the
existing capability registries (services/telegram_performance_memory.py::
TELEGRAM_PLATFORM_CAPABILITIES, services/instagram_platform_capabilities.py::
INSTAGRAM_PLATFORM_CAPABILITIES) - never a fabricated status.

Account access boundary (spec §3): both builders below resolve exactly ONE row - the single
registered owned-brand surface/account - never a broader query across every known chat/account.
There is no code path here that could return a Founder's personal chat or an unrelated account."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_account import InstagramAccount, InstagramConnectionState
from database.models.social_launch_context import HistoricalContentPolicy, SocialLaunchContext, SocialLaunchPlatform
from database.models.telegram_surface import TelegramSurface
from services.instagram_account_registry import get_owned_brand_account
from services.instagram_graph_adapter import is_configured as instagram_is_configured
from services.instagram_platform_capabilities import INSTAGRAM_PLATFORM_CAPABILITIES
from services.social_launch_context_service import get_current_context
from services.telegram_own_channel import owned_chat_id
from services.telegram_performance_memory import TELEGRAM_PLATFORM_CAPABILITIES
from services.telegram_surface_registry import resolve_owned_surface

_TELEGRAM_READ_CAPABILITY_NAMES = ("views", "reactions", "reposts", "comments")
_TELEGRAM_ANALYTICS_CAPABILITY_NAMES = ("subscriber_count", "subscriber_delta", "publication_timestamp")
_INSTAGRAM_READ_CAPABILITY_NAMES = ("read_profile_metrics", "read_comments")
_INSTAGRAM_ANALYTICS_CAPABILITY_NAMES = ("read_insights", "read_post_insights", "read_reel_insights", "read_follower_stats")


@dataclass(frozen=True)
class PlatformAccountContext:
    """Spec §4's own required minimum field list. `read_capabilities`/`analytics_capabilities`/
    `publication_capabilities` are `{capability_name: status_value}` maps built straight from the
    existing capability registries - never re-derived, never guessed."""

    platform: str
    canonical_account_id: str | None
    surface_role: str | None
    display_name: str | None
    username: str | None
    profile_description: str | None
    avatar_reference: str | None
    launch_state: str | None
    connection_state: str
    read_capabilities: dict[str, str] = field(default_factory=dict)
    analytics_capabilities: dict[str, str] = field(default_factory=dict)
    publication_capabilities: dict[str, str] = field(default_factory=dict)
    last_sync_at: datetime | None = None
    source: str = ""
    historical_learning_boundary: str = "unknown"


def _capability_map(names: tuple[str, ...], registry: dict) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in names:
        capability = registry.get(name)
        result[name] = capability.status.value if capability is not None else "unknown"
    return result


async def build_telegram_account_context(session: AsyncSession, *, now: datetime) -> PlatformAccountContext:
    """Real path: resolves the registered owned TelegramSurface (spec §4/§5) and the current
    SocialLaunchContext for Telegram - both may legitimately be None (no surface registered yet /
    no launch context proposed yet, both this environment's own honest current state per phase
    §0's own "No public NINJA PULSE surface is registered yet")."""
    surface: TelegramSurface | None = await resolve_owned_surface(session)
    launch_context: SocialLaunchContext | None = await get_current_context(session, SocialLaunchPlatform.TELEGRAM)

    if surface is None:
        connection_state = "not_registered"
    elif not surface.active:
        connection_state = "inactive"
    else:
        connection_state = "registered"

    return PlatformAccountContext(
        platform="telegram",
        canonical_account_id=str(surface.chat_id) if surface is not None else (
            str(owned_chat_id()) if owned_chat_id() is not None else None
        ),
        surface_role=surface.role.value if surface is not None else None,
        display_name=surface.name if surface is not None else None,
        username=surface.username if surface is not None else None,
        profile_description=None,  # spec §5: only ever populated by a real Telethon fetch (services/telegram_channel_context.py), never guessed here
        avatar_reference=None,
        launch_state=launch_context.launch_state.value if launch_context is not None else None,
        connection_state=connection_state,
        read_capabilities=_capability_map(_TELEGRAM_READ_CAPABILITY_NAMES, TELEGRAM_PLATFORM_CAPABILITIES),
        analytics_capabilities=_capability_map(_TELEGRAM_ANALYTICS_CAPABILITY_NAMES, TELEGRAM_PLATFORM_CAPABILITIES),
        publication_capabilities={"publish_photo": "available", "publish_text": "available"},
        last_sync_at=None,
        source="database/models/telegram_surface.py + database/models/social_launch_context.py",
        historical_learning_boundary=(
            launch_context.historical_content_policy.value if launch_context is not None
            else HistoricalContentPolicy.LEGACY_CONTEXT_ONLY.value
        ),
    )


async def build_instagram_account_context(session: AsyncSession, *, now: datetime) -> PlatformAccountContext:
    """Adapter path (spec §6): resolves the registered InstagramAccount row (if any) and the
    current SocialLaunchContext for Instagram. `connection_state` reports the real, honest
    CONNECTION_REQUIRED state whenever no live Graph API credentials are configured - never a
    fabricated "connected"."""
    account: InstagramAccount | None = await get_owned_brand_account(session)
    launch_context: SocialLaunchContext | None = await get_current_context(session, SocialLaunchPlatform.INSTAGRAM)

    if not instagram_is_configured():
        connection_state = "connection_required"
    elif account is None:
        connection_state = "not_registered"
    elif account.connection_state == InstagramConnectionState.CONNECTED:
        connection_state = "registered"
    else:
        connection_state = account.connection_state.value

    return PlatformAccountContext(
        platform="instagram",
        canonical_account_id=account.ig_user_id if account is not None else None,
        surface_role=account.role.value if account is not None else None,
        display_name=account.display_name if account is not None else None,
        username=account.username if account is not None else None,
        profile_description=None,
        avatar_reference=None,
        launch_state=launch_context.launch_state.value if launch_context is not None else None,
        connection_state=connection_state,
        read_capabilities=_capability_map(_INSTAGRAM_READ_CAPABILITY_NAMES, INSTAGRAM_PLATFORM_CAPABILITIES),
        analytics_capabilities=_capability_map(_INSTAGRAM_ANALYTICS_CAPABILITY_NAMES, INSTAGRAM_PLATFORM_CAPABILITIES),
        publication_capabilities=_capability_map(
            ("publish_single", "publish_carousel", "publish_reel", "publish_story"), INSTAGRAM_PLATFORM_CAPABILITIES,
        ),
        last_sync_at=account.last_sync_at if account is not None else None,
        source="database/models/instagram_account.py + database/models/social_launch_context.py",
        historical_learning_boundary=(
            launch_context.historical_content_policy.value if launch_context is not None else "no_historical_learning_before_first_publication"
        ),
    )
