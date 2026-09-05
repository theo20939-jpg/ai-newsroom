"""add telegram channel memory

Revision ID: 97233eb2e1e9
Revises: f513705e3390
Create Date: 2026-09-05 00:00:00.000000

NINJA Social Intelligence Foundation, Part III §39: one new, purely additive table,
telegram_channel_memory. No existing table, column, or enum is touched or rewritten. Local/test
database only - not applied to production as part of this phase.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "97233eb2e1e9"
down_revision: Union[str, None] = "f513705e3390"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STORY_ROLE = sa.Enum("first", "update", "follow_up", "recap", name="telegram_channel_memory_story_role")


def upgrade() -> None:
    op.create_table(
        "telegram_channel_memory",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("post_id", sa.String(64), nullable=True),
        sa.Column("content_draft_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("topics", sa.JSON(), nullable=True),
        sa.Column("entities", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(300), nullable=True),
        sa.Column("presentation_type", sa.String(50), nullable=True),
        sa.Column("media_type", sa.String(50), nullable=True),
        sa.Column("visual_family", sa.String(100), nullable=True),
        sa.Column("template", sa.String(100), nullable=True),
        sa.Column("renderer_version", sa.String(50), nullable=True),
        sa.Column("headline", sa.String(500), nullable=True),
        sa.Column("story_role", _STORY_ROLE, nullable=True),
        sa.Column("content_objective", sa.String(100), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("experiment_id", sa.String(100), nullable=True),
        sa.Column("performance_snapshots", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_telegram_channel_memory_content_draft_id", "telegram_channel_memory", ["content_draft_id"])
    op.create_index("ix_telegram_channel_memory_story_id", "telegram_channel_memory", ["story_id"])
    op.create_index("ix_telegram_channel_memory_event_id", "telegram_channel_memory", ["event_id"])
    op.create_index("ix_telegram_channel_memory_campaign_id", "telegram_channel_memory", ["campaign_id"])
    op.create_index("ix_telegram_channel_memory_published_at", "telegram_channel_memory", ["published_at"])


def downgrade() -> None:
    op.drop_index("ix_telegram_channel_memory_published_at", table_name="telegram_channel_memory")
    op.drop_index("ix_telegram_channel_memory_campaign_id", table_name="telegram_channel_memory")
    op.drop_index("ix_telegram_channel_memory_event_id", table_name="telegram_channel_memory")
    op.drop_index("ix_telegram_channel_memory_story_id", table_name="telegram_channel_memory")
    op.drop_index("ix_telegram_channel_memory_content_draft_id", table_name="telegram_channel_memory")
    op.drop_table("telegram_channel_memory")
    _STORY_ROLE.drop(op.get_bind(), checkfirst=True)
