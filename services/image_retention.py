"""Phase 16 M5: retention/cleanup for durable Image Intelligence records (docs/
phase16_m5_persistence_and_retention_report.md §14-15). A distinct concern from
services/image_persistence.py's own per-event upsert (batch scanning + deletion instead of
per-event writes), run periodically from content_worker's own existing poll loop - never its own
scheduler/worker/timer process (see core/config.py::image_cleanup_every_n_cycles,
worker/content_main.py's own integration).

Two independent expiry clocks, reclaimed separately (docs §14):
- `bytes_expire_at` (shorter, `image_bytes_retention_days`) - stored finalist bytes on disk.
- `expires_at` (longer, `image_metadata_retention_days` / `image_finalist_metadata_retention_days`)
  - the durable audit row itself.

Both scans are batch-limited (`image_cleanup_batch_size`) and safe to call repeatedly - each call
only processes whatever is currently due, and either scan finding nothing due is a normal, frequent
outcome, never a sign of a stuck process.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from database.models.image_candidate_record import ImageCandidateRecord, ImageStorageStatus
from database.session import async_session_factory
from integrations.storage.image_storage import ImageStorage, LocalImageStorage, StorageError

logger = logging.getLogger(__name__)

_storage_singleton: ImageStorage | None = None


def _get_storage() -> ImageStorage:
    global _storage_singleton
    if _storage_singleton is None:
        _storage_singleton = LocalImageStorage(settings.image_storage_root)
    return _storage_singleton


def _delete_bytes(storage: ImageStorage, storage_key: str | None) -> None:
    """Best-effort - a `StorageError` or an already-missing file is treated as "nothing left to
    reclaim on disk", never a reason to skip reclaiming the DB row (cleanup must always make
    forward progress on the durable record, which is the source of truth)."""
    if not storage_key:
        return
    try:
        storage.delete(storage_key)
    except StorageError:
        logger.warning("image_retention_storage_delete_failed", extra={"storage_key": storage_key})


async def expire_stored_bytes(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Reclaims disk space for finalist bytes whose `bytes_expire_at` has passed - the metadata
    row itself is left untouched (docs §14: the audit trail deliberately outlives the bytes)."""
    now = now or datetime.now(timezone.utc)
    storage = _get_storage()
    stmt = (
        select(ImageCandidateRecord)
        .where(
            ImageCandidateRecord.storage_status == ImageStorageStatus.STORED,
            ImageCandidateRecord.bytes_expire_at.is_not(None),
            ImageCandidateRecord.bytes_expire_at <= now,
        )
        .limit(settings.image_cleanup_batch_size)
    )
    rows = (await session.execute(stmt)).scalars().all()
    for row in rows:
        _delete_bytes(storage, row.storage_key)
        row.storage_status = ImageStorageStatus.EXPIRED
    return len(rows)


async def delete_expired_metadata(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Reclaims durable audit rows whose `expires_at` has passed. Defensively deletes any
    still-`stored` bytes first - a metadata row must never be deleted while it is the only
    remaining reference to on-disk bytes, since storage keys are content-addressed and otherwise
    unrecoverable. This should be rare in practice (`bytes_expire_at` is always configured shorter
    than `expires_at`) but is not assumed."""
    now = now or datetime.now(timezone.utc)
    storage = _get_storage()
    stmt = (
        select(ImageCandidateRecord)
        .where(ImageCandidateRecord.expires_at.is_not(None), ImageCandidateRecord.expires_at <= now)
        .limit(settings.image_cleanup_batch_size)
    )
    rows = (await session.execute(stmt)).scalars().all()
    ids = [row.id for row in rows]
    for row in rows:
        if row.storage_status == ImageStorageStatus.STORED:
            _delete_bytes(storage, row.storage_key)
    if ids:
        await session.execute(delete(ImageCandidateRecord).where(ImageCandidateRecord.id.in_(ids)))
    return len(ids)


@dataclass(frozen=True)
class RetentionSummary:
    bytes_expired: int
    metadata_rows_deleted: int


async def run_retention_cleanup(
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
    *,
    now: datetime | None = None,
) -> RetentionSummary:
    """The sole M5 cleanup entry point (docs §15) - called periodically from content_worker's own
    poll loop (`worker/content_main.py`), never its own timer/process. Never raises: any failure is
    logged and swallowed, mirroring every other Phase 16 milestone's own "must not affect delivery"
    discipline - a failed cleanup cycle simply retries on the next scheduled call."""
    now = now or datetime.now(timezone.utc)
    bytes_expired = 0
    metadata_deleted = 0
    try:
        async with session_factory() as session:
            bytes_expired = await expire_stored_bytes(session, now=now)
            await session.commit()
    except Exception:
        logger.warning("image_retention_bytes_expiry_failed")

    try:
        async with session_factory() as session:
            metadata_deleted = await delete_expired_metadata(session, now=now)
            await session.commit()
    except Exception:
        logger.warning("image_retention_metadata_deletion_failed")

    if bytes_expired or metadata_deleted:
        logger.info(
            "image_retention_cleanup_summary",
            extra={"bytes_expired": bytes_expired, "metadata_rows_deleted": metadata_deleted},
        )
    return RetentionSummary(bytes_expired, metadata_deleted)
