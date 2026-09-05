"""add instagram creative plan/draft and ai call record tables

Revision ID: 075d1af8dc10
Revises: 12c560efce40
Create Date: 2026-09-05 08:30:00.000000

INSTAGRAM-GROWTH-3, item 6/17: instagram_creative_plans, instagram_creative_drafts (AI creative
output persisted as a PROPOSAL, never canonical business truth), and instagram_ai_call_records
(capability/model/token/cost accounting for Instagram's own Gateway usage). See
database/models/instagram_creative_plan.py and database/models/instagram_ai_call_record.py for the
full field-by-field reasoning.

Local/test database only - not applied to production as part of this phase.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "075d1af8dc10"
down_revision: Union[str, None] = "12c560efce40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CREATIVE_PLAN_STATUS = sa.Enum(
    "proposed", "approved", "rejected", "superseded", name="instagram_creative_plan_status",
)
_CREATIVE_DRAFT_STATUS = sa.Enum("proposed", "approved", "rejected", name="instagram_creative_draft_status")


def upgrade() -> None:
    op.create_table(
        "instagram_creative_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("content_opportunity_id", sa.String(length=200), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("launch_campaigns.id"), nullable=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("series_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("instagram_series.id"), nullable=True),
        sa.Column("objective", sa.String(length=50), nullable=False),
        sa.Column("format", sa.String(length=50), nullable=False),
        sa.Column("hook_family", sa.String(length=100), nullable=True),
        sa.Column("business_context_version", sa.String(length=100), nullable=True),
        sa.Column("campaign_state_snapshot", sa.String(length=200), nullable=True),
        sa.Column("status", _CREATIVE_PLAN_STATUS, nullable=False, server_default="proposed"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_instagram_creative_plans_content_opportunity_id", "instagram_creative_plans", ["content_opportunity_id"])
    op.create_index("ix_instagram_creative_plans_campaign_id", "instagram_creative_plans", ["campaign_id"])
    op.create_index("ix_instagram_creative_plans_product_id", "instagram_creative_plans", ["product_id"])
    op.create_index("ix_instagram_creative_plans_series_id", "instagram_creative_plans", ["series_id"])
    op.create_index("ix_instagram_creative_plans_status", "instagram_creative_plans", ["status"])

    op.create_table(
        "instagram_creative_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("creative_plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("instagram_creative_plans.id"), nullable=False),
        sa.Column("format", sa.String(length=50), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("approved_claims", sa.JSON(), nullable=True),
        sa.Column("restricted_claims", sa.JSON(), nullable=True),
        sa.Column("evidence_used", sa.JSON(), nullable=True),
        sa.Column("ai_model", sa.String(length=100), nullable=True),
        sa.Column("ai_capability", sa.String(length=50), nullable=True),
        sa.Column("ai_cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("status", _CREATIVE_DRAFT_STATUS, nullable=False, server_default="proposed"),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_instagram_creative_drafts_creative_plan_id", "instagram_creative_drafts", ["creative_plan_id"])

    op.create_table(
        "instagram_ai_call_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("capability_name", sa.String(length=100), nullable=False),
        sa.Column("model_used", sa.String(length=100), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("prompt_name", sa.String(length=100), nullable=True),
        sa.Column("prompt_version", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_instagram_ai_call_records_capability_name", "instagram_ai_call_records", ["capability_name"])


def downgrade() -> None:
    op.drop_index("ix_instagram_ai_call_records_capability_name", table_name="instagram_ai_call_records")
    op.drop_table("instagram_ai_call_records")

    op.drop_index("ix_instagram_creative_drafts_creative_plan_id", table_name="instagram_creative_drafts")
    op.drop_table("instagram_creative_drafts")
    _CREATIVE_DRAFT_STATUS.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_instagram_creative_plans_status", table_name="instagram_creative_plans")
    op.drop_index("ix_instagram_creative_plans_series_id", table_name="instagram_creative_plans")
    op.drop_index("ix_instagram_creative_plans_product_id", table_name="instagram_creative_plans")
    op.drop_index("ix_instagram_creative_plans_campaign_id", table_name="instagram_creative_plans")
    op.drop_index("ix_instagram_creative_plans_content_opportunity_id", table_name="instagram_creative_plans")
    op.drop_table("instagram_creative_plans")
    _CREATIVE_PLAN_STATUS.drop(op.get_bind(), checkfirst=True)
