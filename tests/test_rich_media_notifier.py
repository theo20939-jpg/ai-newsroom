"""Phase 19 M12: services.image_preview_notifier's rich-media (multi-photo/mixed-media) delivery
extension. Same FakeSession/db_session/tmp_path-storage technique as tests/
test_image_preview_notifier.py - no real Telegram API call.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMediaGroup, SendPhoto, TelegramMethod
from aiogram.types import Chat, InputMediaPhoto
from aiogram.types import Message as AiogramMessage
from aiogram.types import PhotoSize
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.content_draft import ContentDraft, ContentType
from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.image_candidate_record import ImageCandidateRecord, ImageStorageStatus
from database.models.news_event import NewsEvent
from database.models.news_source import SourceType
from integrations.storage.image_storage import LocalImageStorage
from schemas.content_draft import ContentDraftRead
from schemas.video_candidate import NativeVideoHint, VideoDiscoveryMethod, VideoPlatform
from services import image_persistence
from services.image_persistence import get_editorial_image_candidates
from services.image_preview_notifier import build_rich_media_plan, send_news_with_rich_media

_FAKE_TOKEN = "123456:FAKE-TEST-TOKEN-AAAAAAAAAAAAAAAAAAAAAAAAAAAA"


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[TelegramMethod] = []
        self.fail = False

    async def close(self) -> None:
        pass

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None) -> object:
        if self.fail:
            raise TelegramBadRequest(method=method, message="Bad Request: simulated failure")
        self.sent.append(method)
        if isinstance(method, SendMediaGroup):
            return [
                AiogramMessage(
                    message_id=100 + i, date=datetime.now(timezone.utc),
                    chat=Chat(id=method.chat_id, type="private"),
                    photo=[PhotoSize(file_id=f"fake-file-id-{i}", file_unique_id="u", width=10, height=10)],
                )
                for i in range(len(method.media))
            ]
        if isinstance(method, SendPhoto):
            return AiogramMessage(
                message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=method.chat_id, type="private"),
                caption=method.caption,
                photo=[PhotoSize(file_id="fake-file-id-1", file_unique_id="u", width=10, height=10)],
            )
        raise NotImplementedError(f"FakeSession cannot handle {type(method)}")

    async def stream_content(self, *args: object, **kwargs: object) -> object:
        raise NotImplementedError


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)
    yield
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)


async def _make_task_and_draft(db_session: AsyncSession, real_news_event: NewsEvent) -> tuple[EditorialTask, ContentDraftRead]:
    task = EditorialTask(event_id=real_news_event.id, priority=TaskPriority.B)
    db_session.add(task)
    await db_session.flush()
    draft = ContentDraft(
        task_id=task.id, type=ContentType.POST, title="Draft Title",
        body="Draft body text for the rich-media test.", hashtags=None,
    )
    db_session.add(draft)
    await db_session.flush()
    draft_read = ContentDraftRead(
        id=draft.id, task_id=draft.task_id, type=draft.type, title=draft.title, body=draft.body,
        hashtags=draft.hashtags, version=draft.version, status=draft.status,
        created_at=draft.created_at, updated_at=draft.updated_at,
    )
    return task, draft_read


async def _make_candidate_with_bytes(
    db_session: AsyncSession, *, news_event_id, editorial_task_id, content_draft_id, rank: int, tmp_path,
) -> ImageCandidateRecord:
    data = f"fake-bytes-{rank}".encode()
    storage = LocalImageStorage(tmp_path)
    stored = storage.store_validated_image(data, sha256=hashlib.sha256(data).hexdigest(), image_format="JPEG", max_bytes=10_000)
    row = ImageCandidateRecord(
        candidate_id=f"c{rank}", news_event_id=news_event_id, editorial_task_id=editorial_task_id,
        content_draft_id=content_draft_id, source_type=SourceType.RSS, discovery_method="open_graph_image",
        eligible_for_editorial=True, rank=rank, relevance_score=80, quality_score=80,
        image_format="JPEG", storage_status=ImageStorageStatus.STORED, storage_key=stored.storage_key,
    )
    db_session.add(row)
    await db_session.flush()
    return row


_DIRECT_VIDEO = NativeVideoHint(
    discovery_method=VideoDiscoveryMethod.OPEN_GRAPH_VIDEO_SECURE, remote_url="https://cdn.example.com/clip.mp4",
    platform=VideoPlatform.DIRECT_HOSTED,
)
_YOUTUBE_VIDEO = NativeVideoHint(
    discovery_method=VideoDiscoveryMethod.HOSTED_PLATFORM_LINK_IN_ARTICLE,
    remote_url="https://www.youtube.com/watch?v=abc123", platform=VideoPlatform.YOUTUBE,
)


# --- build_rich_media_plan (pure) ----------------------------------------------------------------


def _photo_input_stub():
    return "fake-file-id"


class _StubCandidate:
    telegram_file_id = "fake-file-id"


def test_multiple_photos_are_all_included_with_caption_on_first() -> None:
    candidates = [_StubCandidate(), _StubCandidate(), _StubCandidate()]
    plan = build_rich_media_plan(candidates, None, caption="hello")  # type: ignore[arg-type]
    assert len(plan.media_group_items) == 3
    assert plan.media_group_items[0].caption == "hello"
    assert all(isinstance(m, InputMediaPhoto) for m in plan.media_group_items)
    assert plan.fallback_single_photo is None


def test_direct_hosted_video_is_ordered_last() -> None:
    candidates = [_StubCandidate(), _StubCandidate()]
    plan = build_rich_media_plan(candidates, _DIRECT_VIDEO, caption="hello")
    assert len(plan.media_group_items) == 3
    assert isinstance(plan.media_group_items[0], InputMediaPhoto)
    assert isinstance(plan.media_group_items[1], InputMediaPhoto)
    assert plan.media_group_items[2].media == "https://cdn.example.com/clip.mp4"


def test_youtube_video_is_excluded_from_media_group_and_produces_a_link() -> None:
    candidates = [_StubCandidate(), _StubCandidate()]
    plan = build_rich_media_plan(candidates, _YOUTUBE_VIDEO, caption="hello")
    assert len(plan.media_group_items) == 2  # video never added to the group
    assert all(isinstance(m, InputMediaPhoto) for m in plan.media_group_items)
    assert plan.hosted_platform_link is not None
    assert "youtube.com" in plan.hosted_platform_link


def test_single_photo_falls_back_to_single_send() -> None:
    plan = build_rich_media_plan([_StubCandidate()], None, caption="hello")
    assert plan.fallback_single_photo is not None


def test_no_media_at_all_falls_back() -> None:
    plan = build_rich_media_plan([], None, caption="hello")
    assert plan.media_group_items == []
    assert plan.fallback_single_photo is None


def test_single_photo_plus_youtube_link_falls_back_since_group_would_have_only_one_item() -> None:
    plan = build_rich_media_plan([_StubCandidate()], _YOUTUBE_VIDEO, caption="hello")
    assert len(plan.media_group_items) == 1  # only the photo - YouTube never joins the group
    assert plan.fallback_single_photo is not None


def test_previously_observed_false_positive_channel_link_produces_no_hosted_platform_line() -> None:
    """Video URL Classification Checkpoint regression: this exact URL was a real false positive
    observed in the ~75-minute video-shadow canary (docs/video_shadow_checkpoint.md §8/§11) - it
    is a YouTube channel link, not a video, and now classifies as VideoPlatform.UNKNOWN
    (services/video_discovery.py::classify_video_url()). Feeding the resulting NativeVideoHint
    through the real, unmodified, still-dormant build_rich_media_plan() must produce NO
    hosted_platform_link and NO media-group video item - the exact broken "Video: <channel link>"
    caption line this fix exists to prevent."""
    from services.video_discovery import classify_video_url

    false_positive_url = "https://www.youtube.com/channel/UChjRM_qQAaOAiLNbOGbYcRA"
    resolved_platform = classify_video_url(false_positive_url)
    assert resolved_platform == VideoPlatform.UNKNOWN

    hint = NativeVideoHint(
        discovery_method=VideoDiscoveryMethod.HOSTED_PLATFORM_LINK_IN_ARTICLE,
        remote_url=false_positive_url, platform=resolved_platform,
    )
    candidates = [_StubCandidate(), _StubCandidate()]
    plan = build_rich_media_plan(candidates, hint, caption="hello")

    assert plan.hosted_platform_link is None
    assert len(plan.media_group_items) == 2  # only the two real photos - no video item at all
    assert all(isinstance(m, InputMediaPhoto) for m in plan.media_group_items)


def test_photo_count_is_bounded_to_telegram_media_group_cap() -> None:
    candidates = [_StubCandidate() for _ in range(15)]
    plan = build_rich_media_plan(candidates, _DIRECT_VIDEO, caption="hello")
    assert len(plan.media_group_items) == 10  # Telegram's own hard cap
    assert plan.media_group_items[-1].media == "https://cdn.example.com/clip.mp4"


# --- send_news_with_rich_media (integration-style, FakeSession) ----------------------------------


@pytest.mark.asyncio
async def test_multiple_eligible_photos_send_a_real_media_group(
    db_session: AsyncSession, real_news_event: NewsEvent, tmp_path,
) -> None:
    task, draft = await _make_task_and_draft(db_session, real_news_event)
    await _make_candidate_with_bytes(
        db_session, news_event_id=real_news_event.id, editorial_task_id=task.id, content_draft_id=draft.id,
        rank=1, tmp_path=tmp_path,
    )
    await _make_candidate_with_bytes(
        db_session, news_event_id=real_news_event.id, editorial_task_id=task.id, content_draft_id=draft.id,
        rank=2, tmp_path=tmp_path,
    )
    candidates = await get_editorial_image_candidates(db_session, content_draft_id=draft.id)
    fake_session = FakeSession()
    bot = Bot(token=_FAKE_TOKEN, session=fake_session)

    outcome = await send_news_with_rich_media(
        bot, 42, db_session, draft=draft, event=real_news_event, dry_run=False, image_candidates=candidates,
    )

    assert outcome.sent is True
    assert outcome.has_image is True
    assert len(fake_session.sent) == 1
    assert isinstance(fake_session.sent[0], SendMediaGroup)
    assert len(fake_session.sent[0].media) == 2


@pytest.mark.asyncio
async def test_single_photo_falls_back_to_existing_single_send_path(
    db_session: AsyncSession, real_news_event: NewsEvent, tmp_path,
) -> None:
    task, draft = await _make_task_and_draft(db_session, real_news_event)
    await _make_candidate_with_bytes(
        db_session, news_event_id=real_news_event.id, editorial_task_id=task.id, content_draft_id=draft.id,
        rank=1, tmp_path=tmp_path,
    )
    candidates = await get_editorial_image_candidates(db_session, content_draft_id=draft.id)
    fake_session = FakeSession()
    bot = Bot(token=_FAKE_TOKEN, session=fake_session)

    outcome = await send_news_with_rich_media(
        bot, 42, db_session, draft=draft, event=real_news_event, dry_run=False, image_candidates=candidates,
    )

    assert outcome.sent is True
    # Falls back to send_news_with_image_preview()'s own path - never a media group of size 1
    # (Telegram itself rejects that).
    assert not any(isinstance(m, SendMediaGroup) for m in fake_session.sent)


@pytest.mark.asyncio
async def test_dry_run_never_calls_the_bot(db_session: AsyncSession, real_news_event: NewsEvent, tmp_path) -> None:
    task, draft = await _make_task_and_draft(db_session, real_news_event)
    await _make_candidate_with_bytes(
        db_session, news_event_id=real_news_event.id, editorial_task_id=task.id, content_draft_id=draft.id,
        rank=1, tmp_path=tmp_path,
    )
    await _make_candidate_with_bytes(
        db_session, news_event_id=real_news_event.id, editorial_task_id=task.id, content_draft_id=draft.id,
        rank=2, tmp_path=tmp_path,
    )
    candidates = await get_editorial_image_candidates(db_session, content_draft_id=draft.id)
    fake_session = FakeSession()
    bot = Bot(token=_FAKE_TOKEN, session=fake_session)

    outcome = await send_news_with_rich_media(
        bot, 42, db_session, draft=draft, event=real_news_event, dry_run=True, image_candidates=candidates,
    )

    assert outcome.sent is False
    assert fake_session.sent == []


# ---------------------------------------------------------------------------
# Phase V2.27 - hosted_video_bytes: a downloaded YouTube/Vimeo video becomes a real InputMediaVideo
# (BufferedInputFile) instead of only ever a caption link. Video-only (zero images) support too.
# ---------------------------------------------------------------------------


def test_youtube_video_with_downloaded_bytes_becomes_native_media_item() -> None:
    """TEST 1/7 (Phase V2.27 spec): a YouTube URL with real downloaded bytes present must produce
    a native InputMediaVideo, never a caption link."""
    from aiogram.types import BufferedInputFile, InputMediaVideo

    candidates = [_StubCandidate()]
    plan = build_rich_media_plan(
        candidates, _YOUTUBE_VIDEO, caption="hello", hosted_video_bytes=b"fake-mp4-bytes",
    )
    assert len(plan.media_group_items) == 2
    assert isinstance(plan.media_group_items[0], InputMediaPhoto)
    assert isinstance(plan.media_group_items[1], InputMediaVideo)
    assert isinstance(plan.media_group_items[1].media, BufferedInputFile)
    assert plan.hosted_platform_link is None  # never both a native item AND a link


def test_vimeo_video_with_downloaded_bytes_becomes_native_media_item() -> None:
    """TEST 2 (Phase V2.27 spec): Vimeo behaves identically to YouTube once bytes are provided."""
    from aiogram.types import BufferedInputFile, InputMediaVideo

    vimeo_hint = NativeVideoHint(
        discovery_method=VideoDiscoveryMethod.HOSTED_PLATFORM_LINK_IN_ARTICLE,
        remote_url="https://vimeo.com/76979871", platform=VideoPlatform.VIMEO,
    )
    candidates = [_StubCandidate()]
    plan = build_rich_media_plan(candidates, vimeo_hint, caption="hello", hosted_video_bytes=b"fake-mp4-bytes")
    assert len(plan.media_group_items) == 2
    assert isinstance(plan.media_group_items[1], InputMediaVideo)
    assert isinstance(plan.media_group_items[1].media, BufferedInputFile)
    assert plan.hosted_platform_link is None


def test_youtube_video_without_downloaded_bytes_still_falls_back_to_link() -> None:
    """hosted_video_bytes=None (the default - hosted_video_download_mode='off', or a failed
    download the caller chose to pass through as None) must remain byte-identical to the pre-
    V2.27 caption-link behavior - proven already by test_youtube_video_is_excluded_from_media_
    group_and_produces_a_link() above; this is the same assertion made explicit for the new
    parameter's own default."""
    candidates = [_StubCandidate(), _StubCandidate()]
    plan = build_rich_media_plan(candidates, _YOUTUBE_VIDEO, caption="hello", hosted_video_bytes=None)
    assert len(plan.media_group_items) == 2
    assert all(isinstance(m, InputMediaPhoto) for m in plan.media_group_items)
    assert plan.hosted_platform_link is not None


def test_multiple_images_plus_downloaded_hosted_video() -> None:
    """TEST 8 (Phase V2.27 spec): multiple images + one video - photos first, video last, exactly
    as DIRECT_HOSTED already behaves."""
    from aiogram.types import InputMediaVideo

    candidates = [_StubCandidate(), _StubCandidate(), _StubCandidate()]
    plan = build_rich_media_plan(candidates, _YOUTUBE_VIDEO, caption="hello", hosted_video_bytes=b"fake-mp4-bytes")
    assert len(plan.media_group_items) == 4
    assert all(isinstance(m, InputMediaPhoto) for m in plan.media_group_items[:3])
    assert isinstance(plan.media_group_items[3], InputMediaVideo)
    assert len(plan.photo_candidates) == 3  # video never counted among photo_candidates


def test_video_only_zero_images_produces_a_single_video_item() -> None:
    """TEST 9 (Phase V2.27 spec): zero images + one valid video must still produce a usable plan -
    the historical structural gap (video required an eligible image) is gone."""
    from aiogram.types import BufferedInputFile, InputMediaVideo

    plan = build_rich_media_plan([], _YOUTUBE_VIDEO, caption="hello", hosted_video_bytes=b"fake-mp4-bytes")
    assert len(plan.media_group_items) == 1
    assert isinstance(plan.media_group_items[0], InputMediaVideo)
    assert isinstance(plan.media_group_items[0].media, BufferedInputFile)
    assert plan.photo_candidates == []
    assert plan.fallback_single_photo is None  # no image candidate behind this - never mistaken for one


def test_direct_hosted_video_only_zero_images_unaffected_by_v2_27() -> None:
    """TEST 14 (Phase V2.27 spec): DIRECT_HOSTED non-regression, including the newly-possible
    video-only shape - Telegram still fetches the URL itself, hosted_video_bytes is never
    consulted for this platform."""
    from aiogram.types import InputMediaVideo

    plan = build_rich_media_plan([], _DIRECT_VIDEO, caption="hello")
    assert len(plan.media_group_items) == 1
    assert isinstance(plan.media_group_items[0], InputMediaVideo)
    assert plan.media_group_items[0].media == "https://cdn.example.com/clip.mp4"
    assert plan.photo_candidates == []
    assert plan.fallback_single_photo is None


def test_video_never_counted_among_photo_candidates_mixed_group() -> None:
    """TEST 10 (Phase V2.27 spec) structural proof: worker/content_cycle.py's own V2.25 media-
    group branding loop is bounded to `range(1, len(media_group_photo_candidates))` - this proves
    that bound never includes the video item, for every video shape (direct-hosted, downloaded
    hosted, caption-link-only)."""
    candidates = [_StubCandidate(), _StubCandidate()]
    for video_hint, hosted_bytes in (
        (_DIRECT_VIDEO, None),
        (_YOUTUBE_VIDEO, b"fake-mp4-bytes"),
        (_YOUTUBE_VIDEO, None),
    ):
        plan = build_rich_media_plan(candidates, video_hint, caption="hello", hosted_video_bytes=hosted_bytes)
        assert len(plan.photo_candidates) == 2
        assert len(plan.photo_candidates) <= len(plan.media_group_items)


def test_photo_cap_reserves_a_slot_for_downloaded_hosted_video() -> None:
    """Mirrors test_photo_count_is_bounded_to_telegram_media_group_cap() for the new downloaded-
    bytes case - the reserved-slot logic must key off whether a real video item will exist, not
    only off DIRECT_HOSTED specifically."""
    from aiogram.types import InputMediaVideo

    candidates = [_StubCandidate() for _ in range(15)]
    plan = build_rich_media_plan(candidates, _YOUTUBE_VIDEO, caption="hello", hosted_video_bytes=b"fake-mp4-bytes")
    assert len(plan.media_group_items) == 10  # Telegram's own hard cap
    assert isinstance(plan.media_group_items[-1], InputMediaVideo)
    assert len(plan.photo_candidates) == 9


# ---------------------------------------------------------------------------
# Phase V2.27A - EMBEDDED_PLAYER (source-site/third-party embedded player)
# ---------------------------------------------------------------------------

_EMBEDDED_PLAYER_VIDEO = NativeVideoHint(
    discovery_method=VideoDiscoveryMethod.EMBEDDED_PLAYER_URL,
    remote_url="https://player.example-publisher.com/embed/story-12345",
    platform=VideoPlatform.EMBEDDED_PLAYER,
)


def test_embedded_player_with_downloaded_bytes_becomes_native_media_item() -> None:
    from aiogram.types import BufferedInputFile, InputMediaVideo

    candidates = [_StubCandidate()]
    plan = build_rich_media_plan(
        candidates, _EMBEDDED_PLAYER_VIDEO, caption="hello", hosted_video_bytes=b"fake-mp4-bytes",
    )
    assert len(plan.media_group_items) == 2
    assert isinstance(plan.media_group_items[1], InputMediaVideo)
    assert isinstance(plan.media_group_items[1].media, BufferedInputFile)
    assert plan.hosted_platform_link is None


def test_embedded_player_without_downloaded_bytes_is_dropped_never_a_caption_link() -> None:
    """Unlike YOUTUBE/VIMEO, EMBEDDED_PLAYER never falls back to a caption link - an arbitrary
    third-party embed URL is often not directly clickable/meaningful out of context."""
    candidates = [_StubCandidate(), _StubCandidate()]
    plan = build_rich_media_plan(candidates, _EMBEDDED_PLAYER_VIDEO, caption="hello", hosted_video_bytes=None)
    assert len(plan.media_group_items) == 2  # only the two photos - video silently dropped
    assert all(isinstance(m, InputMediaPhoto) for m in plan.media_group_items)
    assert plan.hosted_platform_link is None


def test_embedded_player_video_only_zero_images() -> None:
    """TEST 9 (Phase V2.27A spec): video-only still works for the new EMBEDDED_PLAYER platform,
    exactly like it already does for YouTube/Vimeo/DIRECT_HOSTED."""
    from aiogram.types import BufferedInputFile, InputMediaVideo

    plan = build_rich_media_plan([], _EMBEDDED_PLAYER_VIDEO, caption="hello", hosted_video_bytes=b"fake-mp4-bytes")
    assert len(plan.media_group_items) == 1
    assert isinstance(plan.media_group_items[0], InputMediaVideo)
    assert isinstance(plan.media_group_items[0].media, BufferedInputFile)
    assert plan.photo_candidates == []
    assert plan.fallback_single_photo is None
