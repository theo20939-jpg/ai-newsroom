"""DIRECTOR-CONTROL-PLANE-1A §12: the exact required Instagram connection-state vocabulary
(NOT_CONFIGURED / CONNECTING / CONNECTED / ERROR), derived from the already-real
`services/platform_account_context.py::PlatformAccountContext.connection_state` string rather than
widening the persisted `InstagramConnectionState` DB enum - this is a read-only reporting view over
already-real state, not a new fact the database needs to store, so no migration is added for it
(phase §32's own "avoid further schema additions if practical" instruction).

`CONNECTING` exists in the vocabulary for a future real OAuth/token-exchange flow (spec §12's own
explicit 4-state list) but is never produced by `resolve_instagram_readiness_state()` today, since
this codebase has no in-progress-connection tracking yet - the derivation is honest about only ever
returning a state it can actually prove from real, already-persisted data. Never fabricates
CONNECTED without a real `InstagramConnectionState.CONNECTED` row (services/instagram_account_
registry.py's own account row), matching `services/instagram_graph_adapter.py::is_configured()`'s
existing "never a fabricated connected account" contract."""
from __future__ import annotations

import enum

from services.platform_account_context import PlatformAccountContext


class InstagramReadinessState(str, enum.Enum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    ERROR = "ERROR"


_ERROR_VALUES = frozenset({"error"})
_CONNECTED_VALUES = frozenset({"registered", "connected"})


def resolve_instagram_readiness_state(context: PlatformAccountContext) -> InstagramReadinessState:
    """Pure mapping from `PlatformAccountContext.connection_state`'s existing internal values
    (`connection_required` / `not_registered` / `registered` / `not_connected` / `error`) to the
    spec's own required 4-state vocabulary. `context.platform` is not checked - a caller is
    expected to have built `context` via `build_instagram_account_context()` already."""
    if context.connection_state in _ERROR_VALUES:
        return InstagramReadinessState.ERROR
    if context.connection_state in _CONNECTED_VALUES:
        return InstagramReadinessState.CONNECTED
    # "connection_required" (Graph API not configured at all), "not_registered" (configured but no
    # account row yet), and "not_connected" (account row exists, never completed connection) are
    # all honestly reported as NOT_CONFIGURED - none of them is a real connected account.
    return InstagramReadinessState.NOT_CONFIGURED


def account_readiness_summary(context: PlatformAccountContext) -> dict[str, str | bool]:
    """Spec §27's own required Instagram-connection-readiness fields, deterministically derived -
    used by both the /accounts command (spec §25) and the readiness test (spec §27)."""
    state = resolve_instagram_readiness_state(context)
    connected = state is InstagramReadinessState.CONNECTED
    return {
        "readiness_state": state.value,
        "account_state": "PRE_LAUNCH" if not connected else "LIVE",
        "first_party_baseline": "NONE" if not connected else "ESTABLISHED",
        "connection_required": not connected,
    }
