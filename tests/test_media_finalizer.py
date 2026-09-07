"""PRODUCTION-SOURCE-RECONCILIATION-1: services/media_finalizer.py tests - the single MEDIA-PROD-1
choke point recovered from the accepted production source (feature/prod-content-recap-release @
250da40). Verifies the real branding/fail-soft/gate contract in isolation from resolve_photo_input()
and apply_master_news_branding()'s own already-tested implementations.

VISUAL-SINGLE-BRAND-MARK-ROLLUP-DEPLOY-1 §8 adds one real, unmocked, end-to-end proof: the JPEG-
comment finalization marker (services/nnj_master_news_overlay.py's own idempotency mechanism) must
survive the ACTUAL supported in-process path a second finalization would take - real bytes through
real storage, resolve_photo_input() and apply_master_news_branding() both UNMOCKED - not merely
asserted at the unit level where those two functions are stubbed out."""
from __future__ import annotations

import hashlib
import io
import uuid
from unittest.mock import MagicMock, patch

import pytest
from aiogram.types import BufferedInputFile
from PIL import Image

from core.config import settings
from database.models.image_candidate_record import ImageStorageStatus
from services import image_persistence
from services.image_persistence import EditorialImageCandidate
from services.media_finalizer import finalize_photo_input


@pytest.fixture(autouse=True)
def _enforce_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "presentation_director_mode", "enforce")
    monkeypatch.setattr(settings, "pulse_brand_enabled", True)


def test_gate_off_passes_through_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "presentation_director_mode", "off")
    original = BufferedInputFile(b"raw-bytes", filename="preview.jpg")
    with patch("services.media_finalizer.resolve_photo_input", return_value=original) as mock_resolve, \
         patch("services.media_finalizer.apply_master_news_branding") as mock_brand:
        result = finalize_photo_input(MagicMock())
    mock_resolve.assert_called_once()
    mock_brand.assert_not_called()
    assert result is original


def test_cached_file_id_is_never_branded() -> None:
    """A cached Telegram file_id (a plain string) has no local bytes to composite onto - passed
    through exactly like the router's own accepted "cached_file_id_no_local_bytes" exception."""
    with patch("services.media_finalizer.resolve_photo_input", return_value="cached-file-id-123") as mock_resolve, \
         patch("services.media_finalizer.apply_master_news_branding") as mock_brand:
        result = finalize_photo_input(MagicMock())
    mock_resolve.assert_called_once()
    mock_brand.assert_not_called()
    assert result == "cached-file-id-123"


def test_none_is_never_branded() -> None:
    with patch("services.media_finalizer.resolve_photo_input", return_value=None), \
         patch("services.media_finalizer.apply_master_news_branding") as mock_brand:
        result = finalize_photo_input(MagicMock())
    mock_brand.assert_not_called()
    assert result is None


def test_local_bytes_are_branded_when_gate_enabled() -> None:
    original = BufferedInputFile(b"raw-bytes", filename="preview.jpg")
    with patch("services.media_finalizer.resolve_photo_input", return_value=original), \
         patch("services.media_finalizer.apply_master_news_branding", return_value=(b"branded-bytes", MagicMock())) as mock_brand:
        result = finalize_photo_input(MagicMock())
    mock_brand.assert_called_once_with(b"raw-bytes")
    assert isinstance(result, BufferedInputFile)
    assert result.data == b"branded-bytes"
    assert result.filename == "preview.jpg"


def test_branding_failure_falls_back_to_original_never_raises() -> None:
    original = BufferedInputFile(b"raw-bytes", filename="preview.jpg")
    with patch("services.media_finalizer.resolve_photo_input", return_value=original), \
         patch("services.media_finalizer.apply_master_news_branding", side_effect=RuntimeError("boom")):
        result = finalize_photo_input(MagicMock())
    assert result is original


def _store_candidate(data: bytes) -> EditorialImageCandidate:
    """Real storage round-trip (no mocking) - mirrors tests/test_final_post_review_notifier.py's
    own established `_branded_fallback_media_plan()` pattern for constructing a real, storage-
    backed candidate."""
    sha256 = hashlib.sha256(data).hexdigest()
    stored = image_persistence._get_storage().store_validated_image(
        data, sha256=sha256, image_format="JPEG", max_bytes=10_000_000,
    )
    return EditorialImageCandidate(
        id=uuid.uuid4(), candidate_id=str(uuid.uuid4()), rank=1, relevance_score=90, quality_score=90,
        discovery_method="test", source_relationship=None, relevance_reason=None, width=1280, height=720,
        observed_mime="image/jpeg", image_format="JPEG", storage_status=ImageStorageStatus.STORED.value,
        storage_key=stored.storage_key, telegram_file_id=None, editor_decision=None, source_url=None,
        article_url=None, warnings=None, is_expired=False, sha256=stored.sha256,
    )


def _quiet_photo_bytes() -> bytes:
    im = Image.new("RGB", (1280, 720), (120, 120, 120))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def test_finalization_marker_survives_the_real_in_process_finalizer_path() -> None:
    """VISUAL-SINGLE-BRAND-MARK-ROLLUP-DEPLOY-1 §8: real storage, real resolve_photo_input(), real
    apply_master_news_branding() - nothing mocked except the settings gate (already-established
    autouse fixture above). Proves the JPEG comment marker is not stripped by any step of the
    ACTUAL finalize_photo_input() -> storage round-trip -> finalize_photo_input() again path a
    second finalization of already-branded content would really take."""
    raw_candidate = _store_candidate(_quiet_photo_bytes())

    first_result = finalize_photo_input(raw_candidate)
    assert isinstance(first_result, BufferedInputFile)
    branded_once = first_result.data
    # A real mark was actually placed on this quiet photo - not a NO_OVERLAY_SAFETY case, so the
    # idempotency guarantee below is being tested against a genuinely branded image.
    assert branded_once != _quiet_photo_bytes()

    # Round-trip the ALREADY-BRANDED bytes back through the same real storage a second candidate
    # would use - proves no storage-layer re-encode strips the marker (services/image_persistence.py
    # ::read_candidate_bytes() / integrations/storage/image_storage.py::LocalImageStorage are both
    # raw-byte passthroughs, confirmed by direct source inspection - this test proves it, not just
    # asserts it from reading the source).
    already_finalized_candidate = _store_candidate(branded_once)

    second_result = finalize_photo_input(already_finalized_candidate)
    assert isinstance(second_result, BufferedInputFile)
    # Byte-identical: the marker was recognized, apply_master_news_branding() short-circuited, no
    # second mark was composited.
    assert second_result.data == branded_once

    third_result = finalize_photo_input(_store_candidate(second_result.data))
    assert isinstance(third_result, BufferedInputFile)
    assert third_result.data == branded_once
