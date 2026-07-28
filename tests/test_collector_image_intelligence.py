"""Tests for services.collector._log_image_intelligence (Phase 16 M1, docs/
phase16_m1_native_media_ingestion_report.md). Unit-level, exercising the private helper directly
- mirrors tests/test_telegram_source.py's own precedent of testing a private, focused function
directly rather than only through the full run_collection_cycle() integration surface.
"""
import logging
from uuid import uuid4

import pytest

from core.config import settings
from database.models.news_source import SourceType
from schemas.image_candidate import ImageDiscoveryMethod, NativeMediaHint
from services.collector import _log_image_intelligence


def test_mode_off_logs_nothing(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(settings, "image_intelligence_mode", "off")
    hint = NativeMediaHint(discovery_method=ImageDiscoveryMethod.RSS_INLINE_IMAGE, remote_url="https://x/y.jpg")

    with caplog.at_level(logging.INFO, logger="services.collector"):
        _log_image_intelligence(uuid4(), SourceType.RSS, [hint])

    assert "image_intelligence_candidates_discovered" not in caplog.text


def test_mode_shadow_logs_candidate_counts(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(settings, "image_intelligence_mode", "shadow")
    hint = NativeMediaHint(discovery_method=ImageDiscoveryMethod.RSS_INLINE_IMAGE, remote_url="https://x/y.jpg")

    with caplog.at_level(logging.INFO, logger="services.collector"):
        _log_image_intelligence(uuid4(), SourceType.RSS, [hint])

    assert "image_intelligence_candidates_discovered" in caplog.text


def test_mode_shadow_with_no_hints_still_logs_zero_counts(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(settings, "image_intelligence_mode", "shadow")

    with caplog.at_level(logging.INFO, logger="services.collector"):
        _log_image_intelligence(uuid4(), SourceType.TELEGRAM, [])

    assert "image_intelligence_candidates_discovered" in caplog.text


def test_consolidation_failure_is_swallowed_not_raised(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Non-blocking: a broken hint/consolidation error must never propagate out of the Collector's
    per-item processing loop."""
    monkeypatch.setattr(settings, "image_intelligence_mode", "shadow")

    def _broken_consolidate(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("services.collector.consolidate_candidates", _broken_consolidate)

    with caplog.at_level(logging.WARNING, logger="services.collector"):
        _log_image_intelligence(uuid4(), SourceType.RSS, [])  # must not raise

    assert "image_intelligence_collector_logging_failed" in caplog.text
