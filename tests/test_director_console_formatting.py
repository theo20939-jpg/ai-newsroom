"""SOCIAL-INTELLIGENCE-INTEGRATION-1/SOCIAL-INTELLIGENCE-OPS-1, spec §12/§23/§59: pure Director
Console rendering tests, including role-based redaction - no DB, no aiogram."""
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
from database.models.strategic_directive import DirectiveStatus, StrategicDirective
from services.business_context_roles import BusinessContextRole
from services.director_console_service import CalendarRow, CalendarView, OpportunitiesView, OpportunityRow, PerformanceEvidenceRow, PerformanceView, PlanView
from services.director_status_service import DirectorConsoleStatus, DirectorStatus, DirectorStatusEntry
from services.instagram_format_director import ContentFormat
from services.instagram_growth_strategist import InstagramGrowthStrategy
from services.instagram_objectives import ContentObjective
from services.telegram_strategy_director import StrategyDirectorAdvisory

_NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
_FOUNDER = BusinessContextRole.FOUNDER
_VIEWER = BusinessContextRole.VIEWER


def test_render_directors_status_never_shows_fake_active() -> None:
    status = DirectorConsoleStatus(
        as_of=_NOW,
        business=[DirectorStatusEntry(name="Campaign Planner", status=DirectorStatus.READY, detail="нет активных кампаний")],
        telegram=[DirectorStatusEntry(name="Channel Director", status=DirectorStatus.DISABLED)],
        instagram=[DirectorStatusEntry(name="Creative Director", status=DirectorStatus.READY)],
    )
    text = render_directors_status(status, role=_FOUNDER)
    assert "DISABLED" in text
    assert "READY" in text
    assert "ACTIVE" not in text.replace("🟢 ACTIVE", "")  # no fabricated ACTIVE label anywhere


def test_render_performance_shows_public_channel_not_configured_not_internal_metrics() -> None:
    view = PerformanceView(as_of=_NOW, telegram_status="PUBLIC_CHANNEL_NOT_CONFIGURED", instagram_status="NO_FIRST_PARTY_DATA")
    text = render_performance(view, role=_FOUNDER)
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
    text = render_performance(view, role=_FOUNDER, platform="telegram")
    assert "n=8" in text
    assert "+18%" in text
    assert "POSSIBLE_SIGNAL" in text
    assert "Best format" not in text


def test_render_calendar_shows_stale_context_annotation() -> None:
    view = CalendarView(as_of=_NOW, rows=[
        CalendarRow(platform="instagram", planned_at=_NOW, concept="launch reel", objective="reach", campaign_id="c1", status=CalendarItemStatus.ACTIVE, context_stale=True),
    ])
    text = render_calendar(view, role=_FOUNDER)
    assert "STALE_CONTEXT" in text
    assert "ACTIVE" in text


def test_render_calendar_never_fabricates_telegram_posts() -> None:
    view = CalendarView(as_of=_NOW, rows=[], notes=["Telegram: календарь публикаций не реализован (нет персистентной модели) - записи не показаны"])
    text = render_calendar(view, role=_FOUNDER)
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
    text = render_opportunities(view, role=_FOUNDER)
    assert "и ещё 4" in text
    assert "score" not in text.lower()


def test_render_plan_shows_founder_directive_and_separate_platform_sections() -> None:
    directive = StrategicDirective(instruction="Store пока не продвигаем.", valid_from=_NOW, priority=1, status=DirectiveStatus.ACTIVE)
    view = PlanView(
        as_of=_NOW, business_context_version="v1", active_directives=[directive],
        telegram_advisory=StrategyDirectorAdvisory(content_balance_notes=["insufficient evidence: no recent channel post history available"]),
        instagram_strategy=InstagramGrowthStrategy(avoidance_notes=["product_mention blocked by active founder directive"]),
    )
    text = render_plan(view, role=_FOUNDER)
    assert "Store" in text
    assert "TELEGRAM PLAN" in text
    assert "INSTAGRAM PLAN" in text
    assert "founder directive" in text


# ---------------------------------------------------------------------------
# spec §9/§10/§59: VIEWER redaction
# ---------------------------------------------------------------------------


def test_viewer_cannot_see_founder_directive_text() -> None:
    directive = StrategicDirective(instruction="Store пока не продвигаем.", valid_from=_NOW, priority=1, status=DirectiveStatus.ACTIVE)
    view = PlanView(as_of=_NOW, business_context_version="v1", active_directives=[directive])
    text = render_plan(view, role=_VIEWER)
    assert "Store" not in text
    assert "продвигаем" not in text


def test_founder_can_see_founder_directive_text() -> None:
    directive = StrategicDirective(instruction="Store пока не продвигаем.", valid_from=_NOW, priority=1, status=DirectiveStatus.ACTIVE)
    view = PlanView(as_of=_NOW, business_context_version="v1", active_directives=[directive])
    text = render_plan(view, role=_FOUNDER)
    assert "Store" in text


def test_viewer_cannot_see_avoidance_notes_embedding_directive_text() -> None:
    view = PlanView(
        as_of=_NOW, business_context_version="v1",
        instagram_strategy=InstagramGrowthStrategy(avoidance_notes=["product_mention for product='store' blocked by active founder directive: 'Store пока не продвигаем.'"]),
    )
    text = render_plan(view, role=_VIEWER)
    assert "продвигаем" not in text


def test_viewer_cannot_see_restricted_claims() -> None:
    row = OpportunityRow(
        source_type="product", topic="NINJA AI launch", news_value=None, campaign_relevance=1.0, trend_relevance=None,
        product_mention_allowed=False, restricted_claims=["exact price: $4.99/month"], instagram_objective=None,
        instagram_format=None, telegram_note="n/a", confidence=0.4,
    )
    view = OpportunitiesView(as_of=_NOW, rows=[row])
    text = render_opportunities(view, role=_VIEWER)
    assert "4.99" not in text
    assert "скрыто по роли" in text


def test_founder_can_see_restricted_claims() -> None:
    row = OpportunityRow(
        source_type="product", topic="NINJA AI launch", news_value=None, campaign_relevance=1.0, trend_relevance=None,
        product_mention_allowed=False, restricted_claims=["exact price: $4.99/month"], instagram_objective=None,
        instagram_format=None, telegram_note="n/a", confidence=0.4,
    )
    view = OpportunitiesView(as_of=_NOW, rows=[row])
    text = render_opportunities(view, role=_FOUNDER)
    assert "4.99" in text


def test_viewer_cannot_see_embargo_details() -> None:
    row = OpportunityRow(
        source_type="product", topic="NINJA AI launch", news_value=None, campaign_relevance=1.0, trend_relevance=None,
        product_mention_allowed=False, restricted_claims=[], instagram_objective=None, instagram_format=None,
        telegram_note="n/a", confidence=0.4, embargo_constraints=["do not reveal before 2026-10-05"],
    )
    view = OpportunitiesView(as_of=_NOW, rows=[row])
    text = render_opportunities(view, role=_VIEWER)
    assert "2026-10-05" not in text


def test_founder_can_see_embargo_details() -> None:
    row = OpportunityRow(
        source_type="product", topic="NINJA AI launch", news_value=None, campaign_relevance=1.0, trend_relevance=None,
        product_mention_allowed=False, restricted_claims=[], instagram_objective=None, instagram_format=None,
        telegram_note="n/a", confidence=0.4, embargo_constraints=["do not reveal before 2026-10-05"],
    )
    view = OpportunitiesView(as_of=_NOW, rows=[row])
    text = render_opportunities(view, role=_FOUNDER)
    assert "2026-10-05" in text


def test_viewer_cannot_see_private_campaign_calendar() -> None:
    view = CalendarView(as_of=_NOW, rows=[
        CalendarRow(platform="instagram", planned_at=_NOW, concept="secret launch reel", objective="reach", campaign_id="c1", status=CalendarItemStatus.ACTIVE),
    ])
    text = render_calendar(view, role=_VIEWER)
    assert "secret launch reel" not in text


def test_founder_can_see_campaign_calendar() -> None:
    view = CalendarView(as_of=_NOW, rows=[
        CalendarRow(platform="instagram", planned_at=_NOW, concept="secret launch reel", objective="reach", campaign_id="c1", status=CalendarItemStatus.ACTIVE),
    ])
    text = render_calendar(view, role=_FOUNDER)
    assert "secret launch reel" in text


def test_editor_can_see_calendar_but_not_founder_directive_text() -> None:
    editor = BusinessContextRole.EDITOR
    calendar_view = CalendarView(as_of=_NOW, rows=[
        CalendarRow(platform="instagram", planned_at=_NOW, concept="editorial concept", objective="reach", campaign_id="c1", status=CalendarItemStatus.ACTIVE),
    ])
    assert "editorial concept" in render_calendar(calendar_view, role=editor)

    directive = StrategicDirective(instruction="Store пока не продвигаем.", valid_from=_NOW, priority=1, status=DirectiveStatus.ACTIVE)
    plan_view = PlanView(as_of=_NOW, business_context_version="v1", active_directives=[directive])
    assert "Store" not in render_plan(plan_view, role=editor)


def test_tentative_campaign_status_hidden_from_viewer() -> None:
    from services.campaign_planner import CampaignPlan

    plan = CampaignPlan(
        campaign_id="c1", product_id="p1", objective=None, phase="AWARENESS", status="tentative",
        date_confidence="rough", start_at=None, end_at=None,
    )
    view = PlanView(as_of=_NOW, business_context_version="v1", active_campaigns=[plan])
    text = render_plan(view, role=_VIEWER)
    assert "TENTATIVE" not in text


def test_tentative_campaign_status_visible_to_founder() -> None:
    from services.campaign_planner import CampaignPlan

    plan = CampaignPlan(
        campaign_id="c1", product_id="p1", objective=None, phase="AWARENESS", status="tentative",
        date_confidence="rough", start_at=None, end_at=None,
    )
    view = PlanView(as_of=_NOW, business_context_version="v1", active_campaigns=[plan])
    text = render_plan(view, role=_FOUNDER)
    assert "TENTATIVE" in text
