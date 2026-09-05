"""add creative_plan_id to instagram content calendar items

Revision ID: 2fb7d650c68b
Revises: 075d1af8dc10
Create Date: 2026-09-05 09:00:00.000000

INSTAGRAM-GROWTH-3, item 8: a planned calendar item must reference the real generated
InstagramCreativePlan, not only the older free-text creative_concept_id. Additive nullable column
only. See database/models/instagram_calendar_item.py for the full reasoning.

Local/test database only - not applied to production as part of this phase.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "2fb7d650c68b"
down_revision: Union[str, None] = "075d1af8dc10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "instagram_content_calendar_items",
        sa.Column("creative_plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("instagram_creative_plans.id"), nullable=True),
    )
    op.create_index(
        "ix_instagram_content_calendar_items_creative_plan_id", "instagram_content_calendar_items", ["creative_plan_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_instagram_content_calendar_items_creative_plan_id", table_name="instagram_content_calendar_items")
    op.drop_column("instagram_content_calendar_items", "creative_plan_id")
