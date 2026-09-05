"""SOCIAL-INTELLIGENCE-OPS-1, spec §61: DirectorRun persistence + staleness tests - creation,
"latest run" retrieval never computes anything, campaign-context staleness, business-context
fingerprint staleness, and idempotent mark_stale()."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.director_run import DirectorRunStatus, DirectorType
from services.business_context_snapshot_service import get_business_context_snapshot
from services.campaign_service import create_campaign, update_campaign
from services.director_run_service import (
    compute_business_context_fingerprint,
    compute_input_fingerprint,
    create_director_run,
    get_latest_run,
    is_run_context_stale,
    mark_stale,
)
from services.product_context_service import create_product


@pytest.mark.asyncio
async def test_create_and_get_latest_run(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    run = await create_director_run(
        db_session, director_type=DirectorType.TELEGRAM_STRATEGY, platform="telegram", generated_at=now,
        input_fingerprint=compute_input_fingerprint("a", "b"), result_payload={"priority_themes": ["ai"]},
    )
    latest = await get_latest_run(db_session, DirectorType.TELEGRAM_STRATEGY)
    assert latest is not None
    assert latest.id == run.id
    assert latest.result_payload == {"priority_themes": ["ai"]}


@pytest.mark.asyncio
async def test_get_latest_run_returns_none_when_absent(db_session: AsyncSession) -> None:
    latest = await get_latest_run(db_session, DirectorType.INSTAGRAM_CREATIVE)
    assert latest is None


@pytest.mark.asyncio
async def test_get_latest_run_picks_most_recent(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    older = await create_director_run(
        db_session, director_type=DirectorType.TELEGRAM_GROWTH, platform="telegram",
        generated_at=now - timedelta(hours=1), input_fingerprint="f1", result_payload={"n": 1},
    )
    newer = await create_director_run(
        db_session, director_type=DirectorType.TELEGRAM_GROWTH, platform="telegram",
        generated_at=now, input_fingerprint="f2", result_payload={"n": 2},
    )
    latest = await get_latest_run(db_session, DirectorType.TELEGRAM_GROWTH)
    assert latest is not None
    assert latest.id == newer.id
    assert latest.id != older.id


@pytest.mark.asyncio
async def test_input_fingerprint_deterministic_for_same_inputs() -> None:
    assert compute_input_fingerprint("a", 1, ["x"]) == compute_input_fingerprint("a", 1, ["x"])
    assert compute_input_fingerprint("a", 1) != compute_input_fingerprint("a", 2)


@pytest.mark.asyncio
async def test_business_context_fingerprint_changes_when_campaign_status_changes(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="drfp", name="DR Fingerprint Product")
    campaign = await create_campaign(
        db_session, product_id=product.id, name="Launch",
        structured_context={"status": "confirmed", "planned_launch_date": (datetime.now(timezone.utc).date()).isoformat(), "date_confidence": "exact"},
    )
    now = datetime.now(timezone.utc)
    before = compute_business_context_fingerprint(await get_business_context_snapshot(db_session, now=now))

    await update_campaign(db_session, campaign.id, structured_context={"status": "delayed"})
    after = compute_business_context_fingerprint(await get_business_context_snapshot(db_session, now=now))
    assert before != after


@pytest.mark.asyncio
async def test_run_is_stale_when_campaign_status_drifts(db_session: AsyncSession) -> None:
    product = await create_product(db_session, slug="drstale", name="DR Stale Product")
    campaign = await create_campaign(
        db_session, product_id=product.id, name="Launch",
        structured_context={"status": "confirmed", "planned_launch_date": (datetime.now(timezone.utc).date()).isoformat(), "date_confidence": "exact"},
    )
    now = datetime.now(timezone.utc)
    run = await create_director_run(
        db_session, director_type=DirectorType.CAMPAIGN_DIRECTOR, platform="cross_platform", generated_at=now,
        input_fingerprint="f", result_payload={}, campaign_id=campaign.id, campaign_status_at_run="confirmed",
    )
    assert await is_run_context_stale(db_session, run, now=now) is False

    await update_campaign(db_session, campaign.id, structured_context={"status": "delayed"})
    assert await is_run_context_stale(db_session, run, now=now) is True


@pytest.mark.asyncio
async def test_run_is_stale_when_business_context_fingerprint_drifts(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    snapshot = await get_business_context_snapshot(db_session, now=now)
    fingerprint = compute_business_context_fingerprint(snapshot)
    run = await create_director_run(
        db_session, director_type=DirectorType.TELEGRAM_STRATEGY, platform="telegram", generated_at=now,
        input_fingerprint="f", result_payload={}, business_context_fingerprint=fingerprint,
    )
    assert await is_run_context_stale(db_session, run, now=now, current_business_context_fingerprint=fingerprint) is False
    assert await is_run_context_stale(db_session, run, now=now, current_business_context_fingerprint="different") is True


@pytest.mark.asyncio
async def test_mark_stale_is_idempotent(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    run = await create_director_run(
        db_session, director_type=DirectorType.TELEGRAM_GROWTH, platform="telegram", generated_at=now,
        input_fingerprint="f", result_payload={}, status=DirectorRunStatus.OK,
    )
    first = await mark_stale(db_session, run.id, reason="context moved")
    assert first.stale_at is not None
    first_stale_at = first.stale_at
    second = await mark_stale(db_session, run.id, reason="context moved again")
    assert second.stale_at == first_stale_at
    assert second.stale_reason == "context moved"  # original reason preserved, never overwritten
