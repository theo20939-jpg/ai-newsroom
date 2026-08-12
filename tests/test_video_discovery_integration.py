"""Phase 19 M10: proves get_or_acquire() persists discovered video hints as
ContentDraftMediaItem rows when video_discovery_mode != "off" - a real, migrated-database
integration test (runtime table-existence skip, mirrors tests/test_editorial_planning_
persistence_integration.py's own established pattern).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.news_event import NewsEvent
from integrations.http.safe_fetch import SafeFetchResult
from services.article_acquisition import get_or_acquire
from services.video_discovery_persistence import get_video_candidates_for_event, persist_video_hint


async def _table_exists(session: AsyncSession, table_name: str) -> bool:
    def _check(sync_session: object) -> bool:
        return inspect(sync_session.connection()).has_table(table_name)  # type: ignore[attr-defined]

    return await session.run_sync(_check)


_ARTICLE_HTML = """
<html><head>
<meta property="og:video:secure_url" content="https://cdn.example.com/clip.mp4">
</head><body>
<p>A real article body with enough content to classify as substantial text for this test to
exercise the full acquisition path end to end, well past the headline-only threshold that would
otherwise short-circuit this flow before video discovery ever runs its course here today.</p>
<a href="https://www.youtube.com/watch?v=abc123">Watch the video</a>
</body></html>
"""


def _fake_fetch_result() -> SafeFetchResult:
    return SafeFetchResult(
        requested_url="https://example.com/article", final_url="https://example.com/article",
        status_code=200, redirect_count=0, declared_content_type="text/html",
        received_byte_count=len(_ARTICLE_HTML), duration_seconds=0.05, body=_ARTICLE_HTML.encode("utf-8"),
    )


def _fake_mp4_result() -> SafeFetchResult:
    body = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100
    return SafeFetchResult(
        requested_url="https://cdn.example.com/clip.mp4", final_url="https://cdn.example.com/clip.mp4",
        status_code=200, redirect_count=0, declared_content_type="video/mp4",
        received_byte_count=len(body), duration_seconds=0.05, body=body,
    )


@pytest.mark.asyncio
async def test_shadow_mode_persists_discovered_video_hints(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not await _table_exists(db_session, "content_draft_media_items"):
        pytest.skip(
            "content_draft_media_items table not present on this DB - migration f2654fa00185 "
            "ships unapplied to the real DB; run this test against a disposable DB that has had "
            "'alembic upgrade head' applied."
        )
    monkeypatch.setattr(settings, "video_discovery_mode", "shadow")
    real_news_event.url = "https://example.com/article"
    await db_session.flush()

    from database.models.content_draft_media_item import ContentDraftMediaItem

    with patch("services.article_acquisition.safe_fetch", new=AsyncMock(return_value=_fake_fetch_result())), \
         patch("services.video_discovery.safe_fetch", new=AsyncMock(return_value=_fake_mp4_result())):
        await get_or_acquire(db_session, real_news_event, triggered_by="test")

    rows = (
        await db_session.execute(
            select(ContentDraftMediaItem).where(ContentDraftMediaItem.event_id == real_news_event.id)
        )
    ).scalars().all()

    # The og:video:secure_url (a .mp4 URL) is direct-hosted and gets bounded-validated (a second,
    # mocked safe_fetch call); the YouTube link found in the article body is never fetched at all
    # (URL-pattern classification only) and persists as unvalidated_hosted_platform.
    youtube_rows = [r for r in rows if r.platform == "youtube"]
    direct_hosted_rows = [r for r in rows if r.platform == "direct_hosted"]
    assert len(youtube_rows) == 1
    assert youtube_rows[0].validation_status == "unvalidated_hosted_platform"
    assert youtube_rows[0].remote_url == "https://www.youtube.com/watch?v=abc123"
    assert len(direct_hosted_rows) == 1
    assert direct_hosted_rows[0].validation_status == "valid"
    assert direct_hosted_rows[0].detected_container == "mp4"


@pytest.mark.asyncio
async def test_off_mode_persists_nothing(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not await _table_exists(db_session, "content_draft_media_items"):
        pytest.skip("content_draft_media_items table not present on this DB.")
    assert settings.video_discovery_mode == "off"
    real_news_event.url = "https://example.com/article"
    await db_session.flush()

    from database.models.content_draft_media_item import ContentDraftMediaItem

    with patch("services.article_acquisition.safe_fetch", new=AsyncMock(return_value=_fake_fetch_result())):
        await get_or_acquire(db_session, real_news_event, triggered_by="test")

    rows = (
        await db_session.execute(
            select(ContentDraftMediaItem).where(ContentDraftMediaItem.event_id == real_news_event.id)
        )
    ).scalars().all()
    assert rows == []


# ---------------------------------------------------------------------------
# Phase 23.1Q (Media Roadmap Recovery, video shadow activation) -
# get_video_candidates_for_event() - the sole read contract for this table, added alongside the
# f2654fa00185 migration finally being applied to the real dev DB.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_video_candidates_excludes_rejected_by_default(
    db_session: AsyncSession, real_news_event: NewsEvent,
) -> None:
    if not await _table_exists(db_session, "content_draft_media_items"):
        pytest.skip("content_draft_media_items table not present on this DB.")
    from schemas.video_candidate import NativeVideoHint, VideoDiscoveryMethod, VideoPlatform, VideoValidation, VideoValidationStatus

    await persist_video_hint(
        db_session, event_id=real_news_event.id,
        hint=NativeVideoHint(
            discovery_method=VideoDiscoveryMethod.OPEN_GRAPH_VIDEO_SECURE, remote_url="https://cdn.example.com/valid.mp4",
            platform=VideoPlatform.DIRECT_HOSTED,
        ),
        validation=VideoValidation(status=VideoValidationStatus.VALID, detected_container="mp4", byte_size=1000),
    )
    await persist_video_hint(
        db_session, event_id=real_news_event.id,
        hint=NativeVideoHint(
            discovery_method=VideoDiscoveryMethod.HTML_VIDEO_TAG, remote_url="https://cdn.example.com/broken.mp4",
            platform=VideoPlatform.DIRECT_HOSTED,
        ),
        validation=VideoValidation(status=VideoValidationStatus.REJECTED, error_code="signature_mismatch"),
    )
    await persist_video_hint(
        db_session, event_id=real_news_event.id,
        hint=NativeVideoHint(
            discovery_method=VideoDiscoveryMethod.HOSTED_PLATFORM_LINK_IN_ARTICLE,
            remote_url="https://www.youtube.com/watch?v=xyz", platform=VideoPlatform.YOUTUBE,
        ),
        validation=VideoValidation(status=VideoValidationStatus.UNVALIDATED_HOSTED_PLATFORM),
    )
    await db_session.flush()

    candidates = await get_video_candidates_for_event(db_session, real_news_event.id)

    urls = {c.remote_url for c in candidates}
    assert "https://cdn.example.com/valid.mp4" in urls
    assert "https://www.youtube.com/watch?v=xyz" in urls  # unvalidated hosted-platform is NOT a rejection
    assert "https://cdn.example.com/broken.mp4" not in urls  # rejected, excluded by default
    assert len(candidates) == 2


@pytest.mark.asyncio
async def test_get_video_candidates_include_rejected_when_requested(
    db_session: AsyncSession, real_news_event: NewsEvent,
) -> None:
    if not await _table_exists(db_session, "content_draft_media_items"):
        pytest.skip("content_draft_media_items table not present on this DB.")
    from schemas.video_candidate import NativeVideoHint, VideoDiscoveryMethod, VideoPlatform, VideoValidation, VideoValidationStatus

    await persist_video_hint(
        db_session, event_id=real_news_event.id,
        hint=NativeVideoHint(
            discovery_method=VideoDiscoveryMethod.HTML_VIDEO_TAG, remote_url="https://cdn.example.com/broken.mp4",
            platform=VideoPlatform.DIRECT_HOSTED,
        ),
        validation=VideoValidation(status=VideoValidationStatus.REJECTED, error_code="signature_mismatch"),
    )
    await db_session.flush()

    candidates = await get_video_candidates_for_event(db_session, real_news_event.id, include_rejected=True)

    assert len(candidates) == 1
    assert candidates[0].validation_status == "rejected"
    assert candidates[0].error_code == "signature_mismatch"


@pytest.mark.asyncio
async def test_get_video_candidates_scoped_to_the_given_event_only(
    db_session: AsyncSession, real_news_event: NewsEvent,
) -> None:
    if not await _table_exists(db_session, "content_draft_media_items"):
        pytest.skip("content_draft_media_items table not present on this DB.")
    import uuid as uuid_module

    from database.models.news_event import EventCategory
    from database.models.news_source import NewsSource, SourceType
    from schemas.video_candidate import NativeVideoHint, VideoDiscoveryMethod, VideoPlatform, VideoValidation, VideoValidationStatus

    # event_id genuinely FK-references news_events.id - a second real event is required, not an
    # arbitrary UUID.
    other_source = NewsSource(
        name="Other Test Source", type=SourceType.RSS, url="https://example.com/other-feed.xml", active=True,
    )
    db_session.add(other_source)
    await db_session.flush()
    other_event = NewsEvent(
        source_id=other_source.id, title="Other test event", content="Other content",
        category=EventCategory.AI, hash=f"other-test-hash-{uuid_module.uuid4()}",
    )
    db_session.add(other_event)
    await db_session.flush()

    await persist_video_hint(
        db_session, event_id=other_event.id,
        hint=NativeVideoHint(
            discovery_method=VideoDiscoveryMethod.HTML_VIDEO_TAG, remote_url="https://cdn.example.com/other-event.mp4",
            platform=VideoPlatform.DIRECT_HOSTED,
        ),
        validation=VideoValidation(status=VideoValidationStatus.VALID, detected_container="mp4"),
    )
    await db_session.flush()

    candidates = await get_video_candidates_for_event(db_session, real_news_event.id)

    assert candidates == []


@pytest.mark.asyncio
async def test_get_video_candidates_respects_limit(
    db_session: AsyncSession, real_news_event: NewsEvent,
) -> None:
    if not await _table_exists(db_session, "content_draft_media_items"):
        pytest.skip("content_draft_media_items table not present on this DB.")
    from schemas.video_candidate import NativeVideoHint, VideoDiscoveryMethod, VideoPlatform, VideoValidation, VideoValidationStatus

    for i in range(3):
        await persist_video_hint(
            db_session, event_id=real_news_event.id,
            hint=NativeVideoHint(
                discovery_method=VideoDiscoveryMethod.HTML_VIDEO_TAG, remote_url=f"https://cdn.example.com/clip{i}.mp4",
                platform=VideoPlatform.DIRECT_HOSTED,
            ),
            validation=VideoValidation(status=VideoValidationStatus.VALID, detected_container="mp4"),
        )
    await db_session.flush()

    candidates = await get_video_candidates_for_event(db_session, real_news_event.id, limit=2)

    assert len(candidates) == 2
