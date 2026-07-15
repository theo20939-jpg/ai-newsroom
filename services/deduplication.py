"""Database duplicate checks for collected news events (Deduplication Service)."""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.news_event import NewsEvent

logger = logging.getLogger(__name__)


async def is_duplicate(session: AsyncSession, content_hash: str) -> bool:
    """Return True if a NewsEvent with this hash already exists."""
    result = await session.execute(select(NewsEvent.id).where(NewsEvent.hash == content_hash))
    return result.scalar_one_or_none() is not None
