"""Phase 19 M6: replays real, historical NewsEvent titles (title/category/collected_at/
published_at only - never full article content) through the real services.story_memory.
match_story(), in chronological order, against a disposable database.

Two independent database connections, deliberately never sharing core.config.settings'
singleton engine (unlike scripts/_phase18_10_muse_code_replay.py's single-DB os.environ-override
trick, which only works for one connection at a time): a READ-ONLY connection to the real
ai_newsroom DB (source of real titles/categories/timestamps only) and a separate connection to a
disposable DB (already migrated to head by the caller via `alembic upgrade head`) that this
script writes NewsEvent/NewsSource/Story/NewsEventStoryLink rows into, exactly mirroring what
services/triage_orchestrator.py would have persisted had story_memory_mode been "shadow" this
whole time. Never writes anything to the real DB, never mutates a real NewsEvent row.

Writes machine predictions (every event's match_story() outcome) to
scripts/_phase19_m6_real_replay_predictions.json - the raw input the human-review-packet builder
(scripts/_phase19_m6_build_calibration_packet.py) stratifies its sample from.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.config import settings
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from services.story_memory import match_story

_OUTPUT_PATH = Path(__file__).with_name("_phase19_m6_real_replay_predictions.json")


def _disposable_url(*, host: str, port: int, user: str, password: str, db: str) -> str:
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"


async def _fetch_real_events(limit: int | None) -> list[dict]:
    """Read-only: title/category/collected_at/published_at/id only, never content/url/body -
    the minimum needed to reproduce chronological same-category matching. Ordered by
    collected_at ascending (the same order services/collector.py would have inserted them)."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    events: list[dict] = []
    async with session_factory() as session:
        stmt = select(
            NewsEvent.id, NewsEvent.title, NewsEvent.category,
            NewsEvent.collected_at, NewsEvent.published_at,
        ).where(NewsEvent.category != EventCategory.UNKNOWN).order_by(NewsEvent.collected_at.asc())
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).all()
        for row in rows:
            events.append(
                {
                    "real_event_id": str(row.id),
                    "title": row.title,
                    "category": row.category.name,
                    "collected_at": row.collected_at.isoformat() if row.collected_at else None,
                    "published_at": row.published_at.isoformat() if row.published_at else None,
                }
            )
    await engine.dispose()
    return events


async def _replay_into_disposable(
    events: list[dict], *, disposable_url: str
) -> list[dict]:
    engine = create_async_engine(disposable_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    predictions: list[dict] = []
    async with session_factory() as session:
        source = NewsSource(id=uuid4(), name="phase19-m6-replay-source", type=SourceType.RSS, active=True)
        session.add(source)
        await session.flush()

        for item in events:
            category = EventCategory[item["category"]]
            reference_now = (
                datetime.fromisoformat(item["collected_at"]) if item["collected_at"] else datetime.now()
            )
            event = NewsEvent(
                id=uuid4(), source_id=source.id, title=item["title"], category=category,
                hash=f"m6-replay-{uuid4()}",
            )
            session.add(event)
            await session.flush()

            signature, result = await match_story(
                session, title=item["title"], category=category, now=reference_now
            )

            if result.outcome == "new_story":
                story = Story(
                    id=uuid4(), title=item["title"], category=category, entities=signature.entities,
                    keywords=signature.keywords, topic_bucket=signature.topic_bucket,
                    first_event_id=event.id, event_count=1,
                )
                session.add(story)
                await session.flush()
                await session.commit()
                matched_story_id: str | None = None
                matched_story_title: str | None = None
            else:
                story_row = await session.get(Story, result.matched_story_id)
                assert story_row is not None
                story_row.event_count += 1
                await session.flush()
                await session.commit()
                matched_story_id = str(result.matched_story_id)
                matched_story_title = story_row.title

            predictions.append(
                {
                    "real_event_id": item["real_event_id"],
                    "title": item["title"],
                    "category": item["category"],
                    "collected_at": item["collected_at"],
                    "outcome": result.outcome,
                    "confidence": result.confidence,
                    "similarity_reason": result.similarity_reason,
                    "topic_bucket": signature.topic_bucket,
                    "entities": signature.entities,
                    "matched_story_id": matched_story_id,
                    "matched_story_title": matched_story_title,
                }
            )

    await engine.dispose()
    return predictions


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="cap on number of real events replayed")
    parser.add_argument("--disposable-host", default="localhost")
    parser.add_argument("--disposable-port", type=int, default=55435)
    parser.add_argument("--disposable-user", default="disposable")
    parser.add_argument("--disposable-password", default="disposable_pw")
    parser.add_argument("--disposable-db", default="phase19_m6")
    args = parser.parse_args()

    disposable_url = _disposable_url(
        host=args.disposable_host, port=args.disposable_port, user=args.disposable_user,
        password=args.disposable_password, db=args.disposable_db,
    )

    print("Reading real NewsEvent rows (read-only, title/category/timestamps only)...")
    events = await _fetch_real_events(args.limit)
    print(f"Fetched {len(events)} real events.")

    print(f"Replaying chronologically against disposable DB at {args.disposable_host}:{args.disposable_port}/{args.disposable_db} ...")
    predictions = await _replay_into_disposable(events, disposable_url=disposable_url)

    _OUTPUT_PATH.write_text(json.dumps(predictions, indent=2), encoding="utf-8")
    print(f"Wrote {len(predictions)} machine predictions to {_OUTPUT_PATH}")

    from collections import Counter

    counts = Counter(p["outcome"] for p in predictions)
    print("Outcome distribution:", dict(counts))


if __name__ == "__main__":
    asyncio.run(main())
