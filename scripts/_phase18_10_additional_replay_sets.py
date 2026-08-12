"""Phase 18.10 Stage 8: additional controlled replay sets required alongside the Muse Code replay -
genuine story updates and similar-but-distinct stories, run through the real
services.story_memory.match_story() against the same disposable database
(ai_newsroom_muse_replay). Read-only with respect to real data; all writes go to the disposable DB.
"""
import asyncio
import os
from uuid import uuid4

os.environ["POSTGRES_DB"] = "ai_newsroom_muse_replay"

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from core.config import settings  # noqa: E402
from database.models.news_event import EventCategory, NewsEvent  # noqa: E402
from database.models.news_source import NewsSource, SourceType  # noqa: E402
from database.models.story import Story  # noqa: E402
from services.story_memory import extract_story_signature, match_story  # noqa: E402

# Set A: a genuine developing story - same event, materially new substance each time (funding
# round progressing through stages). Must link as story_update/supporting_source, never
# semantic_duplicate (titles are deliberately NOT near-identical).
_GENUINE_UPDATE_SET = [
    ("Anthropic in talks to raise new funding round at higher valuation", "STARTUPS"),
    ("Anthropic closes funding round, valuation confirmed at $XX billion", "STARTUPS"),
    ("Anthropic to use new funding round for compute expansion, CEO says", "STARTUPS"),
]

# Set B: similar surface features (same sector, similar phrasing) but genuinely distinct events -
# must NOT merge, must all resolve new_story or uncertain (never a confident duplicate).
_SIMILAR_BUT_DISTINCT_SET = [
    ("OpenAI releases new voice model for developers", "AI"),
    ("Google releases new voice model for Android", "AI"),
    ("Amazon releases new voice model for Alexa", "AI"),
]


async def _replay(label: str, events: list[tuple[str, str]]) -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    print(f"\n=== {label} ===\n")
    async with session_factory() as session:
        source = NewsSource(id=uuid4(), name=f"replay-{label}", type=SourceType.RSS, active=True)
        session.add(source)
        await session.flush()

        for title, category_str in events:
            category = EventCategory[category_str]
            event = NewsEvent(
                id=uuid4(), source_id=source.id, title=title, category=category,
                hash=f"replay-{uuid4()}",
            )
            session.add(event)
            await session.flush()

            signature, result = await match_story(session, title=title, category=category)

            if result.outcome == "new_story":
                story = Story(
                    id=uuid4(), title=title, category=category, entities=signature.entities,
                    keywords=signature.keywords, topic_bucket=signature.topic_bucket,
                    first_event_id=event.id, event_count=1,
                )
                session.add(story)
                await session.flush()
                await session.commit()
                story_ref = f"NEW STORY {story.id}"
            else:
                await session.commit()
                story_ref = f"-> matched story {result.matched_story_id}"

            print(f"[{category_str:10s}] {result.outcome:20s} conf={result.confidence:.2f}  {story_ref}")
            print(f"             title: {title}")
            print(f"             reason: {result.similarity_reason}")
            print()

    await engine.dispose()


async def main() -> None:
    await _replay("SET A: genuine developing story (funding round progression)", _GENUINE_UPDATE_SET)
    await _replay("SET B: similar-surface-but-distinct stories (different companies)", _SIMILAR_BUT_DISTINCT_SET)


if __name__ == "__main__":
    asyncio.run(main())
