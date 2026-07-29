"""Phase 16 M4 - offline backtest against real, already-collected NewsEvent rows (docs/
phase16_m4_relevance_ranking_report.md §20). Read-only: selects a bounded sample of recent real
events (across source types), calls services.image_intelligence.run_shadow_discovery(mode="shadow")
directly in-process for each one (identical to what capabilities/executor.py does at the
CONTENT_GENERATION "copywriting" step), and aggregates the M2/M3/M4 outcome distribution. Does not
write to the database, does not create EditorialTasks/ContentDrafts, does not call any LLM/vision
provider, does not send Telegram messages. All network access is the same bounded M2 safe-fetch
path already used by every prior milestone's own backtest/validation script.

Launch with:
    python -m scripts.phase16_m4_offline_backtest
"""
import asyncio
import json
from collections import Counter

from sqlalchemy import select

from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource
from database.session import async_session_factory
from services.image_intelligence import run_shadow_discovery

SAMPLE_SIZE = 120


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

    events_by_candidate_bucket = Counter()
    discovery_method_counts = Counter()
    source_type_counts = Counter()
    technically_valid_total = 0
    quality_eligible_total = 0
    ranked_total = 0
    top_candidate_counts: list[int] = []
    relevance_scores: list[int] = []
    coverage_present = Counter()
    coverage_seen = Counter()
    per_event_records = []

    for event, source_type, source_name in rows:
        result = await run_shadow_discovery(
            event_id=event.id, source_type=source_type, content=event.content,
            article_url=event.url, mode="shadow", event_title=event.title, source_name=source_name,
        )
        source_type_counts[source_type.value] += 1
        n = len(result.candidates)
        if n == 0:
            events_by_candidate_bucket["zero"] += 1
        elif n == 1:
            events_by_candidate_bucket["one"] += 1
        elif n <= 5:
            events_by_candidate_bucket["two_to_five"] += 1
        else:
            events_by_candidate_bucket["more_than_five"] += 1

        technically_valid_total += result.candidates_validated
        quality_eligible_total += result.candidates_quality_eligible
        ranked_total += result.candidates_ranked
        top_candidate_counts.append(len(result.top_candidate_ids))

        record = {
            "event_id": str(event.id), "source_type": source_type.value, "title": event.title[:80],
            "candidates": n, "ranked": result.candidates_ranked, "top_candidate_ids": result.top_candidate_ids,
            "candidate_details": [],
        }
        for candidate in result.candidates:
            discovery_method_counts[candidate.discovery_method.value] += 1
            if candidate.relevance_validation:
                for key, present in candidate.relevance_validation.coverage.items():
                    coverage_seen[key] += 1
                    if present:
                        coverage_present[key] += 1
                if candidate.relevance_validation.status.value == "ranked":
                    relevance_scores.append(candidate.relevance_validation.relevance_score)
                record["candidate_details"].append({
                    "discovery_method": candidate.discovery_method.value,
                    "relevance_status": candidate.relevance_validation.status.value,
                    "relevance_score": candidate.relevance_validation.relevance_score,
                    "rank": candidate.relevance_validation.rank,
                    "source_relationship": candidate.relevance_validation.source_relationship.value if candidate.relevance_validation.source_relationship else None,
                    "reason": candidate.relevance_validation.reason,
                    "quality_score": candidate.quality_validation.quality_score if candidate.quality_validation else None,
                })
        per_event_records.append(record)

    summary = {
        "events_sampled": len(rows),
        "events_by_candidate_bucket": dict(events_by_candidate_bucket),
        "source_type_distribution": dict(source_type_counts),
        "discovery_method_distribution": dict(discovery_method_counts),
        "candidates_technically_valid_total": technically_valid_total,
        "candidates_quality_eligible_total": quality_eligible_total,
        "candidates_ranked_total": ranked_total,
        "average_top_candidate_count": sum(top_candidate_counts) / len(top_candidate_counts) if top_candidate_counts else 0,
        "relevance_score_distribution": {
            "min": min(relevance_scores) if relevance_scores else None,
            "max": max(relevance_scores) if relevance_scores else None,
            "avg": sum(relevance_scores) / len(relevance_scores) if relevance_scores else None,
            "count": len(relevance_scores),
        },
        "metadata_coverage_rate": {
            key: round(coverage_present[key] / seen, 3) if seen else None
            for key, seen in coverage_seen.items()
        },
    }
    print(json.dumps({"summary": summary, "events": per_event_records}, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
