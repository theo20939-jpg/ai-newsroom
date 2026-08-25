"""Phase I.2: durable human review of one FINAL_POST_AUTHORING `ContentDraft` - the SECOND human
gate this project's pipeline requires (Phase I.1's own architecture decision, restated in this
phase's own instructions): "APPROVED EVENT_RECAP -> FINAL_POST_AUTHORING -> ContentDraft -> FINAL
POST PREVIEW -> human approve/revise -> publication [I.3, not built here]."

Direct structural sibling of `EventRecapReview` (database/models/event_recap_review.py) - identical
persistence-decision reasoning (a human review decision is never conflated onto a shared,
foundational table used by other workflows). Reused deliberately rather than reinvented, for one
row per `ContentDraft` that reaches this gate.

FK is `content_draft_id`, NOT a task id: unlike `EventRecapReview` (scoped to the recap TASK, since
EVENT_RECAP has no separate content artifact yet), a Final Post's actual reviewable artifact IS the
`ContentDraft` row itself (title/body) - the FINAL_POST_AUTHORING task is still reachable
transitively via `ContentDraft.task_id`, so no redundant task FK is added here.

Status is a THREE-value lifecycle - `PENDING` / `APPROVED_FOR_PUBLICATION` / `NEEDS_REVISION` -
deliberately never a bare `APPROVED` (this phase's own explicit "could be confused with an
already-published state" instruction): `APPROVED_FOR_PUBLICATION` means "a human has authorized
this exact ContentDraft for a FUTURE publication," never "this has been published." No publication
timestamp/outcome field exists on this table - I.3 (a later, separate phase) is expected to own
that durable record; this table's own scope ends at the human decision.

`telegram_chat_id`/`telegram_message_id`/`telegram_thread_id` refer to MESSAGE 2 only (the control
message carrying the ✅/✏️ keyboard) - never MESSAGE 1 (the public-like preview photo+caption).
services/final_post_review_notifier.py's own module docstring documents the full two-message
contract this mirrors from services/event_recap_review_notifier.py's own H.2 precedent.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class FinalPostReviewStatus(str, enum.Enum):
    """Three values, mirroring `EventRecapReviewStatus`'s own "keep lifecycle minimal" discipline -
    PENDING/NEEDS_REVISION plus `APPROVED_FOR_PUBLICATION` (never a bare APPROVED - see this
    module's own docstring for why)."""

    PENDING = "pending"
    APPROVED_FOR_PUBLICATION = "approved_for_publication"
    NEEDS_REVISION = "needs_revision"


class FinalPostReview(Base):
    """One durable row per FINAL_POST_AUTHORING `ContentDraft` - the human publication-review
    decision on that draft. References the `ContentDraft` by FK only (UNIQUE - at most one review
    per draft)."""

    __tablename__ = "final_post_reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content_draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_drafts.id"), nullable=False, index=True
    )
    status: Mapped[FinalPostReviewStatus] = mapped_column(
        Enum(
            FinalPostReviewStatus, name="final_post_review_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False, default=FinalPostReviewStatus.PENDING, index=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Delivery tracking for MESSAGE 2 (the control message) ONLY - mirrors EventRecapReview's own
    # identical three columns exactly, for the identical reason (find/edit that message in place).
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
        UniqueConstraint("content_draft_id", name="uq_final_post_reviews_content_draft"),
    )
