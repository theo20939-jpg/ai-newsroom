"""add editorial_channel to telegraph topic proposals

Revision ID: ce83f2ed1c0d
Revises: 61e1dd307a68
Create Date: 2026-08-17 00:00:00.000000

TELEGRAPH editorial channel split: one purely additive, NOT NULL column with a server default -
`telegraph_topic_proposals.editorial_channel`. No existing table, column, or enum is touched or
rewritten. The `server_default` means this ADD COLUMN is safe even against a table with existing
rows (none exist in any real database as of this migration, verified directly against the dev DB
at authoring time), never requiring a separate backfill step.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "ce83f2ed1c0d"
down_revision: Union[str, None] = "61e1dd307a68"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CHANNEL_ENUM = sa.Enum("ninja_ai", "ninja_pulse", name="editorial_channel")


def upgrade() -> None:
    _CHANNEL_ENUM.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "telegraph_topic_proposals",
        sa.Column(
            "editorial_channel", _CHANNEL_ENUM, nullable=False, server_default="ninja_pulse",
        ),
    )
    op.create_index(
        "ix_telegraph_topic_proposals_editorial_channel", "telegraph_topic_proposals", ["editorial_channel"],
    )


def downgrade() -> None:
    op.drop_index("ix_telegraph_topic_proposals_editorial_channel", table_name="telegraph_topic_proposals")
    op.drop_column("telegraph_topic_proposals", "editorial_channel")
    _CHANNEL_ENUM.drop(op.get_bind(), checkfirst=True)
