"""DIRECTOR-CONTROL-PLANE-1 §33-34 / 1C §19: pure text rendering for `/accounts` - no secrets/
tokens ever rendered (PlatformAccountContext itself never carries one - services/platform_account_
context.py's own module docstring; 1C additionally verified by test_instagram_read_security).
Renders only already-persisted state: 0 network calls, 0 writes, 0 Gateway calls."""
from __future__ import annotations

from typing import TYPE_CHECKING

from services.instagram_connection_readiness import account_readiness_summary
from services.platform_account_context import PlatformAccountContext

if TYPE_CHECKING:
    from services.instagram_connection_service import InstagramConnectionReport

_CONNECTION_STATE_LABEL = {
    "not_registered": "не зарегистрирован",
    "registered": "зарегистрирован",
    "inactive": "неактивен",
    "connection_required": "требуется подключение",
    "connecting": "подключение (ожидает проверки)",
    "connected": "подключён",
    "error": "ошибка подключения",
    "identity_mismatch": "ошибка: не тот аккаунт (IDENTITY_MISMATCH)",
}


def _label(state: str) -> str:
    return _CONNECTION_STATE_LABEL.get(state, state)


def _render_capabilities(title: str, capabilities: dict[str, str]) -> str:
    if not capabilities:
        return f"{title}: нет данных"
    parts = ", ".join(f"{name}={status}" for name, status in capabilities.items())
    return f"{title}: {parts}"


_FEED_CONTEXT_AVAILABLE_STATES = frozenset({"registered", "connected"})


def _render_instagram_detail(context: PlatformAccountContext) -> list[str]:
    """DIRECTOR-CONTROL-PLANE-1C §19: the Instagram-specific read-only block. Every value comes
    from `account_readiness_summary()` over the already-persisted PlatformAccountContext - no
    token, no app secret, no raw credential id."""
    summary = account_readiness_summary(context)
    lines = [
        f"Connection readiness: {summary['readiness_state']}",
        f"Account: {('@' + context.username) if context.username else 'неизвестно'}",
        f"Profile read: {summary['profile_read']}",
        f"Media read: {summary['media_read']}",
        f"Insights: {summary['insights_read']}",
        f"Last successful read: {summary['last_successful_read_at'] or 'никогда'}",
        f"Learning baseline: {summary['first_party_baseline']}",
    ]
    token_status = summary.get("token_status")
    if token_status and token_status != "UNKNOWN":
        expiry = summary.get("token_expires_at")
        lines.append(f"Token status: {token_status}" + (f" (expires {expiry})" if expiry else ""))
    return lines


def render_account_context(context: PlatformAccountContext) -> str:
    lines = [
        f"🥷 {context.platform.upper()}",
        f"Статус подключения: {_label(context.connection_state)}",
    ]
    if context.canonical_account_id:
        lines.append(f"Account ID: {context.canonical_account_id}")
    if context.display_name:
        lines.append(f"Название: {context.display_name}")
    if context.username:
        lines.append(f"Username: @{context.username}")
    lines.append(f"Launch state: {context.launch_state or 'не задан'}")
    lines.append(_render_capabilities("Read capabilities", context.read_capabilities))
    lines.append(_render_capabilities("Analytics capabilities", context.analytics_capabilities))
    lines.append(f"Historical learning boundary: {context.historical_learning_boundary}")
    if context.platform == "instagram":
        lines.extend(_render_instagram_detail(context))
    # DIRECTOR-CONTROL-PLANE-1A §25: real feed context (services/telegram_feed_window.py /
    # services/instagram_feed_context.py) is only ever available once the account is actually
    # registered/connected - never claims availability from a bare "connection_required" state.
    feed_available = context.connection_state in _FEED_CONTEXT_AVAILABLE_STATES
    lines.append(f"Feed context для директоров: {'доступен' if feed_available else 'недоступен (аккаунт не зарегистрирован/не подключён)'}")
    return "\n".join(lines)


def render_instagram_connection_report(report: "InstagramConnectionReport") -> str:
    """DIRECTOR-CONTROL-PLANE-1C §20: the `/accounts test instagram` result. Structured, token-
    free - `report` never carries a secret (services/instagram_connection_service.py builds it
    from curated fields only)."""
    lines = [
        "🥷 INSTAGRAM connection test",
        f"Readiness: {report.readiness_state.value}",
        f"Outcome: {report.outcome}",
        f"API calls: {report.api_calls}",
    ]
    if report.connected:
        lines.append(f"Account: {('@' + report.username) if report.username else report.ig_user_id or 'неизвестно'}")
        if report.account_type:
            lines.append(f"Account type: {report.account_type}")
    if report.capabilities:
        lines.append("Capabilities: " + ", ".join(f"{k}={v}" for k, v in report.capabilities.items()))
    if report.token_status and report.token_status != "UNKNOWN":
        expiry = report.token_expires_at.isoformat() if report.token_expires_at is not None else None
        lines.append(f"Token status: {report.token_status}" + (f" (expires {expiry})" if expiry else ""))
    if report.error_code:
        lines.append(f"Error: {report.error_code}" + (f" — {report.error_detail}" if report.error_detail else ""))
    return "\n".join(lines)


def render_accounts_status(telegram: PlatformAccountContext, instagram: PlatformAccountContext) -> str:
    return (
        "🥷 Platform Accounts\n\n"
        + render_account_context(telegram)
        + "\n\n"
        + render_account_context(instagram)
    )
