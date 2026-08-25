"""Source Collector orchestration (Collector Service).

Loads active NewsSource rows, fetches raw items through the adapter
matching each source's type, cleans and deduplicates them, and stores new
NewsEvent rows with status=NEW. category is assigned deterministically from
the resolved source's config-level tags (services.event_category, Phase 15
M2) - never UNKNOWN by default, only when no tag maps to a known category.
Real engagement metrics (views/forwards/replies/reactions_count), where the
source exposes them, are persisted verbatim - never fabricated (Phase 15 M3).
Contains no AI, scoring, ranking or content generation logic - orchestration
only.
"""
import asyncio
import hashlib
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon.errors import FloodWaitError

from core.config import settings
from database.models.news_event import EventStatus, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.session import async_session_factory
from integrations.sources.base import SourceAdapter, SourceFetchContext
from schemas.image_candidate import NativeMediaHint
from schemas.raw_news_item import RawNewsItem
from schemas.source_definition import SourceDefinition
from services import cleaning, deduplication
from services.adapter_registry import AdapterResolution, build_registry
from services.event_category import categorize_from_tags
from services.image_intelligence import consolidate_candidates
from services.source_registry import SourceRegistryReport, load_source_pack

logger = logging.getLogger(__name__)

MAX_FETCH_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.0


class SourceAdapterResolver(Protocol):
    """Structural interface for whatever `_load_active_sources()`/`_process_source()` actually
    call. `services.adapter_registry.AdapterRegistry` already satisfies this exactly, with no
    change to it required - Python's structural typing does not require an explicit subclass
    relationship. A test-owned fake object satisfying only this method never touches
    `AdapterRegistry` or `services.adapter_keys.ADAPTER_KEY_TO_ADAPTER` at all (Phase 12
    Architecture Contract §7)."""

    def resolve(self, source: NewsSource) -> AdapterResolution | None: ...


@dataclass
class CollectionReport:
    """Summary of a single collection cycle, used for logging."""

    sources_processed: int = 0
    sources_failed: int = 0
    events_created: int = 0
    duplicates_skipped: int = 0


async def run_collection_cycle(
    *,
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
    source_pack_loader: Callable[
        [], tuple[list[SourceDefinition], SourceRegistryReport]
    ] = load_source_pack,
    adapter_resolver_factory: Callable[
        [list[SourceDefinition]], SourceAdapterResolver
    ] = build_registry,
) -> CollectionReport:
    """Run one collection pass over all active sources with a registered adapter.

    A database connectivity failure (e.g. Postgres unreachable) is logged and
    turned into an empty report instead of crashing the process - the same
    "one failure must not stop the system" rule already applied per-source.

    `session_factory`, `source_pack_loader`, and `adapter_resolver_factory` are keyword-only,
    defaulted testability seams (Phase 12 Architecture Contract §7) - every default is the exact
    object this function already hardcoded before Phase 12, so calling with zero arguments (as
    every production call site does) is byte-for-byte unchanged in behavior.
    """
    report = CollectionReport()

    try:
        definitions, _registry_report = source_pack_loader()
        registry = adapter_resolver_factory(definitions)

        async with session_factory() as session:
            sources = await _load_active_sources(session, registry)
            # Captured once, before any source is processed - not read from `source` again inside
            # the except branch below, by index rather than by `source.id`. `session.rollback()`
            # there (necessary to clear a failed source's own uncommitted work) expires every
            # attribute of every persistent object in the session's identity map (SQLAlchemy's
            # default rollback behavior, not something this change opts into, and not limited to
            # primary keys) - not just the source that failed, ALL of them, including ones not yet
            # reached in this loop. A post-rollback `source.name`/`source.id` access would need a
            # synchronous lazy-load the async engine can't perform outside an `await`
            # (`sqlalchemy.exc.MissingGreenlet`), which would escape this except block and abort
            # the entire cycle after the first failure - exactly the "one failure blocks
            # everything" bug this phase exists to fix.
            source_names = [source.name for source in sources]

            for index, source in enumerate(sources):
                # A prior iteration's `session.rollback()` (below) expires every attribute of
                # every source loaded above, including ones not yet processed - refresh (a real,
                # properly-awaited reload, safe inside an async session) before touching this
                # source's own attributes again, e.g. `_process_item`'s `source.id`/`source.type`.
                # Only needed once a rollback has actually happened, hence the `expired` check.
                if inspect(source).expired:
                    await session.refresh(source)
                try:
                    await _process_source(session, source, registry, report)
                    report.sources_processed += 1
                except Exception:
                    await session.rollback()
                    report.sources_failed += 1
                    logger.exception("Source %s failed, skipping", source_names[index])
    except Exception:
        logger.exception("Collection cycle aborted - could not connect to the database")

    logger.info(
        "Collection cycle finished: processed=%d failed=%d created=%d duplicates=%d",
        report.sources_processed,
        report.sources_failed,
        report.events_created,
        report.duplicates_skipped,
    )
    return report


async def _load_active_sources(
    session: AsyncSession, registry: SourceAdapterResolver
) -> list[NewsSource]:
    """Load active sources that have a registered adapter."""
    result = await session.execute(select(NewsSource).where(NewsSource.active.is_(True)))
    sources = list(result.scalars().all())
    return [source for source in sources if registry.resolve(source) is not None]


async def _process_source(
    session: AsyncSession, source: NewsSource, registry: SourceAdapterResolver, report: CollectionReport
) -> None:
    """Fetch, clean, deduplicate and store events for a single source."""
    resolution = registry.resolve(source)
    assert resolution is not None, f"{source.name} passed active-source filtering without a resolvable adapter"
    context = SourceFetchContext(definition=resolution.definition)
    raw_items = await _fetch_with_retry(resolution.adapter, source, context)

    for raw in raw_items:
        await _process_item(session, source, raw, resolution.definition, report)

    await session.commit()


async def _fetch_with_retry(
    adapter: SourceAdapter, source: NewsSource, context: SourceFetchContext
) -> list[RawNewsItem]:
    """Fetch from a source, retrying transient failures with exponential backoff.

    A Telegram FloodWaitError is not retried within this cycle - retrying it
    with a short backoff would just fail again, since Telegram requires
    waiting out the reported cooldown. It is logged and the source is
    skipped for the current cycle instead.

    Phase I.2.1A.4: every attempt is wrapped in `asyncio.wait_for(..., timeout=settings.
    news_source_fetch_timeout_seconds)` - a real, reproduced hang (a broken Telegram source
    blocking `adapter.fetch()` forever, with no source-level exception ever raised) proved this
    boundary was previously unbounded for any `SourceAdapter`, not just Telegram. A resulting
    `TimeoutError` is not special-cased - it already flows through the generic `except Exception`
    branch below exactly like any other transient failure, retried up to `MAX_FETCH_ATTEMPTS`
    (each attempt now individually bounded, so the source can delay this cycle by at most
    `MAX_FETCH_ATTEMPTS * news_source_fetch_timeout_seconds` plus backoff, never indefinitely) -
    deliberately not building a distinct non-retryable-timeout code path for this phase (see this
    module's own report for the reasoning: a bounded, already-timed-out retry is acceptable, not
    worth a new retry-policy subsystem). `asyncio.CancelledError` is a `BaseException`, never an
    `Exception` subclass, so it is never caught by `except Exception` below and always propagates
    through `asyncio.wait_for` unmodified - worker shutdown semantics (worker/main.py's own
    documented cancellation-propagation contract) are unaffected by this change.
    """
    delay = RETRY_BACKOFF_SECONDS
    last_error: Exception | None = None

    for attempt in range(1, MAX_FETCH_ATTEMPTS + 1):
        try:
            return await asyncio.wait_for(
                adapter.fetch(source, context), timeout=settings.news_source_fetch_timeout_seconds
            )
        except FloodWaitError as error:
            logger.warning(
                "Rate limited on %s, must wait %ds - skipping for this cycle", source.name, error.seconds
            )
            raise
        except Exception as error:
            last_error = error
            logger.warning(
                "Fetch attempt %d/%d failed for %s: %s", attempt, MAX_FETCH_ATTEMPTS, source.name, error
            )
            if attempt < MAX_FETCH_ATTEMPTS:
                await asyncio.sleep(delay)
                delay *= 2

    assert last_error is not None
    raise last_error


async def _process_item(
    session: AsyncSession,
    source: NewsSource,
    raw: RawNewsItem,
    definition: SourceDefinition | None,
    report: CollectionReport,
) -> None:
    """Clean one raw item, hash it, and store it as a NewsEvent unless it is a duplicate."""
    cleaned = cleaning.clean_item(raw)
    if cleaned is None:
        return

    content_hash = _compute_hash(source.id, cleaned.external_id)

    if await deduplication.is_duplicate(session, content_hash):
        report.duplicates_skipped += 1
        return

    event = NewsEvent(
        source_id=source.id,
        title=cleaned.title,
        content=cleaned.text,
        url=cleaned.url,
        category=categorize_from_tags(definition.tags if definition is not None else None),
        published_at=cleaned.published_at,
        hash=content_hash,
        status=EventStatus.NEW,
        views_count=cleaned.views_count,
        forwards_count=cleaned.forwards_count,
        replies_count=cleaned.replies_count,
        reactions_count=cleaned.reactions_count,
    )

    try:
        async with session.begin_nested():
            session.add(event)
            await session.flush()
    except IntegrityError:
        report.duplicates_skipped += 1
        return

    report.events_created += 1
    _log_image_intelligence(event.id, source.type, cleaned.native_media_hints)


def _log_image_intelligence(
    event_id: uuid.UUID, source_type: SourceType, hints: list[NativeMediaHint]
) -> None:
    """Phase 16 M1 (docs/phase16_m1_native_media_ingestion_report.md): structured audit-trail log
    only - the sole "safe preservation through the existing collection path" this milestone
    provides. Never persisted to PostgreSQL (NewsEvent has no image/media column, M1 adds no
    migration - discovery report §11/§21), and never allowed to affect NewsEvent creation, which
    has already committed by the time this runs. `event.id` only exists after the flush above, so
    this must run after it, not before."""
    if settings.image_intelligence_mode == "off":
        return
    try:
        result = consolidate_candidates(hints, event_id=event_id, source_type=source_type, mode="shadow")
        logger.info(
            "image_intelligence_candidates_discovered",
            extra={
                "event_id": str(event_id),
                "source_type": source_type.value,
                "mode": settings.image_intelligence_mode,
                "candidates_discovered": result.candidates_discovered,
                "candidates_accepted": result.candidates_accepted,
                "candidates_rejected": result.candidates_rejected,
                "discovery_methods": sorted({c.discovery_method.value for c in result.candidates}),
            },
        )
    except Exception:
        logger.warning("image_intelligence_collector_logging_failed", extra={"event_id": str(event_id)})


def _compute_hash(source_id: uuid.UUID, external_id: str) -> str:
    """Compute the exact-message dedup hash from source.id and the item's external_id.

    The Collector is the only component that knows both values, so this is
    the single place the final NewsEvent.hash is calculated.
    """
    return hashlib.sha256(f"{source_id}:{external_id}".encode("utf-8")).hexdigest()
