"""ContentDraftReplyRoutingProposal ORM model (Phase 19 M7).

A standalone table, PK reuses `content_draft_id` (1:1 extension - mirrors database/models/
content_draft_quote.py's own exact convention): at most one reply-routing proposal per draft,
since services/story_telegram_delivery.py::determine_reply_target() is itself a pure, single-
decision function evaluated once per draft.

Persists the reply-routing DECISION (what the system would do / did do) for review - a distinct
concept from database/models/story_telegram_delivery.py::StoryTelegramDelivery, which records
what was ACTUALLY sent. Under `telegram_story_reply_mode == "shadow"`, a proposal row is written
here but StoryTelegramDelivery/the real send are never affected. Under `"enforce"`, both this row
and the real send/StoryTelegramDelivery reflect the same decision (`applied=True` here).
"""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class ContentDraftReplyRoutingProposal(Base):
    __tablename__ = "content_draft_reply_routing_proposals"

    content_draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_drafts.id"), primary_key=True
    )
    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stories.id"), nullable=False, index=True)
    # services/story_telegram_delivery.py's own action vocabulary: "send_as_root" |
    # "send_as_reply" | "fail_closed_route_to_review" - stored verbatim, never re-encoded.
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    proposed_reply_to_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # True only when telegram_story_reply_mode == "enforce" at the time this row was written -
    # i.e. this proposal was actually applied to the real send, not merely computed for review.
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
