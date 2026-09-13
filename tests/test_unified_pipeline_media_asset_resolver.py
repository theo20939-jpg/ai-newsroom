"""UNIFIED-EDITORIAL-PIPELINE-RUNTIME-CLOSURE-1 (S7/S17) - Founder audit Cases A/B, reproduced and
fixed: `services.editorial_pipeline.media_asset_resolver.resolve_selected_media_asset()` resolves
EXACTLY the candidate `MediaSelectionResult.selected` names, never a different one, and never
silently degrades a real, selected candidate into a text-only outcome when its bytes/file_id are
unavailable."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from schemas.media_subject_match import (
    DiscoveryTier,
    MediaProvenance,
    MediaSelectionResult,
    MediaUsageClassification,
    ResolvedMediaCandidate,
)
from services.editorial_pipeline.contracts import MediaAssetResolutionMethod
from services.editorial_pipeline.media_asset_resolver import resolve_selected_media_asset
from services.image_persistence import EditorialImageCandidate

pytestmark = pytest.mark.asyncio


def _legacy_candidate(*, telegram_file_id: str | None, storage_key: str | None = "some/key.jpg") -> EditorialImageCandidate:
    candidate_uuid = uuid4()
    return EditorialImageCandidate(
        id=candidate_uuid, candidate_id="cand-1", rank=1, relevance_score=90, quality_score=90,
        discovery_method="og_image", source_relationship="original_article", relevance_reason="high overlap",
        width=1200, height=800, observed_mime="image/jpeg", image_format="JPEG",
        storage_status="stored", storage_key=storage_key, telegram_file_id=telegram_file_id,
        editor_decision=None, source_url="https://example.com/img.jpg", article_url="https://example.com/article",
        warnings=None, is_expired=False, sha256=None, perceptual_hash=None, final_url=None,
    ), candidate_uuid


def _selection_for(candidate_id: str, image_candidate_record_id: str) -> MediaSelectionResult:
    candidate = ResolvedMediaCandidate(
        candidate_id=candidate_id,
        provenance=MediaProvenance(
            origin_url="https://example.com/a", asset_url="https://example.com/a.jpg",
            discovered_at=datetime.now(timezone.utc), discovery_tier=DiscoveryTier.TIER1_CURRENT_SOURCE,
        ),
        usage_classification=MediaUsageClassification.APPROVED_SOURCE_MEDIA,
        image_candidate_record_id=image_candidate_record_id,
    )
    return MediaSelectionResult(
        intent_primary_entity="x", selected=candidate, selected_score=50.0,
        exact_subject_media_not_found=False, fallback_used=False, candidates_considered=1,
    )


async def test_case_b_valid_cached_file_id_resolves_without_reading_local_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Case B: local bytes are unavailable, but a valid cached Telegram file_id exists - resolution
    must succeed via the file_id, WITHOUT ever calling `read_candidate_bytes()` (S16 - "do not HOLD
    merely because a local temporary file disappeared if a valid Telegram-native reusable media
    reference exists")."""
    legacy, record_id = _legacy_candidate(telegram_file_id="CACHED_FILE_ID_1", storage_key=None)
    selection = _selection_for("cand-1", str(record_id))

    def _must_not_be_called(_candidate):
        raise AssertionError("read_candidate_bytes must not be called when a file_id is available")

    monkeypatch.setattr("services.editorial_pipeline.media_asset_resolver.read_candidate_bytes", _must_not_be_called)

    outcome = await resolve_selected_media_asset(selection, legacy_candidates_by_id={str(record_id): legacy})
    assert outcome.failed is False
    assert outcome.asset is not None
    assert outcome.asset.resolution_method == MediaAssetResolutionMethod.TELEGRAM_FILE_ID
    assert outcome.asset.telegram_file_id == "CACHED_FILE_ID_1"
    assert outcome.asset.candidate_id == "cand-1"


async def test_case_a_no_bytes_no_file_id_fails_resolution_never_silently_text_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Case A: the selected candidate exists, but neither local bytes nor a cached file_id can be
    produced for it. This must be a real, reported resolution FAILURE - never a silent `None`
    treated as a legitimate text-appropriate outcome."""
    legacy, record_id = _legacy_candidate(telegram_file_id=None, storage_key="expired/key.jpg")
    selection = _selection_for("cand-1", str(record_id))

    monkeypatch.setattr("services.editorial_pipeline.media_asset_resolver.read_candidate_bytes", lambda c: None)

    outcome = await resolve_selected_media_asset(selection, legacy_candidates_by_id={str(record_id): legacy})
    assert outcome.failed is True
    assert outcome.asset is None
    assert outcome.failure_detail is not None
    assert "cand-1" in outcome.failure_detail


async def test_local_bytes_resolve_when_no_file_id_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    legacy, record_id = _legacy_candidate(telegram_file_id=None, storage_key="real/key.jpg")
    selection = _selection_for("cand-1", str(record_id))

    monkeypatch.setattr("services.editorial_pipeline.media_asset_resolver.read_candidate_bytes", lambda c: b"real-jpeg-bytes")

    outcome = await resolve_selected_media_asset(selection, legacy_candidates_by_id={str(record_id): legacy})
    assert outcome.failed is False
    assert outcome.asset is not None
    assert outcome.asset.resolution_method == MediaAssetResolutionMethod.LOCAL_STORAGE_BYTES
    assert outcome.asset.resolved_bytes == b"real-jpeg-bytes"


async def test_nothing_selected_is_not_a_resolution_failure() -> None:
    """A `None` selection is a legitimate, ALREADY-APPROVED-upstream outcome (require_media/
    DATA_TYPOGRAPHIC logic decided this before the resolver was ever called) - never itself
    reported as a resolution failure."""
    selection = MediaSelectionResult(
        intent_primary_entity="x", selected=None, exact_subject_media_not_found=True,
        fallback_used=False, candidates_considered=0,
    )
    outcome = await resolve_selected_media_asset(selection)
    assert outcome.failed is False
    assert outcome.asset is None


async def test_bounded_download_disabled_by_default_for_web_discovered_candidate() -> None:
    """S13/S41 - `allow_bounded_download` defaults to False; a Tier 2-5 candidate with no legacy
    record and no local bytes must fail resolution rather than silently reaching out to the network."""
    candidate = ResolvedMediaCandidate(
        candidate_id="web-1",
        provenance=MediaProvenance(
            origin_url="https://news.example/a", asset_url="https://news.example/a.jpg",
            discovered_at=datetime.now(timezone.utc), discovery_tier=DiscoveryTier.TIER4_WEB_IMAGE_DISCOVERY,
        ),
        usage_classification=MediaUsageClassification.EDITORIAL_REVIEW_REQUIRED,
    )
    selection = MediaSelectionResult(
        intent_primary_entity="x", selected=candidate, exact_subject_media_not_found=False,
        fallback_used=False, candidates_considered=1,
    )
    outcome = await resolve_selected_media_asset(selection)  # allow_bounded_download defaults False
    assert outcome.failed is True
