"""SOCIAL-INTELLIGENCE-INTEGRATION-1, spec §12/§23: pure Director Console rendering tests - no
DB, no aiogram."""
from __future__ import annotations

from datetime import datetime, timezone

from bot.director_console_formatting import (
    render_calendar,
    render_directors_status,
    render_opportunities,
    render_performance,
    render_plan,
)
from database.models.instagram_calendar_item import CalendarItemStatus
from services.director_console_service import CalendarRow, CalendarView, OpportunitiesView, OpportunityRow, PerformanceEvidenceRow, PerformanceView, PlanView
from services.director_status_service import DirectorConsoleStatus, DirectorStatus, DirectorStatusEntry
from services.instagram_format_director import ContentFormat
from services.instagram_objectives import ContentObjective

_NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)


def test_render_directors_status_never_shows_fake_active() -> None:
    status = DirectorConsoleStatus(
        as_of=_NOW,
        business=[DirectorStatusEntry(name="Campaign Planner", status=DirectorStatus.READY, detail="нет активных кампаний")],
        telegram=[DirectorStatusEntry(name="Channel Director", status=DirectorStatus.DISABLED)],
        instagram=[DirectorStatusEntry(name="Creative Director", status=DirectorStatus.READY)],
    )
    text = render_directors_status(status)
    assert "DISABLED" in text
    assert "READY" in text
    assert "ACTIVE" not in text.replace("🟢 ACTIVE", "")  # no fabricated ACTIVE label anywhere


def test_render_performance_shows_public_channel_not_configured_not_internal_metrics() -> None:
    view = PerformanceView(as_of=_NOW, telegram_status="PUBLIC_CHANNEL_NOT_CONFIGURED", instagram_status="NO_FIRST_PARTY_DATA")
    text = render_performance(view)
    assert "PUBLIC_CHANNEL_NOT_CONFIGURED" in text
    assert "внутреннего редакционного чата" in text
    assert "NO_FIRST_PARTY_DATA" in text


def test_render_performance_evidence_shows_sample_size_effect_and_stage_never_a_bare_verdict() -> None:
    """Spec §12's own explicit example shape: 'Possible signal: DATA posts show higher forward
    rate, sample: 8 posts, effect: +18%, stage: POSSIBLE_SIGNAL' - never a bare
    'Best format: DATA' without the evidence backing it."""
    view = PerformanceView(
        as_of=_NOW, telegram_status="NO_EVIDENCE_YET",
        telegram_evidence=[PerformanceEvidenceRow(description="DATA posts show higher forward rate", sample_size=8, effect_size=0.18, stage="POSSIBLE_SIGNAL")],
    )
    text = render_performance(view, platform="telegram")
    assert "n=8" in text
    assert "+18%" in text
    assert "POSSIBLE_SIGNAL" in text
    assert "Best format" not in text


def test_render_calendar_shows_stale_context_annotation() -> None:
    view = CalendarView(as_of=_NOW, rows=[
        CalendarRow(platform="instagram", planned_at=_NOW, concept="launch reel", objective="reach", campaign_id="c1", status=CalendarItemStatus.ACTIVE, context_stale=True),
    ])
    text = render_calendar(view)
    assert "STALE_CONTEXT" in text
    assert "ACTIVE" in text


def test_render_calendar_never_fabricates_telegram_posts() -> None:
    view = CalendarView(as_of=_NOW, rows=[], notes=["Telegram: календарь публикаций не реализован (нет персистентной модели) - записи не показаны"])
    text = render_calendar(view)
    assert "не реализован" in text


def test_render_opportunities_paginates_and_never_shows_magic_score() -> None:
    rows = [
        OpportunityRow(
            source_type="product", topic=f"campaign-{i}", news_value=None, campaign_relevance=1.0, trend_relevance=None,
            product_mention_allowed=True, restricted_claims=[], instagram_objective=ContentObjective.REACH,
            instagram_format=ContentFormat.REEL, telegram_note="ok", confidence=0.4,
        )
        for i in range(12)
    ]
    view = OpportunitiesView(as_of=_NOW, rows=rows)
    text = render_opportunities(view)
    assert "и ещё 4" in text
    assert "score" not in text.lower()


def test_render_plan_shows_founder_directive_and_separate_platform_sections() -> None:
    from services.instagram_growth_strategist import InstagramGrowthStrategy
    from services.telegram_strategy_director import StrategyDirectorAdvisory
    from database.models.strategic_directive import StrategicDirective, DirectiveStatus

    directive = StrategicDirective(instruction="Store пока не продвигаем.", valid_from=_NOW, priority=1, status=DirectiveStatus.ACTIVE)
    view = PlanView(
        as_of=_NOW, business_context_version="v1", active_directives=[directive],
        telegram_advisory=StrategyDirectorAdvisory(content_balance_notes=["insufficient evidence: no recent channel post history available"]),
        instagram_strategy=InstagramGrowthStrategy(avoidance_notes=["product_mention blocked by active founder directive"]),
    )
    text = render_plan(view)
    assert "Store" in text
    assert "TELEGRAM PLAN" in text
    assert "INSTAGRAM PLAN" in text
    assert "founder directive" in text
