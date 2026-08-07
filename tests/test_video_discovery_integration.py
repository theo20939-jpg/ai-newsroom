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
