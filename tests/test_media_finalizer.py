"""PRODUCTION-SOURCE-RECONCILIATION-1: services/media_finalizer.py tests - the single MEDIA-PROD-1
choke point recovered from the accepted production source (feature/prod-content-recap-release @
250da40). Verifies the real branding/fail-soft/gate contract in isolation from resolve_photo_input()
and apply_master_news_branding()'s own already-tested implementations."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from aiogram.types import BufferedInputFile

from core.config import settings
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
