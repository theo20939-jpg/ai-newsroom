"""Phase 11 read-only view model for the Telegram Editorial Inbox (docs/
phase11_telegram_editorial_inbox_architecture_contract.md §8).

`ContentDraftRead` (schemas/content_draft.py) is not reused here: it carries only ContentDraft's
own columns and has no field for the joined NewsEvent metadata the card (Contract §12) requires.
Adding those fields to ContentDraftRead would conflate Phase 10's persistence-return-value contract
with Phase 11's joined, presentation-oriented view.
"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EditorialInboxCard(BaseModel):
    """Transport-neutral view of one editorial draft, joined with its source NewsEvent metadata.

    No aiogram type appears here - built by services/editorial_inbox_service.py, consumed by
    bot/formatting.py, never crossing back as a raw ORM object."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    draft_id: UUID
    draft_title: str | None
    draft_body: str | None
    hashtags: list[str] | None
    draft_created_at: datetime
    news_title: str
    news_category: str
    news_url: str | None
    news_published_at: datetime | None
