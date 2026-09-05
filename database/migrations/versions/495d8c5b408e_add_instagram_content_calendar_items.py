"""add instagram content calendar items table

Revision ID: 495d8c5b408e
Revises: 647aa0fe8a5a
Create Date: 2026-09-05 07:00:00.000000

INSTAGRAM GROWTH ENGINE v2, spec §39/§62: one new, purely additive table and enum type -
instagram_content_calendar_items. See database/models/instagram_calendar_item.py for the full
field-by-field reasoning.

Local/test database only - not applied to production as part of this phase.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "495d8c5b408e"
down_revision: Union[str, None] = "647aa0fe8a5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CALENDAR_ITEM_STATUS = sa.Enum(
    "active", "stale", "invalidated", "rescheduled", "done", "cancelled",
    name="instagram_calendar_item_status",
)


def upgrade() -> None:
    op.create_table(
        "instagram_content_calendar_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", _CALENDAR_ITEM_STATUS, nullable=False, server_default="active"),
        sa.Column("opportunity_id", sa.String(length=200), nullable=True),
        sa.Column("creative_concept_id", sa.String(length=200), nullable=True),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("launch_campaigns.id"), nullable=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("objective", sa.String(length=50), nullable=False),
        sa.Column("format", sa.String(length=50), nullable=False),
        sa.Column("depends_on_campaign_phase", sa.String(length=50), nullable=True),
        sa.Column("planned_against_campaign_status", sa.String(length=50), nullable=True),
        sa.Column("planned_against_campaign_phase", sa.String(length=50), nullable=True),
        sa.Column("invalidation_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_instagram_content_calendar_items_planned_at", "instagram_content_calendar_items", ["planned_at"])
    op.create_index("ix_instagram_content_calendar_items_status", "instagram_content_calendar_items", ["status"])
    op.create_index("ix_instagram_content_calendar_items_campaign_id", "instagram_content_calendar_items", ["campaign_id"])
    op.create_index("ix_instagram_content_calendar_items_product_id", "instagram_content_calendar_items", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_instagram_content_calendar_items_product_id", table_name="instagram_content_calendar_items")
    op.drop_index("ix_instagram_content_calendar_items_campaign_id", table_name="instagram_content_calendar_items")
    op.drop_index("ix_instagram_content_calendar_items_status", table_name="instagram_content_calendar_items")
    op.drop_index("ix_instagram_content_calendar_items_planned_at", table_name="instagram_content_calendar_items")
    op.drop_table("instagram_content_calendar_items")
    _CALENDAR_ITEM_STATUS.drop(op.get_bind(), checkfirst=True)
