"""UNIFIED-EDITORIAL-PIPELINE-RUNTIME-CLOSURE-1 (S3.1/S33) - the explicit same-asset invariant
test: PRE_MEDIA_CANDIDATE=A (a legacy-top-ranked, WRONG candidate) vs MEDIA_RESEARCH_WINNER=B
(the actually-selected candidate) must never leak into each other at render time. This test
targets `services.editorial_pipeline.telegram_integration._make_render_callback()` directly - the
EXACT function where the Founder audit's pre-selection-byte-capture bug lived - rather than only
the lower-level `media_asset_resolver` unit tests (already covered separately), so a regression
that reintroduces closing over the wrong candidate fails here specifically.

Also covers replays R4 (missing local storage, valid Telegram file_id -> visual still delivered)
and R5 (missing local storage, no file_id -> HOLD via MediaResolutionFailure, never text-only)."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from aiogram.types import BufferedInputFile

from schemas.media_subject_match import (
    DiscoveryTier,
    MediaProvenance,
    MediaSelectionResult,
    MediaUsageClassification,
    ResolvedMediaCandidate,
)
from services.editorial_pipeline.contracts import (
    CompositionPlan,
    MediaResolutionFailure,
    PresentationFormat,
    StructuredNewsContent,
)
from services.editorial_pipeline.telegram_integration import _make_render_callback
from services.image_persistence import EditorialImageCandidate

pytestmark = pytest.mark.asyncio


def _legacy(*, telegram_file_id: str | None, storage_key: str | None) -> tuple[EditorialImageCandidate, str]:
    row_id = uuid4()
    candidate = EditorialImageCandidate(
        id=row_id, candidate_id=f"legacy-{row_id}", rank=1, relevance_score=90, quality_score=90,
        discovery_method="og_image", source_relationship="original_article", relevance_reason="high overlap",
        width=1200, height=800, observed_mime="image/jpeg", image_format="JPEG",
        storage_status="stored", storage_key=storage_key, telegram_file_id=telegram_file_id,
        editor_decision=None, source_url="https://example.com/img.jpg", article_url="https://example.com/article",
        warnings=None, is_expired=False, sha256=None, perceptual_hash=None, final_url=None,
    )
    return candidate, str(row_id)


def _resolved(record_id: str, candidate_id: str) -> ResolvedMediaCandidate:
    return ResolvedMediaCandidate(
        candidate_id=candidate_id,
        provenance=MediaProvenance(
            origin_url="https://example.com/a", asset_url="https://example.com/a.jpg",
            discovered_at=datetime.now(timezone.utc), discovery_tier=DiscoveryTier.TIER1_CURRENT_SOURCE,
        ),
        usage_classification=MediaUsageClassification.APPROVED_SOURCE_MEDIA,
        image_candidate_record_id=record_id,
    )


def _news_plan() -> CompositionPlan:
    return CompositionPlan(
        presentation_format=PresentationFormat.NEWS, data_strategy=None, photo_input=None,
        media_group_items=(), caption_position="BELOW", branding_strength="STANDARD",
    )


def _news_content() -> StructuredNewsContent:
    return StructuredNewsContent(headline="Headline", body="Body", ending=None, evidence_claim_ids=())


def _callback(legacy_candidates_by_id: dict[str, EditorialImageCandidate]):
    return _make_render_callback(
        legacy_candidates_by_id=legacy_candidates_by_id, copywriting_output={"main_body": "Body"},
        treatment="STANDARD", quote_text=None, quote_speaker=None, category="tech", editorial_code="EC1",
    )


async def test_same_asset_invariant_renders_the_winner_never_the_pre_ranked_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PRE_MEDIA_CANDIDATE = A (legacy-top-ranked, wrong subject).
    MEDIA_RESEARCH_WINNER = B (the real selection).
    SELECTED/RESOLVED/RENDERED must all trace to B - A must never leak in."""
    candidate_a, record_id_a = _legacy(telegram_file_id="FILE_ID_A_WRONG", storage_key="a/key.jpg")
    candidate_b, record_id_b = _legacy(telegram_file_id="FILE_ID_B_CORRECT", storage_key="b/key.jpg")
    legacy_candidates_by_id = {record_id_a: candidate_a, record_id_b: candidate_b}

    # MediaResearchService's own real winner - B, identified ONLY by image_candidate_record_id.
    media_selection = MediaSelectionResult(
        intent_primary_entity="x", selected=_resolved(record_id_b, "resolved-b"), selected_score=90.0,
        exact_subject_media_not_found=False, fallback_used=False, candidates_considered=2,
    )

    render = _callback(legacy_candidates_by_id)
    photo_input, _html = await render(_news_plan(), _news_content(), media_selection)

    assert photo_input == "FILE_ID_B_CORRECT"
    assert photo_input != "FILE_ID_A_WRONG"  # A must never leak into the render output


async def test_same_asset_invariant_holds_even_when_a_was_the_only_candidate_originally_ranked_first(
) -> None:
    """A stronger form of the same test: A is legacy rank 1 (would have been the ONLY candidate
    under the old `limit=1` pre-selection bug), but MediaResearchService's real winner is B - proves
    the render callback never falls back to "whatever legacy ranking put first" when a different
    candidate was actually selected."""
    candidate_a, record_id_a = _legacy(telegram_file_id="FILE_ID_A_WRONG", storage_key=None)
    candidate_b, record_id_b = _legacy(telegram_file_id=None, storage_key="b/key.jpg")
    legacy_candidates_by_id = {record_id_a: candidate_a, record_id_b: candidate_b}

    media_selection = MediaSelectionResult(
        intent_primary_entity="x", selected=_resolved(record_id_b, "resolved-b"), selected_score=90.0,
        exact_subject_media_not_found=False, fallback_used=False, candidates_considered=2,
    )
    render = _callback(legacy_candidates_by_id)

    def _fake_branding(photo_bytes, disable_lower_signature=False):
        assert photo_bytes == b"B-BYTES"  # must be B's bytes, never A's file_id/bytes
        return b"branded-B-bytes", None

    import services.editorial_pipeline.telegram_integration as ti_module
    import services.editorial_pipeline.media_asset_resolver as resolver_module

    def _fake_read_bytes(candidate):
        if candidate.storage_key == "b/key.jpg":
            return b"B-BYTES"
        raise AssertionError("must never read A's bytes when B was selected")

    orig_read = resolver_module.read_candidate_bytes
    orig_brand = ti_module.apply_master_news_branding
    resolver_module.read_candidate_bytes = _fake_read_bytes  # type: ignore[assignment]
    ti_module.apply_master_news_branding = _fake_branding  # type: ignore[assignment]
    try:
        photo_input, _html = await render(_news_plan(), _news_content(), media_selection)
    finally:
        resolver_module.read_candidate_bytes = orig_read  # type: ignore[assignment]
        ti_module.apply_master_news_branding = orig_brand  # type: ignore[assignment]

    assert isinstance(photo_input, BufferedInputFile)


# ---------------------------------------------------------------------------
# R4/R5 - resolution outcomes for the render callback itself.
# ---------------------------------------------------------------------------


async def test_r4_missing_local_storage_valid_file_id_still_delivers() -> None:
    candidate, record_id = _legacy(telegram_file_id="VALID_CACHED_FILE_ID", storage_key=None)
    media_selection = MediaSelectionResult(
        intent_primary_entity="x", selected=_resolved(record_id, "cand-1"), selected_score=50.0,
        exact_subject_media_not_found=False, fallback_used=False, candidates_considered=1,
    )
    render = _callback({record_id: candidate})
    result = await render(_news_plan(), _news_content(), media_selection)
    assert result != (None, result[1] if isinstance(result, tuple) else None)  # not a text-only outcome
    photo_input, _html = result
    assert photo_input == "VALID_CACHED_FILE_ID"


async def test_r5_missing_local_storage_no_file_id_holds_never_text_only(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate, record_id = _legacy(telegram_file_id=None, storage_key="gone/key.jpg")
    monkeypatch.setattr("services.editorial_pipeline.media_asset_resolver.read_candidate_bytes", lambda c: None)
    media_selection = MediaSelectionResult(
        intent_primary_entity="x", selected=_resolved(record_id, "cand-1"), selected_score=50.0,
        exact_subject_media_not_found=False, fallback_used=False, candidates_considered=1,
    )
    render = _callback({record_id: candidate})
    result = await render(_news_plan(), _news_content(), media_selection)
    assert isinstance(result, MediaResolutionFailure)  # never (None, html) - never a text-only send
