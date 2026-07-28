"""Phase 16 M1 - Image Intelligence read-only real-data backtest (docs/
phase16_m1_native_media_ingestion_report.md §17).

Read-only. Computes reconstruct_hints_from_content() + consolidate_candidates() against
already-persisted NewsEvent.content/url rows - never mutates any row, never fetches a network
resource, never downloads an image, never calls an LLM/provider.

This backtests the CONTENT_GENERATION-time reconstruction path only (services.image_intelligence.
reconstruct_hints_from_content), the one path that can legitimately run against historical data -
the richer adapter-time extraction (Telegram photo/document, RSS media_content/enclosure/
thumbnail) operates on raw Telethon/feedparser objects that are never persisted (docs/
phase16_image_intelligence_discovery_report.md §11), so there is nothing to backtest it against
for events collected before this milestone. That path is instead covered by
tests/test_image_intelligence.py's synthetic-fixture unit tests.

Launch with:
    python -m scripts.phase16_m1_image_intelligence_backtest
"""
import asyncio
import json
from collections import defaultdict
from typing import Any

from sqlalchemy import select

from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource
from database.session import async_session_factory
from services.image_intelligence import consolidate_candidates, reconstruct_hints_from_content

SAMPLE_SIZE = 400  # generous oversample of the required >=100, spread across source types


async def main() -> None:
    async with async_session_factory() as session:
        stmt = (
            select(NewsEvent, NewsSource)
            .join(NewsSource, NewsEvent.source_id == NewsSource.id)
            .order_by(NewsEvent.collected_at.desc())
            .limit(SAMPLE_SIZE)
        )
        rows = (await session.execute(stmt)).all()

    by_source_type: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_discovery_method: dict[str, int] = defaultdict(int)
    candidate_bucket_by_source: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    payload_sizes: list[int] = []
    malformed_count = 0
    total_events = 0
    total_candidates_discovered = 0
    total_candidates_accepted = 0
    total_candidates_rejected = 0

    for event, source in rows:
        total_events += 1
        source_type = source.type.value

        try:
            hints = reconstruct_hints_from_content(event.content, event.url)
            result = consolidate_candidates(hints, event_id=event.id, source_type=source.type, mode="shadow")
        except Exception:
            malformed_count += 1
            continue

        total_candidates_discovered += result.candidates_discovered
        total_candidates_accepted += result.candidates_accepted
        total_candidates_rejected += result.candidates_rejected

        by_source_type[source_type]["events"] += 1
        by_source_type[source_type]["candidates_discovered"] += result.candidates_discovered
        by_source_type[source_type]["candidates_accepted"] += result.candidates_accepted
        by_source_type[source_type]["candidates_rejected"] += result.candidates_rejected

        for candidate in result.candidates:
            by_discovery_method[candidate.discovery_method.value] += 1

        accepted = result.candidates_accepted
        if accepted == 0:
            bucket = "0"
        elif accepted == 1:
            bucket = "1"
        elif accepted <= 5:
            bucket = "2-5"
        else:
            bucket = ">5"
        candidate_bucket_by_source[source_type][bucket] += 1

        payload_sizes.append(len(result.model_dump_json()))

    summary: dict[str, Any] = {
        "sample_size": total_events,
        "malformed_or_error_count": malformed_count,
        "totals": {
            "candidates_discovered": total_candidates_discovered,
            "candidates_accepted": total_candidates_accepted,
            "candidates_rejected": total_candidates_rejected,
        },
        "by_source_type": {k: dict(v) for k, v in by_source_type.items()},
        "by_discovery_method": dict(by_discovery_method),
        "candidate_count_bucket_by_source_type": {k: dict(v) for k, v in candidate_bucket_by_source.items()},
        "payload_size_bytes": {
            "min": min(payload_sizes) if payload_sizes else 0,
            "max": max(payload_sizes) if payload_sizes else 0,
            "avg": round(sum(payload_sizes) / len(payload_sizes), 1) if payload_sizes else 0,
        },
        "known_limitation": (
            "This backtest exercises reconstruct_hints_from_content() only (CONTENT_GENERATION-"
            "time path, operates on already-persisted NewsEvent.content/url). It cannot recover "
            "Telegram photo/document hints or RSS media_content/media_thumbnail/enclosure hints "
            "for historical events, since those were never persisted anywhere prior to this "
            "milestone (discovery report §11) - only RSS inline-<img>-in-content is recoverable "
            "here. The full adapter-time extraction capability is validated by tests/"
            "test_image_intelligence.py's synthetic-fixture unit tests instead, and will only "
            "produce real Telegram-native/RSS-structured-field candidates going forward, for "
            "events collected after M1 deploys."
        ),
    }

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
