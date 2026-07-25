"""add engagement metric columns to news_events

Revision ID: c2a4e6f9b3d1
Revises: 8941ebf13fb0
Create Date: 2026-07-25 00:00:00.000000

Phase 15 M3: additive-only. Four nullable Integer columns capturing real, observed engagement
metrics (views/forwards/replies/reactions_count) at collection time, where the source exposes
them (currently: Telegram only). Existing rows get NULL for all four - never a fabricated 0 -
and remain fully valid; no backfill, no data rewrite.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2a4e6f9b3d1"
down_revision: Union[str, None] = "8941ebf13fb0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("news_events", sa.Column("views_count", sa.Integer(), nullable=True))
    op.add_column("news_events", sa.Column("forwards_count", sa.Integer(), nullable=True))
    op.add_column("news_events", sa.Column("replies_count", sa.Integer(), nullable=True))
    op.add_column("news_events", sa.Column("reactions_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("news_events", "reactions_count")
    op.drop_column("news_events", "replies_count")
    op.drop_column("news_events", "forwards_count")
    op.drop_column("news_events", "views_count")
