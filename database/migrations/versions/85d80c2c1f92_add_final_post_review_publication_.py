"""add final post review publication tracking

Revision ID: 85d80c2c1f92
Revises: af2aeb69cf67
Create Date: 2026-09-02 19:42:47.361921

PRESENTATION RECOVERY, Phase I.3: three purely additive, nullable columns on the existing
`final_post_reviews` table - `published_at`/`published_telegram_message_id`/
`published_telegram_chat_id`. No existing table, column, or enum is touched or rewritten. All three
default to NULL (every existing row is, by definition, not-yet-published - no server_default
needed), so this ADD COLUMN is safe against a table with existing rows without any backfill. See
database/models/final_post_review.py's own updated docstring for the full reasoning (status/
decided_* stay owned by the human-decision gate; these three columns are owned exclusively by
services/final_post_publication.py's real-publish step, populated only on a real successful send).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "85d80c2c1f92"
down_revision: Union[str, None] = "af2aeb69cf67"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("final_post_reviews", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("final_post_reviews", sa.Column("published_telegram_message_id", sa.Integer(), nullable=True))
    op.add_column("final_post_reviews", sa.Column("published_telegram_chat_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("final_post_reviews", "published_telegram_chat_id")
    op.drop_column("final_post_reviews", "published_telegram_message_id")
    op.drop_column("final_post_reviews", "published_at")
