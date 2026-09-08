"""DIRECTOR-CONTROL-PLANE-1C §8/§9/§18/§20: the ONE bounded orchestration layer between the
official read-only reader (services/instagram_account_reader.py) and everything downstream
(the InstagramAccount row, PlatformAccountContext, InstagramFeedContext, the Instagram Directors).

Two public entry points, both bounded, both safe to run on demand, neither scheduled:

  run_instagram_connection_check(session)   - §20's explicit admin/diagnostic check: config present ->
                                         official profile fetch -> identity verification ->
                                         capability detection -> persist ONLY safe (non-secret)
                                         metadata onto the owned InstagramAccount row. Returns a
                                         structured report. This is NOT a normal read-command
                                         side effect.

  sync_instagram_feed_context(session) - §18's one bounded read path, reused by Director refresh
                                         (and, later, a scheduled performance collector): official
                                         reader -> normalized media -> build_instagram_feed_context.
                                         Not configured / any fetch failure -> raw_media=None ->
                                         an honestly empty, correctly-labelled prelaunch context
                                         (§10/§15 - never fabricated posts/metrics).

Neither function ever logs, returns, or persists the access token (§7/§24). The only thing written
to the database is the set of non-secret columns migration 4a1b7c9d2e3f added to
`instagram_accounts` - there is no token/app-secret column anywhere to write to.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_account import InstagramAccount, InstagramAccountRole, InstagramConnectionState
from database.models.social_launch_context import SocialLaunchContext, SocialLaunchPlatform
from services.instagram_account_reader import (
    ConnectionCheckResult,
    ConnectionOutcome,
    InstagramAccountReader,
    InstagramReaderConfig,
    InstagramReadError,
    NormalizedProfile,
    media_to_feed_context_row,
)
from services.instagram_account_registry import get_owned_brand_account
from services.instagram_connection_readiness import InstagramReadinessState
from services.instagram_feed_context import InstagramFeedContext, build_instagram_feed_context
from services.social_launch_context_service import get_current_context

logger = logging.getLogger(__name__)

# §17: a full connection test issues at most 2 official calls (profile + insights probe); a feed
# sync issues at most 4 (profile + media list [<=2 pages] + account insights). Reported by the
# functions below as `api_calls`.
CONNECTION_TEST_MAX_API_CALLS = 2
FEED_SYNC_MAX_API_CALLS = 4


@dataclass(frozen=True)
class InstagramConnectionReport:
    """Structured, token-free result of `run_instagram_connection_check()`."""

    readiness_state: InstagramReadinessState
    connected: bool
    outcome: str  # ConnectionOutcome value
    username: str | None = None
    ig_user_id: str | None = None
    account_type: str | None = None
    capabilities: dict[str, str] = field(default_factory=dict)
    error_code: str | None = None
    error_detail: str | None = None  # curated, token-free
    token_status: str = "UNKNOWN"
    token_expires_at: datetime | None = None
    api_calls: int = 0
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    persisted: bool = False


@dataclass(frozen=True)
class InstagramSyncResult:
    """What `sync_instagram_feed_context()` hands back to a Director orchestration."""

    feed_context: InstagramFeedContext
    profile: NormalizedProfile | None
    readiness_state: InstagramReadinessState
    api_calls: int
    error_code: str | None = None


def _reader_from_settings(*, transport=None) -> InstagramAccountReader | None:
    config: InstagramReaderConfig | None = InstagramReaderConfig.from_settings()
    if config is None:
        return None
    return InstagramAccountReader(config, transport=transport)


async def _ensure_owned_account_row(session: AsyncSession) -> InstagramAccount:
    account = await get_owned_brand_account(session)
    if account is not None:
        return account
    account = InstagramAccount(
        role=InstagramAccountRole.OWNED_BRAND_ACCOUNT,
        display_name="NINJA PULSE",
        connection_state=InstagramConnectionState.NOT_CONNECTED,
        active=True,
    )
    session.add(account)
    await session.flush()
    return account


def _apply_check_to_row(account: InstagramAccount, check: ConnectionCheckResult, *, now: datetime) -> None:
    """Persist ONLY non-secret metadata. Never touches a token (there is no token column)."""
    account.access_token_status = check.token_status
    account.access_token_expires_at = check.token_expires_at
    account.last_sync_at = now

    if check.outcome is ConnectionOutcome.CONNECTED and check.profile is not None:
        profile = check.profile
        account.connection_state = InstagramConnectionState.CONNECTED
        account.ig_user_id = profile.ig_user_id
        account.username = profile.username
        account.account_type = profile.account_type
        account.biography = profile.biography
        account.profile_picture_url = profile.profile_picture_url
        account.followers_count = profile.followers_count
        account.follows_count = profile.follows_count
        account.media_count = profile.media_count
        account.last_successful_read_at = now
        account.last_read_error = None
        account.capabilities = check.capabilities.as_map()
        return

    # ERROR / IDENTITY_MISMATCH - record the safe error, keep any prior good identity metadata
    # (so /accounts can still show "@handle - last good read <ts>, now erroring").
    account.connection_state = InstagramConnectionState.ERROR
    account.last_read_error = _safe_error_line(check)
    if check.outcome is ConnectionOutcome.IDENTITY_MISMATCH and check.profile is not None:
        # Deliberately DO NOT adopt the mismatched identity - only note it in the error line.
        account.capabilities = None


def _safe_error_line(check: ConnectionCheckResult) -> str:
    code = check.error_code or check.outcome.value
    detail = (check.error_detail or "").replace("\n", " ")[:200]
    return f"{code}: {detail}" if detail else code


def _readiness_for_row(account: InstagramAccount | None, *, configured: bool) -> InstagramReadinessState:
    if not configured:
        return InstagramReadinessState.NOT_CONFIGURED
    if account is None or account.connection_state == InstagramConnectionState.NOT_CONNECTED:
        # Config present, no successful verification yet - §8's CONNECTING.
        return InstagramReadinessState.CONNECTING
    if account.connection_state == InstagramConnectionState.ERROR:
        return InstagramReadinessState.ERROR
    if account.connection_state == InstagramConnectionState.CONNECTED and account.ig_user_id:
        return InstagramReadinessState.CONNECTED
    return InstagramReadinessState.CONNECTING


async def run_instagram_connection_check(session: AsyncSession, *, transport=None, now: datetime | None = None) -> InstagramConnectionReport:
    """§20's explicit connection check. Safe to run any time. Persists only non-secret metadata."""
    now = now or datetime.now(timezone.utc)
    reader = _reader_from_settings(transport=transport)
    if reader is None:
        return InstagramConnectionReport(
            readiness_state=InstagramReadinessState.NOT_CONFIGURED, connected=False,
            outcome=ConnectionOutcome.NOT_CONFIGURED.value,
            error_detail="instagram_access_token / instagram_business_account_id absent",
        )

    check = await reader.check_connection()
    account = await _ensure_owned_account_row(session)
    _apply_check_to_row(account, check, now=now)
    await session.flush()

    readiness = _readiness_for_row(account, configured=True)
    logger.info(
        "instagram_connection_test outcome=%s readiness=%s api_calls=%d",
        check.outcome.value, readiness.value, check.api_calls,
    )
    return InstagramConnectionReport(
        readiness_state=readiness,
        connected=check.outcome is ConnectionOutcome.CONNECTED,
        outcome=check.outcome.value,
        username=account.username if check.outcome is ConnectionOutcome.CONNECTED else None,
        ig_user_id=account.ig_user_id if check.outcome is ConnectionOutcome.CONNECTED else None,
        account_type=account.account_type if check.outcome is ConnectionOutcome.CONNECTED else None,
        capabilities=check.capabilities.as_map(),
        error_code=check.error_code,
        error_detail=check.error_detail,
        token_status=check.token_status,
        token_expires_at=check.token_expires_at,
        api_calls=check.api_calls,
        checked_at=check.checked_at,
        persisted=True,
    )


async def sync_instagram_feed_context(
    session: AsyncSession, *, now: datetime | None = None, media_limit: int = 25, transport=None,
) -> InstagramSyncResult:
    """§18's one bounded read path. Official reader -> normalized media -> build_instagram_feed_context.
    Not configured OR any fetch failure -> raw_media=None -> honest empty prelaunch context (§10/§15).
    Never raises; never fabricates. Does NOT itself persist (a caller that also wants the row
    refreshed calls `run_instagram_connection_check()` first)."""
    now = now or datetime.now(timezone.utc)
    launch_context: SocialLaunchContext | None = await get_current_context(session, SocialLaunchPlatform.INSTAGRAM)
    account = await get_owned_brand_account(session)
    configured = InstagramReaderConfig.from_settings() is not None
    readiness = _readiness_for_row(account, configured=configured)

    reader = _reader_from_settings(transport=transport)
    if reader is None:
        return InstagramSyncResult(
            feed_context=build_instagram_feed_context(None, readiness_state=readiness, launch_context=launch_context),
            profile=None, readiness_state=readiness, api_calls=0,
        )

    api_calls = 0
    try:
        profile = await reader.fetch_account_context()
        api_calls += 1
        media = await reader.fetch_recent_media(limit=media_limit)
        api_calls += 1
    except InstagramReadError as error:  # §15: a fetch failure must never crash Director planning
        code_value = error.code.value
        logger.warning("instagram_feed_sync_failed code=%s (falling back to empty context)", code_value)
        return InstagramSyncResult(
            feed_context=build_instagram_feed_context(None, readiness_state=InstagramReadinessState.ERROR, launch_context=launch_context),
            profile=None, readiness_state=InstagramReadinessState.ERROR, api_calls=api_calls, error_code=code_value,
        )
    except Exception:  # noqa: BLE001 - defense in depth: any unexpected error still degrades safely
        logger.warning("instagram_feed_sync_failed code=unexpected (falling back to empty context)", exc_info=True)
        code_value = "network"
        return InstagramSyncResult(
            feed_context=build_instagram_feed_context(None, readiness_state=InstagramReadinessState.ERROR, launch_context=launch_context),
            profile=None, readiness_state=InstagramReadinessState.ERROR, api_calls=api_calls, error_code=code_value,
        )

    raw_media = [media_to_feed_context_row(m) for m in media]
    feed_context = build_instagram_feed_context(
        raw_media, readiness_state=InstagramReadinessState.CONNECTED, launch_context=launch_context,
    )
    return InstagramSyncResult(
        feed_context=feed_context, profile=profile,
        readiness_state=InstagramReadinessState.CONNECTED, api_calls=api_calls,
    )


@dataclass(frozen=True)
class InstagramDirectorFeedInputs:
    """§11: the ONE bounded bundle every Instagram Director orchestration consumes. `feed_context`
    goes to the Growth Strategist and the Format Director (both accept `feed_context=`);
    `creative_feed_note` goes to `CreativeDirectorInput.feed_context_note` (a plain string - the
    Creative Director never sees the raw context object or any provider field). No token, no
    provider secret, ever appears in any field here."""

    feed_context: InstagramFeedContext
    creative_feed_note: str
    readiness_state: InstagramReadinessState
    profile_username: str | None
    api_calls: int
    error_code: str | None = None


async def build_instagram_director_feed_inputs(
    session: AsyncSession, *, now: datetime | None = None, media_limit: int = 25, transport=None,
) -> InstagramDirectorFeedInputs:
    """§11/§18/§22: the single entry point a Director orchestration calls to get real, normalized
    Instagram feed context for ALL THREE Instagram Directors at once. Wraps the one bounded
    `sync_instagram_feed_context()` read and derives the Creative Director's text note from the
    same result - so the Growth Strategist, Format Director, and Creative Director are guaranteed
    to be reasoning about the same real feed. Not configured / fetch failure -> honest empty
    context + an honest note; never fabricated."""
    sync = await sync_instagram_feed_context(session, now=now, media_limit=media_limit, transport=transport)
    note = feed_context_note_for_creative(sync.feed_context, sync.profile)
    return InstagramDirectorFeedInputs(
        feed_context=sync.feed_context,
        creative_feed_note=note,
        readiness_state=sync.readiness_state,
        profile_username=sync.profile.username if sync.profile is not None else None,
        api_calls=sync.api_calls,
        error_code=sync.error_code,
    )


def feed_context_note_for_creative(feed_context: InstagramFeedContext, profile: NormalizedProfile | None) -> str:
    """§11: a plain caller-derived text line for CreativeDirectorInput.feed_context_note - a
    Director never sees the raw context object or any provider field, just this honest summary.
    Never includes a token or any secret."""
    state = feed_context.readiness_state
    if state is not InstagramReadinessState.CONNECTED:
        return f"Instagram account readiness={state.value}; no first-party Instagram feed evidence yet."
    if not feed_context.posts:
        return "Instagram account connected but has 0 publications yet - PRE_LAUNCH / cold start; no first-party performance evidence."
    dominant = max(feed_context.media_type_distribution.items(), key=lambda kv: kv[1], default=(None, 0))
    handle = f"@{profile.username}" if profile and profile.username else "the account"
    parts = [f"{handle}: {len(feed_context.posts)} recent posts"]
    if dominant[0]:
        parts.append(f"most common media_type={dominant[0]!r} ({dominant[1]})")
    if feed_context.learning_eligible_posts:
        parts.append(f"{len(feed_context.learning_eligible_posts)} performance-learning-eligible")
    else:
        parts.append("none yet performance-learning-eligible (pre-boundary)")
    return "; ".join(parts) + "."
