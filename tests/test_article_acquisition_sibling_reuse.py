"""Google News sibling-evidence-reuse fix (docs/google_news_sibling_reuse_fix_checkpoint.md) -
DB-integration tests for services.article_acquisition::get_or_acquire()'s new post-failure
fallback. Real Postgres (db_session, rolled back at teardown). Not marked skip - unlike
tests/test_article_acquisition_integration.py, this file is new and the
news_event_article_acquisitions table is confirmed present in the real dev/test DB (extensively
exercised this session).

Real event titles/timing from docs/story_cluster_fragmentation_focused_forensic_report.md
(Clusters A and B) - the two confirmed real regressions this fix responds to.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_event_article_acquisition import (
    ACQUISITION_STATUS_FULL_TEXT,
    ACQUISITION_STATUS_REDIRECT_UNRESOLVED,
    NewsEventArticleAcquisition,
)
from database.models.news_source import NewsSource, SourceType
from services.article_acquisition import AcquisitionOutcome, get_or_acquire
from services.evidence_package import build_evidence_package

_REAL_A1_TITLE = "Российский ИИ отправят на экзамен по духовности — модели проверят на традиционные ценности - 3DNews"
_REAL_A2_TITLE = "Российский ИИ отправят на экзамен по духовности — модели проверят на традиционные ценности"
_REAL_A2_TEXT = (
    "Принятый в июле Госдумой и утверждённый Владимиром Путиным закон «О поддержке развития "
    "технологий искусственного интеллекта в России» требует, чтобы большая фундаментальная модель "
    "соответствовала российскому законодательству и традиционным духовно-нравственным ценностям."
) * 3  # padded past the FULL_TEXT threshold, matching the real acquisition's own tier

_REAL_B1_TITLE = "«Будь это добровольно, никто бы не согласился»: Twitch начал тренировать ИИ на контенте пользователей, никого не"
_REAL_B2_TITLE = "«Будь это добровольно, никто бы не согласился»: Twitch начал тренировать ИИ на контенте пользователей, никого не спросив"


async def _seed_event(
    session: AsyncSession, *, title: str, url: str | None, published_at: datetime,
    category: EventCategory = EventCategory.AI, source_type: SourceType = SourceType.RSS,
) -> NewsEvent:
    source = NewsSource(id=uuid4(), name=f"src-{uuid4().hex[:6]}", type=source_type, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(
        id=uuid4(), source_id=source.id, title=title, url=url, category=category,
        published_at=published_at, hash=f"h-{uuid4()}",
    )
    session.add(event)
    await session.flush()
    return event


async def _seed_rich_acquisition(
    session: AsyncSession, event: NewsEvent, *, raw_text: str,
    effective_completeness_status: str = ACQUISITION_STATUS_FULL_TEXT,
) -> NewsEventArticleAcquisition:
    row = NewsEventArticleAcquisition(
        news_event_id=event.id, canonical_url=event.url, acquisition_status=effective_completeness_status,
        raw_extracted_text=raw_text, effective_completeness_status=effective_completeness_status,
        extracted_char_count=len(raw_text), triggered_by="content_generation_selected",
    )
    session.add(row)
    await session.flush()
    return row


def _redirect_unresolved_outcome(url: str) -> AcquisitionOutcome:
    return AcquisitionOutcome(
        status=ACQUISITION_STATUS_REDIRECT_UNRESOLVED, raw_extracted_text=None, extracted_char_count=None,
        canonical_url=url, source_html_bytes=500000, fetch_duration_ms=1000,
        error_code="google_news_redirect_unresolved",
    )


@pytest.mark.asyncio
async def test_unresolved_wrapper_reuses_rich_sibling_via_suffix_match(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case 1 + real Cluster A shape: exact/rich sibling exists (suffix-stripped title match)."""
    published_at = datetime(2026, 8, 13, 14, 34, 0, tzinfo=timezone.utc)
    rich_event = await _seed_event(db_session, title=_REAL_A2_TITLE, url="https://3dnews.ru/1146777", published_at=published_at)
    await _seed_rich_acquisition(db_session, rich_event, raw_text=_REAL_A2_TEXT)

    wrapper_url = "https://news.google.com/rss/articles/wrapper-a1"
    wrapper_event = await _seed_event(db_session, title=_REAL_A1_TITLE, url=wrapper_url, published_at=published_at)

    async def _fake_acquire_article(url, *, event_id):
        return _redirect_unresolved_outcome(url)

    monkeypatch.setattr("services.article_acquisition.acquire_article", _fake_acquire_article)

    row = await get_or_acquire(db_session, wrapper_event, triggered_by="content_generation_selected")

    assert row.reused_from_news_event_id == rich_event.id
    assert row.effective_completeness_status == ACQUISITION_STATUS_FULL_TEXT
    assert row.raw_extracted_text is None  # text lives on the original row only, matches existing convention


@pytest.mark.asyncio
async def test_rich_sibling_predates_wrapper_by_about_one_minute_reuse_allowed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case 2: matches on published_at (identical, real pattern), independent of collected_at gap."""
    published_at = datetime(2026, 8, 13, 14, 3, 23, tzinfo=timezone.utc)
    rich_event = await _seed_event(db_session, title=_REAL_B2_TITLE, url="https://3dnews.ru/1146774", published_at=published_at)
    await _seed_rich_acquisition(db_session, rich_event, raw_text="real Twitch/Amazon article text. " * 100)

    wrapper_event = await _seed_event(
        db_session, title=_REAL_B1_TITLE, url="https://news.google.com/rss/articles/wrapper-b1", published_at=published_at,
    )

    async def _fake_acquire_article(url, *, event_id):
        return _redirect_unresolved_outcome(url)

    monkeypatch.setattr("services.article_acquisition.acquire_article", _fake_acquire_article)

    row = await get_or_acquire(db_session, wrapper_event, triggered_by="content_generation_selected")

    assert row.reused_from_news_event_id == rich_event.id


@pytest.mark.asyncio
async def test_loosely_related_sibling_never_reused(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Case 3: same category/topic, materially different title -> must NOT reuse."""
    published_at = datetime(2026, 8, 13, 14, 34, 0, tzinfo=timezone.utc)
    unrelated_event = await _seed_event(
        db_session, title="Правительство обсудило меры поддержки ИИ-стартапов", url="https://3dnews.ru/other",
        published_at=published_at,
    )
    await _seed_rich_acquisition(db_session, unrelated_event, raw_text="unrelated real article text. " * 100)

    wrapper_event = await _seed_event(
        db_session, title=_REAL_A1_TITLE, url="https://news.google.com/rss/articles/wrapper-a1-loose",
        published_at=published_at,
    )

    async def _fake_acquire_article(url, *, event_id):
        return _redirect_unresolved_outcome(url)

    monkeypatch.setattr("services.article_acquisition.acquire_article", _fake_acquire_article)

    row = await get_or_acquire(db_session, wrapper_event, triggered_by="content_generation_selected")

    assert row.reused_from_news_event_id is None
    assert row.acquisition_status == ACQUISITION_STATUS_REDIRECT_UNRESOLVED  # current safe fallback preserved


@pytest.mark.asyncio
async def test_no_sibling_preserves_current_safe_fallback(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Case 5: no sibling at all exists -> byte-identical to pre-fix behavior."""
    wrapper_event = await _seed_event(
        db_session, title=_REAL_A1_TITLE, url="https://news.google.com/rss/articles/wrapper-lonely",
        published_at=datetime(2026, 8, 13, 14, 34, 0, tzinfo=timezone.utc),
    )

    async def _fake_acquire_article(url, *, event_id):
        return _redirect_unresolved_outcome(url)

    monkeypatch.setattr("services.article_acquisition.acquire_article", _fake_acquire_article)

    row = await get_or_acquire(db_session, wrapper_event, triggered_by="content_generation_selected")

    assert row.reused_from_news_event_id is None
    assert row.acquisition_status == ACQUISITION_STATUS_REDIRECT_UNRESOLVED
    assert row.raw_extracted_text is None


@pytest.mark.asyncio
async def test_weak_sibling_acquisition_never_promoted(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Case 6: a matching-titled sibling exists, but its OWN acquisition also failed/is weak ->
    must not be promoted as if it were rich evidence."""
    published_at = datetime(2026, 8, 13, 14, 34, 0, tzinfo=timezone.utc)
    weak_sibling_event = await _seed_event(db_session, title=_REAL_A2_TITLE, url="https://3dnews.ru/1146777-weak", published_at=published_at)
    # The sibling's own acquisition is itself REDIRECT_UNRESOLVED/no text - must never be promoted.
    weak_row = NewsEventArticleAcquisition(
        news_event_id=weak_sibling_event.id, canonical_url=weak_sibling_event.url,
        acquisition_status=ACQUISITION_STATUS_REDIRECT_UNRESOLVED, raw_extracted_text=None,
        effective_completeness_status=ACQUISITION_STATUS_REDIRECT_UNRESOLVED,
        triggered_by="content_generation_selected",
    )
    db_session.add(weak_row)
    await db_session.flush()

    wrapper_event = await _seed_event(
        db_session, title=_REAL_A1_TITLE, url="https://news.google.com/rss/articles/wrapper-a1-weaksib",
        published_at=published_at,
    )

    async def _fake_acquire_article(url, *, event_id):
        return _redirect_unresolved_outcome(url)

    monkeypatch.setattr("services.article_acquisition.acquire_article", _fake_acquire_article)

    row = await get_or_acquire(db_session, wrapper_event, triggered_by="content_generation_selected")

    assert row.reused_from_news_event_id is None
    assert row.acquisition_status == ACQUISITION_STATUS_REDIRECT_UNRESOLVED


@pytest.mark.asyncio
async def test_reuse_lineage_persisted_via_reused_from_news_event_id(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case 7: explicit, direct check of the persisted lineage field itself."""
    published_at = datetime(2026, 8, 13, 14, 34, 0, tzinfo=timezone.utc)
    rich_event = await _seed_event(db_session, title=_REAL_A2_TITLE, url="https://3dnews.ru/1146777-lineage", published_at=published_at)
    await _seed_rich_acquisition(db_session, rich_event, raw_text=_REAL_A2_TEXT)
    wrapper_event = await _seed_event(
        db_session, title=_REAL_A1_TITLE, url="https://news.google.com/rss/articles/wrapper-lineage",
        published_at=published_at,
    )

    async def _fake_acquire_article(url, *, event_id):
        return _redirect_unresolved_outcome(url)

    monkeypatch.setattr("services.article_acquisition.acquire_article", _fake_acquire_article)

    await get_or_acquire(db_session, wrapper_event, triggered_by="content_generation_selected")
    await db_session.flush()

    reloaded = await db_session.get(NewsEventArticleAcquisition, wrapper_event.id)
    assert reloaded is not None
    assert reloaded.reused_from_news_event_id == rich_event.id


@pytest.mark.asyncio
async def test_evidence_package_sees_reused_rich_text(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cases 8 + 9: downstream build_evidence_package() (what Research actually reads) resolves
    through the reuse row to the rich sibling's real text, not an empty wrapper."""
    published_at = datetime(2026, 8, 13, 14, 34, 0, tzinfo=timezone.utc)
    rich_event = await _seed_event(db_session, title=_REAL_A2_TITLE, url="https://3dnews.ru/1146777-evpkg", published_at=published_at)
    await _seed_rich_acquisition(db_session, rich_event, raw_text=_REAL_A2_TEXT)
    wrapper_event = await _seed_event(
        db_session, title=_REAL_A1_TITLE, url="https://news.google.com/rss/articles/wrapper-evpkg",
        published_at=published_at,
    )
    wrapper_event.content = "thin rss excerpt only"

    async def _fake_acquire_article(url, *, event_id):
        return _redirect_unresolved_outcome(url)

    monkeypatch.setattr("services.article_acquisition.acquire_article", _fake_acquire_article)

    await get_or_acquire(db_session, wrapper_event, triggered_by="content_generation_selected")
    await db_session.flush()

    package = await build_evidence_package(db_session, wrapper_event)

    assert package.extraction_method == "full_article_acquisition"
    assert package.selected_editorial_text != wrapper_event.content
    assert "Путин" in package.selected_editorial_text  # the real sibling's own rich text, not the thin wrapper


@pytest.mark.asyncio
async def test_sibling_fallback_never_triggers_a_second_fetch(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case 10: no duplicate paid work - acquire_article() is called exactly once for the wrapper
    event (the one real, failed fetch); the sibling fallback only ever reads already-persisted
    rows, never triggers a second network fetch or a second Research call."""
    published_at = datetime(2026, 8, 13, 14, 34, 0, tzinfo=timezone.utc)
    rich_event = await _seed_event(db_session, title=_REAL_A2_TITLE, url="https://3dnews.ru/1146777-nodupe", published_at=published_at)
    await _seed_rich_acquisition(db_session, rich_event, raw_text=_REAL_A2_TEXT)
    wrapper_event = await _seed_event(
        db_session, title=_REAL_A1_TITLE, url="https://news.google.com/rss/articles/wrapper-nodupe",
        published_at=published_at,
    )

    call_count = 0

    async def _fake_acquire_article(url, *, event_id):
        nonlocal call_count
        call_count += 1
        return _redirect_unresolved_outcome(url)

    monkeypatch.setattr("services.article_acquisition.acquire_article", _fake_acquire_article)

    await get_or_acquire(db_session, wrapper_event, triggered_by="content_generation_selected")

    assert call_count == 1


@pytest.mark.asyncio
async def test_stale_sibling_outside_reuse_window_not_reused(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reuses the existing article_acquisition_reuse_window_hours bound - a sibling older than the
    window must not be reused, matching the pre-existing canonical-URL reuse path's own behavior."""
    monkeypatch.setattr(settings, "article_acquisition_reuse_window_hours", 1)
    published_at = datetime(2026, 8, 13, 14, 34, 0, tzinfo=timezone.utc)
    rich_event = await _seed_event(db_session, title=_REAL_A2_TITLE, url="https://3dnews.ru/1146777-stale", published_at=published_at)
    row = await _seed_rich_acquisition(db_session, rich_event, raw_text=_REAL_A2_TEXT)
    row.created_at = datetime.now(timezone.utc) - timedelta(hours=5)
    await db_session.flush()

    wrapper_event = await _seed_event(
        db_session, title=_REAL_A1_TITLE, url="https://news.google.com/rss/articles/wrapper-stale",
        published_at=published_at,
    )

    async def _fake_acquire_article(url, *, event_id):
        return _redirect_unresolved_outcome(url)

    monkeypatch.setattr("services.article_acquisition.acquire_article", _fake_acquire_article)

    result = await get_or_acquire(db_session, wrapper_event, triggered_by="content_generation_selected")

    assert result.reused_from_news_event_id is None
