"""ContentDraftQuote ORM model (Phase 18.10 M5).

A deliberately standalone table, never columns on `ContentDraft` itself - same hot-path-
dependency reasoning as database/models/story_link.py/content_draft_story_link.py: a row here
exists if and only if a verified quote was found for this draft (services/quote_verification.py)
- most drafts will never have one, and `ContentDraft` itself must never depend on this phase's
migration being applied.

`speaker`/`text` come from the LLM (post-verification only - see services/quote_verification.py's
own fail-closed contract); `source_url`/`published_at` are populated deterministically from the
source NewsEvent, never from the LLM - both disclosed, deliberate anti-fabrication measures.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class ContentDraftQuote(Base):
    __tablename__ = "content_draft_quotes"

    content_draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_drafts.id"), primary_key=True
    )
    # Verbatim, original-language quotation - never translated, never paraphrased (services/
    # quote_verification.py verifies this text actually appears in the source before this row is
    # ever created).
    quote_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Kept distinct from quote_text - a translation is never allowed to silently replace or alter
    # the verbatim original this row's own verification was performed against.
    translated_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    speaker: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
