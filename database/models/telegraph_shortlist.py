"""TELEGRAPH Checkpoint 2: durable shortlist + human topic-approval persistence.

Two tables, deliberately minimal - the persistence-decision reasoning lives in the Checkpoint 2
report, summarized here: no existing generic entity fits (`MemeCandidate` is the strongest
structural *pattern* but is meme-pipeline-specific column-for-column; `ContentDraftEditorialPlan`/
`StoryContextSnapshot` are scoped to an already-generating draft, not a pre-approval candidate;
`ContentDraftReplyRoutingProposal` is a system-computed decision, not a human one). These two
tables are the direct structural sibling of `MemeCandidate` (Phase 18 M2) for this different
domain - one durable row per proposed topic, decision columns present from the start (not
speculatively added later), never an article body/research/media payload.

`TelegraphShortlistBatch` anchors one shortlist-formation run and its (at most one) delivered
Telegram message. `TelegraphTopicProposal` is one Story proposed within that batch - references
`Story` by FK only (mirrors every other Story-scoped table in this codebase, e.g.
`StoryContextSnapshot`), snapshots the score/rationale/signals Checkpoint 1 computed AT PROPOSAL
TIME (so re-rendering the same message later is consistent even if Checkpoint 1's own scoring
inputs later change), and never copies `NewsEvent.content`/research text.

`consumed_at` (nullable, unset by this checkpoint) is the one field added ahead of the milestone
that populates it - mirrors `MemeCandidate.content_draft_id`'s own "reserved for future
population" precedent - so a future Checkpoint 3 can query "approved AND not yet consumed"
(`status == APPROVED AND consumed_at IS NULL`) without guessing or adding a fourth status value.
No consumption workflow is implemented here; only the field exists.

`decided_by_telegram_user_id` (security-correction addition): the numeric Telegram user id of
the human who set a final `status`, populated atomically with `status`/`decided_at` inside
`TelegraphShortlistService.set_decision()` - `NULL` while `PENDING`, set exactly once, never
overwritten by a repeated or opposite later decision (the same immutable-final policy already
governs `status`/`decided_at`; this column follows it, not a separate rule). Deliberately just
the numeric id - no username/display-name/profile field is stored, matching the checkpoint's own
"Telegram numeric user ID is enough" requirement.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class TelegraphProposalStatus(str, enum.Enum):
    """Deliberately three values only (the phase brief's own explicit "keep lifecycle minimal" /
    "do NOT add a broad workflow status enum unless needed"). `consumed_at` (a plain nullable
    timestamp on the row, not a fourth status value) is how a future exactly-once Checkpoint 3
    handoff is represented instead."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class TelegraphShortlistBatch(Base):
    """One shortlist-formation run. No article body, no research payload, no media payload -
    only what is needed to anchor its proposals and (once sent) find/edit its own Telegram
    message. A batch is only ever created when `create_telegraph_shortlist()` found at least one
    real candidate (see services/telegraph_shortlist_service.py's own docstring for why a
    zero-candidate window persists no row at all) - so `proposal_count` is always >= 1 for any
    row that exists.

    No separate `status` column: this batch's own state is fully determined by its children
    (`TelegraphTopicProposal.status`) plus whether `telegram_message_id` is set (delivered or
    not) - adding a redundant, independently-mutable status column here would risk the two
    disagreeing, which a derived read never can.
    """

    __tablename__ = "telegraph_shortlist_batches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    proposal_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # Populated once (and only once) services/telegraph_shortlist_notifier.py::
    # send_telegraph_shortlist() actually delivers the message - all three NULL until then (a
    # created-but-undelivered batch is a valid, real state, e.g. a dry-run or a delivery
    # failure - never backfilled with a guess).
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    telegram_thread_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("proposal_count >= 1", name="ck_telegraph_shortlist_batches_proposal_count_positive"),
    )


class TelegraphTopicProposal(Base):
    """One proposed article topic (one `Story`) within one `TelegraphShortlistBatch`. References
    `Story`/`TelegraphShortlistBatch` by FK only - `topic_title`/`rationale_snapshot`/
    `signals_snapshot` are the only content copied in, all of it small, deterministic, and
    already computed by services/telegraph_topic_candidates.py at proposal time (never the
    Story's or any NewsEvent's own full text/research)."""

    __tablename__ = "telegraph_topic_proposals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telegraph_shortlist_batches.id"), nullable=False, index=True
    )
    story_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stories.id"), nullable=False, index=True
    )
    # 1-based position within this batch, snapshotted at creation time from services/
    # telegraph_topic_candidates.py's own deterministic ranking - never re-derived at render
    # time, so the numbered "1./2./3." presentation stays stable across message edits even if a
    # later Checkpoint 1 scoring change would reorder a fresh candidate list.
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    topic_score: Mapped[int] = mapped_column(Integer, nullable=False)
    topic_title: Mapped[str] = mapped_column(Text, nullable=False)
    rationale_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    # Compact dict only (normalized_significance/source_diversity_proxy/evidence_tier/
    # event_count/max_score/max_engagement_potential_score) - never a research bundle. Mirrors
    # `ContentDraftEditorialPlan.plan`'s own "one JSON blob, always read/written as one unit"
    # convention.
    signals_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[TelegraphProposalStatus] = mapped_column(
        Enum(
            TelegraphProposalStatus, name="telegraph_proposal_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False, default=TelegraphProposalStatus.PENDING, index=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Security correction: WHO decided - see module docstring. NULL while PENDING, set once,
    # atomically with status/decided_at, in TelegraphShortlistService.set_decision().
    decided_by_telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Reserved for a future Checkpoint 3 exactly-once handoff - see module docstring. Unset
    # (always NULL) anywhere in this checkpoint; no code here ever writes to it.
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        # Defense in depth, not the primary guarantee: services/telegraph_topic_candidates.py's
        # own "one candidate per Story" property already prevents this at the source, but a
        # database-level constraint costs nothing and catches a future caller mistake outright.
        UniqueConstraint("batch_id", "story_id", name="uq_telegraph_topic_proposals_batch_story"),
        CheckConstraint("rank >= 1", name="ck_telegraph_topic_proposals_rank_positive"),
        CheckConstraint("topic_score >= 0 AND topic_score <= 100", name="ck_telegraph_topic_proposals_score_range"),
    )
