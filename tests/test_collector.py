"""Phase I.2.1A.4: services.collector regression tests for the real, reproduced production
incident - a single hanging/broken SourceAdapter blocking the entire collection cycle
indefinitely. Uses the existing, already-established testability seams
(`session_factory`/`source_pack_loader`/`adapter_resolver_factory`, Phase 12 Architecture
Contract §7) to fully control sources/adapters without any real network call and without needing
the real source pack - real Postgres (db_session fixture) only for the NewsSource rows
`_load_active_sources()` itself queries.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import services.collector as collector_module
from core.config import settings
from database.models.news_source import NewsSource, SourceType
from integrations.sources.base import SourceFetchContext
from schemas.raw_news_item import RawNewsItem
from services.adapter_registry import AdapterResolution
from services.collector import run_collection_cycle


class _HangingAdapter:
    """A SourceAdapter whose fetch() awaits far longer than any test timeout - proves
    `_fetch_with_retry()`'s `asyncio.wait_for` wrapper actually bounds it, rather than relying on
    a real, slow sleep of production duration."""

    def __init__(self) -> None:
        self.fetch_calls = 0

    async def fetch(self, source: NewsSource, context: SourceFetchContext) -> list[RawNewsItem]:
        self.fetch_calls += 1
        await asyncio.sleep(3600)  # never actually reached - the timeout fires first
        return []  # pragma: no cover


class _InstantAdapter:
    def __init__(self, items: list[RawNewsItem]) -> None:
        self._items = items
        self.fetch_calls = 0

    async def fetch(self, source: NewsSource, context: SourceFetchContext) -> list[RawNewsItem]:
        self.fetch_calls += 1
        return self._items


class _NetworkFailureAdapter:
    async def fetch(self, source: NewsSource, context: SourceFetchContext) -> list[RawNewsItem]:
        raise ConnectionError("simulated network failure")


class _CancellingAdapter:
    async def fetch(self, source: NewsSource, context: SourceFetchContext) -> list[RawNewsItem]:
        raise asyncio.CancelledError()


class _FakeResolver:
    """Implements the same structural Protocol services.collector.SourceAdapterResolver
    declares - maps a NewsSource straight to a pre-built fake adapter by name, bypassing the real
    AdapterRegistry/source pack entirely."""

    def __init__(self, adapters_by_name: dict[str, object]) -> None:
        self._adapters_by_name = adapters_by_name

    def resolve(self, source: NewsSource) -> AdapterResolution | None:
        adapter = self._adapters_by_name.get(source.name)
        if adapter is None:
            return None
        return AdapterResolution(adapter=adapter, definition=None)  # type: ignore[arg-type]


def _fake_session_factory(db_session: AsyncSession):
    class _CM:
        async def __aenter__(self) -> AsyncSession:
            return db_session

        async def __aexit__(self, *exc: object) -> bool:
            return False

    return lambda: _CM()


async def _seed_source(session: AsyncSession, *, name: str, source_type: SourceType = SourceType.RSS) -> NewsSource:
    """Commits (not just flushes) the seed NewsSource row.

    A real, already-committed row is what every production NewsSource actually is - long-lived
    data added ages before any collection cycle touches it. `run_collection_cycle()`'s per-source
    failure handler calls `session.rollback()` (services/collector.py `except Exception:` branch),
    which is safe against already-committed rows but would otherwise wipe out a merely-flushed,
    same-transaction seed row too (`join_transaction_mode="create_savepoint"` means this fixture's
    own `session.commit()` only releases a SAVEPOINT, not a real top-level commit, so it stays
    correctly rolled back at test teardown - see tests/conftest.py's db_session fixture)."""
    source = NewsSource(
        id=uuid.uuid4(), name=name, type=source_type, url=f"https://example.com/{uuid.uuid4()}", active=True,
    )
    session.add(source)
    await session.commit()
    return source


@pytest.fixture(autouse=True)
def _fast_retry_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test in this file uses a tiny timeout/backoff so a bounded-retry test completes in
    well under a second, never a real sleep of production duration (Part G's own explicit
    requirement)."""
    monkeypatch.setattr(settings, "news_source_fetch_timeout_seconds", 0.05)
    monkeypatch.setattr(collector_module, "RETRY_BACKOFF_SECONDS", 0.01)


# ---------------------------------------------------------------------------------------------
# Part G - hanging adapter times out, cycle does not hang
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hanging_adapter_times_out_bounded_by_max_attempts(db_session: AsyncSession) -> None:
    await _seed_source(db_session, name="hanging-source", source_type=SourceType.TELEGRAM)
    hanging = _HangingAdapter()
    resolver = _FakeResolver({"hanging-source": hanging})

    report = await asyncio.wait_for(
        run_collection_cycle(
            session_factory=_fake_session_factory(db_session),
            source_pack_loader=lambda: ([], None),  # type: ignore[arg-type]
            adapter_resolver_factory=lambda definitions: resolver,
        ),
        timeout=10,  # real test-level safety net only - the cycle itself must finish far sooner
    )

    assert report.sources_failed == 1
    assert report.sources_processed == 0
    # Retried up to the existing MAX_FETCH_ATTEMPTS, each attempt independently timed out.
    assert hanging.fetch_calls == collector_module.MAX_FETCH_ATTEMPTS


# ---------------------------------------------------------------------------------------------
# Part F - failure is per-source, not per-cycle
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broken_source_does_not_block_subsequent_sources(db_session: AsyncSession) -> None:
    await _seed_source(db_session, name="broken-telegram", source_type=SourceType.TELEGRAM)
    await _seed_source(db_session, name="healthy-rss", source_type=SourceType.RSS)
    await _seed_source(db_session, name="healthy-api", source_type=SourceType.NEWS_API)

    hanging = _HangingAdapter()
    item_a = RawNewsItem(
        external_id="a", title="A healthy headline", text="Body text here.",
        url="https://example.com/a", published_at=datetime.now(timezone.utc),
    )
    item_b = RawNewsItem(
        external_id="b", title="Another healthy headline", text="More body text.",
        url="https://example.com/b", published_at=datetime.now(timezone.utc),
    )
    resolver = _FakeResolver({
        "broken-telegram": hanging,
        "healthy-rss": _InstantAdapter([item_a]),
        "healthy-api": _InstantAdapter([item_b]),
    })

    report = await asyncio.wait_for(
        run_collection_cycle(
            session_factory=_fake_session_factory(db_session),
            source_pack_loader=lambda: ([], None),  # type: ignore[arg-type]
            adapter_resolver_factory=lambda definitions: resolver,
        ),
        timeout=10,
    )

    assert report.sources_failed == 1
    assert report.sources_processed == 2  # both healthy sources still ran
    assert report.events_created == 2


@pytest.mark.asyncio
async def test_network_failure_is_bounded_and_isolated(db_session: AsyncSession) -> None:
    await _seed_source(db_session, name="network-broken", source_type=SourceType.RSS)
    await _seed_source(db_session, name="healthy-rss-2", source_type=SourceType.RSS)
    item = RawNewsItem(
        external_id="c", title="Third headline", text="Body.", url="https://example.com/c",
        published_at=datetime.now(timezone.utc),
    )
    resolver = _FakeResolver({"network-broken": _NetworkFailureAdapter(), "healthy-rss-2": _InstantAdapter([item])})

    report = await asyncio.wait_for(
        run_collection_cycle(
            session_factory=_fake_session_factory(db_session),
            source_pack_loader=lambda: ([], None),  # type: ignore[arg-type]
            adapter_resolver_factory=lambda definitions: resolver,
        ),
        timeout=10,
    )

    assert report.sources_failed == 1
    assert report.sources_processed == 1


# ---------------------------------------------------------------------------------------------
# Part K - CancelledError is never swallowed as an ordinary source failure
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancelled_error_is_not_caught_as_a_source_failure(db_session: AsyncSession) -> None:
    await _seed_source(db_session, name="cancelling-source", source_type=SourceType.RSS)
    resolver = _FakeResolver({"cancelling-source": _CancellingAdapter()})

    with pytest.raises(asyncio.CancelledError):
        await run_collection_cycle(
            session_factory=_fake_session_factory(db_session),
            source_pack_loader=lambda: ([], None),  # type: ignore[arg-type]
            adapter_resolver_factory=lambda definitions: resolver,
        )
