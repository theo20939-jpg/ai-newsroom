"""SOCIAL-INTELLIGENCE-INTEGRATION-1, spec §33-36: /plan, /opportunities, /calendar, /performance
service-level tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_calendar_item import CalendarItemStatus
from database.models.telegram_surface import TelegramSurfaceRole
from services.campaign_service import create_campaign, update_campaign
from services.claim_policy_service import create_claim_policy
from services.director_console_service import (
    build_calendar_view,
    build_opportunities_view,
    build_performance_view,
    build_plan_view,
)
from services.instagram_calendar_service import create_calendar_item
from services.product_context_service import create_product
from services.strategic_directive_service import create_directive
from services.telegram_surface_registry import create_surface


async def _make_confirmed_campaign(db_session: AsyncSession, *, slug: str, days_out: int = 2):
    product = await create_product(db_session, slug=slug, name=f"Product {slug}")
    now = datetime.now(timezone.utc)
    campaign = await create_campaign(
        db_session, product_id=product.id, name=f"{slug} launch",
        structured_context={
            "status": "confirmed", "planned_launch_date": (now.date() + timedelta(days=days_out)).isoformat(),
            "date_confidence": "exact",
        },
    )
    return product, campaign


# ---------------------------------------------------------------------------
# /plan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_view_shows_no_current_advisory_when_nothing_has_executed(db_session: AsyncSession) -> None:
    """SOCIAL-INTELLIGENCE-OPS-1A spec §4: /plan is a pure read - it must never compute an
    advisory itself. With no DirectorRun ever persisted, it must show an honest NO_CURRENT_ADVISORY
    note, never silently generate one."""
    _, campaign = await _make_confirmed_campaign(db_session, slug="plana")
    now = datetime.now(timezone.utc)
    plan = await build_plan_view(db_session, now=now)

    assert plan.telegram_advisory is None
    assert "NO_CURRENT_ADVISORY" in plan.telegram_note
    assert plan.instagram_strategy is None
    assert "NO_CURRENT_ADVISORY" in plan.instagram_note
    assert len(plan.active_campaigns) == 1
    assert plan.active_campaigns[0].campaign_id == str(campaign.id)


@pytest.mark.asyncio
async def test_plan_view_shows_separate_persisted_telegram_and_instagram_advisories(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once a real execution has persisted a run for each platform (director_execution_service.py,
    tested separately), /plan must display them - as genuinely separate objects derived from
    different logic paths, never the same object or a copy of one into the other's shape."""
    from core.config import settings
    from services.director_execution_service import run_instagram_growth_strategist, run_telegram_strategy_director

    monkeypatch.setattr(settings, "director_run_persistence_enabled", True)
    await _make_confirmed_campaign(db_session, slug="planasep")
    now = datetime.now(timezone.utc)
    await run_telegram_strategy_director(db_session, now=now)
    await run_instagram_growth_strategist(db_session, now=now)

    plan = await build_plan_view(db_session, now=now)
    assert plan.telegram_advisory is not None
    assert plan.instagram_strategy is not None
    assert plan.telegram_advisory is not plan.instagram_strategy


@pytest.mark.asyncio
async def test_plan_view_surfaces_founder_directive(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    await create_directive(db_session, instruction="Store пока не продвигаем.", priority=1, valid_from=now, created_by=1)
    plan = await build_plan_view(db_session, now=now)
    assert len(plan.active_directives) == 1
    assert "Store" in plan.active_directives[0].instruction


@pytest.mark.asyncio
async def test_plan_view_surfaces_claim_restriction(db_session: AsyncSession) -> None:
    from database.models.claim_policy import ClaimStatus

    product, _ = await _make_confirmed_campaign(db_session, slug="planb")
    await create_claim_policy(db_session, product_id=product.id, claim_text="exact price", status=ClaimStatus.RESTRICTED)
    plan = await build_plan_view(db_session, now=datetime.now(timezone.utc))
    # Restricted claims are exposed on the opportunity built from the campaign (checked in detail
    # via /opportunities below) - /plan itself just needs to surface the campaign they attach to.
    assert plan.active_campaigns


@pytest.mark.asyncio
async def test_business_context_fingerprint_changes_when_campaign_state_changes(db_session: AsyncSession) -> None:
    """Underlies spec §26/§33's "stale platform plan detected when context version old" - proves
    the fingerprint a cached consumer would compare against actually changes on real state change."""
    _, campaign = await _make_confirmed_campaign(db_session, slug="planc")
    before = await build_plan_view(db_session, now=datetime.now(timezone.utc))
    await update_campaign(db_session, campaign.id, structured_context={"status": "delayed"})
    after = await build_plan_view(db_session, now=datetime.now(timezone.utc))
    assert before.business_context_version != after.business_context_version


@pytest.mark.asyncio
async def test_plan_view_has_no_side_effects(db_session: AsyncSession) -> None:
    await _make_confirmed_campaign(db_session, slug="pland")
    before = await build_plan_view(db_session, now=datetime.now(timezone.utc))
    after = await build_plan_view(db_session, now=datetime.now(timezone.utc))
    assert before.business_context_version == after.business_context_version


# ---------------------------------------------------------------------------
# /opportunities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_opportunity_dimensions_stay_separate(db_session: AsyncSession) -> None:
    await _make_confirmed_campaign(db_session, slug="oppa")
    view = await build_opportunities_view(db_session, now=datetime.now(timezone.utc))
    product_rows = [r for r in view.rows if r.source_type == "product"]
    assert product_rows
    row = product_rows[0]
    assert row.campaign_relevance is not None
    assert row.news_value is None  # never blended into one score


@pytest.mark.asyncio
async def test_opportunity_preserves_product_mention_permission_and_restricted_claims(db_session: AsyncSession) -> None:
    from database.models.claim_policy import ClaimStatus

    product, _ = await _make_confirmed_campaign(db_session, slug="oppb")
    await create_claim_policy(db_session, product_id=product.id, claim_text="exact price", status=ClaimStatus.RESTRICTED)
    view = await build_opportunities_view(db_session, now=datetime.now(timezone.utc))
    row = next(r for r in view.rows if r.source_type == "product")
    assert row.product_mention_allowed is True  # confirmed campaign
    assert "exact price" in row.restricted_claims


@pytest.mark.asyncio
async def test_opportunity_platform_recommendations_are_independent(db_session: AsyncSession) -> None:
    await _make_confirmed_campaign(db_session, slug="oppc")
    view = await build_opportunities_view(db_session, now=datetime.now(timezone.utc))
    row = next(r for r in view.rows if r.source_type == "product")
    assert row.instagram_objective is not None
    assert row.instagram_format is not None
    assert isinstance(row.telegram_note, str) and row.telegram_note


@pytest.mark.asyncio
async def test_opportunities_view_produces_real_hybrid_row(db_session: AsyncSession, real_news_event) -> None:
    """SOCIAL-INTELLIGENCE-OPS-1 spec §20: a Story genuinely relevant to an active campaign
    produces ONE real HYBRID row (not fabricated, not a fake magic score) - and that Story is never
    ALSO shown a second time as a plain NEWS row."""
    from uuid import uuid4

    from database.models.story import Story

    product = await create_product(db_session, slug="hybridtest", name="NINJA AI")
    campaign = await create_campaign(
        db_session, product_id=product.id, name="AI launch",
        structured_context={
            "status": "confirmed", "date_confidence": "exact",
            "key_messages": ["ai coding assistant", "developer productivity"],
        },
    )
    story = Story(
        id=uuid4(), title="New AI coding assistant boosts developer productivity", category=real_news_event.category,
        entities=[], keywords=[], topic_bucket="product", first_event_id=real_news_event.id, event_count=1,
    )
    db_session.add(story)
    await db_session.flush()

    view = await build_opportunities_view(db_session, now=datetime.now(timezone.utc))
    hybrid_rows = [r for r in view.rows if r.source_type == "hybrid"]
    assert len(hybrid_rows) == 1
    assert hybrid_rows[0].campaign_relevance is not None
    assert hybrid_rows[0].news_value is not None
    # never shown a second time as a plain NEWS row
    assert not any(r.source_type == "news" and r.topic == story.title for r in view.rows)
    assert not any(r.source_type == "product" and r.topic == f"campaign:{campaign.id}" for r in view.rows)


@pytest.mark.asyncio
async def test_no_campaign_no_story_notes_are_honest(db_session: AsyncSession) -> None:
    view = await build_opportunities_view(db_session, now=datetime.now(timezone.utc))
    assert view.rows == []
    assert any("PRODUCT" in n for n in view.notes)
    assert any("NEWS" in n for n in view.notes)
    assert any("TREND" in n for n in view.notes)
    assert any("HYBRID" in n for n in view.notes)


# ---------------------------------------------------------------------------
# /calendar
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_calendar_shows_active_item(db_session: AsyncSession) -> None:
    item = await create_calendar_item(
        db_session, planned_at=datetime.now(timezone.utc), objective="reach", format="reel",
    )
    view = await build_calendar_view(db_session, now=datetime.now(timezone.utc))
    row = next(r for r in view.rows if r.platform == "instagram")
    assert row.status == CalendarItemStatus.ACTIVE
    assert row.planned_at == item.planned_at


@pytest.mark.asyncio
async def test_calendar_detects_stale_context_after_delay_not_yet_invalidated(db_session: AsyncSession) -> None:
    _, campaign = await _make_confirmed_campaign(db_session, slug="cala")
    await create_calendar_item(
        db_session, planned_at=datetime.now(timezone.utc), objective="reach", format="reel", campaign_id=campaign.id,
        depends_on_campaign_phase="LAUNCH", planned_against_campaign_status="confirmed", planned_against_campaign_phase="LAUNCH",
    )
    await update_campaign(db_session, campaign.id, structured_context={"status": "delayed"})
    view = await build_calendar_view(db_session, now=datetime.now(timezone.utc))
    row = next(r for r in view.rows if r.campaign_id == str(campaign.id))
    assert row.status == CalendarItemStatus.ACTIVE  # invalidation service never ran
    assert row.context_stale is True  # but the console still detects the drift


@pytest.mark.asyncio
async def test_calendar_shows_delay_invalidation_after_service_runs(db_session: AsyncSession) -> None:
    from services.instagram_calendar_service import invalidate_items_for_campaign_change
    from database.models.campaign import CampaignStatus

    _, campaign = await _make_confirmed_campaign(db_session, slug="calb")
    await create_calendar_item(
        db_session, planned_at=datetime.now(timezone.utc), objective="reach", format="reel", campaign_id=campaign.id,
        depends_on_campaign_phase="LAUNCH", planned_against_campaign_status="confirmed", planned_against_campaign_phase="LAUNCH",
    )
    await invalidate_items_for_campaign_change(
        db_session, campaign_id=campaign.id, new_status=CampaignStatus.DELAYED, new_phase="AWARENESS", reason="delayed",
    )
    view = await build_calendar_view(db_session, now=datetime.now(timezone.utc))
    row = next(r for r in view.rows if r.campaign_id == str(campaign.id))
    assert row.status == CalendarItemStatus.INVALIDATED
    assert row.context_stale is False  # already invalidated - not double-flagged


@pytest.mark.asyncio
async def test_calendar_shows_cancel_invalidation(db_session: AsyncSession) -> None:
    from services.instagram_calendar_service import invalidate_items_for_campaign_change
    from database.models.campaign import CampaignStatus

    _, campaign = await _make_confirmed_campaign(db_session, slug="calc")
    await create_calendar_item(
        db_session, planned_at=datetime.now(timezone.utc), objective="product_click", format="single", campaign_id=campaign.id,
        depends_on_campaign_phase="LAUNCH", planned_against_campaign_status="confirmed", planned_against_campaign_phase="LAUNCH",
    )
    await update_campaign(db_session, campaign.id, structured_context={"status": "cancelled"})
    await invalidate_items_for_campaign_change(
        db_session, campaign_id=campaign.id, new_status=CampaignStatus.CANCELLED, new_phase=None, reason="campaign cancelled",
    )
    view = await build_calendar_view(db_session, now=datetime.now(timezone.utc))
    row = next(r for r in view.rows if r.campaign_id == str(campaign.id))
    assert row.status == CalendarItemStatus.INVALIDATED


@pytest.mark.asyncio
async def test_calendar_shows_rescheduled_item(db_session: AsyncSession) -> None:
    from services.instagram_calendar_service import reschedule_calendar_item

    item = await create_calendar_item(db_session, planned_at=datetime.now(timezone.utc), objective="reach", format="reel")
    new_time = datetime.now(timezone.utc) + timedelta(days=5)
    await reschedule_calendar_item(db_session, item.id, new_planned_at=new_time, reason="moved to confirmed date")
    view = await build_calendar_view(db_session, now=datetime.now(timezone.utc))
    row = next(r for r in view.rows if r.planned_at == new_time)
    assert row.status == CalendarItemStatus.RESCHEDULED


@pytest.mark.asyncio
async def test_calendar_platform_filter(db_session: AsyncSession) -> None:
    await create_calendar_item(db_session, planned_at=datetime.now(timezone.utc), objective="reach", format="reel")
    view = await build_calendar_view(db_session, now=datetime.now(timezone.utc), platform="telegram")
    assert view.rows == []
    assert any("Telegram" in n for n in view.notes)


@pytest.mark.asyncio
async def test_calendar_shows_real_telegram_item(db_session: AsyncSession) -> None:
    """Spec §28: /calendar must show real Telegram entries when present - no fabricated platform
    parity, and no more "not implemented" placeholder note once a real item exists."""
    from database.models.telegram_content_calendar_item import TelegramCalendarItemStatus, TelegramContentRole
    from services.telegram_calendar_service import create_calendar_item as create_telegram_calendar_item

    item = await create_telegram_calendar_item(
        db_session, planned_at=datetime.now(timezone.utc), objective="reach", content_role=TelegramContentRole.NEWS,
        presentation_hint="digest",
    )
    view = await build_calendar_view(db_session, now=datetime.now(timezone.utc), platform="telegram")
    row = next(r for r in view.rows if r.platform == "telegram")
    assert row.status == TelegramCalendarItemStatus.ACTIVE.value
    assert row.planned_at == item.planned_at
    assert row.concept == "digest"
    assert not any("не реализован" in n for n in view.notes)


@pytest.mark.asyncio
async def test_calendar_shows_both_platforms_without_filter(db_session: AsyncSession) -> None:
    from database.models.telegram_content_calendar_item import TelegramContentRole
    from services.telegram_calendar_service import create_calendar_item as create_telegram_calendar_item

    await create_calendar_item(db_session, planned_at=datetime.now(timezone.utc), objective="reach", format="reel")
    await create_telegram_calendar_item(
        db_session, planned_at=datetime.now(timezone.utc), objective="reach", content_role=TelegramContentRole.NEWS,
    )
    view = await build_calendar_view(db_session, now=datetime.now(timezone.utc))
    platforms = {r.platform for r in view.rows}
    assert platforms == {"instagram", "telegram"}


@pytest.mark.asyncio
async def test_calendar_detects_telegram_stale_context(db_session: AsyncSession) -> None:
    from services.telegram_calendar_service import create_calendar_item as create_telegram_calendar_item
    from database.models.telegram_content_calendar_item import TelegramContentRole

    _, campaign = await _make_confirmed_campaign(db_session, slug="tgcalstale")
    await create_telegram_calendar_item(
        db_session, planned_at=datetime.now(timezone.utc), objective="product_click",
        content_role=TelegramContentRole.CAMPAIGN, campaign_id=campaign.id, depends_on_campaign_phase="LAUNCH",
        planned_against_campaign_status="confirmed", planned_against_campaign_phase="LAUNCH",
    )
    await update_campaign(db_session, campaign.id, structured_context={"status": "delayed"})
    view = await build_calendar_view(db_session, now=datetime.now(timezone.utc))
    row = next(r for r in view.rows if r.platform == "telegram" and r.campaign_id == str(campaign.id))
    assert row.context_stale is True


@pytest.mark.asyncio
async def test_calendar_view_is_read_only(db_session: AsyncSession) -> None:
    item = await create_calendar_item(db_session, planned_at=datetime.now(timezone.utc), objective="reach", format="reel")
    await build_calendar_view(db_session, now=datetime.now(timezone.utc))
    from services.instagram_calendar_service import list_calendar_items
    refreshed = await list_calendar_items(db_session)
    assert next(i for i in refreshed if i.id == item.id).status == CalendarItemStatus.ACTIVE


# ---------------------------------------------------------------------------
# /performance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_performance_internal_channel_not_shown_as_public(db_session: AsyncSession) -> None:
    view = await build_performance_view(db_session, now=datetime.now(timezone.utc))
    assert view.telegram_status == "PUBLIC_CHANNEL_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_performance_accepts_configured_public_surface(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "telegram_owned_channel_id", -1009999999999)
    await create_surface(
        db_session, chat_id=-1009999999999, role=TelegramSurfaceRole.PUBLIC_NEWS_CHANNEL,
        name="NINJA PULSE", analytics_enabled=True, active=True,
    )
    view = await build_performance_view(db_session, now=datetime.now(timezone.utc))
    assert view.telegram_status != "PUBLIC_CHANNEL_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_performance_instagram_is_honest_no_data(db_session: AsyncSession) -> None:
    view = await build_performance_view(db_session, now=datetime.now(timezone.utc))
    assert view.instagram_status == "NO_FIRST_PARTY_DATA"


@pytest.mark.asyncio
async def test_performance_shows_real_evidence_rows_without_ever_persisting_a_run(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SOCIAL-INTELLIGENCE-OPS-1A spec §5: /performance renders real aggregated evidence (not a
    hardcoded placeholder) via the pure, side-effect-free aggregator - but must NEVER persist a
    DirectorRun itself, even with the persistence flag on (that belongs exclusively to
    services/director_execution_service.py::run_telegram_growth_director())."""
    from uuid import uuid4

    from core.config import settings
    from database.models.director_run import DirectorRun, DirectorType
    from database.models.telegram_channel_memory import TelegramChannelMemory
    from database.models.telegram_post_performance import SnapshotWindow, TelegramPostPerformanceSnapshot
    from services.director_run_service import get_latest_run

    monkeypatch.setattr(settings, "telegram_owned_channel_id", -1009999999999)
    monkeypatch.setattr(settings, "director_run_persistence_enabled", True)
    await create_surface(
        db_session, chat_id=-1009999999999, role=TelegramSurfaceRole.PUBLIC_NEWS_CHANNEL,
        name="NINJA PULSE", analytics_enabled=True, active=True,
    )
    now = datetime.now(timezone.utc)
    for i in range(3):
        memory = TelegramChannelMemory(published_at=now - timedelta(days=1, hours=i), category="news")
        db_session.add(memory)
        await db_session.flush()
        db_session.add(TelegramPostPerformanceSnapshot(
            id=uuid4(), channel_memory_id=memory.id, telegram_message_id=None, window=SnapshotWindow.H24,
            captured_at=now - timedelta(hours=i), age_seconds=86400, views=5000 + i * 100,
            capability_version="v", collector="test",
        ))
    await db_session.commit()

    run_count_before = (await db_session.execute(select(func.count()).select_from(DirectorRun))).scalar_one()
    view = await build_performance_view(db_session, now=now)
    run_count_after = (await db_session.execute(select(func.count()).select_from(DirectorRun))).scalar_one()

    assert view.telegram_status == "OK"
    assert view.telegram_evidence  # real pattern rows, not an empty placeholder
    assert run_count_after == run_count_before  # zero DirectorRun rows written by a read
    assert await get_latest_run(db_session, DirectorType.TELEGRAM_GROWTH) is None


@pytest.mark.asyncio
async def test_plan_never_persists_a_director_run(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SOCIAL-INTELLIGENCE-OPS-1A spec §1/§4: /plan must never persist a DirectorRun, even with
    the persistence flag on - it is a pure read of already-persisted state."""
    from core.config import settings
    from database.models.director_run import DirectorRun, DirectorType
    from services.director_run_service import get_latest_run

    monkeypatch.setattr(settings, "director_run_persistence_enabled", True)
    await _make_confirmed_campaign(db_session, slug="planrun")
    now = datetime.now(timezone.utc)

    run_count_before = (await db_session.execute(select(func.count()).select_from(DirectorRun))).scalar_one()
    await build_plan_view(db_session, now=now)
    run_count_after = (await db_session.execute(select(func.count()).select_from(DirectorRun))).scalar_one()

    assert run_count_after == run_count_before
    assert await get_latest_run(db_session, DirectorType.TELEGRAM_STRATEGY) is None
    assert await get_latest_run(db_session, DirectorType.INSTAGRAM_GROWTH) is None


# ---------------------------------------------------------------------------
# SOCIAL-INTELLIGENCE-OPS-1A spec §15: read-purity contract for every console read command -
# DB row counts across every table a read command could plausibly write to must be identical
# before and after the call.
# ---------------------------------------------------------------------------


async def _domain_row_counts(db_session: AsyncSession) -> dict[str, int]:
    from database.models.campaign import LaunchCampaign
    from database.models.director_run import DirectorRun
    from database.models.instagram_calendar_item import InstagramContentCalendarItem
    from database.models.strategic_directive import StrategicDirective
    from database.models.telegram_content_calendar_item import TelegramContentCalendarItem

    tables = {
        "director_run": DirectorRun, "instagram_calendar_item": InstagramContentCalendarItem,
        "telegram_calendar_item": TelegramContentCalendarItem, "launch_campaign": LaunchCampaign,
        "strategic_directive": StrategicDirective,
    }
    return {
        name: (await db_session.execute(select(func.count()).select_from(model))).scalar_one()
        for name, model in tables.items()
    }


@pytest.mark.asyncio
async def test_plan_view_is_fully_read_pure(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "director_run_persistence_enabled", True)
    await _make_confirmed_campaign(db_session, slug="purityplan")
    before = await _domain_row_counts(db_session)
    await build_plan_view(db_session, now=datetime.now(timezone.utc))
    assert await _domain_row_counts(db_session) == before


@pytest.mark.asyncio
async def test_opportunities_view_is_fully_read_pure(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "director_run_persistence_enabled", True)
    await _make_confirmed_campaign(db_session, slug="purityopp")
    before = await _domain_row_counts(db_session)
    await build_opportunities_view(db_session, now=datetime.now(timezone.utc))
    assert await _domain_row_counts(db_session) == before


@pytest.mark.asyncio
async def test_calendar_view_is_fully_read_pure(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "director_run_persistence_enabled", True)
    await create_calendar_item(db_session, planned_at=datetime.now(timezone.utc), objective="reach", format="reel")
    before = await _domain_row_counts(db_session)
    await build_calendar_view(db_session, now=datetime.now(timezone.utc))
    assert await _domain_row_counts(db_session) == before


@pytest.mark.asyncio
async def test_performance_view_is_fully_read_pure(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "director_run_persistence_enabled", True)
    monkeypatch.setattr(settings, "telegram_owned_channel_id", -1007778889990)
    await create_surface(
        db_session, chat_id=-1007778889990, role=TelegramSurfaceRole.PUBLIC_NEWS_CHANNEL,
        name="Purity Channel", analytics_enabled=True, active=True,
    )
    before = await _domain_row_counts(db_session)
    await build_performance_view(db_session, now=datetime.now(timezone.utc))
    assert await _domain_row_counts(db_session) == before


@pytest.mark.asyncio
async def test_performance_view_surfaces_stale_context_on_persisted_growth_run(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SOCIAL-INTELLIGENCE-OPS-1A spec §9: staleness must be preserved, never hidden by a read
    command - /performance's `telegram_last_run_summary` must carry the same STALE_CONTEXT marker
    /directors already shows, sourced from the same shared describe_latest_run()."""
    from core.config import settings
    from database.models.director_run import DirectorType
    from services.director_run_service import create_director_run

    now = datetime.now(timezone.utc)
    await create_director_run(
        db_session, director_type=DirectorType.TELEGRAM_GROWTH, platform="telegram", generated_at=now,
        input_fingerprint="f", result_payload={}, decision="stale decision",
        business_context_fingerprint="some-old-fingerprint",
    )
    monkeypatch.setattr(settings, "telegram_owned_channel_id", -1006665554443)
    await create_surface(
        db_session, chat_id=-1006665554443, role=TelegramSurfaceRole.PUBLIC_NEWS_CHANNEL,
        name="Stale Channel", analytics_enabled=True, active=True,
    )
    view = await build_performance_view(db_session, now=now)
    assert view.telegram_last_run_summary is not None
    assert "STALE_CONTEXT" in view.telegram_last_run_summary
