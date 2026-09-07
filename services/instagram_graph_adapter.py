"""DIRECTOR-CONTROL-PLANE-1 §6: the Instagram Graph API adapter shape. Confirmed by services/
instagram_platform_capabilities.py's own real forensic sweep: no Meta Graph API client, no
Instagram credential setting, no publish/read call exists anywhere in this codebase. This module
is the readiness/adapter layer spec §6 explicitly asks for when live credentials are not available
- "implement the adapter/config/readiness layer and return CONNECTION_REQUIRED. Do not block the
rest of the architecture." It never fabricates a live API call result and never invents an
unsupported metric; `is_configured()` is the one gate every caller must check first.

Scope boundary (spec §3): every method below targets the ONE owned NINJA PULSE professional/
business account only - there is no method here that could reach a personal account, an unrelated
account, or a DM/address-book surface, because the Graph API endpoints used (`/me`, `/{ig-id}/media`,
`/{media-id}/insights`) are inherently scoped to the single authorized business account a token
grants access to."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.config import settings


class InstagramNotConnectedError(Exception):
    """Raised by any real-fetch method when `is_configured()` is False - callers must catch this
    and report CONNECTION_REQUIRED, never silently degrade to a fabricated empty-but-connected
    state."""


def is_configured() -> bool:
    return settings.instagram_access_token is not None and settings.instagram_business_account_id is not None


@dataclass(frozen=True)
class InstagramProfileSnapshot:
    """Spec §6's own required profile fields - every field optional/None until a real connected
    fetch populates it; never a guessed default."""

    ig_user_id: str
    username: str | None = None
    bio: str | None = None
    profile_picture_url: str | None = None
    followers_count: int | None = None
    media_count: int | None = None


@dataclass(frozen=True)
class InstagramMediaItem:
    media_id: str
    media_type: str  # IMAGE | VIDEO | CAROUSEL_ALBUM
    caption: str | None
    timestamp: str | None
    permalink: str | None
    # Populated only where the Graph API's own insights endpoint actually returned a value for
    # this specific media - a missing key here means "not returned", never a guessed 0 (mirrors
    # services/telegram_performance_memory.py's own "unavailable != zero" contract exactly).
    metrics: dict[str, int] = field(default_factory=dict)


async def fetch_profile_snapshot() -> InstagramProfileSnapshot:
    """Real implementation would call GET /{ig-user-id}?fields=username,biography,profile_picture_url,
    followers_count,media_count against graph.facebook.com using settings.instagram_access_token -
    not implemented here because no real token/account id is configured in this environment
    (spec §6's own explicit scope: adapter/readiness layer only, never a fabricated live result).
    Always raises when not configured; a future phase with real credentials fills in the actual
    httpx call inside this same function signature."""
    if not is_configured():
        raise InstagramNotConnectedError("Instagram Graph API is not configured - CONNECTION_REQUIRED")
    raise NotImplementedError(  # pragma: no cover - unreachable without real credentials
        "instagram_access_token/instagram_business_account_id are configured, but the real Graph "
        "API call is not implemented in this phase - no live credentials were available to build "
        "and verify it against (spec §6's own 'do not invent unverified behavior' instruction)."
    )


async def fetch_recent_media(limit: int = 25) -> list[InstagramMediaItem]:
    """Real implementation would call GET /{ig-user-id}/media?fields=id,media_type,caption,
    timestamp,permalink&limit={limit}. Same not-configured/not-implemented split as
    fetch_profile_snapshot() above."""
    if not is_configured():
        raise InstagramNotConnectedError("Instagram Graph API is not configured - CONNECTION_REQUIRED")
    raise NotImplementedError(  # pragma: no cover - unreachable without real credentials
        "See fetch_profile_snapshot()'s own docstring - same real-credential gap."
    )


async def fetch_media_insights(media_id: str) -> dict[str, Any]:
    """Real implementation would call GET /{media-id}/insights?metric=reach,impressions,likes,
    comments,shares,saved (metric set varies by media_type per Meta's own documented constraints -
    a real implementation must request only metrics valid for the specific media_type, never a
    fixed list that silently errors on Reels vs. Carousels). Same not-configured/not-implemented
    split as the two functions above."""
    if not is_configured():
        raise InstagramNotConnectedError("Instagram Graph API is not configured - CONNECTION_REQUIRED")
    raise NotImplementedError(  # pragma: no cover - unreachable without real credentials
        "See fetch_profile_snapshot()'s own docstring - same real-credential gap."
    )
