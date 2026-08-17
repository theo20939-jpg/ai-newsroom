"""TELEGRAPH Checkpoint 6: durable human review of one generated TELEGRAPH article.

Persistence decision: no existing table fits. `TelegraphTopicProposal` (Checkpoint 2) already
carries its OWN, separate, immutable-once-final decision (the human's TOPIC approval) - conflating
a second, later, ARTICLE-review decision onto the same row would corrupt that already-reviewed
design (its own "immutable final decision" guarantee stops meaning anything if a second decision
type can still mutate the row). `EditorialTask.workflow` (the TELEGRAPH_ARTICLE task's own JSON)
holds the LLM's OUTPUT, not a human decision about that output - mixing the two would blur the
same "system output vs. human decision" boundary Checkpoint 2's own report already drew between
`TelegraphTopicProposal.signals_snapshot` (system-computed) and its `status`/`decided_by_*`
columns (human-decided). `EditorialTask` itself is a shared, foundational table used by every
workflow type in this codebase - adding TELEGRAPH-review-specific columns there would be scope
creep into NEWS_ANALYSIS/CONTENT_GENERATION/MEME_GENERATION's own table.

`TelegraphArticleReview` is therefore the direct structural sibling of `TelegraphTopicProposal`
for this later stage - same shape, same decision-audit discipline (status/decided_at/
decided_by_telegram_user_id/telegram delivery tracking), reused deliberately rather than
reinvented, for a different row (one per generated article, not one per proposed topic).
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class TelegraphArticleReviewStatus(str, enum.Enum):
    """Three values, mirroring TelegraphProposalStatus's own "keep lifecycle minimal" discipline
    - PENDING/APPROVED plus NEEDS_REVISION (this stage's own "reject" analogue: an article is
    never silently discarded, it is sent back for a human-directed revision instead, per the
    Checkpoint 6 brief's own explicit "approve / request revision" action pair)."""

    PENDING = "pending"
    APPROVED = "approved"
    NEEDS_REVISION = "needs_revision"


class TelegraphArticleReview(Base):
    """One durable row per generated TELEGRAPH_ARTICLE task - the human review decision on that
    article. References the `EditorialTask` running the article-generation workflow by FK only
    (UNIQUE - at most one review per article task), plus the originating proposal for convenient
    display/traceability back to the original topic decision."""

    __tablename__ = "telegraph_article_reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    article_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("editorial_tasks.id"), nullable=False, index=True
    )
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telegraph_topic_proposals.id"), nullable=False, index=True
    )
    status: Mapped[TelegraphArticleReviewStatus] = mapped_column(
        Enum(
            TelegraphArticleReviewStatus, name="telegraph_article_review_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False, default=TelegraphArticleReviewStatus.PENDING, index=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Delivery tracking - mirrors TelegraphShortlistBatch's own identical three columns exactly,
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
        UniqueConstraint("article_task_id", name="uq_telegraph_article_reviews_article_task"),
    )
