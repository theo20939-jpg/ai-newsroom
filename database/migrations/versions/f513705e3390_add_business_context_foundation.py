"""add business context foundation

Revision ID: f513705e3390
Revises: 85d80c2c1f92
Create Date: 2026-09-05 00:00:00.000000

NINJA Social Intelligence Foundation, Part I/II: eight new, purely additive tables and their
enum types. No existing table, column, or enum is touched or rewritten - see each corresponding
database/models/*.py file's own docstring for the full field-by-field reasoning:

products, product_context_versions, product_events, launch_campaigns, campaign_milestones,
claim_policies, strategic_directives, business_context_proposals.

Local/test database only - this migration is NOT applied to production as part of this phase.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f513705e3390"
down_revision: Union[str, None] = "85d80c2c1f92"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PRODUCT_STATUS = sa.Enum(
    "idea", "discovery", "development", "private_beta", "public_beta", "pre_launch", "live",
    "paused", "sunset", name="product_status",
)
_PRODUCT_EVENT_TYPE = sa.Enum(
    "development_started", "milestone_reached", "private_beta", "public_beta", "feature_ready",
    "pricing_approved", "launch_date_confirmed", "launch_delayed", "product_launched",
    "major_update", "partnership", "promotion", "incident", name="product_event_type",
)
_PRODUCT_EVENT_VISIBILITY = sa.Enum(
    "internal_only", "preparation_allowed", "public_allowed", name="product_event_visibility",
)
_CAMPAIGN_STATUS = sa.Enum(
    "draft", "tentative", "confirmed", "delayed", "cancelled", "launched", "completed",
    name="campaign_status",
)
_CAMPAIGN_DATE_CONFIDENCE = sa.Enum(
    "exact", "estimated", "rough", "unknown", name="campaign_date_confidence",
)
_CAMPAIGN_MILESTONE_VISIBILITY = sa.Enum(
    "internal_only", "preparation_allowed", "public_allowed", name="campaign_milestone_visibility",
)
_CLAIM_STATUS = sa.Enum("approved", "restricted", "embargoed", name="claim_status")
_DIRECTIVE_STATUS = sa.Enum("active", "expired", "superseded", "cancelled", name="directive_status")
_BUSINESS_CONTEXT_COMMAND_TYPE = sa.Enum(
    "product", "campaign", "milestone", "directive", "claim", "context",
    name="business_context_command_type",
)
_BUSINESS_CONTEXT_PROPOSAL_STATUS = sa.Enum(
    "pending", "confirmed", "cancelled", "expired", name="business_context_proposal_status",
)


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", _PRODUCT_STATUS, nullable=False, server_default="idea"),
        sa.Column("current_stage", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_audience", sa.Text(), nullable=True),
        sa.Column("core_value_propositions", sa.JSON(), nullable=True),
        sa.Column("current_features", sa.JSON(), nullable=True),
        sa.Column("planned_features", sa.JSON(), nullable=True),
        sa.Column("pricing_status", sa.String(200), nullable=True),
        sa.Column("product_url", sa.String(500), nullable=True),
        sa.Column("waitlist_url", sa.String(500), nullable=True),
        sa.Column("owner", sa.String(200), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("slug", name="uq_products_slug"),
    )
    op.create_index("ix_products_slug", "products", ["slug"])
    op.create_index("ix_products_status", "products", ["status"])

    op.create_table(
        "product_context_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("raw_instruction", sa.String(), nullable=False),
        sa.Column("structured_context", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(50), nullable=False, server_default="telegram"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_topic_id", sa.Integer(), nullable=True),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("confirmed_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "supersedes_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("product_context_versions.id"),
            nullable=True,
        ),
        sa.UniqueConstraint("product_id", "version", name="uq_product_context_versions_product_version"),
    )
    op.create_index("ix_product_context_versions_product_id", "product_context_versions", ["product_id"])

    op.create_table(
        "product_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("event_type", _PRODUCT_EVENT_TYPE, nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("importance", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("visibility", _PRODUCT_EVENT_VISIBILITY, nullable=False, server_default="internal_only"),
        sa.Column("source", sa.String(50), nullable=False, server_default="telegram"),
        sa.Column("raw_instruction", sa.String(), nullable=True),
        sa.Column("structured_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_product_events_product_id", "product_events", ["product_id"])
    op.create_index("ix_product_events_event_type", "product_events", ["event_type"])
    op.create_index("ix_product_events_event_at", "product_events", ["event_at"])
    op.create_index("ix_product_events_visibility", "product_events", ["visibility"])

    op.create_table(
        "launch_campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("status", _CAMPAIGN_STATUS, nullable=False, server_default="draft"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("planned_launch_date", sa.Date(), nullable=True),
        sa.Column("date_confidence", _CAMPAIGN_DATE_CONFIDENCE, nullable=False, server_default="unknown"),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("target_audiences", sa.JSON(), nullable=True),
        sa.Column("primary_goal", sa.String(300), nullable=True),
        sa.Column("secondary_goals", sa.JSON(), nullable=True),
        sa.Column("key_messages", sa.JSON(), nullable=True),
        sa.Column("approved_claims", sa.JSON(), nullable=True),
        sa.Column("restricted_claims", sa.JSON(), nullable=True),
        sa.Column("required_cta", sa.String(300), nullable=True),
        sa.Column("available_assets", sa.JSON(), nullable=True),
        sa.Column("embargo_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_launch_campaigns_product_id", "launch_campaigns", ["product_id"])
    op.create_index("ix_launch_campaigns_status", "launch_campaigns", ["status"])

    op.create_table(
        "campaign_milestones",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column(
            "campaign_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("launch_campaigns.id"), nullable=True,
        ),
        sa.Column("type", sa.String(100), nullable=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("milestone_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("importance", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("visibility", _CAMPAIGN_MILESTONE_VISIBILITY, nullable=False, server_default="internal_only"),
        sa.Column("publicity_allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("asset_preparation_allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_campaign_milestones_product_id", "campaign_milestones", ["product_id"])
    op.create_index("ix_campaign_milestones_campaign_id", "campaign_milestones", ["campaign_id"])
    op.create_index("ix_campaign_milestones_milestone_at", "campaign_milestones", ["milestone_at"])
    op.create_index("ix_campaign_milestones_visibility", "campaign_milestones", ["visibility"])

    op.create_table(
        "claim_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column(
            "campaign_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("launch_campaigns.id"), nullable=True,
        ),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("status", _CLAIM_STATUS, nullable=False),
        sa.Column("embargoed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_claim_policies_product_id", "claim_policies", ["product_id"])
    op.create_index("ix_claim_policies_campaign_id", "claim_policies", ["campaign_id"])
    op.create_index("ix_claim_policies_status", "claim_policies", ["status"])

    op.create_table(
        "strategic_directives",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(300), nullable=True),
        sa.Column("products", sa.JSON(), nullable=True),
        sa.Column("platforms", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="telegram"),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("status", _DIRECTIVE_STATUS, nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_strategic_directives_valid_from", "strategic_directives", ["valid_from"])
    op.create_index("ix_strategic_directives_valid_until", "strategic_directives", ["valid_until"])
    op.create_index("ix_strategic_directives_status", "strategic_directives", ["status"])

    op.create_table(
        "business_context_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("command_type", _BUSINESS_CONTEXT_COMMAND_TYPE, nullable=False),
        sa.Column("status", _BUSINESS_CONTEXT_PROPOSAL_STATUS, nullable=False, server_default="pending"),
        sa.Column("raw_instruction", sa.String(), nullable=False),
        sa.Column("proposed_change_set", sa.JSON(), nullable=False),
        sa.Column("parsed_structure", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_topic_id", sa.Integer(), nullable=True),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.BigInteger(), nullable=True),
        sa.Column("resulting_version_ids", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_business_context_proposals_command_type", "business_context_proposals", ["command_type"])
    op.create_index("ix_business_context_proposals_status", "business_context_proposals", ["status"])


def downgrade() -> None:
    op.drop_index("ix_business_context_proposals_status", table_name="business_context_proposals")
    op.drop_index("ix_business_context_proposals_command_type", table_name="business_context_proposals")
    op.drop_table("business_context_proposals")
    _BUSINESS_CONTEXT_PROPOSAL_STATUS.drop(op.get_bind(), checkfirst=True)
    _BUSINESS_CONTEXT_COMMAND_TYPE.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_strategic_directives_status", table_name="strategic_directives")
    op.drop_index("ix_strategic_directives_valid_until", table_name="strategic_directives")
    op.drop_index("ix_strategic_directives_valid_from", table_name="strategic_directives")
    op.drop_table("strategic_directives")
    _DIRECTIVE_STATUS.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_claim_policies_status", table_name="claim_policies")
    op.drop_index("ix_claim_policies_campaign_id", table_name="claim_policies")
    op.drop_index("ix_claim_policies_product_id", table_name="claim_policies")
    op.drop_table("claim_policies")
    _CLAIM_STATUS.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_campaign_milestones_visibility", table_name="campaign_milestones")
    op.drop_index("ix_campaign_milestones_milestone_at", table_name="campaign_milestones")
    op.drop_index("ix_campaign_milestones_campaign_id", table_name="campaign_milestones")
    op.drop_index("ix_campaign_milestones_product_id", table_name="campaign_milestones")
    op.drop_table("campaign_milestones")
    _CAMPAIGN_MILESTONE_VISIBILITY.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_launch_campaigns_status", table_name="launch_campaigns")
    op.drop_index("ix_launch_campaigns_product_id", table_name="launch_campaigns")
    op.drop_table("launch_campaigns")
    _CAMPAIGN_DATE_CONFIDENCE.drop(op.get_bind(), checkfirst=True)
    _CAMPAIGN_STATUS.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_product_events_visibility", table_name="product_events")
    op.drop_index("ix_product_events_event_at", table_name="product_events")
    op.drop_index("ix_product_events_event_type", table_name="product_events")
    op.drop_index("ix_product_events_product_id", table_name="product_events")
    op.drop_table("product_events")
    _PRODUCT_EVENT_VISIBILITY.drop(op.get_bind(), checkfirst=True)
    _PRODUCT_EVENT_TYPE.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_product_context_versions_product_id", table_name="product_context_versions")
    op.drop_table("product_context_versions")

    op.drop_index("ix_products_status", table_name="products")
    op.drop_index("ix_products_slug", table_name="products")
    op.drop_table("products")
    _PRODUCT_STATUS.drop(op.get_bind(), checkfirst=True)
