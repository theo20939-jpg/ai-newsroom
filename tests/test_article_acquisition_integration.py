"""Phase 19 M1: DB-integration tests for services.article_acquisition - real Postgres (db_session,
rolled back at teardown). Requires the news_event_article_acquisitions table.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_event_article_acquisition import (
    ACQUISITION_STATUS_FETCH_FAILED,
    NewsEventArticleAcquisition,
)
from database.models.news_source import NewsSource, SourceType
from services.article_acquisition import get_effective_acquisition, get_or_acquire

pytestmark = pytest.mark.skip(
    reason=(
        "Requires Alembic migration a3f7c9e15d02 (adds the 'news_event_article_acquisitions' "
        "table) to be applied first - Phase 19 M1 ships this migration unapplied by explicit "
        "instruction (design-only; the user applies it separately). Remove this skip once the "
        "migration has been applied to the target database - until then every test in this file "
        "would fail with 'relation \"news_event_article_acquisitions\" does not exist', not "
        "because the code is wrong, but because the schema hasn't been migrated yet."
    )
)


async def _seed_event(session: AsyncSession, *, url: str | None, source_type: SourceType = SourceType.RSS) -> NewsEvent:
    source = NewsSource(id=uuid4(), name=f"src-{uuid4().hex[:6]}", type=source_type, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(
        id=uuid4(), source_id=source.id, title="t", url=url, category=EventCategory.UNKNOWN,
        hash=f"h-{uuid4()}",
    )
    session.add(event)
    await session.flush()
    return event


@pytest.mark.asyncio
async def test_missing_url_produces_fetch_failed_row_never_raises(db_session: AsyncSession) -> None:
    event = await _seed_event(db_session, url=None)

    row = await get_or_acquire(db_session, event, triggered_by="content_generation_selected")

    assert row.acquisition_status == ACQUISITION_STATUS_FETCH_FAILED
    assert row.error_code == "missing_url"


@pytest.mark.asyncio
async def test_same_event_retried_does_not_refetch(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    call_count = 0

    async def _fake_acquire_article(url, *, event_id):
        nonlocal call_count
        call_count += 1
        from services.article_acquisition import AcquisitionOutcome
        return AcquisitionOutcome(
            status="FULL_TEXT", raw_extracted_text="x" * 3000, extracted_char_count=3000,
            canonical_url=url, source_html_bytes=5000, fetch_duration_ms=10, error_code=None,
        )

    monkeypatch.setattr("services.article_acquisition.acquire_article", _fake_acquire_article)
    event = await _seed_event(db_session, url="https://example.com/a")

    first = await get_or_acquire(db_session, event, triggered_by="content_generation_selected")
    await db_session.flush()
    second = await get_or_acquire(db_session, event, triggered_by="content_generation_selected")

    assert first.news_event_id == second.news_event_id
    assert call_count == 1


@pytest.mark.asyncio
async def test_two_events_same_canonical_url_within_window_reuse_one_fetch(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    call_count = 0

    async def _fake_acquire_article(url, *, event_id):
        nonlocal call_count
        call_count += 1
        from services.article_acquisition import AcquisitionOutcome
        return AcquisitionOutcome(
            status="FULL_TEXT", raw_extracted_text="real article text" * 200, extracted_char_count=3400,
            canonical_url=url, source_html_bytes=5000, fetch_duration_ms=10, error_code=None,
        )

    monkeypatch.setattr("services.article_acquisition.acquire_article", _fake_acquire_article)
    shared_url = f"https://example.com/shared-{uuid4().hex[:8]}"
    event_a = await _seed_event(db_session, url=shared_url)
    event_b = await _seed_event(db_session, url=shared_url)

    row_a = await get_or_acquire(db_session, event_a, triggered_by="content_generation_selected")
    await db_session.flush()
    row_b = await get_or_acquire(db_session, event_b, triggered_by="content_generation_selected")

    assert call_count == 1
    assert row_b.reused_from_news_event_id == row_a.news_event_id
    assert row_b.raw_extracted_text is None  # text lives only on the original row


@pytest.mark.asyncio
async def test_different_canonical_urls_never_share_a_row(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_acquire_article(url, *, event_id):
        from services.article_acquisition import AcquisitionOutcome
        return AcquisitionOutcome(
            status="FULL_TEXT", raw_extracted_text="text", extracted_char_count=4, canonical_url=url,
            source_html_bytes=100, fetch_duration_ms=5, error_code=None,
        )

    monkeypatch.setattr("services.article_acquisition.acquire_article", _fake_acquire_article)
    event_a = await _seed_event(db_session, url=f"https://example.com/a-{uuid4().hex[:8]}")
    event_b = await _seed_event(db_session, url=f"https://example.com/b-{uuid4().hex[:8]}")

    await get_or_acquire(db_session, event_a, triggered_by="content_generation_selected")
    await db_session.flush()
    row_b = await get_or_acquire(db_session, event_b, triggered_by="content_generation_selected")

    assert row_b.reused_from_news_event_id is None


@pytest.mark.asyncio
async def test_reuse_never_chains_beyond_one_hop(db_session: AsyncSession) -> None:
    """A reuse row is never itself a valid reuse target - get_effective_acquisition() must
    degrade safely (return None) rather than chain, if this invariant is ever violated."""
    root = await _seed_event(db_session, url="https://example.com/root")
    leaf = await _seed_event(db_session, url="https://example.com/root")  # same URL, unused here
    broken_leaf_event = await _seed_event(db_session, url="https://example.com/root")

    root_row = NewsEventArticleAcquisition(
        news_event_id=root.id, canonical_url=root.url, acquisition_status="FULL_TEXT",
        raw_extracted_text="real text", effective_completeness_status="FULL_TEXT",
        triggered_by="content_generation_selected",
    )
    db_session.add(root_row)
    await db_session.flush()

    # Deliberately construct an invalid second-hop chain to prove the guard fires.
    broken_leaf = NewsEventArticleAcquisition(
        news_event_id=broken_leaf_event.id, canonical_url=root.url, reused_from_news_event_id=leaf.id,
        acquisition_status="FULL_TEXT", effective_completeness_status="FULL_TEXT",
        triggered_by="content_generation_selected",
    )
    leaf_row = NewsEventArticleAcquisition(
        news_event_id=leaf.id, canonical_url=root.url, reused_from_news_event_id=root.id,
        acquisition_status="FULL_TEXT", effective_completeness_status="FULL_TEXT",
        triggered_by="content_generation_selected",
    )
    db_session.add_all([leaf_row, broken_leaf])
    await db_session.flush()

    result = await get_effective_acquisition(db_session, broken_leaf.news_event_id)

    assert result is None  # never chains, never returns wrong text


@pytest.mark.asyncio
async def test_reuse_window_expiry_triggers_fresh_fetch(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "article_acquisition_reuse_window_hours", 1)
    shared_url = f"https://example.com/stale-{uuid4().hex[:8]}"
    old_event = await _seed_event(db_session, url=shared_url)
    stale_row = NewsEventArticleAcquisition(
        news_event_id=old_event.id, canonical_url=shared_url, acquisition_status="FULL_TEXT",
        raw_extracted_text="old text", effective_completeness_status="FULL_TEXT",
        triggered_by="content_generation_selected",
        created_at=datetime.now(timezone.utc) - timedelta(hours=5),
    )
    db_session.add(stale_row)
    await db_session.flush()

    call_count = 0

    async def _fake_acquire_article(url, *, event_id):
        nonlocal call_count
        call_count += 1
        from services.article_acquisition import AcquisitionOutcome
        return AcquisitionOutcome(
            status="FULL_TEXT", raw_extracted_text="fresh text", extracted_char_count=11,
            canonical_url=url, source_html_bytes=50, fetch_duration_ms=5, error_code=None,
        )

    monkeypatch.setattr("services.article_acquisition.acquire_article", _fake_acquire_article)
    new_event = await _seed_event(db_session, url=shared_url)

    row = await get_or_acquire(db_session, new_event, triggered_by="content_generation_selected")

    assert call_count == 1  # outside the window - a fresh fetch happened
    assert row.reused_from_news_event_id is None


@pytest.mark.asyncio
async def test_effective_acquisition_resolves_through_reuse_row(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_acquire_article(url, *, event_id):
        from services.article_acquisition import AcquisitionOutcome
        return AcquisitionOutcome(
            status="FULL_TEXT", raw_extracted_text="the real text", extracted_char_count=13,
            canonical_url=url, source_html_bytes=50, fetch_duration_ms=5, error_code=None,
        )

    monkeypatch.setattr("services.article_acquisition.acquire_article", _fake_acquire_article)
    shared_url = f"https://example.com/dup-{uuid4().hex[:8]}"
    event_a = await _seed_event(db_session, url=shared_url)
    event_b = await _seed_event(db_session, url=shared_url)

    await get_or_acquire(db_session, event_a, triggered_by="content_generation_selected")
    await db_session.flush()
    await get_or_acquire(db_session, event_b, triggered_by="content_generation_selected")
    await db_session.flush()

    effective = await get_effective_acquisition(db_session, event_b.id)

    assert effective is not None
    assert effective.raw_extracted_text == "the real text"
    assert effective.news_event_id == event_a.id
