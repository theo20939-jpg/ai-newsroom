"""SOCIAL-INTELLIGENCE-OPS-1A, spec §16/§17: DirectorExecutionService tests - real execution
persists a DirectorRun only when explicitly enabled, unknown AI cost stays null (never a fabricated
0), a deterministic execution never fabricates provider metadata, and the same console reads a
persisted run back without ever modifying it."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.director_run import DirectorRun, DirectorType
from database.models.telegram_channel_memory import TelegramChannelMemory
from database.models.telegram_post_performance import SnapshotWindow, TelegramPostPerformanceSnapshot
from database.models.telegram_surface import TelegramSurfaceRole
from services.campaign_service import create_campaign
from services.director_execution_service import (
    run_instagram_growth_strategist,
    run_telegram_growth_director,
    run_telegram_strategy_director,
)
from services.director_run_service import get_latest_run
from services.product_context_service import create_product
from services.telegram_surface_registry import create_surface


async def _make_confirmed_campaign(db_session: AsyncSession, *, slug: str):
    product = await create_product(db_session, slug=slug, name=f"Product {slug}")
    now = datetime.now(timezone.utc)
    campaign = await create_campaign(
        db_session, product_id=product.id, name=f"{slug} launch",
        structured_context={
            "status": "confirmed", "planned_launch_date": (now.date() + timedelta(days=2)).isoformat(),
            "date_confidence": "exact",
        },
    )
    return product, campaign


@pytest.mark.asyncio
async def test_telegram_strategy_execution_computes_but_does_not_persist_when_flag_off(
    db_session: AsyncSession,
) -> None:
    result = await run_telegram_strategy_director(db_session, now=datetime.now(timezone.utc))
    assert result.advisory is not None  # computation always runs
    assert result.run is None  # persistence disabled by default
    assert await get_latest_run(db_session, DirectorType.TELEGRAM_STRATEGY) is None


@pytest.mark.asyncio
async def test_telegram_strategy_execution_persists_when_enabled(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "director_run_persistence_enabled", True)
    await _make_confirmed_campaign(db_session, slug="exectg")
    result = await run_telegram_strategy_director(db_session, now=datetime.now(timezone.utc))
    assert result.run is not None
    assert result.run.director_type == DirectorType.TELEGRAM_STRATEGY
    assert result.run.business_context_fingerprint is not None
    # Deterministic execution - no real LLM call was ever made, so provider metadata and cost
    # must stay null, never a fabricated "0.0" that would look like a known, free run.
    assert result.run.model_provider is None
    assert result.run.model_name is None
    assert result.run.cost_usd is None

    latest = await get_latest_run(db_session, DirectorType.TELEGRAM_STRATEGY)
    assert latest is not None
    assert latest.id == result.run.id


@pytest.mark.asyncio
async def test_instagram_growth_execution_persists_real_active_campaign_context(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "director_run_persistence_enabled", True)
    await _make_confirmed_campaign(db_session, slug="execig")
    result = await run_instagram_growth_strategist(db_session, now=datetime.now(timezone.utc))
    assert result.run is not None
    assert result.run.status.value == "ok"
    assert result.run.confidence == result.strategy.confidence
    assert result.run.model_provider is None
    assert result.run.cost_usd is None


@pytest.mark.asyncio
async def test_instagram_growth_execution_waiting_for_data_with_no_campaigns(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "director_run_persistence_enabled", True)
    result = await run_instagram_growth_strategist(db_session, now=datetime.now(timezone.utc))
    assert result.run is not None
    assert result.run.status.value == "waiting_for_data"


@pytest.mark.asyncio
async def test_telegram_growth_execution_returns_no_advisory_without_real_evidence(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No public analytics surface, no channel memory - nothing to advise on. Never a fabricated
    advisory over absent evidence, and never a persisted run either."""
    from core.config import settings

    monkeypatch.setattr(settings, "director_run_persistence_enabled", True)
    result = await run_telegram_growth_director(db_session, now=datetime.now(timezone.utc))
    assert result.advisory is None
    assert result.run is None
    assert result.aggregate_status == "PUBLIC_CHANNEL_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_telegram_growth_execution_persists_real_evidence(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "telegram_owned_channel_id", -1004443332221)
    monkeypatch.setattr(settings, "director_run_persistence_enabled", True)
    await create_surface(
        db_session, chat_id=-1004443332221, role=TelegramSurfaceRole.PUBLIC_NEWS_CHANNEL,
        name="Exec Channel", analytics_enabled=True, active=True,
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

    result = await run_telegram_growth_director(db_session, now=now)
    assert result.advisory is not None
    assert result.run is not None
    assert result.run.director_type == DirectorType.TELEGRAM_GROWTH
    assert result.run.evidence_stage is not None


@pytest.mark.asyncio
async def test_repeated_execution_creates_a_new_run_each_time_not_collapsed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec §8: distinct time-based observations are never collapsed into one row, even for
    identical inputs - each real execution call is its own independent DirectorRun."""
    from core.config import settings

    monkeypatch.setattr(settings, "director_run_persistence_enabled", True)
    await _make_confirmed_campaign(db_session, slug="execidem")
    now = datetime.now(timezone.utc)
    first = await run_telegram_strategy_director(db_session, now=now)
    second = await run_telegram_strategy_director(db_session, now=now)
    assert first.run is not None and second.run is not None
    assert first.run.id != second.run.id

    count = (await db_session.execute(
        select(func.count()).select_from(DirectorRun).where(DirectorRun.director_type == DirectorType.TELEGRAM_STRATEGY)
    )).scalar_one()
    assert count == 2
