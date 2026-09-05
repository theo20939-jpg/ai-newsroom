"""NINJA Social Intelligence Foundation, Part II: pure Business Context Command Center rendering.
No aiogram/Bot type, no database access - mirrors bot/event_recap_review_formatting.py's own
"pure functions, no database access" discipline exactly, testable with zero Telegram mocking."""
from __future__ import annotations

from database.models.business_context_proposal import BusinessContextProposal
from services.business_context_command_registry import CommandDefinition, commands_for_role
from services.business_context_roles import BusinessContextRole
from services.business_context_snapshot_service import BusinessContextSnapshot

_STATUS_DOT = {
    "live": "🟢", "public_beta": "🟡", "private_beta": "🟡", "pre_launch": "🟠",
    "development": "🔵", "discovery": "🔵", "idea": "⚪", "paused": "⏸", "sunset": "⚫",
}


def render_status(snapshot: BusinessContextSnapshot) -> str:
    """Spec §26's own example shape, rendered from real, deterministic snapshot data only - never
    fakes a platform SYNCED status the codebase does not actually implement (this phase implements
    no Telegram/Instagram Director consumption yet, so no such line is rendered at all here -
    adding it, honestly, is the responsibility of whichever future phase actually wires a director
    to read this snapshot)."""
    lines = ["🥷 NINJA Business Context", ""]
    for summary in snapshot.products:
        product = summary.product
        dot = _STATUS_DOT.get(product.status.value, "⚪")
        lines.append(f"NINJA {product.name}")
        lines.append(f"{dot} {product.status.value.upper()}")
        if summary.active_campaign is not None:
            plan = summary.active_campaign
            phase_text = f" · {plan.phase}" if plan.phase else ""
            lines.append(f"Кампания: {plan.status.upper()}{phase_text}")
        lines.append("")

    lines.append(f"Активных кампаний: {len(snapshot.active_campaigns)}")
    lines.append(f"Действующих директив: {len(snapshot.active_directives)}")
    lines.append(f"Ближайших milestones: {len(snapshot.upcoming_milestones)}")
    return "\n".join(lines).strip()


def render_product_detail(snapshot: BusinessContextSnapshot, slug: str) -> str | None:
    for summary in snapshot.products:
        if summary.product.slug == slug:
            product = summary.product
            lines = [f"🥷 NINJA {product.name}", "", f"Статус: {product.status.value.upper()}"]
            if product.current_stage:
                lines.append(f"Стадия: {product.current_stage}")
            if summary.active_campaign is not None:
                plan = summary.active_campaign
                lines.append(f"Кампания: {plan.status.upper()} (фаза: {plan.phase or '-'})")
                if plan.key_messages:
                    lines.append("Ключевые сообщения: " + "; ".join(plan.key_messages))
            return "\n".join(lines)
    return None


def render_help(role: BusinessContextRole, allowed_commands: frozenset[str]) -> str:
    """Spec §27/§29: derived from COMMAND_REGISTRY only, filtered to the caller's own role - never
    a second, hand-authored help string."""
    lines = [
        "🥷 NINJA Command Center", "",
        "Здесь можно передавать информацию о продуктах, кампаниях и бизнес-приоритетах "
        "директорам NINJA.", "",
        "Доступные вам команды:", "",
    ]
    for command in commands_for_role(allowed_commands):
        lines.append(f"/{command.name}")
        lines.append(command.description)
        lines.append("")
    return "\n".join(lines).strip()


def render_help_detail(command: CommandDefinition) -> str:
    lines = [f"📖 /{command.name}", "", command.detailed_help]
    if command.examples:
        lines.append("")
        lines.append("Пример:")
        lines.append(command.examples[0])
    if command.is_mutation:
        lines.extend([
            "", "Что произойдёт:", "",
            "1. AI разберёт сообщение.", "2. Покажет структурированную версию.",
            "3. Вы проверите изменения.",
            "4. После подтверждения информация попадёт в Business Context.",
            "5. Telegram и Instagram Directors получат обновлённый контекст.", "",
            "Ни одно сообщение не становится активной директивой без подтверждения.",
        ])
    return "\n".join(lines)


def render_proposal_preview(proposal: BusinessContextProposal) -> str:
    """MESSAGE the confirm/edit/cancel keyboard is attached to (spec §21's own example shape) -
    a plain, honest listing of every operation in `proposal.proposed_change_set`, never a
    summarized/lossy rendering that could hide a change from the confirming human."""
    lines = ["🥷 Проверьте предложенные изменения", ""]
    for i, op in enumerate(proposal.proposed_change_set, start=1):
        entity_type = op.get("entity_type", "?")
        lines.append(f"{i}. {entity_type}")
        for key, value in op.items():
            if key in ("entity_type", "action") or value in (None, "", [], {}):
                continue
            lines.append(f"   {key}: {value}")
    lines.append("")
    lines.append("[✅ Подтвердить] [✏️ Исправить] [❌ Отмена]")
    return "\n".join(lines)


def render_quickstart_manual() -> str:
    """Spec §36 (Business Context) / SOCIAL-INTELLIGENCE-INTEGRATION-1 §22 (Director Console
    section) - Russian, user-facing, renderer-only (never auto-pinned by this phase)."""
    return (
        "NINJA Command Center\n\n"
        "General — точка управления бизнес-контекстом NINJA.\n\n"
        "Здесь авторизованные участники сообщают системе о состоянии продуктов, запусках, "
        "маркетинговых кампаниях и стратегических приоритетах.\n\n"
        "Используйте /help, чтобы посмотреть команды.\n\n"
        "Команды принимают обычный текст.\n\n"
        "Бот сначала покажет, как понял сообщение. Изменения сохраняются только после "
        "подтверждения.\n\n"
        "Обычные сообщения General не являются командами.\n\n"
        "/status — текущая картина.\n"
        "/help — инструкция.\n\n"
        "Директора:\n\n"
        "/directors — состояние AI-директоров\n"
        "/plan — текущий Telegram + Instagram контент-план\n"
        "/opportunities — актуальные новости/тренды/кампании для контента\n"
        "/calendar — будущий контент и его статус\n"
        "/performance — реальные сигналы эффективности"
    )
