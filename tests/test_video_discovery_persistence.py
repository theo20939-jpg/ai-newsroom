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
from services.video_discovery_persistence import (
    EligibleVideoCandidate,
    persist_video_hint,
    to_native_video_hint,
    unvalidated_hosted_platform_result,
)


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


# ---------------------------------------------------------------------------------------------
# Production wiring (docs/video_delivery_wiring_checkpoint.md): to_native_video_hint() converts
# the read contract (EligibleVideoCandidate) back into the pydantic/enum shape build_rich_media_
# plan() expects.
# ---------------------------------------------------------------------------------------------


def _eligible_candidate(**overrides: object) -> EligibleVideoCandidate:
    base: dict[str, object] = dict(
        id=uuid.uuid4(), event_id=uuid.uuid4(), content_draft_id=None,
        discovery_method="open_graph_video_secure", remote_url="https://cdn.example.com/clip.mp4",
        platform="direct_hosted", declared_width=1280, declared_height=720,
        declared_mime_type="video/mp4", declared_duration_seconds=30,
        validation_status="valid", detected_container="mp4", byte_size=5000, error_code=None,
    )
    base.update(overrides)
    return EligibleVideoCandidate(**base)  # type: ignore[arg-type]


def test_to_native_video_hint_converts_a_valid_direct_hosted_candidate() -> None:
    candidate = _eligible_candidate()

    hint = to_native_video_hint(candidate)

    assert hint is not None
    assert hint.discovery_method == VideoDiscoveryMethod.OPEN_GRAPH_VIDEO_SECURE
    assert hint.remote_url == "https://cdn.example.com/clip.mp4"
    assert hint.platform == VideoPlatform.DIRECT_HOSTED
    assert hint.declared_width == 1280
    assert hint.declared_height == 720
    assert hint.declared_mime_type == "video/mp4"
    assert hint.declared_duration_seconds == 30


def test_to_native_video_hint_converts_a_youtube_candidate() -> None:
    candidate = _eligible_candidate(
        discovery_method="hosted_platform_link_in_article",
        remote_url="https://www.youtube.com/watch?v=abc123", platform="youtube",
        declared_width=None, declared_height=None, declared_mime_type=None,
        declared_duration_seconds=None, validation_status="unvalidated_hosted_platform",
        detected_container=None, byte_size=None,
    )

    hint = to_native_video_hint(candidate)

    assert hint is not None
    assert hint.platform == VideoPlatform.YOUTUBE
    assert hint.remote_url == "https://www.youtube.com/watch?v=abc123"


def test_to_native_video_hint_returns_none_for_an_unrecognized_platform_value() -> None:
    """A stored value that no longer maps onto a known VideoPlatform member (e.g. a future
    migration, manual data edit, or schema drift) must degrade to "no video", never raise."""
    candidate = _eligible_candidate(platform="some_future_platform")

    assert to_native_video_hint(candidate) is None


def test_to_native_video_hint_returns_none_for_an_unrecognized_discovery_method_value() -> None:
    candidate = _eligible_candidate(discovery_method="some_future_method")

    assert to_native_video_hint(candidate) is None


# ---------------------------------------------------------------------------------------------
# Phase V2.27A TEST 7 - select_best_video_candidate(): DIRECT_HOSTED > YOUTUBE/VIMEO >
# EMBEDDED_PLAYER resolution order.
# ---------------------------------------------------------------------------------------------


def test_direct_hosted_preferred_over_youtube_and_embedded_player() -> None:
    from services.video_discovery_persistence import select_best_video_candidate

    direct = _eligible_candidate(platform="direct_hosted", remote_url="https://cdn.example.com/a.mp4")
    youtube = _eligible_candidate(platform="youtube", remote_url="https://www.youtube.com/watch?v=abc123")
    embedded = _eligible_candidate(platform="embedded_player", remote_url="https://player.example.com/embed/1")

    # Order in the input list must not matter - only platform-tier priority does.
    assert select_best_video_candidate([youtube, embedded, direct]) is direct
    assert select_best_video_candidate([embedded, direct, youtube]) is direct


def test_youtube_or_vimeo_preferred_over_embedded_player_when_no_direct_hosted() -> None:
    """TEST 8 (Phase V2.27A spec): YouTube/Vimeo behavior unchanged - still outranks the new
    EMBEDDED_PLAYER tier when no DIRECT_HOSTED candidate exists for this event."""
    from services.video_discovery_persistence import select_best_video_candidate

    vimeo = _eligible_candidate(platform="vimeo", remote_url="https://vimeo.com/76979871")
    embedded = _eligible_candidate(platform="embedded_player", remote_url="https://player.example.com/embed/1")

    assert select_best_video_candidate([embedded, vimeo]) is vimeo


def test_embedded_player_selected_only_when_nothing_stronger_available() -> None:
    from services.video_discovery_persistence import select_best_video_candidate

    embedded = _eligible_candidate(platform="embedded_player", remote_url="https://player.example.com/embed/1")

    assert select_best_video_candidate([embedded]) is embedded


def test_ties_within_a_tier_resolve_to_earliest_discovered() -> None:
    """Mirrors get_video_candidates_for_event()'s own created_at-ascending ordering - the first
    item in the input list, within the same priority tier, wins (stable, never re-sorted)."""
    from services.video_discovery_persistence import select_best_video_candidate

    first = _eligible_candidate(platform="youtube", remote_url="https://www.youtube.com/watch?v=first")
    second = _eligible_candidate(platform="vimeo", remote_url="https://vimeo.com/22222")

    assert select_best_video_candidate([first, second]) is first


def test_empty_candidate_list_returns_none() -> None:
    from services.video_discovery_persistence import select_best_video_candidate

    assert select_best_video_candidate([]) is None


def test_unrecognized_platform_value_sorts_last_never_raises() -> None:
    from services.video_discovery_persistence import select_best_video_candidate

    unknown = _eligible_candidate(platform="some_future_platform")
    embedded = _eligible_candidate(platform="embedded_player")

    assert select_best_video_candidate([unknown, embedded]) is embedded
