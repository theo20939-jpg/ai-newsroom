"""add telegram content calendar items table

Revision ID: aa42c5f27ff1
Revises: 4c287b2097ea
Create Date: 2026-09-05 11:30:00.000000

SOCIAL-INTELLIGENCE-OPS-1, spec §21/§22: telegram_content_calendar_items - the real,
Telegram-specific calendar model, structurally separate from instagram_content_calendar_items
(shared business truth, separate platform execution). See
database/models/telegram_content_calendar_item.py for the full reasoning.

Local/test database only - not applied to production as part of this phase.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "aa42c5f27ff1"
down_revision: Union[str, None] = "4c287b2097ea"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CALENDAR_ITEM_STATUS = sa.Enum(
    "active", "stale", "invalidated", "rescheduled", "done", "cancelled", name="telegram_calendar_item_status",
)
_CONTENT_ROLE = sa.Enum(
    "news", "update", "data", "quote", "recap", "campaign", "evergreen", "other", name="telegram_content_role",
)


def upgrade() -> None:
    op.create_table(
        "telegram_content_calendar_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", _CALENDAR_ITEM_STATUS, nullable=False, server_default="active"),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("launch_campaigns.id"), nullable=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("surface_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("telegram_surfaces.id"), nullable=True),
        sa.Column("content_role", _CONTENT_ROLE, nullable=False),
        sa.Column("objective", sa.String(length=50), nullable=False),
        sa.Column("presentation_hint", sa.String(length=100), nullable=True),
        sa.Column("source_opportunity_id", sa.String(length=200), nullable=True),
        sa.Column("business_context_version", sa.String(length=100), nullable=True),
        sa.Column("depends_on_campaign_phase", sa.String(length=50), nullable=True),
        sa.Column("planned_against_campaign_status", sa.String(length=50), nullable=True),
        sa.Column("planned_against_campaign_phase", sa.String(length=50), nullable=True),
        sa.Column("director_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("invalidation_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_telegram_content_calendar_items_planned_at", "telegram_content_calendar_items", ["planned_at"])
    op.create_index("ix_telegram_content_calendar_items_status", "telegram_content_calendar_items", ["status"])
    op.create_index("ix_telegram_content_calendar_items_story_id", "telegram_content_calendar_items", ["story_id"])
    op.create_index("ix_telegram_content_calendar_items_campaign_id", "telegram_content_calendar_items", ["campaign_id"])
    op.create_index("ix_telegram_content_calendar_items_product_id", "telegram_content_calendar_items", ["product_id"])
    op.create_index("ix_telegram_content_calendar_items_surface_id", "telegram_content_calendar_items", ["surface_id"])
    op.create_index("ix_telegram_content_calendar_items_director_run_id", "telegram_content_calendar_items", ["director_run_id"])


def downgrade() -> None:
    op.drop_index("ix_telegram_content_calendar_items_director_run_id", table_name="telegram_content_calendar_items")
    op.drop_index("ix_telegram_content_calendar_items_surface_id", table_name="telegram_content_calendar_items")
    op.drop_index("ix_telegram_content_calendar_items_product_id", table_name="telegram_content_calendar_items")
    op.drop_index("ix_telegram_content_calendar_items_campaign_id", table_name="telegram_content_calendar_items")
    op.drop_index("ix_telegram_content_calendar_items_story_id", table_name="telegram_content_calendar_items")
    op.drop_index("ix_telegram_content_calendar_items_status", table_name="telegram_content_calendar_items")
    op.drop_index("ix_telegram_content_calendar_items_planned_at", table_name="telegram_content_calendar_items")
    op.drop_table("telegram_content_calendar_items")
    _CONTENT_ROLE.drop(op.get_bind(), checkfirst=True)
    _CALENDAR_ITEM_STATUS.drop(op.get_bind(), checkfirst=True)
