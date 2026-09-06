"""SOCIAL-INTELLIGENCE-PRELAUNCH-1 §10/§12/§22: pure /launch and /directors-refresh rendering. No
aiogram/Bot type, no database access - mirrors bot/telegram_surface_formatting.py's own
discipline exactly."""
from __future__ import annotations

from database.models.social_launch_context import SocialLaunchContext
from database.models.social_launch_proposal import SocialLaunchProposal
from services.social_prelaunch_advisory import PrelaunchAdvisory

_LAUNCH_STATE_LABEL = {
    "pre_launch": "PRE_LAUNCH", "transition": "TRANSITION", "live": "LIVE", "paused": "PAUSED",
}
_DATE_STATUS_LABEL = {"unscheduled": "UNSCHEDULED", "tentative": "TENTATIVE", "confirmed": "CONFIRMED"}


def _mode_label(context: SocialLaunchContext | None) -> str:
    """spec §10: a truthful COLD_START state is a NORMAL state, never rendered as an error."""
    if context is None:
        return "PRE_LAUNCH / COLD_START (не настроено)"
    if context.launch_state.value in ("pre_launch", "transition") and context.learning_start_at is None:
        return f"{_LAUNCH_STATE_LABEL[context.launch_state.value]} / COLD_START"
    return _LAUNCH_STATE_LABEL[context.launch_state.value]


def render_launch_context(platform_label: str, context: SocialLaunchContext | None) -> str:
    lines = [f"🥷 NINJA PULSE {platform_label}", "", f"Режим: {_mode_label(context)}"]
    if context is None:
        lines += [
            "", "Контекст запуска ещё не настроен.",
            f"Используйте /launch {platform_label.lower()} <инструкция>, чтобы настроить.",
        ]
        return "\n".join(lines)

    lines.append(f"Целевая идентичность: {context.target_identity}")
    if context.current_identity:
        lines.append(f"Текущая идентичность: {context.current_identity}")
    lines.append(f"Дата запуска: {context.planned_launch_at.strftime('%Y-%m-%d') if context.planned_launch_at else 'не назначена'} "
                 f"({_DATE_STATUS_LABEL[context.launch_date_status.value]})")
    lines.append(f"Политика обучения: {context.baseline_policy.value}")
    lines.append(f"Политика по старому контенту: {context.historical_content_policy.value}")
    lines.append(
        "Первичные данные: "
        + (f"с {context.learning_start_at.strftime('%Y-%m-%d %H:%M UTC')}" if context.learning_start_at else "ОТСУТСТВУЮТ")
    )
    lines.append(f"Версия контекста: v{context.version}")
    return "\n".join(lines)


def render_launch_proposal_preview(proposal: SocialLaunchProposal) -> str:
    structure = proposal.parsed_structure or {}
    lines = [
        "🥷 Проверьте предложенный контекст запуска", "",
        f"Платформа: {proposal.platform.value.upper()}",
        f"Резюме: {structure.get('summary', '(без резюме)')}",
    ]
    for key, label in (
        ("target_identity", "Целевая идентичность"), ("current_identity", "Текущая идентичность"),
        ("launch_state", "Статус запуска"), ("planned_launch_at", "Дата запуска"),
        ("launch_date_status", "Статус даты"), ("baseline_policy", "Политика обучения"),
        ("historical_content_policy", "Политика по старому контенту"),
    ):
        if structure.get(key):
            lines.append(f"{label}: {structure[key]}")
    lines.append("")
    lines.append("[✅ Подтвердить] [✏️ Исправить] [❌ Отмена]")
    return "\n".join(lines)


def render_prelaunch_advisory(platform_label: str, advisory: PrelaunchAdvisory) -> str:
    """spec §22's own required field list, rendered plainly - never a generic marketing essay."""
    def _section(title: str, items: list[str]) -> list[str]:
        if not items:
            return []
        return [f"{title}:"] + [f"- {item}" for item in items] + [""]

    lines = [f"🥷 Pre-launch advisory — {platform_label}", ""]
    lines.append(f"Текущее состояние: {advisory.current_state}")
    lines.append(f"Целевое состояние: {advisory.target_state}")
    lines.append("")
    lines += _section("Цели запуска", advisory.launch_objectives)
    lines += _section("Задачи перехода", advisory.transition_tasks)
    lines += _section("Контентные столпы", advisory.content_pillars)
    lines += _section("Первая последовательность публикаций", advisory.initial_content_sequence)
    if advisory.cadence_hypothesis:
        lines.append(f"Гипотеза по частоте публикаций: {advisory.cadence_hypothesis}")
        lines.append("")
    lines += _section("Форматные гипотезы", advisory.format_hypotheses)
    if advisory.visual_direction:
        lines.append(f"Визуальное направление: {advisory.visual_direction}")
        lines.append("")
    lines += _section("Настройка профиля/канала", advisory.profile_setup)
    lines += _section("Закреплённый/вводный контент", advisory.pinned_intro_content)
    lines += _section("Первые вопросы для изучения", advisory.first_learning_questions)
    lines += _section("План измерений", advisory.measurement_plan)
    lines += _section("Риски", advisory.risks)
    return "\n".join(lines).strip()


def render_refresh_confirmation(target: str, *, runs_today: int, max_runs_per_day: int, cost_known: bool, cost_today: float | None) -> str:
    cost_line = f"${cost_today:.2f} потрачено сегодня" if cost_known else "стоимость сегодняшних запусков неизвестна"
    return (
        "🥷 Обновить advisory-директоров?\n\n"
        f"Цель: {target}\n"
        f"Запусков сегодня: {runs_today}/{max_runs_per_day}\n"
        f"Бюджет: {cost_line}\n\n"
        "[✅ Запустить] [❌ Отмена]"
    )


_BUDGET_DECISION_LABEL = {
    "daily_run_limit_reached": "Достигнут дневной лимит запусков.",
    "daily_budget_exhausted": "Достигнут дневной бюджет.",
    "budget_unknown": "Стоимость сегодняшних запусков неизвестна - обновление заблокировано из соображений безопасности.",
}


def render_budget_blocked(decision_value: str) -> str:
    return f"🥷 {_BUDGET_DECISION_LABEL.get(decision_value, decision_value)}"
