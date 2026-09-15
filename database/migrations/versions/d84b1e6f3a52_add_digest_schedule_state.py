"""add digest schedule state (Migration 2)

Revision ID: d84b1e6f3a52
Revises: a3f7c1d9e042
Create Date: 2026-09-15 00:00:00.000000

INSTAGRAM-CONTENT-STRATEGY-V2 Phase 4 (NEWS_DIGEST). One new, purely additive table -
`digest_schedule_state` - the durable wall-clock cadence state the 72h NEWS_DIGEST lane needs
(a plain in-memory `cycle_count % N` counter, as `worker/content_main.py` uses for image
retention, would reset on every process restart - unsafe for a 72-hour guarantee). Kept as its
own migration, separate from Migration 1 (Director extension) and the future Migration 3 (Trend
persistence) - each rollout boundary gets its own migration, never bundled.

Local/test database only - this migration is NOT applied to production as part of this phase.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d84b1e6f3a52"
down_revision: Union[str, None] = "a3f7c1d9e042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "digest_schedule_state",
        sa.Column("schedule_key", sa.String(50), primary_key=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("digest_schedule_state")
