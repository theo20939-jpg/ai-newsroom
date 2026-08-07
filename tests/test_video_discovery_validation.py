"""Phase 19 M10: services.video_discovery.validate_direct_hosted_video() - mocks safe_fetch()
directly (no real network), mirrors this codebase's own unit-test-level mocking convention for
functions whose only external dependency is a single safe_fetch() call.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from integrations.http.safe_fetch import FetchErrorCode, SafeFetchError, SafeFetchPolicy, SafeFetchResult
from schemas.video_candidate import VideoValidationStatus
from services.video_discovery import validate_direct_hosted_video

_POLICY = SafeFetchPolicy(
    connect_timeout_seconds=3.0, read_timeout_seconds=8.0, total_timeout_seconds=15.0,
    max_redirects=3, max_bytes=20_000_000,
)


def _fake_result(body: bytes) -> SafeFetchResult:
    return SafeFetchResult(
        requested_url="https://cdn.example.com/clip.mp4", final_url="https://cdn.example.com/clip.mp4",
        status_code=200, redirect_count=0, declared_content_type="video/mp4",
        received_byte_count=len(body), duration_seconds=0.1, body=body,
    )


@pytest.mark.asyncio
async def test_valid_mp4_bytes_are_accepted() -> None:
    body = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100
    with patch("services.video_discovery.safe_fetch", new=AsyncMock(return_value=_fake_result(body))):
        result = await validate_direct_hosted_video("https://cdn.example.com/clip.mp4", policy=_POLICY)
    assert result.status == VideoValidationStatus.VALID
    assert result.detected_container == "mp4"
    assert result.byte_size == len(body)


@pytest.mark.asyncio
async def test_valid_webm_bytes_are_accepted() -> None:
    body = b"\x1a\x45\xdf\xa3" + b"\x00" * 100
    with patch("services.video_discovery.safe_fetch", new=AsyncMock(return_value=_fake_result(body))):
        result = await validate_direct_hosted_video("https://cdn.example.com/clip.webm", policy=_POLICY)
    assert result.status == VideoValidationStatus.VALID
    assert result.detected_container == "webm_mkv"


@pytest.mark.asyncio
async def test_non_video_bytes_are_rejected() -> None:
    body = b"<html>this is not a video</html>"
    with patch("services.video_discovery.safe_fetch", new=AsyncMock(return_value=_fake_result(body))):
        result = await validate_direct_hosted_video("https://cdn.example.com/fake.mp4", policy=_POLICY)
    assert result.status == VideoValidationStatus.REJECTED
    assert result.error_code == "signature_mismatch"


@pytest.mark.asyncio
async def test_fetch_failure_is_rejected_with_structured_error_code() -> None:
    error = SafeFetchError(FetchErrorCode.TOTAL_TIMEOUT, "took too long")
    with patch("services.video_discovery.safe_fetch", new=AsyncMock(side_effect=error)):
        result = await validate_direct_hosted_video("https://cdn.example.com/clip.mp4", policy=_POLICY)
    assert result.status == VideoValidationStatus.REJECTED
    assert result.error_code == "total_timeout"
