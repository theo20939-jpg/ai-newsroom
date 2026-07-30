"""Phase 16 M5/M6: durable persistence for Image Intelligence results (docs/
phase16_m5_persistence_and_retention_report.md §16, docs/phase16_m6_telegram_editorial_preview_
report.md §7). The sole place SQLAlchemy writes for image candidates happen - `services/
image_relevance.py`, `services/image_quality.py`, `services/image_deduplication.py`, and
`integrations/http/safe_fetch.py` never touch the database; `bot/handlers/image_preview.py`
never touches the database or the storage abstraction directly either - every read/write it
needs goes through this module.

Responsibilities, kept in one module because they share the same row shape and idempotency
rules: (1) convert a finished `ImageIntelligenceResult` into durable `ImageCandidateRecord` rows
(`persist_image_intelligence_result`); (2) expose the bounded read query M6 uses
(`get_editorial_image_candidates`); (3) M6's own link/decision/byte-resolution helpers
(`link_candidates_to_content_draft`, `set_editor_decision`, `reject_all_candidates`,
`read_candidate_bytes`, `record_telegram_file_id`). Retention/cleanup lives in the separate
`services/image_retention.py` (a distinct concern - batch scanning and deletion, not per-event
upsert or interactive editorial state).
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.image_candidate_record import (
    ImageCandidateRecord,
    ImageEditorDecision,
    ImageQualityStatus,
    ImageRelevanceStatus,
    ImageStorageStatus,
)
from integrations.storage.image_storage import ImageStorage, LocalImageStorage, StorageError
from schemas.image_candidate import ImageCandidate, ImageCandidateStatus, ImageIntelligenceResult, QualityStatus

logger = logging.getLogger(__name__)

# Mirrors integrations.storage.image_storage's own supported-format set - kept as a separate
# constant here (rather than imported) so eligibility can be checked without constructing a
# storage key, which requires a valid sha256 that may not exist for a rejected/failed candidate.
_SUPPORTED_STORAGE_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "GIF"})

# Query-parameter names that commonly carry temporary/signed credentials (CDN signed URLs, SAS
# tokens, etc.) - stripped before persistence (docs §20). Deliberately a small, explicit,
# case-insensitive set - never a blind "strip everything" (which would make a stored URL useless
# for future provenance/debugging).
_SENSITIVE_QUERY_PARAMS = frozenset(
    {
        "token", "auth", "authorization", "key", "apikey", "api_key", "secret", "sig",
        "signature", "session", "sessionid", "credential", "password", "access_token", "x-amz-signature",
        "x-amz-credential", "x-amz-security-token",
    }
)

_METADATA_ONLY_FIELDS_EXCLUDED_FROM_UPSERT = frozenset(
    {"storage_status", "storage_key", "stored_byte_size", "stored_at", "storage_error_code", "content_draft_id"}
)

_storage_singleton: ImageStorage | None = None


def _get_storage() -> ImageStorage:
    global _storage_singleton
    if _storage_singleton is None:
        _storage_singleton = LocalImageStorage(settings.image_storage_root)
    return _storage_singleton


def sanitize_url(url: str | None) -> str | None:
    """Removes query parameters that commonly carry temporary credentials; keeps every other
    parameter (needed to actually identify the asset later) and the full path (docs §20)."""
    if not url:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.query:
        return url
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in _SENSITIVE_QUERY_PARAMS]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def _is_storage_eligible(candidate: ImageCandidate) -> bool:
    """Docs §12 - every condition must hold. Deliberately redundant with `services.image_
    relevance`'s own `eligible_for_editorial` flag (never trusts it alone) since this function is
    the last line of defense before bytes are written to disk."""
    if candidate.status != ImageCandidateStatus.VALIDATED:
        return False
    quality = candidate.quality_validation
    if quality is None or quality.status in (
        QualityStatus.REJECTED_QUALITY, QualityStatus.DUPLICATE_EXACT, QualityStatus.DUPLICATE_NEAR,
    ):
        return False
    if quality.deduplication.is_representative is False:
        return False
    relevance = candidate.relevance_validation
    if relevance is None or not relevance.eligible_for_editorial:
        return False
    technical = candidate.technical_validation
    if technical is None or technical.animated:
        return False
    if not technical.format or technical.format.upper() not in _SUPPORTED_STORAGE_FORMATS:
        return False
    if not technical.sha256:
        return False
    return True


def _quality_status_enum(candidate: ImageCandidate) -> ImageQualityStatus | None:
    if candidate.quality_validation is None:
        return None
    return ImageQualityStatus(candidate.quality_validation.status.value)


def _relevance_status_enum(candidate: ImageCandidate) -> ImageRelevanceStatus | None:
    if candidate.relevance_validation is None:
        return None
    return ImageRelevanceStatus(candidate.relevance_validation.status.value)


def _metadata_row_values(
    candidate: ImageCandidate, *, news_event_id: UUID, editorial_task_id: UUID | None, now: datetime,
) -> dict:
    technical = candidate.technical_validation
    quality = candidate.quality_validation
    relevance = candidate.relevance_validation
    is_finalist = bool(relevance and relevance.eligible_for_editorial)
    retention_days = (
        settings.image_finalist_metadata_retention_days if is_finalist else settings.image_metadata_retention_days
    )
    return {
        "candidate_id": candidate.candidate_id,
        "news_event_id": news_event_id,
        "editorial_task_id": editorial_task_id,
        "source_type": candidate.source_type,
        "discovery_method": candidate.discovery_method.value,
        "source_name": None,  # not carried on ImageCandidate itself - reserved, always None from M5
        "article_url": sanitize_url(candidate.source_url if candidate.telegram is None else None),
        "source_url": sanitize_url(candidate.source_url),
        "remote_url": sanitize_url(candidate.remote_url),
        "final_url": sanitize_url(technical.final_url) if technical else None,
        "provenance_confidence": relevance.components.get("provenance") if relevance else None,
        "source_relationship": relevance.source_relationship.value if relevance and relevance.source_relationship else None,
        "observed_mime": technical.observed_mime if technical else None,
        "image_format": technical.format if technical else None,
        "width": technical.width if technical else None,
        "height": technical.height if technical else None,
        "pixel_count": technical.pixel_count if technical else None,
        "aspect_ratio": technical.aspect_ratio if technical else None,
        "byte_size": technical.byte_size if technical else None,
        "animated": technical.animated if technical else None,
        "frame_count": technical.frame_count if technical else None,
        "sha256": technical.sha256 if technical else None,
        "perceptual_hash": quality.deduplication.perceptual_hash if quality else None,
        "quality_status": _quality_status_enum(candidate),
        "quality_score": quality.quality_score if quality else None,
        "quality_hard_rejection_reasons": quality.hard_rejection_reasons if quality else None,
        "quality_warnings": quality.quality_warnings if quality else None,
        "quality_components": quality.quality_components if quality else None,
        "exact_cluster_id": quality.deduplication.exact_cluster_id if quality else None,
        "near_duplicate_cluster_id": quality.deduplication.perceptual_cluster_id if quality else None,
        "duplicate_of_candidate_id": quality.deduplication.duplicate_of if quality else None,
        "is_representative": quality.deduplication.is_representative if quality else None,
        "relevance_status": _relevance_status_enum(candidate),
        "relevance_score": relevance.relevance_score if relevance else None,
        "rank": relevance.rank if relevance else None,
        "eligible_for_editorial": bool(relevance and relevance.eligible_for_editorial),
        "relevance_components": relevance.components if relevance else None,
        "relevance_penalties": relevance.penalties if relevance else None,
        "relevance_coverage": relevance.coverage if relevance else None,
        "relevance_reason": relevance.reason if relevance else None,
        "updated_at": now,
        "expires_at": now + timedelta(days=retention_days),
    }


async def _upsert_metadata_row(session: AsyncSession, values: dict) -> None:
    """Idempotent upsert keyed on (news_event_id, candidate_id) - storage_*/content_draft_id are
    deliberately excluded from the UPDATE SET clause (docs §17): a metadata-only rerun must never
    reset a previously-stored file's DB record back to not_requested, and must never clobber a
    future (M6) editor-assigned content_draft_id."""
    stmt = pg_insert(ImageCandidateRecord).values(**values)
    update_columns = {
        column.name: getattr(stmt.excluded, column.name)
        for column in ImageCandidateRecord.__table__.columns
        if column.name not in _METADATA_ONLY_FIELDS_EXCLUDED_FROM_UPSERT and column.name not in ("id", "created_at")
    }
    stmt = stmt.on_conflict_do_update(
        constraint="uq_image_candidates_event_candidate", set_=update_columns,
    )
    await session.execute(stmt)


async def _apply_storage_result(
    session: AsyncSession, *, news_event_id: UUID, candidate_id: str,
    storage_status: ImageStorageStatus, storage_key: str | None = None,
    stored_byte_size: int | None = None, storage_error_code: str | None = None,
) -> None:
    """A second, narrowly-scoped update touching only the storage_* columns - never the audit
    fields above, so it can never race-clobber them (docs §18)."""
    now = datetime.now(timezone.utc)
    values: dict = {"storage_status": storage_status, "storage_error_code": storage_error_code}
    if storage_status == ImageStorageStatus.STORED:
        values.update({
            "storage_key": storage_key, "stored_byte_size": stored_byte_size, "stored_at": now,
            "bytes_expire_at": now + timedelta(days=settings.image_bytes_retention_days),
        })
    stmt = (
        select(ImageCandidateRecord)
        .where(ImageCandidateRecord.news_event_id == news_event_id, ImageCandidateRecord.candidate_id == candidate_id)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return
    for key, value in values.items():
        setattr(row, key, value)


@dataclass(frozen=True)
class PersistenceSummary:
    candidates_persisted: int
    finalists_requested: int
    files_stored: int
    bytes_stored: int
    storage_failures: int


async def persist_image_intelligence_result(
    session: AsyncSession,
    *,
    result: ImageIntelligenceResult,
    editorial_task_id: UUID | None,
    image_bytes_by_candidate_id: dict[str, bytes],
) -> PersistenceSummary:
    """The sole M5 write entry point (docs §16/§19). Always persists metadata for every bounded
    candidate in `result.candidates` when `image_candidate_persistence_mode != "off"`; additionally
    stores bytes for up to `image_max_stored_per_event` eligible finalists, bounded by
    `image_max_total_stored_bytes_per_event`, only when mode == "finalists". Never raises - any
    single candidate's failure (metadata or storage) is logged and skipped, the rest continue
    (docs §18's "one failed retry does not leave contradictory storage states")."""
    mode = settings.image_candidate_persistence_mode
    now = datetime.now(timezone.utc)
    persisted = 0
    finalists_requested = 0
    files_stored = 0
    bytes_stored = 0
    storage_failures = 0
    total_bytes_this_event = 0

    for candidate in result.candidates:
        try:
            values = _metadata_row_values(
                candidate, news_event_id=result.event_id, editorial_task_id=editorial_task_id, now=now,
            )
            await _upsert_metadata_row(session, values)
            persisted += 1
        except Exception:
            logger.warning(
                "image_persistence_metadata_upsert_failed",
                extra={"event_id": str(result.event_id), "candidate_id": candidate.candidate_id},
            )
            continue

    if mode != "finalists":
        return PersistenceSummary(persisted, 0, 0, 0, 0)

    finalists = sorted(
        (c for c in result.candidates if c.relevance_validation and c.relevance_validation.eligible_for_editorial),
        key=lambda c: c.relevance_validation.rank or 0,  # type: ignore[union-attr]
    )[: settings.image_max_stored_per_event]

    storage = _get_storage()
    for candidate in finalists:
        finalists_requested += 1
        if not _is_storage_eligible(candidate):
            continue
        data = image_bytes_by_candidate_id.get(candidate.candidate_id)
        if data is None:
            continue
        technical = candidate.technical_validation
        assert technical is not None and technical.sha256 is not None and technical.format is not None
        if total_bytes_this_event + len(data) > settings.image_max_total_stored_bytes_per_event:
            continue  # bounded per-event budget - remaining finalists simply stay not_requested

        try:
            stored = storage.store_validated_image(
                data, sha256=technical.sha256, image_format=technical.format,
                max_bytes=settings.image_max_total_stored_bytes_per_event,
            )
        except StorageError as error:
            storage_failures += 1
            await _apply_storage_result(
                session, news_event_id=result.event_id, candidate_id=candidate.candidate_id,
                storage_status=ImageStorageStatus.FAILED, storage_error_code=error.code,
            )
            continue
        except Exception:
            storage_failures += 1
            logger.warning(
                "image_persistence_storage_unexpected_error",
                extra={"event_id": str(result.event_id), "candidate_id": candidate.candidate_id},
            )
            await _apply_storage_result(
                session, news_event_id=result.event_id, candidate_id=candidate.candidate_id,
                storage_status=ImageStorageStatus.FAILED, storage_error_code="internal_storage_error",
            )
            continue

        total_bytes_this_event += stored.byte_size
        files_stored += 1
        bytes_stored += stored.byte_size
        await _apply_storage_result(
            session, news_event_id=result.event_id, candidate_id=candidate.candidate_id,
            storage_status=ImageStorageStatus.STORED, storage_key=stored.storage_key,
            stored_byte_size=stored.byte_size,
        )

    logger.info(
        "image_persistence_summary",
        extra={
            "event_id": str(result.event_id), "mode": mode, "candidates_persisted": persisted,
            "finalists_requested": finalists_requested, "files_stored": files_stored,
            "bytes_stored": bytes_stored, "storage_failures": storage_failures,
        },
    )
    return PersistenceSummary(persisted, finalists_requested, files_stored, bytes_stored, storage_failures)


@dataclass(frozen=True)
class EditorialImageCandidate:
    """The M6 retrieval contract (docs §19 of the M5 report, §7 of the M6 report) - an internal
    storage reference (`storage_key`) is exposed, never a filesystem path or public URL. Bytes are
    resolved only through `read_candidate_bytes()` below, never by the caller reaching into
    `integrations.storage.image_storage` directly."""

    id: UUID
    candidate_id: str
    rank: int | None
    relevance_score: int | None
    quality_score: int | None
    discovery_method: str
    source_relationship: str | None
    relevance_reason: str | None
    width: int | None
    height: int | None
    observed_mime: str | None
    image_format: str | None
    storage_status: str
    storage_key: str | None
    telegram_file_id: str | None
    editor_decision: str | None
    source_url: str | None
    article_url: str | None
    warnings: list | None
    is_expired: bool


async def get_editorial_image_candidates(
    session: AsyncSession, *, news_event_id: UUID | None = None, content_draft_id: UUID | None = None, limit: int = 5,
) -> list[EditorialImageCandidate]:
    """The M6 read contract (docs §19 of the M5 report). Exactly one of
    `news_event_id`/`content_draft_id` should be provided. Returns eligible-for-editorial rows
    ordered by rank, each flagged with whether its metadata row has already passed `expires_at`
    (M6 treats `is_expired=True` as unusable, even if the row has not yet been physically cleaned
    up by the next scheduled retention cycle)."""
    stmt = select(ImageCandidateRecord).where(ImageCandidateRecord.eligible_for_editorial.is_(True))
    if news_event_id is not None:
        stmt = stmt.where(ImageCandidateRecord.news_event_id == news_event_id)
    if content_draft_id is not None:
        stmt = stmt.where(ImageCandidateRecord.content_draft_id == content_draft_id)
    stmt = stmt.order_by(ImageCandidateRecord.rank.asc().nulls_last()).limit(limit)

    now = datetime.now(timezone.utc)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        EditorialImageCandidate(
            id=row.id, candidate_id=row.candidate_id, rank=row.rank, relevance_score=row.relevance_score,
            quality_score=row.quality_score, discovery_method=row.discovery_method,
            source_relationship=row.source_relationship, relevance_reason=row.relevance_reason,
            width=row.width, height=row.height,
            observed_mime=row.observed_mime, image_format=row.image_format,
            storage_status=row.storage_status.value, storage_key=row.storage_key,
            telegram_file_id=row.telegram_file_id,
            editor_decision=row.editor_decision.value if row.editor_decision else None,
            source_url=row.source_url, article_url=row.article_url, warnings=row.quality_warnings,
            is_expired=bool(row.expires_at and row.expires_at <= now),
        )
        for row in rows
    ]


async def link_candidates_to_content_draft(
    session: AsyncSession, *, editorial_task_id: UUID, content_draft_id: UUID,
) -> int:
    """Phase 16 M6 (docs/phase16_m6_telegram_editorial_preview_report.md §7): populates the
    `content_draft_id` M5 always left `NULL` (M5 report §5 - "always NULL when written by M5's own
    integration point... no ContentDraft exists yet at the copywriting step"). Called exactly once,
    immediately after `ContentDraftService.create_from_result()` succeeds
    (`scripts/run_content_generation.py`) - the first point in the pipeline where both a
    `content_draft_id` and the originating `editorial_task_id` are simultaneously available.
    A single bounded `UPDATE`, scoped to one task's own rows - never touches any other task's
    candidates. Returns the number of rows linked (0 is a normal, frequent outcome: most events
    have no image candidates at all, or Image Intelligence never ran for this task)."""
    stmt = (
        update(ImageCandidateRecord)
        .where(ImageCandidateRecord.editorial_task_id == editorial_task_id)
        .values(content_draft_id=content_draft_id)
    )
    result = await session.execute(stmt)
    return result.rowcount or 0  # type: ignore[attr-defined]  # CursorResult at runtime for an UPDATE; Result[Any]'s stub doesn't expose it statically


async def set_editor_decision(
    session: AsyncSession, *, content_draft_id: UUID, candidate_row_id: UUID,
) -> bool:
    """Phase 16 M6 (docs §8): records "use this image" for one draft. At most one row per
    `content_draft_id` is ever `SELECTED` - every sibling row for the same draft is set to
    `REJECTED` in the same statement, never left in a stale `SELECTED` state from an earlier
    decision (idempotent: pressing "Use image" again on the already-selected candidate is a safe
    no-op). Returns `False` (no write performed) if `candidate_row_id` does not belong to
    `content_draft_id` at all - callback data referencing a candidate from a different draft, or a
    row that no longer exists, is never silently applied to the wrong draft."""
    now = datetime.now(timezone.utc)
    owns_candidate = (
        await session.execute(
            select(ImageCandidateRecord.id).where(
                ImageCandidateRecord.id == candidate_row_id,
                ImageCandidateRecord.content_draft_id == content_draft_id,
            )
        )
    ).scalar_one_or_none()
    if owns_candidate is None:
        return False

    await session.execute(
        update(ImageCandidateRecord)
        .where(
            ImageCandidateRecord.content_draft_id == content_draft_id,
            ImageCandidateRecord.id != candidate_row_id,
        )
        .values(editor_decision=ImageEditorDecision.REJECTED, editor_decision_at=now)
    )
    await session.execute(
        update(ImageCandidateRecord)
        .where(ImageCandidateRecord.id == candidate_row_id)
        .values(editor_decision=ImageEditorDecision.SELECTED, editor_decision_at=now)
    )
    return True


async def reject_all_candidates(session: AsyncSession, *, content_draft_id: UUID) -> int:
    """Phase 16 M6 (docs §8): records "no image" for one draft - every candidate row for
    `content_draft_id` is set to `REJECTED`. Deliberately not a separate tri-state flag on
    `ContentDraft` itself (no schema change to that table): "no image chosen" is represented
    entirely as "zero rows for this draft are `SELECTED`", which this achieves directly.
    Idempotent - pressing "No image" again re-applies the same, already-true state. Returns the
    number of rows updated (0 is valid: a draft with zero image candidates at all)."""
    now = datetime.now(timezone.utc)
    result = await session.execute(
        update(ImageCandidateRecord)
        .where(ImageCandidateRecord.content_draft_id == content_draft_id)
        .values(editor_decision=ImageEditorDecision.REJECTED, editor_decision_at=now)
    )
    return result.rowcount or 0  # type: ignore[attr-defined]  # CursorResult at runtime for an UPDATE; Result[Any]'s stub doesn't expose it statically


def read_candidate_bytes(candidate: EditorialImageCandidate) -> bytes | None:
    """Phase 16 M6 (docs §7): the sole place `bot/handlers/image_preview.py` ever resolves actual
    image bytes - it never imports or calls `integrations.storage.image_storage` directly. Returns
    `None` (never raises) whenever bytes are not available for any reason: `storage_status` is not
    `"stored"`, no `storage_key`, or the file itself is missing/unreadable (`StorageError`, e.g.
    after an out-of-band deletion or an already-expired-and-cleaned-up row) - the caller always
    falls back to a text-only preview rather than crash."""
    if candidate.storage_status != ImageStorageStatus.STORED.value or not candidate.storage_key:
        return None
    storage = _get_storage()
    try:
        return storage.read(candidate.storage_key)
    except StorageError:
        logger.warning(
            "image_preview_storage_read_failed",
            extra={"candidate_row_id": str(candidate.id), "storage_key": candidate.storage_key},
        )
        return None
    except OSError:
        logger.warning(
            "image_preview_storage_read_os_error",
            extra={"candidate_row_id": str(candidate.id)},
        )
        return None


async def record_telegram_file_id(session: AsyncSession, *, candidate_row_id: UUID, file_id: str) -> None:
    """Phase 16 M6 (docs §11): caches the Telegram-issued `file_id` after the first successful
    upload of a candidate's bytes, so every subsequent view of the same candidate can be resent via
    `bot.send_photo(chat_id, photo=file_id)` - a plain string, no local byte read at all. Never
    itself a public URL; only ever resolvable by a bot holding this application's own bot token."""
    await session.execute(
        update(ImageCandidateRecord)
        .where(ImageCandidateRecord.id == candidate_row_id)
        .values(telegram_file_id=file_id)
    )
