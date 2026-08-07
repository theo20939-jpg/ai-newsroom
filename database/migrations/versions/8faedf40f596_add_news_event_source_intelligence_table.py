"""add news event source intelligence table

Revision ID: 8faedf40f596
Revises: 280fa1e7d6d2
Create Date: 2026-08-07 00:00:00.000000

Phase 19 M8 (docs/phase19_m8_source_intelligence.md): one new, purely additive, standalone table -
`news_event_source_intelligence`. PK reuses `news_event_id` (1:1 extension, mirrors
`news_event_article_acquisitions`/`news_event_story_links`' own convention). `news_events` is not
altered.

Depends on: `source_intelligence_mode` (core/config.py). Written but NOT applied as part of
Phase 19's implementation, per explicit instruction (migration design only - the user applies it
separately).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "8faedf40f596"
down_revision: Union[str, None] = "280fa1e7d6d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "news_event_source_intelligence",
        sa.Column(
            "news_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("news_events.id"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("is_first_in_story", sa.Boolean(), nullable=False),
        sa.Column("match_type", sa.String(length=32), nullable=True),
        sa.Column("reliability_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("news_event_source_intelligence")
