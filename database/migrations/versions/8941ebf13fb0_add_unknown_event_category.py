"""add UNKNOWN value to event_category enum

Revision ID: 8941ebf13fb0
Revises: fbb55860708f
Create Date: 2026-07-14 00:00:00.000000

Note: PostgreSQL does not support removing a value from an enum type, so
downgrade() cannot cleanly reverse this migration. Rows using UNKNOWN would
need to be reassigned to another category before the value could be dropped
by recreating the type - out of scope for this migration.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8941ebf13fb0"
down_revision: Union[str, None] = "fbb55860708f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE event_category ADD VALUE IF NOT EXISTS 'UNKNOWN'")


def downgrade() -> None:
    raise NotImplementedError(
        "PostgreSQL does not support dropping a value from an enum type; "
        "reverting this migration requires a manual data migration."
    )
