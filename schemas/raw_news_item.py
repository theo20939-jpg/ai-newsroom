"""Validated contract returned by every source adapter."""
from datetime import datetime

from pydantic import BaseModel, Field

from schemas.image_candidate import NativeMediaHint


class RawNewsItem(BaseModel):
    """A single unprocessed item fetched from an external source.

    Deliberately unaware of the database: adapters (Telegram, RSS, News API)
    only know how to produce this shape, not how it gets persisted.

    Phase 15 M3: the four engagement fields below are real, observed metrics from the source
    itself (e.g. Telethon's Message.views/forwards/replies/reactions) - never fabricated. `None`
    means "this source/message does not expose this metric" (RSS/web sources always leave all
    four `None`); a real `0` means "observed, confirmed zero" - the two are never conflated (see
    services/cleaning.py and database/models/news_event.py for how this distinction is
    preserved downstream).

    Phase 16 M1: `native_media_hints` is additive and optional (default `[]`) - an adapter that
    never sets it (GitHub/HN/arXiv) is byte-for-byte unchanged. It exists only so
    services/collector.py can log a native-media audit trail once a NewsEvent's real `event_id`
    is known (docs/phase16_m1_native_media_ingestion_report.md §3); it is never persisted to
    PostgreSQL as-is - NewsEvent has no column for it, and M1 adds no migration.
    """

    external_id: str
    title: str | None = None  # explicit title candidate, if the source separates it from text/body
    text: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    views_count: int | None = None
    forwards_count: int | None = None
    replies_count: int | None = None
    reactions_count: int | None = None
    native_media_hints: list[NativeMediaHint] = Field(default_factory=list)
