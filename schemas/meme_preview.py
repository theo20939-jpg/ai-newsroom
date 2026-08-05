"""MemePreviewCard (Phase 18 M8): the transport-neutral view model for a meme's Telegram
editorial preview (docs/phase18_m8_telegram_editorial_preview_report.md).

Mirrors `schemas.editorial_inbox.EditorialInboxCard`'s own established role exactly - a plain,
pure-data view model built from already-loaded ORM rows/upstream results, never an ORM object
itself, consumed by both `bot/meme_preview_formatting.py` (rendering) and
`services/meme_preview_notifier.py` (sending) without either needing to know how the data was
assembled.
"""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MemePreviewCard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: UUID
    news_title: str
    news_url: str | None
    news_category: str

    # The final overlay/caption text (schemas.meme_copy.MemeCopy) - never the raw MemeConcept.
    top_text: str
    bottom_text: str | None
    telegram_caption: str
    editor_explanation: str | None
    alt_text: str

    # Reference only - never raw bytes on this model (mirrors every other Phase 18 result schema's
    # "storage_key is an internal reference only" discipline).
    image_storage_key: str | None

    # Human-readable summaries built from M3/M7's own structured results - short, editor-facing,
    # never the full raw assessment JSON (mirrors bot/formatting.py's own "editorial card, not a
    # technical readout" discipline).
    safety_summary: str
    quality_summary: str
