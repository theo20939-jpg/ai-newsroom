"""add publication fields to telegraph article reviews

Revision ID: e0da237ec184
Revises: b0e95ddf7b05
Create Date: 2026-08-31 00:00:00.000000

TELEGRAPH LIVE PUBLISH: two purely additive, nullable columns on the existing
`telegraph_article_reviews` table - `published_url`/`published_at`. No existing table, column, or
enum is touched or rewritten. Both columns default to NULL (no server_default needed - every
existing row is, by definition, unpublished under the old code), so this ADD COLUMN is safe
against a table with existing rows without any backfill. See database/models/
telegraph_article_review.py's own updated module docstring for the full persistence-decision
reasoning (why this reuses the existing row instead of a new standalone table).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e0da237ec184"
down_revision: Union[str, None] = "b0e95ddf7b05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("telegraph_article_reviews", sa.Column("published_url", sa.Text(), nullable=True))
    op.add_column(
        "telegraph_article_reviews", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("telegraph_article_reviews", "published_at")
    op.drop_column("telegraph_article_reviews", "published_url")
