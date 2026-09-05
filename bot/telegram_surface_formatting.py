"""SOCIAL-INTELLIGENCE-OPS-1, spec §7: pure /surface rendering. No aiogram/Bot type, no database
access - mirrors bot/business_context_formatting.py's own discipline exactly."""
from __future__ import annotations

from database.models.telegram_surface import TelegramSurface
from database.models.telegram_surface_proposal import TelegramSurfaceProposal

_ROLE_LABEL = {
    "internal_editorial": "INTERNAL_EDITORIAL", "public_news_channel": "PUBLIC_NEWS_CHANNEL",
    "public_gaming_channel": "PUBLIC_GAMING_CHANNEL", "public_product_channel": "PUBLIC_PRODUCT_CHANNEL",
    "other": "OTHER",
}


def render_surface_status(surfaces: list[TelegramSurface]) -> str:
    """Spec §7's own required example shape - never invents an unresolved channel identity; a
    surface only ever appears here because it is a real, already-configured row."""
    lines = ["🥷 Telegram Surfaces", ""]
    if not surfaces:
        lines.append("Ни одна поверхность ещё не настроена.")
        lines.append("Используйте /surface, чтобы настроить.")
        return "\n".join(lines)

    for surface in surfaces:
        lines.append(surface.name)
        lines.append(_ROLE_LABEL.get(surface.role.value, surface.role.value.upper()))
        lines.append(f"Analytics: {'ENABLED' if surface.analytics_enabled else 'DISABLED'}")
        lines.append(f"Status: {'CONFIGURED' if surface.active else 'INACTIVE'}")
        lines.append("")
    return "\n".join(lines).strip()


def render_surface_proposal_preview(proposal: TelegramSurfaceProposal) -> str:
    lines = [
        "🥷 Проверьте предложенную настройку поверхности", "",
        f"Название: {proposal.name}",
        f"Роль: {_ROLE_LABEL.get(proposal.role.value, proposal.role.value.upper())}",
    ]
    if proposal.username:
        lines.append(f"Username: @{proposal.username.lstrip('@')}")
    lines.append(f"Аналитика: {'включить' if proposal.analytics_enabled else 'не включать'}")
    lines.append(f"Активна: {'да' if proposal.active else 'нет'}")
    lines.append("")
    lines.append("[✅ Подтвердить] [✏️ Исправить] [❌ Отмена]")
    return "\n".join(lines)
