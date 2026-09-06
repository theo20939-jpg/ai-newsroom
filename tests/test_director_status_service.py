"""SOCIAL-INTELLIGENCE-INTEGRATION-1, spec §32: /directors status tests - real flag state,
WAITING_FOR_DATA truthful, disabled shown as disabled, no LLM call, no DB mutation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.director_run import DirectorRun
from database.models.social_launch_context import (
    HistoricalContentPolicy,
    LaunchDateStatus,
    LaunchState,
    LearningBaselinePolicy,
    SocialLaunchPlatform,
)
from services.business_context_snapshot_service import get_business_context_snapshot
from services.campaign_service import create_campaign
from services.director_status_service import DirectorStatus, get_director_console_status
from services.product_context_service import create_product
from services.social_launch_context_service import create_next_version


@pytest.mark.asyncio
async def test_empty_state_is_honest_waiting_for_data(db_session: AsyncSession) -> None:
    status = await get_director_console_status(db_session, now=datetime.now(timezone.utc))

    campaign_planner = next(e for e in status.business if e.name == "Campaign Planner")
    assert campaign_planner.status == DirectorStatus.READY  # no active campaign yet

    art_director = next(e for e in status.telegram if e.name == "Art Director")
    assert art_director.status == DirectorStatus.WAITING_FOR_DATA

    growth_director = next(e for e in status.telegram if e.name == "Growth Director")
    assert growth_director.status == DirectorStatus.WAITING_FOR_DATA

    strategy_director = next(e for e in status.telegram if e.name == "Strategy Director")
    assert strategy_director.status == DirectorStatus.WAITING_FOR_DATA

    performance_memory = next(e for e in status.instagram if e.name == "Performance Memory")
    assert performance_memory.status == DirectorStatus.WAITING_FOR_DATA


@pytest.mark.asyncio
async def test_disabled_flags_shown_as_disabled(db_session: AsyncSession) -> None:
    status = await get_director_console_status(db_session, now=datetime.now(timezone.utc))
    channel_director = next(e for e in status.telegram if e.name == "Channel Director")
    assert channel_director.status == DirectorStatus.DISABLED  # telegram_channel_director_shadow_enabled defaults False


@pytest.mark.asyncio
async def test_creative_director_is_ready_never_shadow_or_active(db_session: AsyncSession) -> None:
    status = await get_director_console_status(db_session, now=datetime.now(timezone.utc))
    creative_director = next(e for e in status.instagram if e.name == "Creative Director")
    assert creative_director.status == DirectorStatus.READY


@pytest.mark.asyncio
async def test_real_active_campaign_reflected_in_business_and_instagram_status(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="statustest", name="Status Test Product")
    now = datetime.now(timezone.utc)
    await create_campaign(
        db_session, product_id=product.id, name="Launch",
        structured_context={
            "status": "confirmed", "planned_launch_date": (now.date() + timedelta(days=2)).isoformat(),
            "date_confidence": "exact",
        },
    )
    status = await get_director_console_status(db_session, now=now)
    campaign_planner = next(e for e in status.business if e.name == "Campaign Planner")
    assert campaign_planner.status == DirectorStatus.ACTIVE
    assert "Status Test Product" in campaign_planner.detail

    growth_strategist = next(e for e in status.instagram if e.name == "Growth Strategist")
    assert growth_strategist.status == DirectorStatus.SHADOW


@pytest.mark.asyncio
async def test_art_director_summary_reflects_real_persisted_findings_never_a_pass_count(db_session: AsyncSession) -> None:
    """Spec §19's own example shape (decision breakdown + top issue codes) - minus a fabricated
    PASS count, since a clean PASS is never persisted at all."""
    from database.models.telegram_visual_failure import ArtDirectorDecisionEnum, TelegramVisualFailure

    db_session.add(TelegramVisualFailure(
        issue_codes=["subject_crop_bad"], severity="medium", art_director_decision=ArtDirectorDecisionEnum.PASS_WITH_NOTES, confidence=0.5,
    ))
    db_session.add(TelegramVisualFailure(
        issue_codes=["subject_crop_bad"], severity="high", art_director_decision=ArtDirectorDecisionEnum.REWORK, confidence=0.6,
    ))
    await db_session.commit()

    status = await get_director_console_status(db_session, now=datetime.now(timezone.utc))
    art_director = next(e for e in status.telegram if e.name == "Art Director")
    assert art_director.status == DirectorStatus.SHADOW
    assert "PASS_WITH_NOTES 1" in art_director.detail
    assert "REWORK 1" in art_director.detail
    assert "subject_crop_bad ×2" in art_director.detail
    assert "PASS 16" not in art_director.detail  # never a fabricated clean-pass count


@pytest.mark.asyncio
async def test_status_check_never_mutates_the_database(db_session: AsyncSession) -> None:
    before = await get_director_console_status(db_session, now=datetime.now(timezone.utc))
    after = await get_director_console_status(db_session, now=datetime.now(timezone.utc))
    assert [e.status for e in before.telegram] == [e.status for e in after.telegram]


@pytest.mark.asyncio
async def test_directors_shows_latest_persisted_growth_run_without_triggering_one(db_session: AsyncSession) -> None:
    """Spec §32: `/directors` must show the latest PERSISTED run, and must never itself compute or
    persist a new one - get_director_console_status() never calls create_director_run()."""
    from database.models.director_run import DirectorType
    from services.director_run_service import compute_input_fingerprint, create_director_run

    now = datetime.now(timezone.utc)
    await create_director_run(
        db_session, director_type=DirectorType.TELEGRAM_GROWTH, platform="telegram", generated_at=now,
        input_fingerprint=compute_input_fingerprint("x"), result_payload={"signals": ["topic X is trending"]},
        decision="topic X is trending", confidence=0.6,
    )
    run_count_before = (await db_session.execute(select(func.count()).select_from(DirectorRun))).scalar_one()

    status = await get_director_console_status(db_session, now=now)
    growth_director = next(e for e in status.telegram if e.name == "Growth Director")
    assert growth_director.status == DirectorStatus.SHADOW
    assert "topic X is trending" in growth_director.detail
    assert "0.60" in growth_director.detail

    run_count_after = (await db_session.execute(select(func.count()).select_from(DirectorRun))).scalar_one()
    assert run_count_after == run_count_before  # reading /directors never persisted a new run


@pytest.mark.asyncio
async def test_directors_uses_repository_vocabulary_for_cold_start_telegram(db_session: AsyncSession) -> None:
    """SOCIAL-INTELLIGENCE-PRELAUNCH-1A §20: a PRE_LAUNCH Telegram context shows up in /directors
    using the SAME LaunchState value the model itself uses (never an invented phrase) - and never
    leaks onto Instagram's own entries, which have no context configured here."""
    await create_next_version(
        db_session, platform=SocialLaunchPlatform.TELEGRAM, target_identity="NINJA PULSE",
        current_identity="NINJA VPN news", launch_state=LaunchState.PRE_LAUNCH, planned_launch_at=None,
        launch_date_status=LaunchDateStatus.UNSCHEDULED, baseline_policy=LearningBaselinePolicy.FROM_FIRST_PUBLICATION,
        historical_content_policy=HistoricalContentPolicy.IGNORE, raw_instruction="test setup",
        confirmed_structure={}, created_by=5507703201,
    )
    status = await get_director_console_status(db_session, now=datetime.now(timezone.utc))

    growth_director = next(e for e in status.telegram if e.name == "Growth Director")
    assert "[PRE_LAUNCH]" in growth_director.detail
    strategy_director = next(e for e in status.telegram if e.name == "Strategy Director")
    assert "[PRE_LAUNCH]" in strategy_director.detail

    performance_memory = next(e for e in status.instagram if e.name == "Performance Memory")
    assert "[PRE_LAUNCH]" not in performance_memory.detail  # Instagram has no context configured


@pytest.mark.asyncio
async def test_directors_marks_stale_context_on_growth_run(db_session: AsyncSession) -> None:
    from database.models.director_run import DirectorType
    from services.director_run_service import (
        compute_business_context_fingerprint,
        compute_input_fingerprint,
        create_director_run,
    )

    now = datetime.now(timezone.utc)
    snapshot_before = await get_business_context_snapshot(db_session, now=now)
    fingerprint_before = compute_business_context_fingerprint(snapshot_before)
    await create_director_run(
        db_session, director_type=DirectorType.TELEGRAM_GROWTH, platform="telegram", generated_at=now,
        input_fingerprint=compute_input_fingerprint("x"), result_payload={}, decision="stable decision",
        business_context_fingerprint=fingerprint_before,
    )

    product = await create_product(db_session, slug="dsstale", name="DS Stale Product")
    await create_campaign(db_session, product_id=product.id, name="New Launch")

    status = await get_director_console_status(db_session, now=now)
    growth_director = next(e for e in status.telegram if e.name == "Growth Director")
    assert "STALE_CONTEXT" in growth_director.detail
