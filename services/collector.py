"""Source Collector orchestration (Collector Service).

Loads active NewsSource rows, fetches raw items through the adapter
matching each source's type, cleans and deduplicates them, and stores new
NewsEvent rows with status=NEW and category=UNKNOWN. Contains no AI,
scoring, ranking or content generation logic - orchestration only.
"""
import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.errors import FloodWaitError

from database.models.news_event import EventCategory, EventStatus, NewsEvent
from database.models.news_source import NewsSource
from database.session import async_session_factory
from integrations.sources.base import SourceAdapter, SourceFetchContext
from schemas.raw_news_item import RawNewsItem
from services import cleaning, deduplication
from services.adapter_registry import AdapterRegistry, build_registry
from services.source_registry import load_source_pack

logger = logging.getLogger(__name__)

MAX_FETCH_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.0


@dataclass
class CollectionReport:
    """Summary of a single collection cycle, used for logging."""

    sources_processed: int = 0
    sources_failed: int = 0
    events_created: int = 0
    duplicates_skipped: int = 0


async def run_collection_cycle() -> CollectionReport:
    """Run one collection pass over all active sources with a registered adapter.

    A database connectivity failure (e.g. Postgres unreachable) is logged and
    turned into an empty report instead of crashing the process - the same
    "one failure must not stop the system" rule already applied per-source.
    """
    report = CollectionReport()

    try:
        definitions, _registry_report = load_source_pack()
        registry = build_registry(definitions)

        async with async_session_factory() as session:
            sources = await _load_active_sources(session, registry)

            for source in sources:
                try:
                    await _process_source(session, source, registry, report)
                    report.sources_processed += 1
                except Exception:
                    await session.rollback()
                    report.sources_failed += 1
                    logger.exception("Source %s failed, skipping", source.name)
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


async def _load_active_sources(session: AsyncSession, registry: AdapterRegistry) -> list[NewsSource]:
    """Load active sources that have a registered adapter."""
    result = await session.execute(select(NewsSource).where(NewsSource.active.is_(True)))
    sources = list(result.scalars().all())
    return [source for source in sources if registry.resolve(source) is not None]


async def _process_source(
    session: AsyncSession, source: NewsSource, registry: AdapterRegistry, report: CollectionReport
) -> None:
    """Fetch, clean, deduplicate and store events for a single source."""
    resolution = registry.resolve(source)
    assert resolution is not None, f"{source.name} passed active-source filtering without a resolvable adapter"
    context = SourceFetchContext(definition=resolution.definition)
    raw_items = await _fetch_with_retry(resolution.adapter, source, context)

    for raw in raw_items:
        await _process_item(session, source, raw, report)

    await session.commit()


async def _fetch_with_retry(
    adapter: SourceAdapter, source: NewsSource, context: SourceFetchContext
) -> list[RawNewsItem]:
    """Fetch from a source, retrying transient failures with exponential backoff.

    A Telegram FloodWaitError is not retried within this cycle - retrying it
    with a short backoff would just fail again, since Telegram requires
    waiting out the reported cooldown. It is logged and the source is
    skipped for the current cycle instead.
    """
    delay = RETRY_BACKOFF_SECONDS
    last_error: Exception | None = None

    for attempt in range(1, MAX_FETCH_ATTEMPTS + 1):
        try:
            return await adapter.fetch(source, context)
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
    session: AsyncSession, source: NewsSource, raw: RawNewsItem, report: CollectionReport
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
        category=EventCategory.UNKNOWN,
        published_at=cleaned.published_at,
        hash=content_hash,
        status=EventStatus.NEW,
    )

    try:
        async with session.begin_nested():
            session.add(event)
            await session.flush()
    except IntegrityError:
        report.duplicates_skipped += 1
        return

    report.events_created += 1


def _compute_hash(source_id: uuid.UUID, external_id: str) -> str:
    """Compute the exact-message dedup hash from source.id and the item's external_id.

    The Collector is the only component that knows both values, so this is
    the single place the final NewsEvent.hash is calculated.
    """
    return hashlib.sha256(f"{source_id}:{external_id}".encode("utf-8")).hexdigest()
