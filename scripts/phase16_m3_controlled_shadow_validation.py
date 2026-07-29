"""Phase 16 M3 - controlled shadow validation against real, already-collected NewsEvent rows
(docs/phase16_m3_quality_and_deduplication_report.md §27). Read-only: selects a bounded sample of
recent real events, calls services.image_intelligence.run_shadow_discovery(mode="shadow") directly
in-process for each one, and prints the resulting ImageIntelligenceResult. Does not write to the
database, does not create EditorialTasks/ContentDrafts, does not call any LLM/vision provider, does
not send Telegram messages, and does not modify core/config.py or .env - IMAGE_INTELLIGENCE_MODE
stays "off" for the deployed worker; this script passes mode="shadow" as an explicit function
argument only, scoped to this one-off read-only process.

Launch with:
    python -m scripts.phase16_m3_controlled_shadow_validation
"""
import asyncio
import json

from sqlalchemy import select

from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource
from database.session import async_session_factory
from services.image_intelligence import run_shadow_discovery

SAMPLE_SIZE = 8


async def main() -> None:
    async with async_session_factory() as session:
        stmt = (
            select(NewsEvent, NewsSource.type)
            .join(NewsSource, NewsSource.id == NewsEvent.source_id)
            .where(NewsEvent.content.is_not(None))
            .order_by(NewsEvent.collected_at.desc())
            .limit(SAMPLE_SIZE)
        )
        rows = (await session.execute(stmt)).all()
        # read-only: session is never flushed/committed, no ORM objects mutated.

    summaries = []
    for event, source_type in rows:
        result = await run_shadow_discovery(
            event_id=event.id, source_type=source_type, content=event.content,
            article_url=event.url, mode="shadow",
        )
        summaries.append({
            "event_id": str(event.id), "source_type": source_type.value, "version": result.version,
            "candidates_total": len(result.candidates),
            "candidates_quality_accepted": result.candidates_quality_accepted,
            "candidates_rejected_quality": result.candidates_rejected_quality,
            "candidates_duplicate_exact": result.candidates_duplicate_exact,
            "candidates_duplicate_near": result.candidates_duplicate_near,
            "candidates_review": result.candidates_review,
            "candidates": [
                {
                    "remote_url": c.remote_url, "status": c.status.value,
                    "quality_status": c.quality_validation.status.value if c.quality_validation else None,
                    "quality_score": c.quality_validation.quality_score if c.quality_validation else None,
                }
                for c in result.candidates
            ],
        })

    print(json.dumps({"sample_size": len(summaries), "results": summaries}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
