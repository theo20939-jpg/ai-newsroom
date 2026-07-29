"""Phase 16 M4 - controlled shadow validation against real, already-collected NewsEvent rows
(docs/phase16_m4_relevance_ranking_report.md §26). Read-only: selects a bounded sample of recent
real events, calls services.image_intelligence.run_shadow_discovery(mode="shadow") directly
in-process for each one (title/source_name included, exactly as capabilities/executor.py now does),
and prints the resulting ranking. Does not write to the database, does not create EditorialTasks/
ContentDrafts, does not call any LLM/vision provider, does not send Telegram messages, and does not
modify core/config.py or .env - IMAGE_INTELLIGENCE_MODE stays "off" for the deployed worker; this
script passes mode="shadow" as an explicit function argument only, scoped to this one-off read-only
process. Intended to be run via `docker exec` against the freshly rebuilt content_worker container
to validate the actually-deployed image, not just the host checkout.

Launch with:
    python -m scripts.phase16_m4_controlled_shadow_validation
"""
import asyncio
import json

from sqlalchemy import select

from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource
from database.session import async_session_factory
from services.image_intelligence import run_shadow_discovery

SAMPLE_SIZE = 15


async def main() -> None:
    async with async_session_factory() as session:
        stmt = (
            select(NewsEvent, NewsSource.type, NewsSource.name)
            .join(NewsSource, NewsSource.id == NewsEvent.source_id)
            .order_by(NewsEvent.collected_at.desc())
            .limit(SAMPLE_SIZE)
        )
        rows = (await session.execute(stmt)).all()
        # read-only: session is never flushed/committed, no ORM objects mutated.

    summaries = []
    for event, source_type, source_name in rows:
        result = await run_shadow_discovery(
            event_id=event.id, source_type=source_type, content=event.content,
            article_url=event.url, mode="shadow", event_title=event.title, source_name=source_name,
        )
        summaries.append({
            "event_id": str(event.id), "source_type": source_type.value, "version": result.version,
            "candidates_total": len(result.candidates),
            "candidates_quality_eligible": result.candidates_quality_eligible,
            "candidates_ranked": result.candidates_ranked,
            "top_candidate_ids": result.top_candidate_ids,
            "candidates": [
                {
                    "discovery_method": c.discovery_method.value,
                    "relevance_status": c.relevance_validation.status.value if c.relevance_validation else None,
                    "relevance_score": c.relevance_validation.relevance_score if c.relevance_validation else None,
                    "rank": c.relevance_validation.rank if c.relevance_validation else None,
                    "eligible_for_editorial": c.relevance_validation.eligible_for_editorial if c.relevance_validation else None,
                }
                for c in result.candidates
            ],
        })

    print(json.dumps({"sample_size": len(summaries), "results": summaries}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
