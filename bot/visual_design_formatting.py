"""VISUAL-DESIGN-AUTONOMY-1, spec §52-54: /design rendering - pure functions over already-computed
VisualDesignView/VisualDesignScopeDetailView, gated by the SAME DirectorConsoleAccessPolicy every
other console renderer uses (never a second, ad hoc privacy check)."""
from __future__ import annotations

from services.business_context_roles import BusinessContextRole
from services.director_console_access_policy import REDACTED_LABEL, DirectorConsoleAccessPolicy
from services.visual_design_console_service import (
    VisualDesignScopeDetailView,
    VisualDesignView,
    VisualHealthStatus,
)

_HEALTH_LABEL = {
    VisualHealthStatus.HEALTHY: "HEALTHY", VisualHealthStatus.WATCH: "WATCH",
    VisualHealthStatus.DEGRADED: "DEGRADED", VisualHealthStatus.FROZEN: "FROZEN",
    VisualHealthStatus.INSUFFICIENT_DATA: "INSUFFICIENT_DATA",
}


def render_design_status(view: VisualDesignView, *, role: BusinessContextRole) -> str:
    lines = ["🥷 Visual System", ""]
    if not view.scopes:
        lines.append("Ни для одного scope ещё не создан Designer Brief.")
    for scope in view.scopes:
        lines.append(scope.scope.upper())
        lines.append(f"Brief v{scope.active_brief_version}" if scope.active_brief_version else "Brief: нет")
        lines.append(scope.active_brief_status.upper())
        health = scope.health
        lines.append(f"Health: {_HEALTH_LABEL[health.status]}")
        if health.status not in (VisualHealthStatus.INSUFFICIENT_DATA, VisualHealthStatus.FROZEN):
            lines.append(f"Recent: {health.pass_count} PASS / {health.notes_count} NOTES / {health.rework_count} REWORK / {health.block_count} BLOCK")
        if health.dominant_issue_codes:
            lines.append("Recent issue: " + ", ".join(health.dominant_issue_codes))
        lines.append("")

    lines.append("Budget today:")
    if view.daily_cost_known:
        lines.append(f"${view.daily_cost_so_far:.2f} / ${view.daily_cost_limit:.2f}")
    else:
        lines.append("неизвестно (есть попытки без учтённой стоимости)")

    return "\n".join(lines).strip()


def render_design_scope_detail(view: VisualDesignScopeDetailView, *, role: BusinessContextRole) -> str:
    policy = DirectorConsoleAccessPolicy(role=role)
    lines = [f"🥷 Visual System — {view.scope.upper()}", ""]
    lines.append(f"Brief: v{view.active_brief_version}" if view.active_brief_version else "Brief: нет")
    lines.append(f"Статус: {view.active_brief_status.upper()}")
    if view.last_change_at:
        lines.append(f"Последнее изменение: {view.last_change_at.strftime('%Y-%m-%d %H:%M UTC')}")
    if view.last_change_reason:
        lines.append(f"Причина: {view.last_change_reason}")
    lines.append("")

    health = view.health
    lines.append(f"Health: {_HEALTH_LABEL[health.status]}")
    lines.append(f"Recent: {health.pass_count} PASS / {health.notes_count} NOTES / {health.rework_count} REWORK / {health.block_count} BLOCK")
    if health.dominant_issue_codes:
        lines.append("Частые проблемы: " + ", ".join(health.dominant_issue_codes))
    lines.append("")

    lines.append(f"Откат доступен: {'да' if view.rollback_available else 'нет'}")

    if view.brief_text is not None:
        if policy.can_see_unreleased_creative_concepts():
            lines.append("")
            lines.append("Текст брифа:")
            lines.append(view.brief_text)
        else:
            lines.append("")
            lines.append(REDACTED_LABEL)

    return "\n".join(lines).strip()
