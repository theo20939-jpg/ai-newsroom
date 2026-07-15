"""Validated contract returned by every source adapter."""
from datetime import datetime

from pydantic import BaseModel


class RawNewsItem(BaseModel):
    """A single unprocessed item fetched from an external source.

    Deliberately unaware of the database: adapters (Telegram, RSS, News API)
    only know how to produce this shape, not how it gets persisted.
    """

    external_id: str
    text: str | None = None
    url: str | None = None
    published_at: datetime | None = None
