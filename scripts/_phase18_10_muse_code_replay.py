"""Phase 18.10 M8 replay: real, historical Muse Code NewsEvent titles from the Phase 18.9 live
test, fed through the real services.story_memory.match_story() in chronological order, against a
disposable database (never the real ai_newsroom database). Read-only with respect to real data -
only queries the real DB once, up front, to extract the titles/categories; all matching happens
against the disposable database's own empty `stories` table.
"""
import asyncio
import os
from uuid import uuid4

os.environ["POSTGRES_DB"] = "ai_newsroom_muse_replay"

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from core.config import settings  # noqa: E402
from database.models.news_event import NewsEvent  # noqa: E402
from database.models.news_source import NewsSource, SourceType  # noqa: E402
from database.models.story import Story  # noqa: E402
from services.story_memory import extract_story_signature, match_story  # noqa: E402

_REAL_EVENTS = [
    ("Meta launches Muse Code, an AI agent for large code bases", "STARTUPS"),
    ("Meta Is Challenging Claude Code and Codex With New Muse Code", "GADGETS"),
    ("Meta launches Muse Code AI coding agent for macOS and Linux", "GADGETS"),
    ("Meta releases Muse Code in beta, a terminal coding agent powered by Muse Spark 1.2", "TECH"),
    ("Meta introduces Muse Code, its take on a coding agent", "GADGETS"),
    ("Meta has launched Muse Code, an artificial intelligence agent dedicated to programming", "AI"),
    ("Introducing Muse Code and Muse Spark 1.2", "SOFTWARE"),
]


async def main() -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    print(f"Replaying {len(_REAL_EVENTS)} real historical Muse Code titles, chronological order:\n")
    async with session_factory() as session:
        source = NewsSource(id=uuid4(), name="replay-source", type=SourceType.RSS, active=True)
        session.add(source)
        await session.flush()

        for title, category_str in _REAL_EVENTS:
            from database.models.news_event import EventCategory
            category = EventCategory[category_str]

            # A real NewsEvent row is required (stories.first_event_id has a real FK) - mirrors
            # what services/collector.py would have inserted for each of these real historical
            # items.
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


if __name__ == "__main__":
    asyncio.run(main())
