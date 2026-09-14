"""INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1 §8/§12/§15: durable publication state, deterministic
idempotency, and DB-level concurrency safety - against the real, isolated test DB (migration
`d7e4a92f1b83`), mirroring `tests/test_unified_pipeline_recovery_concurrency_and_platform_scoping.py`'s
own established pattern exactly."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_publication_job import InstagramPublicationJob, InstagramPublicationState
from services.instagram_publication_state import InstagramPublicationStateService, compute_idempotency_key

pytestmark = pytest.mark.asyncio


def test_idempotency_key_is_deterministic_never_based_on_random_package_id() -> None:
    key_a = compute_idempotency_key(platform="instagram", package_identity="story-42", content_format="single", schema_version="v1")
    key_b = compute_idempotency_key(platform="instagram", package_identity="story-42", content_format="single", schema_version="v1")
    assert key_a == key_b  # same logical identity -> same key, regardless of how many times a
    # package is independently rebuilt (each build gets its own random package_id, but that is
    # never an input to this function)


def test_idempotency_key_differs_for_different_stories_or_formats() -> None:
    base = compute_idempotency_key(platform="instagram", package_identity="story-1", content_format="single", schema_version="v1")
    different_story = compute_idempotency_key(platform="instagram", package_identity="story-2", content_format="single", schema_version="v1")
    different_format = compute_idempotency_key(platform="instagram", package_identity="story-1", content_format="carousel", schema_version="v1")
    assert base != different_story
    assert base != different_format


async def test_get_or_create_returns_the_same_open_row_on_retry(db_session: AsyncSession) -> None:
    service = InstagramPublicationStateService()
    key = compute_idempotency_key(platform="instagram", package_identity="story-retry", content_format="single", schema_version="v1")

    first = await service.get_or_create(db_session, idempotency_key=key, package_id="pkg-a", package_identity="story-retry", content_format="single")
    second = await service.get_or_create(db_session, idempotency_key=key, package_id="pkg-b", package_identity="story-retry", content_format="single")

    assert first.id == second.id  # a retry converges onto the SAME durable row, never a duplicate
    assert first.state == InstagramPublicationState.NOT_ATTEMPTED


async def test_transition_updates_state_and_records_media_id(db_session: AsyncSession) -> None:
    service = InstagramPublicationStateService()
    key = compute_idempotency_key(platform="instagram", package_identity="story-pub", content_format="single", schema_version="v1")
    job = await service.get_or_create(db_session, idempotency_key=key, package_id="pkg-c", package_identity="story-pub", content_format="single")

    job = await service.transition(db_session, job=job, state=InstagramPublicationState.CREATING_CONTAINER, increment_attempt=True)
    assert job.attempt_count == 1
    job = await service.transition(db_session, job=job, state=InstagramPublicationState.PUBLISHED, media_id="17999999999", permalink="https://instagram.com/p/xyz/")
    assert job.state == InstagramPublicationState.PUBLISHED
    assert job.media_id == "17999999999"
    assert job.resolved_at is not None


async def test_no_duplicate_open_row_for_the_same_identity_under_a_simulated_race(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mirrors the real Telegram recovery concurrency test exactly: `find_open_job` is patched to
    report "nothing open" on its first call only (simulating the real race window), and the real
    partial unique index (`ix_instagram_publication_jobs_open_identity`) is what actually prevents
    the duplicate - not the Python-level check alone."""
    service = InstagramPublicationStateService()
    key = compute_idempotency_key(platform="instagram", package_identity="story-race", content_format="single", schema_version="v1")

    winner = InstagramPublicationJob(
        id=uuid.uuid4(), idempotency_key=key, package_id="pkg-winner", package_identity="story-race",
        content_format="single", account_key="default", state=InstagramPublicationState.NOT_ATTEMPTED, attempt_count=0,
    )
    db_session.add(winner)
    await db_session.flush()

    real_find_open_job = InstagramPublicationStateService.find_open_job
    call_count = {"n": 0}

    async def _patched(self, session, *, idempotency_key):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return None
        return await real_find_open_job(self, session, idempotency_key=idempotency_key)

    monkeypatch.setattr(InstagramPublicationStateService, "find_open_job", _patched)

    result = await service.get_or_create(db_session, idempotency_key=key, package_id="pkg-loser", package_identity="story-race", content_format="single")
    assert result.id == winner.id  # converged onto the winner, never a second open row

    from sqlalchemy import select

    rows = (await db_session.execute(
        select(InstagramPublicationJob).where(InstagramPublicationJob.idempotency_key == key)
    )).scalars().all()
    open_rows = [r for r in rows if r.state in (
        InstagramPublicationState.NOT_ATTEMPTED, InstagramPublicationState.CREATING_CONTAINER,
        InstagramPublicationState.CONTAINER_CREATED, InstagramPublicationState.PUBLISHING, InstagramPublicationState.AMBIGUOUS,
    )]
    assert len(open_rows) == 1
