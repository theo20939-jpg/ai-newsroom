"""NINJA PULSE RECAP Phase R2 integration, Phase D.0: durable human review of one synthesized
EVENT_RECAP EditorialTask. Direct structural sibling of `TelegraphArticleReview` (database/models/
telegraph_article_review.py) - identical persistence-decision reasoning (a human review decision is
never conflated onto the `EditorialTask` row itself, which is a shared, foundational table used by
every workflow type in this codebase). Reused deliberately rather than reinvented, for one row per
EVENT_RECAP workflow task.

One real difference from `TelegraphArticleReview`: no `proposal_id` FK. EVENT_RECAP has no separate
topic-proposal stage the way TELEGRAPH_ARTICLE has `TelegraphTopicProposal` - a Story is recapped
directly (services/event_recap_processor.py::generate_recap_for_story()'s own module docstring),
so this table's only FK is to the EditorialTask itself.

Deliberately excludes (per Phase D.0's own explicit scope - the pre-implementation architectural
audit found no existing table fits, see docs/ for that report): a Story FK (this review is scoped
to the recap TASK, not the Story directly - mirrors `TelegraphArticleReview` being scoped to the
article task, never the Story), a ContentDraft FK (no publish/content-draft stage exists for
EVENT_RECAP), and any publish-related field. EVENT_RECAP stays shadow-only;
`EventRecapCandidate.publishable` (services/event_recap.py) is untouched by and has no equivalent
column on this table.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class EventRecapReviewStatus(str, enum.Enum):
    """Three values, mirroring `TelegraphArticleReviewStatus`'s own identical "keep lifecycle
    minimal" discipline - PENDING/APPROVED plus NEEDS_REVISION (a recap is never silently
    discarded, it is sent back for a human-directed revision instead)."""

    PENDING = "pending"
    APPROVED = "approved"
    NEEDS_REVISION = "needs_revision"


class EventRecapReview(Base):
    """One durable row per EVENT_RECAP `EditorialTask` - the human review decision on that
    synthesized recap. References the `EditorialTask` running the EVENT_RECAP workflow by FK only
    (UNIQUE - at most one review per recap task)."""

    __tablename__ = "event_recap_reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recap_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("editorial_tasks.id"), nullable=False, index=True
    )
    status: Mapped[EventRecapReviewStatus] = mapped_column(
        Enum(
            EventRecapReviewStatus, name="event_recap_review_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False, default=EventRecapReviewStatus.PENDING, index=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Delivery tracking - mirrors TelegraphArticleReview's own identical three columns exactly,
    # for the identical reason (find/edit the review's own Telegram message in place).
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    telegram_thread_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("recap_task_id", name="uq_event_recap_reviews_recap_task"),
    )
