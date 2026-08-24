"""add event recap reviews table

Revision ID: 8b76ac53ee1d
Revises: ce83f2ed1c0d
Create Date: 2026-08-24 00:00:00.000000

NINJA PULSE RECAP Phase R2 integration, Phase D.0: one new, purely additive table -
`event_recap_reviews`. No existing table, column, or enum is touched or rewritten. Mirrors
`61e1dd307a68_add_telegraph_article_reviews_table.py`'s own shape for a structurally identical
later stage of a different workflow - see database/models/event_recap_review.py's own module
docstring for the full persistence-decision reasoning (in particular, why this table has no
`proposal_id`-equivalent FK, unlike its Telegraph sibling).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "8b76ac53ee1d"
down_revision: Union[str, None] = "ce83f2ed1c0d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUS_ENUM = sa.Enum("pending", "approved", "needs_revision", name="event_recap_review_status")


def upgrade() -> None:
    op.create_table(
        "event_recap_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "recap_task_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("editorial_tasks.id"), nullable=False, index=True,
        ),
        sa.Column("status", _STATUS_ENUM, nullable=False, server_default="pending"),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("telegram_thread_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("recap_task_id", name="uq_event_recap_reviews_recap_task"),
    )
    op.create_index(
        "ix_event_recap_reviews_status", "event_recap_reviews", ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_event_recap_reviews_status", table_name="event_recap_reviews")
    op.drop_table("event_recap_reviews")
    _STATUS_ENUM.drop(op.get_bind(), checkfirst=True)
