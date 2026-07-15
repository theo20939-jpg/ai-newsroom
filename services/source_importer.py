"""Idempotent upsert logic for importing NewsSource records.

Used by scripts/import_sources.py, which handles file I/O and validation;
this module only decides what happens to already-validated items.
"""
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.news_source import NewsSource
from schemas.source_import import SourceImportItem

logger = logging.getLogger(__name__)


@dataclass
class ImportReport:
    """Summary of a source import run."""

    created: int = 0
    updated: int = 0
    skipped: int = 0


async def import_sources(session: AsyncSession, items: list[SourceImportItem]) -> ImportReport:
    """Upsert a list of already-validated source items into the database."""
    report = ImportReport()

    for item in items:
        await _upsert_source(session, item, report)

    await session.commit()
    return report


async def _upsert_source(session: AsyncSession, item: SourceImportItem, report: ImportReport) -> None:
    """Insert a new source, update a changed one, or count it as skipped."""
    existing = await _find_by_url(session, item.url)

    if existing is None:
        session.add(
            NewsSource(
                name=item.name,
                type=item.type,
                url=item.url,
                category=item.category,
                reliability_score=item.reliability_score,
                active=item.active,
            )
        )
        report.created += 1
        return

    if _has_changes(existing, item):
        existing.name = item.name
        existing.type = item.type
        existing.category = item.category
        existing.reliability_score = item.reliability_score
        existing.active = item.active
        report.updated += 1
    else:
        report.skipped += 1


async def _find_by_url(session: AsyncSession, url: str) -> NewsSource | None:
    """Look up an existing source by its URL, the natural import key."""
    result = await session.execute(select(NewsSource).where(NewsSource.url == url))
    return result.scalar_one_or_none()


def _has_changes(existing: NewsSource, item: SourceImportItem) -> bool:
    """Check whether the import item differs from the stored record."""
    return (
        existing.name != item.name
        or existing.type != item.type
        or existing.category != item.category
        or existing.reliability_score != item.reliability_score
        or existing.active != item.active
    )
