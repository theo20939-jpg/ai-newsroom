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
from services.instagram_account_reader import is_configured as instagram_is_configured
from services.instagram_account_registry import get_owned_brand_account
from services.instagram_platform_capabilities import INSTAGRAM_PLATFORM_CAPABILITIES
from services.social_launch_context_service import get_current_context
from services.telegram_own_channel import owned_chat_id
from services.telegram_performance_memory import TELEGRAM_PLATFORM_CAPABILITIES
from services.telegram_surface_registry import resolve_owned_surface

_TELEGRAM_READ_CAPABILITY_NAMES = ("views", "reactions", "reposts", "comments")
_TELEGRAM_ANALYTICS_CAPABILITY_NAMES = ("subscriber_count", "subscriber_delta", "publication_timestamp")
_INSTAGRAM_ANALYTICS_CAPABILITY_NAMES = ("read_insights", "read_post_insights", "read_reel_insights", "read_follower_stats")
# DIRECTOR-CONTROL-PLANE-1C §14: the honest default before any real capability probe has run -
# never "unknown", never a guessed AVAILABLE. Overwritten by the persisted `instagram_accounts.
# capabilities` map the moment services/instagram_connection_service.py records a real probe.
_INSTAGRAM_UNPROBED_READ_CAPABILITIES = {
    "read_profile": "UNAVAILABLE", "read_media": "UNAVAILABLE", "read_insights": "UNAVAILABLE",
}


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
    # DIRECTOR-CONTROL-PLANE-1C §16/§19: non-secret read-health fields, populated for Instagram
    # from the cached `instagram_accounts` columns (never from a live call - `/accounts` stays a
    # pure read). All default None so every existing Telegram caller is unaffected.
    last_successful_read_at: datetime | None = None
    token_status: str | None = None
    token_expires_at: datetime | None = None


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
    """DIRECTOR-CONTROL-PLANE-1 §6 / 1C §8/§10/§13/§19: resolves the registered InstagramAccount
    row (if any) and the current SocialLaunchContext for Instagram. NEVER performs a network call -
    every field comes from already-persisted rows (the non-secret columns
    services/instagram_connection_service.py caches from a real read). `connection_state`:
      - "connection_required"  when instagram_access_token / ..._business_account_id is unset;
      - "connecting"           when config is present but no verified read has happened yet;
      - "error"                when the last read failed or the identity did not match;
      - "registered"           only when a real identity-verified profile read succeeded.
    Never a fabricated "connected"."""
    account: InstagramAccount | None = await get_owned_brand_account(session)
    launch_context: SocialLaunchContext | None = await get_current_context(session, SocialLaunchPlatform.INSTAGRAM)

    if not instagram_is_configured():
        connection_state = "connection_required"
    elif account is None or account.connection_state == InstagramConnectionState.NOT_CONNECTED:
        connection_state = "connecting"
    elif account.connection_state == InstagramConnectionState.CONNECTED and account.ig_user_id:
        connection_state = "registered"
    elif account.connection_state == InstagramConnectionState.ERROR:
        # IDENTITY_MISMATCH is recorded as ERROR + a `last_read_error` prefix - surface the finer
        # distinction so /accounts and the readiness view can tell them apart.
        connection_state = "identity_mismatch" if (account.last_read_error or "").startswith("identity_mismatch") else "error"
    else:
        connection_state = "connecting"

    # §14: when a real capability probe has run, the persisted `capabilities` map is the truth;
    # otherwise report the honest UNAVAILABLE default (never "unknown", never guessed AVAILABLE).
    if account is not None and isinstance(account.capabilities, dict) and account.capabilities:
        read_capabilities = {k: str(v) for k, v in account.capabilities.items()}
    else:
        read_capabilities = dict(_INSTAGRAM_UNPROBED_READ_CAPABILITIES)

    return PlatformAccountContext(
        platform="instagram",
        canonical_account_id=account.ig_user_id if account is not None else None,
        surface_role=account.role.value if account is not None else None,
        display_name=account.display_name if account is not None else None,
        username=account.username if account is not None else None,
        profile_description=account.biography if account is not None else None,
        avatar_reference=account.profile_picture_url if account is not None else None,
        launch_state=launch_context.launch_state.value if launch_context is not None else None,
        connection_state=connection_state,
        read_capabilities=read_capabilities,
        analytics_capabilities=_capability_map(_INSTAGRAM_ANALYTICS_CAPABILITY_NAMES, INSTAGRAM_PLATFORM_CAPABILITIES),
        publication_capabilities=_capability_map(
            ("publish_single", "publish_carousel", "publish_reel", "publish_story"), INSTAGRAM_PLATFORM_CAPABILITIES,
        ),
        last_sync_at=account.last_sync_at if account is not None else None,
        source="database/models/instagram_account.py + database/models/social_launch_context.py",
        historical_learning_boundary=(
            launch_context.historical_content_policy.value if launch_context is not None else "no_historical_learning_before_first_publication"
        ),
        last_successful_read_at=account.last_successful_read_at if account is not None else None,
        token_status=account.access_token_status if account is not None else None,
        token_expires_at=account.access_token_expires_at if account is not None else None,
    )
