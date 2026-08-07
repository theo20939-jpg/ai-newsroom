"""Phase 19 M10: services.video_discovery_persistence - fake-session unit tests, mirrors tests/
test_editorial_plan_persistence.py's own established pattern.
"""
from __future__ import annotations

import uuid

import pytest

from schemas.video_candidate import (
    NativeVideoHint,
    VideoDiscoveryMethod,
    VideoPlatform,
    VideoValidation,
    VideoValidationStatus,
)
from services.video_discovery_persistence import persist_video_hint, unvalidated_hosted_platform_result


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, row: object) -> None:
        self.added.append(row)


@pytest.mark.asyncio
async def test_persists_direct_hosted_video_with_validation_result() -> None:
    session = _FakeSession()
    event_id = uuid.uuid4()
    hint = NativeVideoHint(
        discovery_method=VideoDiscoveryMethod.OPEN_GRAPH_VIDEO_SECURE, remote_url="https://cdn.example.com/clip.mp4",
        platform=VideoPlatform.DIRECT_HOSTED, declared_width=1280, declared_height=720,
    )
    validation = VideoValidation(status=VideoValidationStatus.VALID, detected_container="mp4", byte_size=5000)

    await persist_video_hint(session, event_id=event_id, hint=hint, validation=validation)

    assert len(session.added) == 1
    row = session.added[0]
    assert row.event_id == event_id
    assert row.media_type == "video"
    assert row.remote_url == "https://cdn.example.com/clip.mp4"
    assert row.platform == "direct_hosted"
    assert row.validation_status == "valid"
    assert row.detected_container == "mp4"
    assert row.byte_size == 5000


@pytest.mark.asyncio
async def test_persists_youtube_hint_as_unvalidated_hosted_platform() -> None:
    session = _FakeSession()
    hint = NativeVideoHint(
        discovery_method=VideoDiscoveryMethod.HOSTED_PLATFORM_LINK_IN_ARTICLE,
        remote_url="https://www.youtube.com/watch?v=abc123", platform=VideoPlatform.YOUTUBE,
    )

    await persist_video_hint(
        session, event_id=uuid.uuid4(), hint=hint, validation=unvalidated_hosted_platform_result(),
    )

    row = session.added[0]
    assert row.validation_status == "unvalidated_hosted_platform"
    assert row.detected_container is None
    assert row.byte_size is None


@pytest.mark.asyncio
async def test_content_draft_id_defaults_to_none() -> None:
    session = _FakeSession()
    hint = NativeVideoHint(
        discovery_method=VideoDiscoveryMethod.HTML_VIDEO_TAG, remote_url="https://cdn.example.com/clip.mp4",
        platform=VideoPlatform.DIRECT_HOSTED,
    )

    await persist_video_hint(
        session, event_id=uuid.uuid4(), hint=hint,
        validation=VideoValidation(status=VideoValidationStatus.REJECTED, error_code="signature_mismatch"),
    )

    assert session.added[0].content_draft_id is None
