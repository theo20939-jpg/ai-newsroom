"""create final post reviews table

Revision ID: b0e95ddf7b05
Revises: 8b76ac53ee1d
Create Date: 2026-08-25 17:46:18.716084

Phase I.2: one new, purely additive table - `final_post_reviews`. No existing table, column, or
enum is touched or rewritten. Mirrors `8b76ac53ee1d_add_event_recap_reviews_table.py`'s own shape
for a structurally identical later human-review stage of a different workflow - see
database/models/final_post_review.py's own module docstring for the full persistence-decision
reasoning (in particular, why this table's FK is `content_draft_id`, not a task id, and why the
status enum is APPROVED_FOR_PUBLICATION rather than a bare APPROVED).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b0e95ddf7b05'
down_revision: Union[str, None] = '8b76ac53ee1d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUS_ENUM = sa.Enum(
    "pending", "approved_for_publication", "needs_revision", name="final_post_review_status",
)


def upgrade() -> None:
    op.create_table(
        "final_post_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "content_draft_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("content_drafts.id"), nullable=False, index=True,
        ),
        sa.Column("status", _STATUS_ENUM, nullable=False, server_default="pending"),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("telegram_thread_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("content_draft_id", name="uq_final_post_reviews_content_draft"),
    )
    op.create_index(
        "ix_final_post_reviews_status", "final_post_reviews", ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_final_post_reviews_status", table_name="final_post_reviews")
    op.drop_table("final_post_reviews")
    _STATUS_ENUM.drop(op.get_bind(), checkfirst=True)
