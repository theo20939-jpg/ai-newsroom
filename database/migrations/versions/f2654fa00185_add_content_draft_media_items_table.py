"""add content draft media items table

Revision ID: f2654fa00185
Revises: 8faedf40f596
Create Date: 2026-08-07 00:00:00.000000

Phase 19 M10 (docs/phase19_m10_video_discovery.md): one new, purely additive, standalone table -
`content_draft_media_items`. Surrogate PK (not PK-reuse) since a media item is discovered once
per content-generation attempt, before a ContentDraft row necessarily exists. Neither
`news_events` nor `content_drafts` is altered. Scoped to video candidates for this milestone
(`media_type="video"`); named generically as the shared future home for M11's media ranking.

Depends on: `video_discovery_mode` (core/config.py). Written but NOT applied as part of Phase 19's
implementation, per explicit instruction (migration design only - the user applies it separately).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f2654fa00185"
down_revision: Union[str, None] = "8faedf40f596"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "content_draft_media_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("news_events.id"), nullable=False),
        sa.Column("content_draft_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("content_drafts.id"), nullable=True),
        sa.Column("media_type", sa.String(length=16), nullable=False, server_default="video"),
        sa.Column("discovery_method", sa.String(length=64), nullable=False),
        sa.Column("remote_url", sa.String(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("declared_width", sa.Integer(), nullable=True),
        sa.Column("declared_height", sa.Integer(), nullable=True),
        sa.Column("declared_mime_type", sa.String(length=64), nullable=True),
        sa.Column("declared_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.Column("detected_container", sa.String(length=16), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_content_draft_media_items_event_id", "content_draft_media_items", ["event_id"])
    op.create_index("ix_content_draft_media_items_content_draft_id", "content_draft_media_items", ["content_draft_id"])


def downgrade() -> None:
    op.drop_index("ix_content_draft_media_items_content_draft_id", table_name="content_draft_media_items")
    op.drop_index("ix_content_draft_media_items_event_id", table_name="content_draft_media_items")
    op.drop_table("content_draft_media_items")
