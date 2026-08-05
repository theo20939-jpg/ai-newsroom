"""Phase 18.5 M1 - read-only shadow collection driver (docs/
phase18_5_meme_shadow_validation_discovery.md).

Reads already-persisted `NewsEvent` rows directly (SELECT only - no INSERT/UPDATE/DELETE
anywhere in this file) and runs the existing, unmodified `services.meme_opportunity.
assess_meme_opportunity()` classifier against each one via `services.meme_shadow_analytics.
evaluate_event_shadow()`. Writes the normalized results to
`scripts/_phase18_5_shadow_collection_results.json` - never to the database, never to
`EditorialTask.workflow`, never creating any new row of any kind.

Does not import `capabilities.executor`, `workflows.runner`, `bot`, or any LLM Gateway module -
this script cannot make an LLM call, an image-generation call, or a Telegram send even by
accident (verified directly by `tests/test_phase18_5_shadow_analytics.py`'s own import-boundary
check).

Usage: `python scripts/phase18_5_shadow_collection.py [--limit N]`
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource
from database.session import async_session_factory
from schemas.meme_shadow_analytics import MemeShadowCollectionResult
from services.meme_shadow_analytics import evaluate_event_shadow

_OUTPUT_PATH = Path(__file__).parent / "_phase18_5_shadow_collection_results.json"


async def collect(limit: int | None = None) -> MemeShadowCollectionResult:
    now = datetime.now(timezone.utc)
    records = []
    scanned = 0

    async with async_session_factory() as session:
        stmt = (
            select(NewsEvent, NewsSource.name)
            .join(NewsSource, NewsEvent.source_id == NewsSource.id)
            .order_by(NewsEvent.published_at.desc().nulls_last())
        )
        if limit is not None:
            stmt = stmt.limit(limit)

        result = await session.execute(stmt)
        for event, source_name in result.all():
            scanned += 1
            record = evaluate_event_shadow(
                event.id, event.title, event.content, event.category, event.published_at,
                source_name, now=now,
            )
            if record is not None:
                records.append(record)

    return MemeShadowCollectionResult(collected_at=now, events_scanned=scanned, records=records)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of NewsEvent rows to scan")
    args = parser.parse_args()

    collection = await collect(limit=args.limit)
    _OUTPUT_PATH.write_text(collection.model_dump_json(indent=2), encoding="utf-8")
    print(f"Scanned {collection.events_scanned} events, produced {len(collection.records)} shadow records.")
    print(f"Written to {_OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
