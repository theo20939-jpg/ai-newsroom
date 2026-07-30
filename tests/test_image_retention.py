"""Tests for services.image_retention's Phase 16 M5 retention/cleanup (docs/
phase16_m5_persistence_and_retention_report.md §14-15). Uses the same `independent_session_factory`
pattern as tests/test_content_worker_cycle.py - `run_retention_cleanup` opens its own sessions via
a session_factory, which the db_session fixture's single rolled-back transaction cannot satisfy;
rows are genuinely committed here and deleted in each test's own teardown.
"""
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from database.models.image_candidate_record import ImageCandidateRecord, ImageStorageStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from integrations.storage.image_storage import LocalImageStorage
from services import image_retention
from tests.test_triage_orchestrator_claims import independent_session_factory

_DATA = b"fake-stored-bytes-for-retention-tests"
_SHA256 = hashlib.sha256(_DATA).hexdigest()


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    monkeypatch.setattr(image_retention, "_storage_singleton", None)
    yield
    monkeypatch.setattr(image_retention, "_storage_singleton", None)


@pytest_asyncio.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine, session_factory = independent_session_factory()
    try:
        yield session_factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def real_event(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[NewsEvent]:
    async with factory() as session:
        source = NewsSource(name=f"retention-test-{uuid.uuid4()}", type=SourceType.RSS, active=True)
        session.add(source)
        await session.flush()
        event = NewsEvent(
            source_id=source.id, title="Retention test event", content="c",
            category=EventCategory.AI, hash=f"retention-hash-{uuid.uuid4()}",
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
    try:
        yield event
    finally:
        async with factory() as session:
            await session.execute(delete(ImageCandidateRecord).where(ImageCandidateRecord.news_event_id == event.id))
            await session.execute(delete(NewsEvent).where(NewsEvent.id == event.id))
            await session.execute(delete(NewsSource).where(NewsSource.id == event.source_id))
            await session.commit()


async def _insert_row(
    factory: async_sessionmaker[AsyncSession],
    event: NewsEvent,
    *,
    candidate_id: str,
    storage_status: ImageStorageStatus = ImageStorageStatus.NOT_REQUESTED,
    storage_key: str | None = None,
    bytes_expire_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> uuid.UUID:
    async with factory() as session:
        row = ImageCandidateRecord(
            candidate_id=candidate_id, news_event_id=event.id, source_type=SourceType.RSS,
            discovery_method="open_graph_image", eligible_for_editorial=False,
            storage_status=storage_status, storage_key=storage_key,
            bytes_expire_at=bytes_expire_at, expires_at=expires_at,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


async def _get_row(factory: async_sessionmaker[AsyncSession], row_id: uuid.UUID) -> ImageCandidateRecord | None:
    async with factory() as session:
        return (await session.execute(select(ImageCandidateRecord).where(ImageCandidateRecord.id == row_id))).scalar_one_or_none()


@pytest.mark.asyncio
async def test_expire_stored_bytes_deletes_file_and_marks_expired(
    factory: async_sessionmaker[AsyncSession], real_event: NewsEvent,
) -> None:
    storage = LocalImageStorage(settings.image_storage_root)
    stored = storage.store_validated_image(_DATA, sha256=_SHA256, image_format="JPEG", max_bytes=10_000)
    now = datetime.now(timezone.utc)
    row_id = await _insert_row(
        factory, real_event, candidate_id="stale-bytes", storage_status=ImageStorageStatus.STORED,
        storage_key=stored.storage_key, bytes_expire_at=now - timedelta(days=1),
    )

    async with factory() as session:
        count = await image_retention.expire_stored_bytes(session, now=now)
        await session.commit()

    assert count == 1
    assert not storage.exists(stored.storage_key)
    row = await _get_row(factory, row_id)
    assert row.storage_status == ImageStorageStatus.EXPIRED


@pytest.mark.asyncio
async def test_expire_stored_bytes_ignores_bytes_not_yet_due(
    factory: async_sessionmaker[AsyncSession], real_event: NewsEvent,
) -> None:
    storage = LocalImageStorage(settings.image_storage_root)
    stored = storage.store_validated_image(_DATA, sha256=_SHA256, image_format="JPEG", max_bytes=10_000)
    now = datetime.now(timezone.utc)
    row_id = await _insert_row(
        factory, real_event, candidate_id="fresh-bytes", storage_status=ImageStorageStatus.STORED,
        storage_key=stored.storage_key, bytes_expire_at=now + timedelta(days=6),
    )

    async with factory() as session:
        count = await image_retention.expire_stored_bytes(session, now=now)
        await session.commit()

    assert count == 0
    assert storage.exists(stored.storage_key)
    row = await _get_row(factory, row_id)
    assert row.storage_status == ImageStorageStatus.STORED


@pytest.mark.asyncio
async def test_delete_expired_metadata_removes_row(
    factory: async_sessionmaker[AsyncSession], real_event: NewsEvent,
) -> None:
    now = datetime.now(timezone.utc)
    row_id = await _insert_row(
        factory, real_event, candidate_id="stale-metadata", expires_at=now - timedelta(days=1),
    )

    async with factory() as session:
        count = await image_retention.delete_expired_metadata(session, now=now)
        await session.commit()

    assert count == 1
    assert await _get_row(factory, row_id) is None


@pytest.mark.asyncio
async def test_delete_expired_metadata_ignores_rows_not_yet_due(
    factory: async_sessionmaker[AsyncSession], real_event: NewsEvent,
) -> None:
    now = datetime.now(timezone.utc)
    row_id = await _insert_row(
        factory, real_event, candidate_id="fresh-metadata", expires_at=now + timedelta(days=29),
    )

    async with factory() as session:
        count = await image_retention.delete_expired_metadata(session, now=now)
        await session.commit()

    assert count == 0
    assert await _get_row(factory, row_id) is not None


@pytest.mark.asyncio
async def test_delete_expired_metadata_defensively_reclaims_still_stored_bytes(
    factory: async_sessionmaker[AsyncSession], real_event: NewsEvent,
) -> None:
    """docs §14 - a metadata row must never be deleted while its bytes are still marked stored,
    since the content-addressed storage key would otherwise become permanently unrecoverable."""
    storage = LocalImageStorage(settings.image_storage_root)
    stored = storage.store_validated_image(_DATA, sha256=_SHA256, image_format="JPEG", max_bytes=10_000)
    now = datetime.now(timezone.utc)
    row_id = await _insert_row(
        factory, real_event, candidate_id="overdue-metadata-still-stored",
        storage_status=ImageStorageStatus.STORED, storage_key=stored.storage_key,
        expires_at=now - timedelta(days=1),
    )

    async with factory() as session:
        count = await image_retention.delete_expired_metadata(session, now=now)
        await session.commit()

    assert count == 1
    assert not storage.exists(stored.storage_key)
    assert await _get_row(factory, row_id) is None


@pytest.mark.asyncio
async def test_run_retention_cleanup_end_to_end(
    factory: async_sessionmaker[AsyncSession], real_event: NewsEvent,
) -> None:
    storage = LocalImageStorage(settings.image_storage_root)
    stored = storage.store_validated_image(_DATA, sha256=_SHA256, image_format="JPEG", max_bytes=10_000)
    now = datetime.now(timezone.utc)
    bytes_row_id = await _insert_row(
        factory, real_event, candidate_id="e2e-bytes", storage_status=ImageStorageStatus.STORED,
        storage_key=stored.storage_key, bytes_expire_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=29),
    )
    metadata_row_id = await _insert_row(
        factory, real_event, candidate_id="e2e-metadata", expires_at=now - timedelta(hours=1),
    )

    summary = await image_retention.run_retention_cleanup(factory, now=now)

    assert summary.bytes_expired == 1
    assert summary.metadata_rows_deleted == 1
    bytes_row = await _get_row(factory, bytes_row_id)
    assert bytes_row.storage_status == ImageStorageStatus.EXPIRED
    assert await _get_row(factory, metadata_row_id) is None


@pytest.mark.asyncio
async def test_run_retention_cleanup_is_a_safe_no_op_when_nothing_is_due(
    factory: async_sessionmaker[AsyncSession], real_event: NewsEvent,
) -> None:
    now = datetime.now(timezone.utc)
    row_id = await _insert_row(
        factory, real_event, candidate_id="not-due-yet", expires_at=now + timedelta(days=10),
    )

    summary = await image_retention.run_retention_cleanup(factory, now=now)

    assert summary.bytes_expired == 0
    assert summary.metadata_rows_deleted == 0
    assert await _get_row(factory, row_id) is not None


@pytest.mark.asyncio
async def test_expire_stored_bytes_batch_size_bound(
    factory: async_sessionmaker[AsyncSession], real_event: NewsEvent, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "image_cleanup_batch_size", 1)
    storage = LocalImageStorage(settings.image_storage_root)
    now = datetime.now(timezone.utc)
    row_ids = []
    for i in range(3):
        data = _DATA + str(i).encode()
        sha = hashlib.sha256(data).hexdigest()
        stored = storage.store_validated_image(data, sha256=sha, image_format="JPEG", max_bytes=10_000)
        row_ids.append(
            await _insert_row(
                factory, real_event, candidate_id=f"batch-{i}", storage_status=ImageStorageStatus.STORED,
                storage_key=stored.storage_key, bytes_expire_at=now - timedelta(days=1),
            )
        )

    async with factory() as session:
        count = await image_retention.expire_stored_bytes(session, now=now)
        await session.commit()

    assert count == 1  # bounded by image_cleanup_batch_size, not the full due set
