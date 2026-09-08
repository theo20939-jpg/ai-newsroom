"""DIRECTOR-CONTROL-PLANE-1A §12 / 1C §8: the exact required Instagram connection-state vocabulary
(NOT_CONFIGURED / CONNECTING / CONNECTED / ERROR), derived from
`services/platform_account_context.py::PlatformAccountContext.connection_state`.

1C makes all four states operational:
  NOT_CONFIGURED - required secret/config absent (`instagram_access_token` / `..._business_account_id`).
  CONNECTING     - config present but no successful bounded profile read has verified the account
                   yet (no InstagramAccount row, or the row is still `not_connected`).
  CONNECTED      - a real bounded profile read succeeded AND the returned identity matched the
                   configured target (services/instagram_connection_service.py persisted
                   `InstagramConnectionState.CONNECTED` + a real `ig_user_id`).
  ERROR          - config present but the official read failed, OR the returned identity did not
                   match the configured account (IDENTITY_MISMATCH - surfaced via `last_read_error`,
                   never silently accepted).

CONNECTED is NEVER produced merely because a token string exists (§8) - it requires the persisted
row state that only a successful, identity-verified `run_instagram_connection_check()` writes.
"""
from __future__ import annotations

import enum

from services.platform_account_context import PlatformAccountContext


class InstagramReadinessState(str, enum.Enum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    ERROR = "ERROR"


_ERROR_VALUES = frozenset({"error", "identity_mismatch"})
_CONNECTED_VALUES = frozenset({"registered", "connected"})
_CONNECTING_VALUES = frozenset({"connecting"})


def resolve_instagram_readiness_state(context: PlatformAccountContext) -> InstagramReadinessState:
    """Pure mapping from `PlatformAccountContext.connection_state`'s internal values
    (`connection_required` / `not_registered` / `connecting` / `registered` / `connected` /
    `not_connected` / `error` / `identity_mismatch`) to the spec's 4-state vocabulary."""
    if context.connection_state in _ERROR_VALUES:
        return InstagramReadinessState.ERROR
    if context.connection_state in _CONNECTED_VALUES:
        return InstagramReadinessState.CONNECTED
    if context.connection_state in _CONNECTING_VALUES:
        return InstagramReadinessState.CONNECTING
    # "connection_required" (config absent), "not_registered", "not_connected" - none is a
    # configured, verified connection.
    return InstagramReadinessState.NOT_CONFIGURED


def account_readiness_summary(context: PlatformAccountContext) -> dict[str, object]:
    """§19/§27's required Instagram-connection-readiness fields, deterministically derived from the
    already-persisted PlatformAccountContext - used by `/accounts`, `run_instagram_connection_check`'s
    report, and the readiness tests. Never performs a network call; never surfaces a token."""
    state = resolve_instagram_readiness_state(context)
    connected = state is InstagramReadinessState.CONNECTED
    caps = context.read_capabilities or {}
    return {
        "readiness_state": state.value,
        "account_state": "PRE_LAUNCH" if not connected else "LIVE",
        # §12: connecting to the account does NOT create a first-party baseline - that only begins
        # once a real NINJA PULSE publication exists and the canonical SocialLaunchContext policy
        # marks it learning-eligible. A CONNECTED-but-empty account still reports NONE.
        "first_party_baseline": "NONE" if not connected else "ESTABLISHED",
        "connection_required": not connected,
        "profile_read": caps.get("read_profile", "UNAVAILABLE"),
        "media_read": caps.get("read_media", "UNAVAILABLE"),
        "insights_read": caps.get("read_insights", "UNAVAILABLE"),
        "last_successful_read_at": (
            context.last_successful_read_at.isoformat() if context.last_successful_read_at is not None else None
        ),
        "token_status": context.token_status or "UNKNOWN",
        "token_expires_at": (
            context.token_expires_at.isoformat() if context.token_expires_at is not None else None
        ),
    }
