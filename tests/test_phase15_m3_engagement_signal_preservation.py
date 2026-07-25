"""Phase 15 M3 - engagement signal preservation: end-to-end persistence proofs and structural
"no scoring change" guarantees.

Real Postgres, no separate test database (same convention as tests/test_automation_integration.py)
- independent_session_factory() with explicit, FK-safe, test-owned cleanup. `factory`/
`test_source` fixtures are locally redefined (not imported) - mirrors
tests/test_phase15_m1_invalid_title_gate.py's own established convention for this exact reason
(importing a `@pytest_asyncio.fixture`-decorated function and also using its name as a test
parameter trips Ruff's F811 "redefinition"); only the plain, non-fixture helpers
(`_fake_seam`/`_make_definition`) are imported from tests.test_automation_integration.
"""
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from database.models.editorial_task import EditorialTask
from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource, SourceType
from schemas.raw_news_item import RawNewsItem
from services.collector import run_collection_cycle
from tests.test_automation_integration import _fake_seam, _make_definition
from tests.test_triage_orchestrator_claims import independent_session_factory


@pytest_asyncio.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine, session_factory = independent_session_factory()
    yield session_factory
    await engine.dispose()


@pytest_asyncio.fixture
async def test_source(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[NewsSource]:
    unique_name = f"phase15-m3-test-{uuid4()}"

    async with factory() as session:
        source = NewsSource(name=unique_name, type=SourceType.TELEGRAM, active=True)
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

# ---------------------------------------------------------------------------
# F. Persistence: adapter -> RawNewsItem -> Collector -> NewsEvent, metrics survive every
#    boundary. D. RSS/no-metric sources persist NULL, never a fabricated value.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_engagement_metrics_survive_collection_into_news_event(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource
) -> None:
    item = RawNewsItem(
        external_id=f"phase15-m3-test-item-{uuid4()}",
        text="A high-engagement Telegram post",
        views_count=10000,
        forwards_count=120,
        replies_count=35,
        reactions_count=62,
    )
    _adapter, seam = _fake_seam(test_source, [item])

    report = await run_collection_cycle(session_factory=factory, **seam)
    assert report.events_created == 1

    async with factory() as session:
        event = (
            await session.execute(select(NewsEvent).where(NewsEvent.source_id == test_source.id))
        ).scalars().one()

    assert event.views_count == 10000
    assert event.forwards_count == 120
    assert event.replies_count == 35
    assert event.reactions_count == 62


@pytest.mark.asyncio
async def test_real_zero_engagement_metrics_survive_collection_as_zero(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource
) -> None:
    item = RawNewsItem(
        external_id=f"phase15-m3-test-item-{uuid4()}",
        text="A quiet Telegram post",
        views_count=0,
        forwards_count=0,
        replies_count=0,
        reactions_count=0,
    )
    _adapter, seam = _fake_seam(test_source, [item])

    await run_collection_cycle(session_factory=factory, **seam)

    async with factory() as session:
        event = (
            await session.execute(select(NewsEvent).where(NewsEvent.source_id == test_source.id))
        ).scalars().one()

    assert event.views_count == 0
    assert event.forwards_count == 0
    assert event.replies_count == 0
    assert event.reactions_count == 0


@pytest.mark.asyncio
async def test_source_without_engagement_metrics_persists_null_not_fabricated(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource
) -> None:
    """Mirrors an RSS/web-sourced item - no engagement fields set on RawNewsItem at all."""
    item = RawNewsItem(
        external_id=f"phase15-m3-test-item-{uuid4()}", text="An RSS-sourced article, no metrics"
    )
    _adapter, seam = _fake_seam(test_source, [item])

    await run_collection_cycle(session_factory=factory, **seam)

    async with factory() as session:
        event = (
            await session.execute(select(NewsEvent).where(NewsEvent.source_id == test_source.id))
        ).scalars().one()

    assert event.views_count is None
    assert event.forwards_count is None
    assert event.replies_count is None
    assert event.reactions_count is None


@pytest.mark.asyncio
async def test_category_assignment_unaffected_by_engagement_metrics(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource
) -> None:
    """Cross-check against Phase 15 M2: engagement persistence and category assignment are
    independent - both apply correctly to the same event in the same cycle."""
    item = RawNewsItem(
        external_id=f"phase15-m3-test-item-{uuid4()}",
        text="An AI story with real engagement",
        views_count=500,
        forwards_count=10,
    )
    definition = _make_definition(tags=["ai", "llm"])
    _adapter, seam = _fake_seam(test_source, [item], definition=definition)

    await run_collection_cycle(session_factory=factory, **seam)

    async with factory() as session:
        event = (
            await session.execute(select(NewsEvent).where(NewsEvent.source_id == test_source.id))
        ).scalars().one()

    from database.models.news_event import EventCategory

    assert event.category == EventCategory.AI
    assert event.views_count == 500
    assert event.forwards_count == 10
    assert event.replies_count is None
    assert event.reactions_count is None


# ---------------------------------------------------------------------------
# G. Existing rows / schema compatibility - a NewsEvent constructed without any engagement
#    field (mirrors a pre-migration historical row after the additive migration runs) stays
#    valid, with all four fields NULL.
# ---------------------------------------------------------------------------


def test_news_event_constructible_without_engagement_fields() -> None:
    event = NewsEvent(
        source_id=uuid4(),
        title="Historical event",
        content="body",
        hash=f"hash-{uuid4()}",
    )
    assert event.views_count is None
    assert event.forwards_count is None
    assert event.replies_count is None
    assert event.reactions_count is None


# ---------------------------------------------------------------------------
# H. No scoring change - structural proof that nothing in the deterministic Triage formula,
#    the LLM ScoringCapability, or the CONTENT_GENERATION eligibility query reads any of the
#    four new fields. Mirrors tests/test_engagement_capability.py's identical proof for
#    EngagementCapability itself.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "services/triage.py",
        "capabilities/scoring_capability.py",
        "scripts/run_content_generation.py",
        "workflows/definitions/news_analysis.py",
        "workflows/definitions/content_generation.py",
    ],
)
def test_no_scoring_or_eligibility_path_reads_new_engagement_fields(path: str) -> None:
    source = Path(path).read_text(encoding="utf-8")
    for field_name in ("views_count", "forwards_count", "replies_count", "reactions_count"):
        assert field_name not in source, f"{path} unexpectedly references {field_name}"


def test_content_generation_min_score_setting_unchanged_by_m3() -> None:
    from core.config import settings

    # M3 must not touch this value - confirms no test/process-scoped drift crept in.
    assert settings.content_generation_min_score == 65


# ---------------------------------------------------------------------------
# I. No new provider calls - the Collector's own code path (already proven zero-LLM-call in
#    Phase 15 M1/M2) is unaffected; this is a structural proof the new module-level imports in
#    the changed files introduce nothing LLM-related.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "schemas/raw_news_item.py",
        "integrations/sources/telegram_source.py",
        "services/cleaning.py",
        "database/models/news_event.py",
    ],
)
def test_m3_changed_files_import_no_llm_gateway_or_capability(path: str) -> None:
    source = Path(path).read_text(encoding="utf-8")
    for forbidden in ("llm_gateway", "capabilities.", "call_generate"):
        assert forbidden not in source
