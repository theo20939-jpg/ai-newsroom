"""add story context snapshots and content draft reply routing proposals tables

Revision ID: 280fa1e7d6d2
Revises: b4d92a7f6e13
Create Date: 2026-08-07 00:00:00.000000

Phase 19 M7 (docs/phase19_m7_story_timeline_and_reply_routing.md): two new, purely additive,
standalone tables.

`story_context_snapshots` - surrogate PK (not PK-reuse), mirrors `content_draft_editorial_plans`'
own reasoning: a snapshot is produced once per content-generation attempt, before a ContentDraft
row necessarily exists.

`content_draft_reply_routing_proposals` - PK reuses `content_draft_id` (1:1 extension, mirrors
`content_draft_quotes`' own convention): at most one reply-routing proposal per draft.

Neither `news_events` nor `content_drafts` is altered.

Depends on: `story_context_mode`, `telegram_story_reply_mode` (core/config.py). Written but NOT
applied as part of Phase 19's implementation, per explicit instruction (migration design only -
the user applies it separately).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "280fa1e7d6d2"
down_revision: Union[str, None] = "b4d92a7f6e13"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "story_context_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("news_events.id"), nullable=False),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stories.id"), nullable=False),
        sa.Column("content_draft_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("content_drafts.id"), nullable=True),
        sa.Column("timeline", postgresql.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_story_context_snapshots_event_id", "story_context_snapshots", ["event_id"])
    op.create_index("ix_story_context_snapshots_story_id", "story_context_snapshots", ["story_id"])
    op.create_index("ix_story_context_snapshots_content_draft_id", "story_context_snapshots", ["content_draft_id"])

    op.create_table(
        "content_draft_reply_routing_proposals",
        sa.Column(
            "content_draft_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("content_drafts.id"),
            primary_key=True,
        ),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stories.id"), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("proposed_reply_to_message_id", sa.BigInteger(), nullable=True),
        sa.Column("applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_content_draft_reply_routing_proposals_story_id",
        "content_draft_reply_routing_proposals", ["story_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_content_draft_reply_routing_proposals_story_id",
        table_name="content_draft_reply_routing_proposals",
    )
    op.drop_table("content_draft_reply_routing_proposals")

    op.drop_index("ix_story_context_snapshots_content_draft_id", table_name="story_context_snapshots")
    op.drop_index("ix_story_context_snapshots_story_id", table_name="story_context_snapshots")
    op.drop_index("ix_story_context_snapshots_event_id", table_name="story_context_snapshots")
    op.drop_table("story_context_snapshots")
