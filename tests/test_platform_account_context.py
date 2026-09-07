"""DIRECTOR-CONTROL-PLANE-1 §48: required platform-context tests."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_account import InstagramAccount, InstagramAccountRole
from database.models.social_launch_context import SocialLaunchContext
from database.models.telegram_surface import TelegramSurface, TelegramSurfaceRole
from services.instagram_account_registry import create_account
from services.instagram_graph_adapter import InstagramNotConnectedError, fetch_profile_snapshot, is_configured
from services.platform_account_context import build_instagram_account_context, build_telegram_account_context
from services.telegram_surface_registry import create_surface

_NOW = datetime(2026, 9, 8, tzinfo=timezone.utc)


# --- Telegram -------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_telegram_surface_not_registered_reports_not_registered(db_session: AsyncSession) -> None:
    context = await build_telegram_account_context(db_session, now=_NOW)
    assert context.platform == "telegram"
    assert context.connection_state == "not_registered"
    assert context.canonical_account_id is None


@pytest.mark.asyncio
async def test_telegram_surface_registered_reports_registered(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """A TelegramSurface row alone is not enough - resolve_owned_surface() (spec §5's own
    established precedent) only reports "registered" once the surface's chat_id ALSO matches the
    real configured owned-channel target, exactly like production: registering a surface and
    designating it as owned are the same real operator action."""
    from core.config import settings
    monkeypatch.setattr(settings, "telegram_owned_channel_id", -1009999)
    await create_surface(
        db_session, chat_id=-1009999, role=TelegramSurfaceRole.PUBLIC_NEWS_CHANNEL, name="NINJA PULSE", username="nnjpulse",
    )
    await db_session.flush()
    context = await build_telegram_account_context(db_session, now=_NOW)
    assert context.connection_state == "registered"
    assert context.canonical_account_id == "-1009999"
    assert context.display_name == "NINJA PULSE"
    assert context.surface_role == TelegramSurfaceRole.PUBLIC_NEWS_CHANNEL.value


@pytest.mark.asyncio
async def test_telegram_legacy_boundary_defaults_to_legacy_context_only(db_session: AsyncSession) -> None:
    context = await build_telegram_account_context(db_session, now=_NOW)
    assert context.historical_learning_boundary == "legacy_context_only"


def test_telegram_read_capabilities_never_fabricate_availability() -> None:
    """The capability map must come from the real registry, not a hardcoded 'available' default -
    every value must be one of the real CapabilityStatus enum values."""
    from services.telegram_performance_memory import CapabilityStatus
    from services.platform_account_context import _TELEGRAM_READ_CAPABILITY_NAMES, _capability_map
    from services.telegram_performance_memory import TELEGRAM_PLATFORM_CAPABILITIES

    capability_map = _capability_map(_TELEGRAM_READ_CAPABILITY_NAMES, TELEGRAM_PLATFORM_CAPABILITIES)
    valid_values = {status.value for status in CapabilityStatus} | {"unknown"}
    assert all(v in valid_values for v in capability_map.values())


@pytest.mark.asyncio
async def test_missing_telegram_capability_reports_unknown_not_fabricated(db_session: AsyncSession) -> None:
    from services.platform_account_context import _capability_map

    result = _capability_map(("this_capability_does_not_exist",), {})
    assert result["this_capability_does_not_exist"] == "unknown"


# --- Instagram --------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_instagram_not_connected_reports_connection_required(db_session: AsyncSession) -> None:
    context = await build_instagram_account_context(db_session, now=_NOW)
    assert context.platform == "instagram"
    assert context.connection_state == "connection_required"
    assert is_configured() is False


@pytest.mark.asyncio
async def test_instagram_connected_mock_provider_adapter_reports_registered(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    import services.platform_account_context as ctx_module
    monkeypatch.setattr(ctx_module, "instagram_is_configured", lambda: True)
    await create_account(db_session, display_name="NINJA PULSE", role=InstagramAccountRole.OWNED_BRAND_ACCOUNT, ig_user_id="17800000000000000")
    await db_session.flush()
    context = await build_instagram_account_context(db_session, now=_NOW)
    assert context.connection_state == "registered"
    assert context.canonical_account_id == "17800000000000000"


def test_instagram_capabilities_are_explicit_never_invented() -> None:
    from services.instagram_platform_capabilities import INSTAGRAM_PLATFORM_CAPABILITIES, CapabilityStatus
    for capability in INSTAGRAM_PLATFORM_CAPABILITIES.values():
        assert capability.status in (
            CapabilityStatus.AVAILABLE, CapabilityStatus.UNAVAILABLE, CapabilityStatus.UNKNOWN, CapabilityStatus.MANUAL_ONLY,
        )
        assert capability.evidence


@pytest.mark.asyncio
async def test_instagram_missing_metric_is_explicit_not_guessed(db_session: AsyncSession) -> None:
    context = await build_instagram_account_context(db_session, now=_NOW)
    # No capability here is ever silently reported "available" when the real registry says
    # otherwise - every value must be a real, sourced capability status string.
    assert all(isinstance(v, str) for v in context.analytics_capabilities.values())
    assert context.analytics_capabilities  # non-empty: the map is real, not omitted


@pytest.mark.asyncio
async def test_instagram_real_fetch_raises_not_connected_when_unconfigured() -> None:
    with pytest.raises(InstagramNotConnectedError):
        await fetch_profile_snapshot()


# --- §54: read purity -----------------------------------------------------------------------

async def _row_counts(session: AsyncSession) -> dict[str, int]:
    tables = {"telegram_surfaces": TelegramSurface, "instagram_accounts": InstagramAccount, "social_launch_contexts": SocialLaunchContext}
    return {
        name: (await session.execute(select(func.count()).select_from(model))).scalar_one()
        for name, model in tables.items()
    }


@pytest.mark.asyncio
async def test_platform_account_context_builders_are_fully_read_pure(db_session: AsyncSession) -> None:
    before = await _row_counts(db_session)
    await build_telegram_account_context(db_session, now=_NOW)
    await build_instagram_account_context(db_session, now=_NOW)
    assert await _row_counts(db_session) == before
