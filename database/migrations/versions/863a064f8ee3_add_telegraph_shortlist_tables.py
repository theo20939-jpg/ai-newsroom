"""add telegraph shortlist tables

Revision ID: 863a064f8ee3
Revises: 3f37cf34109d
Create Date: 2026-08-16 00:00:00.000000

TELEGRAPH Checkpoint 2 (docs/telegraph_checkpoint_2_shortlist_and_approval_report.md): two new,
purely additive tables - the single migration this checkpoint needs. No existing table, column,
or enum is touched or rewritten. Mirrors `21177d5b859e_add_meme_candidates_table.py`'s own
shape/discipline (one durable row per candidate, decision columns present from the start) for a
different domain - see database/models/telegraph_shortlist.py's own module docstring for the full
persistence-decision reasoning (no existing generic entity fits; MemeCandidate is the structural
pattern reused, not the table itself).

Security-correction revision (pre-commit, same revision id - this migration had not yet been
applied to any real database when the correction was made, so it is edited in place rather than
chained as a second migration): added `decided_by_telegram_user_id` (nullable BigInteger) to
`telegraph_topic_proposals` for decision auditability. No other shape change.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "863a064f8ee3"
down_revision: Union[str, None] = "3f37cf34109d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUS_ENUM = sa.Enum("pending", "approved", "rejected", name="telegraph_proposal_status")


def upgrade() -> None:
    op.create_table(
        "telegraph_shortlist_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("proposal_count", sa.Integer(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("telegram_thread_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "proposal_count >= 1", name="ck_telegraph_shortlist_batches_proposal_count_positive"
        ),
    )

    op.create_table(
        "telegraph_topic_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "batch_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("telegraph_shortlist_batches.id"), nullable=False, index=True,
        ),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stories.id"), nullable=False, index=True),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("topic_score", sa.Integer(), nullable=False),
        sa.Column("topic_title", sa.Text(), nullable=False),
        sa.Column("rationale_snapshot", sa.Text(), nullable=False),
        sa.Column("signals_snapshot", sa.JSON(), nullable=False),
        sa.Column("status", _STATUS_ENUM, nullable=False, server_default="pending"),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("batch_id", "story_id", name="uq_telegraph_topic_proposals_batch_story"),
        sa.CheckConstraint("rank >= 1", name="ck_telegraph_topic_proposals_rank_positive"),
        sa.CheckConstraint(
            "topic_score >= 0 AND topic_score <= 100", name="ck_telegraph_topic_proposals_score_range"
        ),
    )
    op.create_index("ix_telegraph_topic_proposals_status", "telegraph_topic_proposals", ["status"])


def downgrade() -> None:
    op.drop_index("ix_telegraph_topic_proposals_status", table_name="telegraph_topic_proposals")
    op.drop_table("telegraph_topic_proposals")
    op.drop_table("telegraph_shortlist_batches")
    _STATUS_ENUM.drop(op.get_bind(), checkfirst=True)
