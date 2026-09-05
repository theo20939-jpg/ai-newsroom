"""VISUAL-DESIGN-AUTONOMY-1, spec §76: /design rendering tests - VIEWER never sees unreleased
brief text (reuses DirectorConsoleAccessPolicy.can_see_unreleased_creative_concepts(), same gate
already proven for other console renderers), FOUNDER does."""
from __future__ import annotations

from datetime import datetime, timezone

from bot.visual_design_formatting import render_design_scope_detail, render_design_status
from services.business_context_roles import BusinessContextRole
from services.visual_design_console_service import (
    VisualDesignScopeDetailView,
    VisualDesignView,
    VisualHealthSummary,
    VisualHealthStatus,
    VisualScopeSummary,
)

_NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
_FOUNDER = BusinessContextRole.FOUNDER
_VIEWER = BusinessContextRole.VIEWER


def test_status_shows_health_and_budget() -> None:
    view = VisualDesignView(
        as_of=_NOW,
        scopes=[VisualScopeSummary(
            scope="data", active_brief_version=13, active_brief_status="active",
            health=VisualHealthSummary(status=VisualHealthStatus.WATCH, pass_count=20, notes_count=2, rework_count=5, dominant_issue_codes=["visual_too_busy"]),
        )],
        daily_cost_known=True, daily_cost_so_far=1.5, daily_cost_limit=20.0,
    )
    text = render_design_status(view, role=_FOUNDER)
    assert "DATA" in text
    assert "Brief v13" in text
    assert "WATCH" in text
    assert "visual_too_busy" in text
    assert "$1.50 / $20.00" in text


def test_status_shows_unknown_budget_honestly() -> None:
    view = VisualDesignView(as_of=_NOW, scopes=[], daily_cost_known=False, daily_cost_so_far=None, daily_cost_limit=20.0)
    text = render_design_status(view, role=_FOUNDER)
    assert "неизвестно" in text
    assert "0.00" not in text  # never a fabricated known-zero value


def test_viewer_never_sees_brief_text() -> None:
    detail = VisualDesignScopeDetailView(
        as_of=_NOW, scope="data", active_brief_version=13, active_brief_status="active",
        last_change_reason=None, last_change_at=None,
        health=VisualHealthSummary(status=VisualHealthStatus.HEALTHY), rollback_available=True,
        brief_text="secret unreleased creative direction text",
    )
    viewer_text = render_design_scope_detail(detail, role=_VIEWER)
    assert "secret unreleased" not in viewer_text
    assert "скрыто" in viewer_text

    founder_text = render_design_scope_detail(detail, role=_FOUNDER)
    assert "secret unreleased creative direction text" in founder_text


def test_adaptation_status_shown_with_honest_label() -> None:
    detail = VisualDesignScopeDetailView(
        as_of=_NOW, scope="data", active_brief_version=13, active_brief_status="active",
        last_change_reason=None, last_change_at=None,
        health=VisualHealthSummary(status=VisualHealthStatus.HEALTHY), rollback_available=False,
        adaptation_status="repeated_pattern_detected",
    )
    text = render_design_scope_detail(detail, role=_FOUNDER)
    assert "Repeated pattern detected" in text


def test_viewer_never_sees_latest_candidate_reason() -> None:
    detail = VisualDesignScopeDetailView(
        as_of=_NOW, scope="data", active_brief_version=13, active_brief_status="active",
        last_change_reason=None, last_change_at=None,
        health=VisualHealthSummary(status=VisualHealthStatus.HEALTHY), rollback_available=False,
        adaptation_status="candidate_ready", latest_candidate_reason="repeated VISUAL_TOO_BUSY on DATA",
    )
    viewer_text = render_design_scope_detail(detail, role=_VIEWER)
    assert "VISUAL_TOO_BUSY" not in viewer_text

    founder_text = render_design_scope_detail(detail, role=_FOUNDER)
    assert "repeated VISUAL_TOO_BUSY on DATA" in founder_text
