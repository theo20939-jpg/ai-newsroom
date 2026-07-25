"""Phase 12 collector DI seam tests (Contract §7) and the offline automation
integration proof (Contract §25) - collocated per the Contract's own
discretion-at-Planning-level allowance (§22), since both concern the same
fake-source-pack/fake-adapter-resolver seam.

Real Postgres, no separate test database (this repository has none - see
docs/phase12_fresh_news_automation_implementation_plan.md §12.0): every test here uses
independent_session_factory() bound to settings.database_url, with explicit, FK-safe,
test-owned cleanup - never rollback-only isolation (run_collection_cycle()/run_triage_cycle()
commit internally through their own injected session_factory() calls, which an outer test
transaction cannot undo) and never a table-wide delete.
"""
import inspect
from collections.abc import AsyncIterator
from unittest.mock import patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from database.models.ai_execution import AIExecution
from database.models.content_draft import ContentDraft
from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.session import async_session_factory as production_session_factory
from schemas.raw_news_item import RawNewsItem
from schemas.source_definition import SourceDefinition
from services.adapter_registry import build_registry
from services.collector import run_collection_cycle
from services.source_registry import SourceRegistryReport, load_source_pack
from services.triage_orchestrator import run_triage_cycle
from tests.fakes.fake_source_adapter import FakeAdapterRegistry, FakeSourceAdapter
from tests.test_triage_orchestrator_claims import independent_session_factory

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A fresh, factory-shaped, real-Postgres session factory (settings.database_url) -
    the same helper tests/test_triage_orchestrator_cycle.py already proves compatible
    with run_triage_cycle(session_factory=...); reused here for run_collection_cycle's
    identically-shaped parameter (Contract §7)."""
    engine, session_factory = independent_session_factory()
    yield session_factory
    await engine.dispose()


@pytest_asyncio.fixture
async def test_source(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[NewsSource]:
    """A real, uniquely-named, committed NewsSource, plus FK-safe test-owned cleanup of
    every NewsEvent/EditorialTask row that flows from it (Plan §12.0). _load_active_sources()
    queries NewsSource directly from the database - a fake source_pack_loader alone does not
    create this row, so it is inserted explicitly here."""
    unique_name = f"phase12-integration-test-{uuid4()}"

    async with factory() as session:
        pre_existing = (
            await session.execute(select(NewsSource.id).where(NewsSource.name == unique_name))
        ).scalars().all()
        assert not pre_existing, "test-owned NewsSource name collided before creation"

        source = NewsSource(name=unique_name, type=SourceType.RSS, active=True)
        session.add(source)
        await session.commit()

    try:
        yield source
    finally:
        async with factory() as session:
            event_ids = (
                await session.execute(select(NewsEvent.id).where(NewsEvent.source_id == source.id))
            ).scalars().all()
            if event_ids:
                await session.execute(delete(EditorialTask).where(EditorialTask.event_id.in_(event_ids)))
                await session.execute(delete(NewsEvent).where(NewsEvent.id.in_(event_ids)))
            await session.execute(delete(NewsSource).where(NewsSource.id == source.id))
            await session.commit()

        async with factory() as session:
            remaining = (
                await session.execute(select(NewsSource.id).where(NewsSource.name == unique_name))
            ).scalars().all()
            assert not remaining, "test-owned NewsSource row survived cleanup - pollution"


def _fake_seam(
    source: NewsSource,
    items: list[RawNewsItem],
    *,
    error: Exception | None = None,
    definition: SourceDefinition | None = None,
) -> tuple[FakeSourceAdapter, dict]:
    """Build a fake source_pack_loader/adapter_resolver_factory pair for run_collection_cycle(),
    scoped to resolve only the given test-owned source - never any other active NewsSource row
    in the shared database (Plan §12.0).

    `definition`, when given, is handed straight through to FakeAdapterRegistry (Phase 15 M2) -
    the exact same object services.collector._process_item now reads .tags from to assign
    NewsEvent.category, mirroring how services.adapter_registry.AdapterRegistry.resolve() hands
    back a real SourceDefinition in production.
    """
    adapter = FakeSourceAdapter(items=items, error=error)

    def fake_source_pack_loader() -> tuple[list[SourceDefinition], SourceRegistryReport]:
        return [], SourceRegistryReport()  # unused by the fake resolver below

    def fake_adapter_resolver_factory(_definitions: list) -> FakeAdapterRegistry:
        return FakeAdapterRegistry(adapter, resolvable_source_ids={source.id}, definition=definition)

    return adapter, {
        "source_pack_loader": fake_source_pack_loader,
        "adapter_resolver_factory": fake_adapter_resolver_factory,
    }


def _make_definition(*, tags: list[str]) -> SourceDefinition:
    """A minimal, valid SourceDefinition for M2 category-assignment tests - every field besides
    `tags` is an arbitrary valid placeholder, since only `.tags` is read by
    services.event_category.categorize_from_tags()."""
    return SourceDefinition(
        id="phase15_m2_test_source",
        name="Phase 15 M2 Test Source",
        category="media",
        type="rss",
        url="https://example.com/phase15-m2-test-feed.xml",
        language="en",
        region="global",
        priority=50,
        reliability=0.5,
        fetch_interval="30m",
        enabled=True,
        tags=tags,
    )


# ---------------------------------------------------------------------------
# M1 - Collector DI seam (Contract §7)
# ---------------------------------------------------------------------------


def test_run_collection_cycle_defaults_are_production_objects() -> None:
    """Calling with zero arguments must resolve to the exact pre-Phase-12 hardcoded objects -
    proving the signature addition changes nothing about production/default behavior."""
    signature = inspect.signature(run_collection_cycle)

    assert signature.parameters["session_factory"].default is production_session_factory
    assert signature.parameters["source_pack_loader"].default is load_source_pack
    assert signature.parameters["adapter_resolver_factory"].default is build_registry


@pytest.mark.asyncio
async def test_injected_session_factory_is_used(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource
) -> None:
    _adapter, seam = _fake_seam(
        test_source, [RawNewsItem(external_id=f"item-{uuid4()}", text="Hello world")]
    )

    report = await run_collection_cycle(session_factory=factory, **seam)

    assert report.events_created == 1
    async with factory() as session:
        rows = (
            await session.execute(select(NewsEvent).where(NewsEvent.source_id == test_source.id))
        ).scalars().all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_injected_source_pack_loader_is_used(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource
) -> None:
    calls: list[int] = []

    def counting_loader() -> tuple[list[SourceDefinition], SourceRegistryReport]:
        calls.append(1)
        return [], SourceRegistryReport()

    adapter = FakeSourceAdapter(items=[])

    def resolver_factory(_definitions: list) -> FakeAdapterRegistry:
        return FakeAdapterRegistry(adapter, resolvable_source_ids={test_source.id})

    await run_collection_cycle(
        session_factory=factory,
        source_pack_loader=counting_loader,
        adapter_resolver_factory=resolver_factory,
    )

    assert calls == [1]


@pytest.mark.asyncio
async def test_injected_adapter_resolver_factory_is_used(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource
) -> None:
    item = RawNewsItem(external_id=f"item-{uuid4()}", text="Hello world")
    adapter, seam = _fake_seam(test_source, [item])

    report = await run_collection_cycle(session_factory=factory, **seam)

    assert report.events_created == 1
    assert len(adapter.received_calls) == 1
    assert adapter.received_calls[0][0].id == test_source.id


@pytest.mark.asyncio
async def test_fake_path_never_touches_real_adapter_registry_construction(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource
) -> None:
    _adapter, seam = _fake_seam(
        test_source, [RawNewsItem(external_id=f"item-{uuid4()}", text="Hello world")]
    )

    with patch("services.adapter_registry.build_registry") as mocked_build_registry:
        await run_collection_cycle(session_factory=factory, **seam)
        mocked_build_registry.assert_not_called()


@pytest.mark.asyncio
async def test_fake_path_never_touches_adapter_key_to_adapter_singleton(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource
) -> None:
    _adapter, seam = _fake_seam(
        test_source, [RawNewsItem(external_id=f"item-{uuid4()}", text="Hello world")]
    )

    class _ExplodingMapping(dict):
        def get(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("ADAPTER_KEY_TO_ADAPTER must not be consulted on the fake path")

    # Patched at services.adapter_registry's own namespace - the module-global name
    # AdapterRegistry.resolve() would actually look up, per `from services.adapter_keys import
    # ADAPTER_KEY_TO_ADAPTER` (a separate binding from services.adapter_keys' own attribute).
    with patch("services.adapter_registry.ADAPTER_KEY_TO_ADAPTER", _ExplodingMapping()):
        report = await run_collection_cycle(session_factory=factory, **seam)

    assert report.events_created == 1


def test_fakes_module_imports_no_network_library() -> None:
    """Static proof that FakeSourceAdapter/FakeAdapterRegistry cannot perform network I/O -
    checked at the import-statement level rather than by blocking sockets at runtime, since a
    runtime socket block would also break this same test's own real Postgres connection
    (asyncpg uses sockets too)."""
    import tests.fakes.fake_source_adapter as fake_module

    source_text = inspect.getsource(fake_module)
    for forbidden in ("httpx", "telethon", "feedparser", "aiohttp", "requests"):
        assert forbidden not in source_text, f"{forbidden} must never be imported by the fakes module"


# ---------------------------------------------------------------------------
# M4 - Offline automation integration proof (Contract §25)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_offline_chain_creates_events_and_editorial_tasks_with_no_downstream_execution(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource
) -> None:
    item_a = RawNewsItem(external_id=f"phase12-test-item-{uuid4()}", text="First test article body")
    item_b = RawNewsItem(external_id=f"phase12-test-item-{uuid4()}", text="Second test article body")
    _adapter, seam = _fake_seam(test_source, [item_a, item_b])

    collection_report = await run_collection_cycle(session_factory=factory, **seam)
    assert collection_report.events_created == 2
    assert collection_report.sources_failed == 0

    async with factory() as session:
        event_ids = (
            await session.execute(select(NewsEvent.id).where(NewsEvent.source_id == test_source.id))
        ).scalars().all()
    assert len(event_ids) == 2

    # run_triage_cycle() re-queries ALL eligible NewsEvent rows in the shared database on every
    # invocation (Contract §8) - tasks_created may exceed 2 if unrelated real events are also
    # eligible; assertions below are scoped strictly to this test's own event_ids.
    triage_report = await run_triage_cycle(session_factory=factory)
    assert triage_report.tasks_created >= 2

    async with factory() as session:
        tasks = (
            await session.execute(select(EditorialTask).where(EditorialTask.event_id.in_(event_ids)))
        ).scalars().all()

    assert len(tasks) == 2
    assert all(task.status == TaskStatus.CREATED for task in tasks)

    task_ids = [task.id for task in tasks]
    async with factory() as session:
        ai_execution_rows = (
            await session.execute(select(AIExecution.id).where(AIExecution.task_id.in_(task_ids)))
        ).scalars().all()
        content_draft_rows = (
            await session.execute(select(ContentDraft.id).where(ContentDraft.task_id.in_(task_ids)))
        ).scalars().all()

    assert ai_execution_rows == [], "no WorkflowRunner/NEWS_ANALYSIS execution may occur in Phase 12"
    assert content_draft_rows == [], "no ContentDraft may be generated by Phase 12"


@pytest.mark.asyncio
async def test_repeated_poll_does_not_duplicate_events(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource
) -> None:
    item = RawNewsItem(external_id=f"phase12-test-item-{uuid4()}", text="Repeated poll test body")
    _adapter, seam = _fake_seam(test_source, [item])

    first_report = await run_collection_cycle(session_factory=factory, **seam)
    assert first_report.events_created == 1
    assert first_report.duplicates_skipped == 0

    second_report = await run_collection_cycle(session_factory=factory, **seam)
    assert second_report.events_created == 0
    assert second_report.duplicates_skipped == 1


@pytest.mark.asyncio
async def test_repeated_triage_does_not_create_duplicate_active_tasks(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource
) -> None:
    item = RawNewsItem(external_id=f"phase12-test-item-{uuid4()}", text="Triage dedup test body")
    _adapter, seam = _fake_seam(test_source, [item])

    await run_collection_cycle(session_factory=factory, **seam)

    first_triage = await run_triage_cycle(session_factory=factory)
    assert first_triage.tasks_created >= 1

    # simulates the next scheduled cycle's automatic triage call
    await run_triage_cycle(session_factory=factory)

    async with factory() as session:
        event_id = (
            await session.execute(select(NewsEvent.id).where(NewsEvent.source_id == test_source.id))
        ).scalars().one()
        tasks = (
            await session.execute(select(EditorialTask).where(EditorialTask.event_id == event_id))
        ).scalars().all()

    assert len(tasks) == 1, "a second scheduled triage pass must not create a duplicate active task"


# ---------------------------------------------------------------------------
# Phase 15 M2 - category assignment from the resolved source's config-level tags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collected_event_category_assigned_from_definition_tags(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource
) -> None:
    item = RawNewsItem(external_id=f"phase15-m2-test-item-{uuid4()}", text="An AI research article")
    definition = _make_definition(tags=["ai", "llm", "research"])
    _adapter, seam = _fake_seam(test_source, [item], definition=definition)

    report = await run_collection_cycle(session_factory=factory, **seam)
    assert report.events_created == 1

    async with factory() as session:
        event = (
            await session.execute(select(NewsEvent).where(NewsEvent.source_id == test_source.id))
        ).scalars().one()

    assert event.category == EventCategory.AI


@pytest.mark.asyncio
async def test_collected_event_category_prefers_specific_tag_over_ai(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource
) -> None:
    """Mirrors a real source-pack entry (nvidia_blog: ['ai', 'gpu', 'hardware', 'robotics',
    'nvidia']) - proves the mapping is not a silent 'everything = AI' fallback."""
    item = RawNewsItem(external_id=f"phase15-m2-test-item-{uuid4()}", text="A new GPU announcement")
    definition = _make_definition(tags=["ai", "gpu", "hardware"])
    _adapter, seam = _fake_seam(test_source, [item], definition=definition)

    await run_collection_cycle(session_factory=factory, **seam)

    async with factory() as session:
        event = (
            await session.execute(select(NewsEvent).where(NewsEvent.source_id == test_source.id))
        ).scalars().one()

    assert event.category == EventCategory.HARDWARE


@pytest.mark.asyncio
async def test_collected_event_category_stays_unknown_for_unrecognized_tags(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource
) -> None:
    item = RawNewsItem(external_id=f"phase15-m2-test-item-{uuid4()}", text="Unclassifiable content")
    definition = _make_definition(tags=["totally-unrecognized-tag"])
    _adapter, seam = _fake_seam(test_source, [item], definition=definition)

    await run_collection_cycle(session_factory=factory, **seam)

    async with factory() as session:
        event = (
            await session.execute(select(NewsEvent).where(NewsEvent.source_id == test_source.id))
        ).scalars().one()

    assert event.category == EventCategory.UNKNOWN


@pytest.mark.asyncio
async def test_collected_event_category_stays_unknown_without_a_resolved_definition(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource
) -> None:
    """No SourceDefinition resolves for this source (e.g. a manually imported source with no
    matching pack entry, AdapterResolution.definition=None) - regression: must safely stay
    UNKNOWN, never raise and never guess."""
    item = RawNewsItem(external_id=f"phase15-m2-test-item-{uuid4()}", text="No definition available")
    _adapter, seam = _fake_seam(test_source, [item])  # definition=None, the existing default

    await run_collection_cycle(session_factory=factory, **seam)

    async with factory() as session:
        event = (
            await session.execute(select(NewsEvent).where(NewsEvent.source_id == test_source.id))
        ).scalars().one()

    assert event.category == EventCategory.UNKNOWN
