"""UNIFIED-EDITORIAL-PIPELINE-RUNTIME-CLOSURE-1 (S7): the real final-asset resolver.

Founder audit gap A ("selected media and rendered media can diverge") and gap B ("visual-required
posts can still degrade to text-only when the selected media exists logically but cannot actually
be resolved") both trace to the SAME root cause: the pre-cutover Telegram call site
(`services/editorial_pipeline/telegram_integration.py`) captured a candidate's bytes via closure
BEFORE `MediaResearchService` ever ran, then used those pre-captured bytes unconditionally in the
render callback - regardless of what `MediaSelectionResult.selected` actually was, and with no
distinction between "no bytes because none exist" and "no bytes because this is a legitimate
text-appropriate composition".

This module is the fix: resolution happens exactly once, AFTER `MediaResearchService.research()`
has already produced its `MediaSelectionResult`, and resolves EXACTLY the candidate that result
names (`media_selection.selected`) - never a different one. There is no code path in this module
that can hand back an asset for any `candidate_id` other than the one it was asked to resolve.

Resolution priority (S16 - never invents a different image when resolution fails):

    1. a valid, cached Telegram file_id (zero bytes read - `bot/image_preview_media.py`'s own
       existing, proven "file_id first" policy, reused verbatim via the SAME legacy
       `EditorialImageCandidate` record the selected `ResolvedMediaCandidate` wraps)
    2. persisted local/storage bytes for that SAME legacy record (`read_candidate_bytes()`)
    3. a bounded, safety-checked download from the selected candidate's OWN `asset_url`
       (Tier 2-5 web-discovered candidates only - `services.media_download_cache.
       download_and_validate()`, the same SSRF-safe/bounded boundary `services/image_intelligence.py`
       already uses; never a second, divergent network-safety implementation - S41)
    4. resolution failure - `MediaResolutionOutcome.failed` is `True`; the caller must route this
       to recovery, never to an ordinary text send (S7/S17/S18).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from schemas.media_subject_match import DiscoveryTier, MediaSelectionResult, ResolvedMediaCandidate
from services.editorial_pipeline.contracts import MediaAssetResolutionMethod, SelectedMediaAsset
from services.image_persistence import EditorialImageCandidate, read_candidate_bytes

logger = logging.getLogger(__name__)

DEFAULT_BOUNDED_DOWNLOAD_CACHE_DIR = Path("var") / "media_research_cache"
"""S13's own "bounded" requirement, applied to resolution-time downloads too - reuses
`services.media_download_cache.DEFAULT_POLICY` (timeouts/redirects/max_bytes already bounded
there, never re-specified here) rather than inventing a second download policy."""


@dataclass(frozen=True)
class MediaResolutionOutcome:
    asset: SelectedMediaAsset | None
    failed: bool
    failure_detail: str | None = None

    @property
    def is_ready(self) -> bool:
        return not self.failed and self.asset is not None and self.asset.photo_input_ready


def _asset_from_candidate_metadata(
    candidate: ResolvedMediaCandidate, *, resolution_method: MediaAssetResolutionMethod,
    telegram_file_id: str | None = None, resolved_bytes: bytes | None = None,
    mime_type: str | None = None, width: int | None = None, height: int | None = None,
    sha256: str | None = None,
) -> SelectedMediaAsset:
    return SelectedMediaAsset(
        candidate_id=candidate.candidate_id,
        resolution_method=resolution_method,
        source_url=candidate.provenance.asset_url,
        origin_url=candidate.provenance.origin_url,
        discovery_tier=candidate.provenance.discovery_tier,
        usage_classification=candidate.usage_classification,
        subject_match=candidate.subject_match.subject_match if candidate.subject_match else None,
        subject_confidence=candidate.subject_match.confidence if candidate.subject_match else None,
        telegram_file_id=telegram_file_id,
        resolved_bytes=resolved_bytes,
        mime_type=mime_type,
        width=width or candidate.width,
        height=height or candidate.height,
        sha256=sha256 or candidate.sha256,
    )


async def resolve_selected_media_asset(
    media_selection: MediaSelectionResult, *,
    legacy_candidates_by_id: dict[str, EditorialImageCandidate] | None = None,
    allow_bounded_download: bool = False,
    download_cache_dir: Path = DEFAULT_BOUNDED_DOWNLOAD_CACHE_DIR,
) -> MediaResolutionOutcome:
    """Resolves EXACTLY `media_selection.selected` - the one candidate `MediaResearchService`
    actually chose. Returns `failed=True` (never a substitute image) when nothing usable can be
    produced for that specific candidate. `legacy_candidates_by_id` must be keyed by the SAME
    `image_candidate_record_id` the caller used to build the tier1 pool passed into
    `MediaResearchService.research()` - looking the record up again here (rather than re-querying
    the DB) is what makes it structurally impossible for this function to accidentally resolve a
    DIFFERENT candidate than the one that was actually selected.

    `allow_bounded_download` defaults to `False` (production-safe default, matching every other
    new network capability this phase introduces - S13/S41): a Tier 2-5 candidate with no legacy
    record and no local bytes fails resolution rather than silently reaching out to the network
    unless a caller has explicitly opted in."""
    selected = media_selection.selected
    if selected is None:
        return MediaResolutionOutcome(asset=None, failed=False)  # nothing selected - not a
        # resolution failure; the orchestrator's own require_media/DATA_TYPOGRAPHIC logic already
        # decided whether that is acceptable BEFORE this function is ever called.

    legacy_record = (
        legacy_candidates_by_id.get(selected.image_candidate_record_id)
        if legacy_candidates_by_id and selected.image_candidate_record_id else None
    )

    if legacy_record is not None:
        if legacy_record.telegram_file_id:
            logger.info(
                "media_asset_resolved",
                extra={"candidate_id": selected.candidate_id, "method": MediaAssetResolutionMethod.TELEGRAM_FILE_ID.value},
            )
            return MediaResolutionOutcome(
                asset=_asset_from_candidate_metadata(
                    selected, resolution_method=MediaAssetResolutionMethod.TELEGRAM_FILE_ID,
                    telegram_file_id=legacy_record.telegram_file_id,
                    mime_type=legacy_record.observed_mime, width=legacy_record.width, height=legacy_record.height,
                ),
                failed=False,
            )
        data = read_candidate_bytes(legacy_record)
        if data is not None:
            logger.info(
                "media_asset_resolved",
                extra={"candidate_id": selected.candidate_id, "method": MediaAssetResolutionMethod.LOCAL_STORAGE_BYTES.value},
            )
            return MediaResolutionOutcome(
                asset=_asset_from_candidate_metadata(
                    selected, resolution_method=MediaAssetResolutionMethod.LOCAL_STORAGE_BYTES,
                    resolved_bytes=data, mime_type=legacy_record.observed_mime,
                    width=legacy_record.width, height=legacy_record.height,
                ),
                failed=False,
            )
        # A legacy record exists but neither a file_id nor local bytes resolved - Case A exactly.
        # Never fall through to an ordinary text send; a Tier-1 candidate has no safe network
        # download target of its own (its "asset_url" is the ORIGINATING ARTICLE's own image URL,
        # already known to be unreadable via the app's own storage - re-downloading it bypasses
        # nothing that already failed for a real reason, e.g. the storage row expired on purpose).
        detail = f"candidate {selected.candidate_id}: legacy record has neither telegram_file_id nor readable local bytes"
        logger.warning("media_asset_resolution_failed", extra={"candidate_id": selected.candidate_id, "detail": detail})
        return MediaResolutionOutcome(asset=None, failed=True, failure_detail=detail)

    if selected.local_path:
        try:
            data = Path(selected.local_path).read_bytes()
        except OSError:
            data = None
        if data is not None:
            return MediaResolutionOutcome(
                asset=_asset_from_candidate_metadata(
                    selected, resolution_method=MediaAssetResolutionMethod.LOCAL_STORAGE_BYTES, resolved_bytes=data,
                ),
                failed=False,
            )

    if allow_bounded_download and selected.provenance.discovery_tier != DiscoveryTier.TIER1_CURRENT_SOURCE:
        from services.media_download_cache import download_and_validate

        outcome = await download_and_validate(selected.provenance.asset_url, cache_dir=download_cache_dir)
        if outcome.ok and outcome.local_path:
            try:
                data = Path(outcome.local_path).read_bytes()
            except OSError:
                data = None
            if data is not None:
                logger.info(
                    "media_asset_resolved",
                    extra={"candidate_id": selected.candidate_id, "method": MediaAssetResolutionMethod.BOUNDED_DOWNLOAD.value},
                )
                return MediaResolutionOutcome(
                    asset=_asset_from_candidate_metadata(
                        selected, resolution_method=MediaAssetResolutionMethod.BOUNDED_DOWNLOAD,
                        resolved_bytes=data, width=outcome.width, height=outcome.height, sha256=outcome.sha256,
                    ),
                    failed=False,
                )
        detail = f"candidate {selected.candidate_id}: bounded download failed ({outcome.error_code})"
        logger.warning("media_asset_resolution_failed", extra={"candidate_id": selected.candidate_id, "detail": detail})
        return MediaResolutionOutcome(asset=None, failed=True, failure_detail=detail)

    detail = f"candidate {selected.candidate_id}: no legacy record, no local_path, bounded download not permitted"
    logger.warning("media_asset_resolution_failed", extra={"candidate_id": selected.candidate_id, "detail": detail})
    return MediaResolutionOutcome(asset=None, failed=True, failure_detail=detail)
