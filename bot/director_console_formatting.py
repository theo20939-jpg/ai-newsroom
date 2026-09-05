"""SOCIAL-INTELLIGENCE-INTEGRATION-1/SOCIAL-INTELLIGENCE-OPS-1, spec §13/§23/§54/§55/§56: pure
Director Console rendering. No aiogram/Bot type, no database access - mirrors
bot/business_context_formatting.py's own "pure functions, no database access" discipline exactly.
Russian, user-facing, compact (spec §23) - no internal DB IDs unless genuinely useful for debugging
context, no giant JSON dumps.

CRITICAL (spec §54): every renderer takes the caller's `role` and consults the ONE
DirectorConsoleAccessPolicy (services/director_console_access_policy.py) for every sensitive-field
decision - never an ad hoc `if role == VIEWER` check invented locally per renderer."""
from __future__ import annotations

from database.models.instagram_calendar_item import CalendarItemStatus
from services.business_context_roles import BusinessContextRole
from services.director_console_access_policy import REDACTED_LABEL, DirectorConsoleAccessPolicy
from services.director_console_service import CalendarView, OpportunitiesView, PerformanceView, PlanView
from services.director_status_service import DirectorConsoleStatus, DirectorStatus

_STATUS_LABEL = {
    DirectorStatus.DISABLED: "🔕 DISABLED", DirectorStatus.READY: "🟡 READY",
    DirectorStatus.SHADOW: "🌓 SHADOW", DirectorStatus.ACTIVE: "🟢 ACTIVE",
    DirectorStatus.WAITING_FOR_DATA: "⏳ WAITING_FOR_DATA", DirectorStatus.UNAVAILABLE: "⛔ UNAVAILABLE",
    DirectorStatus.UNKNOWN: "❔ UNKNOWN",
}
_MAX_OPPORTUNITY_ROWS = 8
_MAX_CALENDAR_ROWS = 10
_SENSITIVE_CAMPAIGN_STATUSES = frozenset({"tentative"})


def _as_of_line(as_of) -> str:  # noqa: ANN001 - datetime, kept untyped to avoid a needless import
    return f"по состоянию на {as_of.strftime('%Y-%m-%d %H:%M UTC')}"


def render_directors_status(status: DirectorConsoleStatus, *, role: BusinessContextRole) -> str:
    # `role`/DirectorConsoleAccessPolicy kept as parameters for interface uniformity across all 5
    # console renderers (spec §54) - DirectorStatusEntry.detail strings never currently embed a
    # TENTATIVE status or launch date (services/director_status_service.py only ever surfaces
    # product name + derived phase, and a TENTATIVE campaign's derived phase is always the same
    # generic AWARENESS a CONFIRMED campaign's early phase would also show - see
    # services/campaign_planner.py::derive_phase()), so no redaction is currently applicable here.
    # If a future change to DirectorStatusEntry.detail ever adds a real launch date/status, gate
    # it through DirectorConsoleAccessPolicy.can_see_tentative_launch_dates() the same way
    # render_plan() already does.
    del role
    lines = ["🥷 NINJA Директора", "", _as_of_line(status.as_of), ""]

    lines.append("БИЗНЕС")
    for entry in status.business:
        lines.append(f"{entry.name}")
        lines.append(_STATUS_LABEL.get(entry.status, entry.status.value))
        if entry.detail:
            lines.append(entry.detail)
        lines.append("")

    lines.append("TELEGRAM")
    for entry in status.telegram:
        lines.append(entry.name)
        lines.append(_STATUS_LABEL.get(entry.status, entry.status.value))
        if entry.detail:
            lines.append(entry.detail)
        lines.append("")

    lines.append("INSTAGRAM")
    for entry in status.instagram:
        lines.append(entry.name)
        lines.append(_STATUS_LABEL.get(entry.status, entry.status.value))
        if entry.detail:
            lines.append(entry.detail)
        lines.append("")

    return "\n".join(lines).strip()


def render_plan(view: PlanView, *, role: BusinessContextRole, platform: str | None = None) -> str:
    policy = DirectorConsoleAccessPolicy(role=role)
    lines = ["🥷 NINJA План", "", _as_of_line(view.as_of), ""]

    lines.append("BUSINESS PRIORITY / CAMPAIGN PHASE")
    if not view.active_campaigns:
        lines.append("нет активных кампаний")
    for plan in view.active_campaigns:
        if plan.status in _SENSITIVE_CAMPAIGN_STATUSES and not policy.can_see_tentative_launch_dates():
            lines.append(f"- кампания {plan.campaign_id}: {REDACTED_LABEL}")
        else:
            lines.append(f"- кампания {plan.campaign_id}: статус {plan.status.upper()}, фаза {plan.phase or '-'}")
    lines.append("")

    lines.append("FOUNDER DIRECTIVES")
    if not policy.can_see_founder_directive_text():
        lines.append(REDACTED_LABEL if view.active_directives else "нет действующих директив")
    elif not view.active_directives:
        lines.append("нет действующих директив")
    else:
        for directive in view.active_directives:
            lines.append(f"- {directive.instruction}")
    lines.append("")

    if platform in (None, "telegram"):
        lines.append("TELEGRAM PLAN")
        if view.telegram_note:
            lines.append(view.telegram_note)
        elif view.telegram_advisory is not None:
            if view.telegram_advisory.priority_themes:
                lines.append("Приоритетные темы: " + ", ".join(view.telegram_advisory.priority_themes))
            for note in view.telegram_advisory.content_balance_notes:
                lines.append(f"- {note}")
            for note in view.telegram_advisory.campaign_support_notes:
                lines.append(f"- {note}")
        lines.append("")

    if platform in (None, "instagram"):
        lines.append("INSTAGRAM PLAN")
        if view.instagram_note:
            lines.append(view.instagram_note)
        elif view.instagram_strategy is not None:
            if view.instagram_strategy.objective_mix:
                mix = ", ".join(f"{k}: {v}" for k, v in view.instagram_strategy.objective_mix.items())
                lines.append(f"Распределение целей: {mix}")
            # avoidance_notes/risks may embed a Founder Directive's own wording (services/
            # instagram_growth_strategist.py::apply_founder_directive_precedence()) - gated the
            # same way as the FOUNDER DIRECTIVES section itself, never shown as a "loophole".
            if policy.can_see_internal_campaign_strategy_notes():
                for note in view.instagram_strategy.avoidance_notes:
                    lines.append(f"- ограничение: {note}")
                for risk in view.instagram_strategy.risks:
                    lines.append(f"- риск: {risk}")
            elif view.instagram_strategy.avoidance_notes or view.instagram_strategy.risks:
                lines.append(f"- {REDACTED_LABEL}")
        lines.append("")

    return "\n".join(lines).strip()


def render_opportunities(view: OpportunitiesView, *, role: BusinessContextRole, platform: str | None = None) -> str:
    policy = DirectorConsoleAccessPolicy(role=role)
    lines = ["🥷 NINJA Возможности для контента", "", _as_of_line(view.as_of), ""]

    shown = view.rows[:_MAX_OPPORTUNITY_ROWS]
    if not shown:
        lines.append("Нет доступных возможностей.")
    for row in shown:
        lines.append(f"[{row.source_type.upper()}] {row.topic}")
        dims = []
        if row.news_value is not None:
            dims.append(f"news_value={row.news_value:.2f}")
        if row.campaign_relevance is not None:
            dims.append(f"campaign_relevance={row.campaign_relevance:.2f}")
        if row.trend_relevance is not None:
            dims.append(f"trend_relevance={row.trend_relevance:.2f}")
        if dims:
            lines.append(", ".join(dims))
        if platform in (None, "instagram"):
            lines.append(f"Instagram: {row.instagram_objective.value if row.instagram_objective else '-'} / {row.instagram_format.value if row.instagram_format else '-'}")
        if platform in (None, "telegram"):
            lines.append(f"Telegram: {row.telegram_note}")
        lines.append(f"Упоминание продукта: {'РАЗРЕШЕНО' if row.product_mention_allowed else 'НЕ РАЗРЕШЕНО'}")
        if row.restricted_claims:
            lines.append("Запрещённые утверждения: " + (", ".join(row.restricted_claims) if policy.can_see_restricted_claims() else REDACTED_LABEL))
        if row.embargo_constraints:
            lines.append("Эмбарго: " + (", ".join(row.embargo_constraints) if policy.can_see_embargo_details() else REDACTED_LABEL))
        lines.append(f"Уверенность: {row.confidence:.2f}")
        lines.append("")

    if len(view.rows) > _MAX_OPPORTUNITY_ROWS:
        lines.append(f"… и ещё {len(view.rows) - _MAX_OPPORTUNITY_ROWS}. Используйте более узкий запрос.")
        lines.append("")

    for note in view.notes:
        lines.append(f"ℹ️ {note}")

    return "\n".join(lines).strip()


_CALENDAR_STATUS_LABEL = {
    CalendarItemStatus.ACTIVE: "ACTIVE", CalendarItemStatus.STALE: "STALE",
    CalendarItemStatus.INVALIDATED: "INVALIDATED", CalendarItemStatus.RESCHEDULED: "RESCHEDULED",
    CalendarItemStatus.DONE: "DONE", CalendarItemStatus.CANCELLED: "CANCELLED",
}


def render_calendar(view: CalendarView, *, role: BusinessContextRole, platform: str | None = None) -> str:
    policy = DirectorConsoleAccessPolicy(role=role)
    lines = ["🥷 NINJA Календарь контента", "", _as_of_line(view.as_of), ""]

    if not policy.can_see_unpublished_calendar():
        lines.append(REDACTED_LABEL)
        lines.append("Календарь доступен ролям с операционным доступом к контенту.")
        return "\n".join(lines).strip()

    shown = view.rows[:_MAX_CALENDAR_ROWS]
    if not shown and not view.notes:
        lines.append("Нет запланированного контента.")
    for row in shown:
        status_label = _CALENDAR_STATUS_LABEL.get(row.status, row.status.value)
        if row.context_stale:
            status_label += " (STALE_CONTEXT)"
        lines.append(f"{row.planned_at.strftime('%Y-%m-%d %H:%M UTC')} · {row.platform.upper()}")
        lines.append(f"{row.concept} · цель: {row.objective}")
        lines.append(f"Статус: {status_label}")
        lines.append("")

    if len(view.rows) > _MAX_CALENDAR_ROWS:
        lines.append(f"… и ещё {len(view.rows) - _MAX_CALENDAR_ROWS}.")
        lines.append("")

    for note in view.notes:
        lines.append(f"ℹ️ {note}")

    return "\n".join(lines).strip()


def render_performance(view: PerformanceView, *, role: BusinessContextRole, platform: str | None = None) -> str:
    lines = ["🥷 NINJA Эффективность", "", _as_of_line(view.as_of), ""]

    if platform in (None, "telegram"):
        lines.append("TELEGRAM")
        if view.telegram_status == "PUBLIC_CHANNEL_NOT_CONFIGURED":
            lines.append("PUBLIC_CHANNEL_NOT_CONFIGURED - публичный канал NINJA PULSE не настроен.")
            lines.append("Метрики внутреннего редакционного чата НЕ являются метриками аудитории.")
        elif view.telegram_status == "NO_EVIDENCE_YET":
            lines.append("Публичный канал настроен, но данных ещё недостаточно.")
        else:
            lines.append(view.telegram_status)
        for evidence in view.telegram_evidence:
            lines.append(f"- {evidence.description} (n={evidence.sample_size}, эффект={evidence.effect_size:+.0%}, стадия={evidence.stage})")
        lines.append("")

    if platform in (None, "instagram"):
        lines.append("INSTAGRAM")
        if view.instagram_status == "NO_FIRST_PARTY_DATA":
            lines.append("NO_FIRST_PARTY_DATA - аккаунт Instagram не подключён.")
        else:
            lines.append(view.instagram_status)
        lines.append("")

    return "\n".join(lines).strip()
