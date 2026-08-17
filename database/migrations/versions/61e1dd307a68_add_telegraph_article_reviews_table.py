"""add telegraph article reviews table

Revision ID: 61e1dd307a68
Revises: 6025a320a45c
Create Date: 2026-08-17 00:00:00.000000

TELEGRAPH Checkpoint 6 (docs/telegraph_checkpoint_6_telegram_delivery_report.md): one new,
purely additive table - `telegraph_article_reviews`. No existing table, column, or enum is
touched or rewritten. Mirrors `863a064f8ee3_add_telegraph_shortlist_tables.py`'s own shape for a
later stage - see database/models/telegraph_article_review.py's own module docstring for the
full persistence-decision reasoning.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "61e1dd307a68"
down_revision: Union[str, None] = "6025a320a45c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUS_ENUM = sa.Enum("pending", "approved", "needs_revision", name="telegraph_article_review_status")


def upgrade() -> None:
    op.create_table(
        "telegraph_article_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "article_task_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("editorial_tasks.id"), nullable=False, index=True,
        ),
        sa.Column(
            "proposal_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("telegraph_topic_proposals.id"), nullable=False, index=True,
        ),
        sa.Column("status", _STATUS_ENUM, nullable=False, server_default="pending"),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("telegram_thread_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("article_task_id", name="uq_telegraph_article_reviews_article_task"),
    )
    op.create_index(
        "ix_telegraph_article_reviews_status", "telegraph_article_reviews", ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_telegraph_article_reviews_status", table_name="telegraph_article_reviews")
    op.drop_table("telegraph_article_reviews")
    _STATUS_ENUM.drop(op.get_bind(), checkfirst=True)
