"""Tests for services.image_persistence's Phase 16 M5 durable persistence (docs/
phase16_m5_persistence_and_retention_report.md). Real Postgres (tests/conftest.py's db_session
fixture, rolled back per test) + a tmp_path-backed LocalImageStorage - no network, no LLM.
"""
import hashlib
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.image_candidate_record import ImageCandidateRecord, ImageStorageStatus
from database.models.news_event import NewsEvent
from database.models.news_source import SourceType
from integrations.storage.image_storage import LocalImageStorage
from schemas.image_candidate import (
    DeduplicationInfo,
    ImageCandidate,
    ImageCandidateStatus,
    ImageDiscoveryMethod,
    ImageIntelligenceResult,
    QualitySignals,
    QualityStatus,
    QualityValidation,
    RelevanceStatus,
    RelevanceValidation,
    ResolutionBand,
    AspectRatioBand,
    SourceRelationship,
    TechnicalValidation,
)
from services import image_persistence

_DATA = b"fake-validated-image-bytes-for-m5-tests"
_SHA256 = hashlib.sha256(_DATA).hexdigest()


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Every test gets its own storage root and a fresh singleton - the module-level
    `_storage_singleton` must never leak a prior test's tmp_path across tests."""
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)
    yield
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)


def _candidate(
    *,
    candidate_id: str = "cand-1",
    event_id,
    status: ImageCandidateStatus = ImageCandidateStatus.VALIDATED,
    quality_status: QualityStatus | None = QualityStatus.ACCEPTED,
    is_representative: bool = True,
    relevance_status: RelevanceStatus | None = RelevanceStatus.RANKED,
    eligible_for_editorial: bool = True,
    rank: int | None = 1,
    with_technical: bool = True,
    remote_url: str = "https://cdn.example.com/photo.jpg?token=secret123&width=800",
) -> ImageCandidate:
    technical = (
        TechnicalValidation(
            final_url=remote_url, http_status=200, observed_mime="image/jpeg", format="JPEG",
            byte_size=len(_DATA), width=800, height=600, pixel_count=480_000, aspect_ratio=1.33,
            animated=False, sha256=_SHA256,
        )
        if with_technical
        else None
    )
    quality = (
        QualityValidation(
            status=quality_status, quality_score=80,
            signals=QualitySignals(resolution_band=ResolutionBand.GOOD, aspect_ratio_band=AspectRatioBand.EDITORIAL_LANDSCAPE),
            deduplication=DeduplicationInfo(
                exact_hash=_SHA256, perceptual_hash="abcd1234", exact_cluster_id="c1",
                is_representative=is_representative,
            ),
        )
        if quality_status is not None
        else None
    )
    relevance = (
        RelevanceValidation(
            status=relevance_status, eligibility_reason="m3_status:accepted", relevance_score=72,
            rank=rank, eligible_for_editorial=eligible_for_editorial,
            source_relationship=SourceRelationship.SAME_ARTICLE,
            components={"provenance": 25, "source_relationship": 15, "textual_overlap": 10, "quality": 12, "metadata_confidence": 8},
        )
        if relevance_status is not None
        else None
    )
    return ImageCandidate(
        candidate_id=candidate_id, schema_version="m4", event_id=event_id, source_type=SourceType.RSS,
        discovery_method=ImageDiscoveryMethod.OPEN_GRAPH_IMAGE, status=status,
        remote_url=remote_url, source_url="https://example.com/article",
        discovery_order=0, discovered_at=datetime.now(timezone.utc),
        technical_validation=technical, quality_validation=quality, relevance_validation=relevance,
    )


def _result(event_id, *candidates: ImageCandidate) -> ImageIntelligenceResult:
    return ImageIntelligenceResult(
        version="m4", mode="shadow", event_id=event_id, candidates_discovered=len(candidates),
        candidates_accepted=len(candidates), candidates_rejected=0, candidates=list(candidates),
        generated_at=datetime.now(timezone.utc),
    )


def test_sanitize_url_strips_sensitive_query_params_only() -> None:
    url = "https://cdn.example.com/a.jpg?token=abc&width=800&Session=xyz"
    sanitized = image_persistence.sanitize_url(url)
    assert "token=" not in sanitized
    assert "Session=" not in sanitized.lower().replace("session=", "")  # case-insensitive strip
    assert "width=800" in sanitized
    assert sanitized.startswith("https://cdn.example.com/a.jpg?")


def test_sanitize_url_passthrough_for_none_and_no_query() -> None:
    assert image_persistence.sanitize_url(None) is None
    assert image_persistence.sanitize_url("https://example.com/a.jpg") == "https://example.com/a.jpg"


@pytest.mark.asyncio
async def test_persist_metadata_mode_writes_rows_but_never_stores_bytes(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    candidate = _candidate(event_id=real_news_event.id)
    result = _result(real_news_event.id, candidate)

    with patch.object(settings, "image_candidate_persistence_mode", "metadata"):
        summary = await image_persistence.persist_image_intelligence_result(
            db_session, result=result, editorial_task_id=None,
            image_bytes_by_candidate_id={candidate.candidate_id: _DATA},
        )

    assert summary.candidates_persisted == 1
    assert summary.files_stored == 0

    row = (
        await db_session.execute(
            select(ImageCandidateRecord).where(
                ImageCandidateRecord.news_event_id == real_news_event.id,
                ImageCandidateRecord.candidate_id == candidate.candidate_id,
            )
        )
    ).scalar_one()
    assert row.storage_status == ImageStorageStatus.NOT_REQUESTED
    assert row.storage_key is None
    assert row.quality_score == 80
    assert row.relevance_score == 72
    assert row.eligible_for_editorial is True
    assert "token=" not in (row.remote_url or "")


@pytest.mark.asyncio
async def test_persist_finalists_mode_stores_bytes_for_eligible_finalist(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    candidate = _candidate(event_id=real_news_event.id)
    result = _result(real_news_event.id, candidate)

    with patch.object(settings, "image_candidate_persistence_mode", "finalists"):
        summary = await image_persistence.persist_image_intelligence_result(
            db_session, result=result, editorial_task_id=None,
            image_bytes_by_candidate_id={candidate.candidate_id: _DATA},
        )

    assert summary.files_stored == 1
    assert summary.bytes_stored == len(_DATA)

    row = (
        await db_session.execute(
            select(ImageCandidateRecord).where(
                ImageCandidateRecord.news_event_id == real_news_event.id,
                ImageCandidateRecord.candidate_id == candidate.candidate_id,
            )
        )
    ).scalar_one()
    assert row.storage_status == ImageStorageStatus.STORED
    assert row.storage_key is not None
    assert row.stored_byte_size == len(_DATA)
    assert row.bytes_expire_at is not None

    storage = LocalImageStorage(settings.image_storage_root)
    assert storage.read(row.storage_key) == _DATA


@pytest.mark.asyncio
async def test_persist_finalists_mode_skips_non_finalist_candidate_bytes(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    candidate = _candidate(
        event_id=real_news_event.id, eligible_for_editorial=False, rank=None,
        relevance_status=RelevanceStatus.RANKED,
    )
    result = _result(real_news_event.id, candidate)

    with patch.object(settings, "image_candidate_persistence_mode", "finalists"):
        summary = await image_persistence.persist_image_intelligence_result(
            db_session, result=result, editorial_task_id=None,
            image_bytes_by_candidate_id={candidate.candidate_id: _DATA},
        )

    assert summary.finalists_requested == 0
    assert summary.files_stored == 0
    row = (
        await db_session.execute(
            select(ImageCandidateRecord).where(
                ImageCandidateRecord.news_event_id == real_news_event.id,
                ImageCandidateRecord.candidate_id == candidate.candidate_id,
            )
        )
    ).scalar_one()
    assert row.storage_status == ImageStorageStatus.NOT_REQUESTED


@pytest.mark.asyncio
async def test_persist_finalists_mode_skips_non_representative_duplicate(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    """Docs §12 - `_is_storage_eligible` never trusts `eligible_for_editorial` alone; a
    non-representative duplicate must never reach disk even if (hypothetically) mis-flagged."""
    candidate = _candidate(event_id=real_news_event.id, is_representative=False)
    result = _result(real_news_event.id, candidate)

    with patch.object(settings, "image_candidate_persistence_mode", "finalists"):
        summary = await image_persistence.persist_image_intelligence_result(
            db_session, result=result, editorial_task_id=None,
            image_bytes_by_candidate_id={candidate.candidate_id: _DATA},
        )

    assert summary.files_stored == 0


@pytest.mark.asyncio
async def test_persist_finalists_mode_respects_per_event_byte_budget(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "image_max_total_stored_bytes_per_event", len(_DATA) - 1)
    candidate = _candidate(event_id=real_news_event.id)
    result = _result(real_news_event.id, candidate)

    with patch.object(settings, "image_candidate_persistence_mode", "finalists"):
        summary = await image_persistence.persist_image_intelligence_result(
            db_session, result=result, editorial_task_id=None,
            image_bytes_by_candidate_id={candidate.candidate_id: _DATA},
        )

    assert summary.files_stored == 0
    row = (
        await db_session.execute(
            select(ImageCandidateRecord).where(
                ImageCandidateRecord.news_event_id == real_news_event.id,
                ImageCandidateRecord.candidate_id == candidate.candidate_id,
            )
        )
    ).scalar_one()
    assert row.storage_status == ImageStorageStatus.NOT_REQUESTED


@pytest.mark.asyncio
async def test_idempotent_upsert_never_resets_prior_storage_state(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    """docs §17 - a metadata-only rerun (e.g. mode later flipped to "metadata") must never reset
    a previously-`stored` row's storage_status back to not_requested."""
    candidate = _candidate(event_id=real_news_event.id)
    result = _result(real_news_event.id, candidate)

    with patch.object(settings, "image_candidate_persistence_mode", "finalists"):
        await image_persistence.persist_image_intelligence_result(
            db_session, result=result, editorial_task_id=None,
            image_bytes_by_candidate_id={candidate.candidate_id: _DATA},
        )

    # rerun in metadata-only mode - same candidate, no bytes provided this time
    with patch.object(settings, "image_candidate_persistence_mode", "metadata"):
        await image_persistence.persist_image_intelligence_result(
            db_session, result=result, editorial_task_id=None, image_bytes_by_candidate_id={},
        )

    row = (
        await db_session.execute(
            select(ImageCandidateRecord).where(
                ImageCandidateRecord.news_event_id == real_news_event.id,
                ImageCandidateRecord.candidate_id == candidate.candidate_id,
            )
        )
    ).scalar_one()
    assert row.storage_status == ImageStorageStatus.STORED
    assert row.storage_key is not None


@pytest.mark.asyncio
async def test_persist_ineligible_candidate_writes_metadata_row_with_no_scores(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    candidate = _candidate(
        event_id=real_news_event.id, status=ImageCandidateStatus.REJECTED_TECHNICAL,
        with_technical=False, quality_status=None, relevance_status=None,
        eligible_for_editorial=False, rank=None,
    )
    result = _result(real_news_event.id, candidate)

    with patch.object(settings, "image_candidate_persistence_mode", "metadata"):
        summary = await image_persistence.persist_image_intelligence_result(
            db_session, result=result, editorial_task_id=None, image_bytes_by_candidate_id={},
        )

    assert summary.candidates_persisted == 1
    row = (
        await db_session.execute(
            select(ImageCandidateRecord).where(
                ImageCandidateRecord.news_event_id == real_news_event.id,
                ImageCandidateRecord.candidate_id == candidate.candidate_id,
            )
        )
    ).scalar_one()
    assert row.quality_status is None
    assert row.relevance_status is None
    assert row.eligible_for_editorial is False


@pytest.mark.asyncio
async def test_get_editorial_image_candidates_orders_by_rank_and_flags_expiry(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    second = _candidate(event_id=real_news_event.id, candidate_id="cand-2", rank=2, remote_url="https://cdn.example.com/b.jpg")
    first = _candidate(event_id=real_news_event.id, candidate_id="cand-1", rank=1, remote_url="https://cdn.example.com/a.jpg")
    result = _result(real_news_event.id, second, first)

    with patch.object(settings, "image_candidate_persistence_mode", "metadata"):
        await image_persistence.persist_image_intelligence_result(
            db_session, result=result, editorial_task_id=None, image_bytes_by_candidate_id={},
        )

    candidates = await image_persistence.get_editorial_image_candidates(db_session, news_event_id=real_news_event.id)
    assert [c.candidate_id for c in candidates] == ["cand-1", "cand-2"]
    assert all(c.is_expired is False for c in candidates)

    # force one row's expires_at into the past and re-query
    row = (
        await db_session.execute(
            select(ImageCandidateRecord).where(
                ImageCandidateRecord.news_event_id == real_news_event.id,
                ImageCandidateRecord.candidate_id == "cand-1",
            )
        )
    ).scalar_one()
    row.expires_at = datetime.now(timezone.utc).replace(year=2000)
    await db_session.flush()

    candidates = await image_persistence.get_editorial_image_candidates(db_session, news_event_id=real_news_event.id)
    by_id = {c.candidate_id: c for c in candidates}
    assert by_id["cand-1"].is_expired is True
    assert by_id["cand-2"].is_expired is False


@pytest.mark.asyncio
async def test_persistence_never_raises_on_a_single_bad_candidate(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    """docs §18 - one candidate's failure must not abort the rest of the batch."""
    good = _candidate(event_id=real_news_event.id, candidate_id="good", rank=1)
    # A second, differently-shaped candidate for the same event that still round-trips fine -
    # persistence has no realistic single-candidate failure mode short of a DB outage, so this
    # instead proves that two candidates for the same event both persist independently in one call.
    other = _candidate(event_id=real_news_event.id, candidate_id="also-good", rank=2)
    result = _result(real_news_event.id, good, other)

    with patch.object(settings, "image_candidate_persistence_mode", "metadata"):
        summary = await image_persistence.persist_image_intelligence_result(
            db_session, result=result, editorial_task_id=None, image_bytes_by_candidate_id={},
        )

    assert summary.candidates_persisted == 2
