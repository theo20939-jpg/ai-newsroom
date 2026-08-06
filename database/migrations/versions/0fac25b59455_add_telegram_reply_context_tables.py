"""add telegram reply context tables

Revision ID: 0fac25b59455
Revises: c2bc6affb100
Create Date: 2026-08-06 00:00:00.000000

Phase 18.10 M3 (docs/phase18_10_editorial_intelligence_report.md): two new, purely additive,
standalone tables - `content_draft_story_links` and `story_telegram_deliveries`. No existing
table, column, index, or enum is touched or rewritten - mirrors `c2bc6affb100`'s own
already-established discipline (and the exact hot-path-dependency lesson it fixed): `ContentDraft`
itself is never altered.

A CHECK constraint enforces "a send is not successful unless telegram_message_id is persisted" at
the database level: `delivery_status = 'sent'` is structurally impossible with a NULL
`telegram_message_id`.

Written but NOT applied as part of Phase 18.10's implementation, per explicit instruction
(migration design only - the user applies it separately).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0fac25b59455"
down_revision: Union[str, None] = "c2bc6affb100"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DELIVERY_TYPE_ENUM = sa.Enum("root", "reply", name="telegram_delivery_type")
_DELIVERY_STATUS_ENUM = sa.Enum("sent", "failed", "unconfirmed", "skipped_review", name="telegram_delivery_status")


def upgrade() -> None:
    op.create_table(
        "content_draft_story_links",
        sa.Column("content_draft_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("content_drafts.id"), primary_key=True),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stories.id"), nullable=False),
        sa.Column("is_story_update", sa.Boolean(), nullable=False),
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("news_events.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_content_draft_story_links_story_id", "content_draft_story_links", ["story_id"])

    op.create_table(
        "story_telegram_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stories.id"), nullable=False),
        sa.Column("content_draft_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("content_drafts.id"), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("reply_to_message_id", sa.BigInteger(), nullable=True),
        sa.Column("delivery_type", _DELIVERY_TYPE_ENUM, nullable=False),
        sa.Column("delivery_status", _DELIVERY_STATUS_ENUM, nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_story_telegram_deliveries_idempotency_key"),
        sa.CheckConstraint(
            "delivery_status != 'sent' OR telegram_message_id IS NOT NULL",
            name="ck_story_telegram_deliveries_sent_requires_message_id",
        ),
    )
    op.create_index("ix_story_telegram_deliveries_story_id", "story_telegram_deliveries", ["story_id"])
    op.create_index("ix_story_telegram_deliveries_content_draft_id", "story_telegram_deliveries", ["content_draft_id"])


def downgrade() -> None:
    op.drop_index("ix_story_telegram_deliveries_content_draft_id", table_name="story_telegram_deliveries")
    op.drop_index("ix_story_telegram_deliveries_story_id", table_name="story_telegram_deliveries")
    op.drop_table("story_telegram_deliveries")
    _DELIVERY_STATUS_ENUM.drop(op.get_bind(), checkfirst=True)
    _DELIVERY_TYPE_ENUM.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_content_draft_story_links_story_id", table_name="content_draft_story_links")
    op.drop_table("content_draft_story_links")
