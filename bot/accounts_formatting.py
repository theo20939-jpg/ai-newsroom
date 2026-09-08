"""DIRECTOR-CONTROL-PLANE-1 §33-34: pure text rendering for `/accounts` - no secrets/tokens ever
rendered (spec §34's own explicit "No secrets/tokens" instruction; PlatformAccountContext itself
never carries one - services/platform_account_context.py's own module docstring)."""
from __future__ import annotations

from services.platform_account_context import PlatformAccountContext

_CONNECTION_STATE_LABEL = {
    "not_registered": "не зарегистрирован",
    "registered": "зарегистрирован",
    "inactive": "неактивен",
    "connection_required": "требуется подключение",
    "connected": "подключён",
    "error": "ошибка подключения",
}


def _label(state: str) -> str:
    return _CONNECTION_STATE_LABEL.get(state, state)


def _render_capabilities(title: str, capabilities: dict[str, str]) -> str:
    if not capabilities:
        return f"{title}: нет данных"
    parts = ", ".join(f"{name}={status}" for name, status in capabilities.items())
    return f"{title}: {parts}"


_FEED_CONTEXT_AVAILABLE_STATES = frozenset({"registered", "connected"})


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
    # DIRECTOR-CONTROL-PLANE-1A §25: real feed context (services/telegram_feed_window.py /
    # services/instagram_feed_context.py) is only ever available once the account is actually
    # registered/connected - never claims availability from a bare "connection_required" state.
    feed_available = context.connection_state in _FEED_CONTEXT_AVAILABLE_STATES
    lines.append(f"Feed context для директоров: {'доступен' if feed_available else 'недоступен (аккаунт не зарегистрирован/не подключён)'}")
    return "\n".join(lines)


def render_accounts_status(telegram: PlatformAccountContext, instagram: PlatformAccountContext) -> str:
    return (
        "🥷 Platform Accounts\n\n"
        + render_account_context(telegram)
        + "\n\n"
        + render_account_context(instagram)
    )
