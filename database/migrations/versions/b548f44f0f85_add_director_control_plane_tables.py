"""add director control plane tables

Revision ID: b548f44f0f85
Revises: 8f3d21a97c44
Create Date: 2026-09-08 00:00:00.000000

DIRECTOR-CONTROL-PLANE-1 §55: five new, purely additive tables - instagram_accounts,
director_editorial_decisions, director_editorial_tasks, design_spec_versions,
design_reference_assets. No existing table, column, or enum is touched or rewritten. Local/test
database only - not applied to production as part of this phase.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b548f44f0f85"
down_revision: Union[str, None] = "8f3d21a97c44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INSTAGRAM_ACCOUNT_ROLE = sa.Enum("owned_brand_account", "other", name="instagram_account_role")
_INSTAGRAM_CONNECTION_STATE = sa.Enum("not_connected", "connected", "error", name="instagram_connection_state")
_EDITORIAL_GATE_DECISION = sa.Enum(
    "drop", "hold", "send_to_editor", "priority", "breaking", name="editorial_gate_decision",
)
_DIRECTOR_TASK_REASON = sa.Enum(
    "feed_gap", "campaign", "trend", "series", "follow_up", "product", "explainer", "other",
    name="director_task_reason",
)
_DIRECTOR_TASK_STATUS = sa.Enum(
    "proposed", "research_required", "researched", "converted_to_draft", "rejected", "superseded",
    name="director_task_status",
)
_DESIGN_SPEC_STATUS = sa.Enum("active", "candidate", "superseded", "rejected", "frozen", name="design_spec_status")
_DESIGN_SPEC_TYPE = sa.Enum(
    "design_direction_reference", "declarative_visual_params", "account_presentation", name="design_spec_type",
)
_DESIGN_REFERENCE_ROLE = sa.Enum(
    "approved_reference", "rejected_reference", "account_feed_reference", "layout_reference",
    "typography_reference", "color_reference", "profile_reference", "needs_founder_review",
    name="design_reference_role",
)


def upgrade() -> None:
    op.create_table(
        "instagram_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ig_user_id", sa.String(64), nullable=True, unique=True),
        sa.Column("username", sa.String(200), nullable=True),
        sa.Column("role", _INSTAGRAM_ACCOUNT_ROLE, nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("connection_state", _INSTAGRAM_CONNECTION_STATE, nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("analytics_enabled", sa.Boolean(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_instagram_accounts_ig_user_id", "instagram_accounts", ["ig_user_id"])
    op.create_index("ix_instagram_accounts_role", "instagram_accounts", ["role"])

    op.create_table(
        "director_editorial_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("decision", _EDITORIAL_GATE_DECISION, nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("short_reason", sa.Text(), nullable=False),
        sa.Column("director", sa.String(100), nullable=False),
        sa.Column("director_version", sa.String(20), nullable=False),
        sa.Column("context_fingerprint", sa.String(64), nullable=False),
        sa.Column("launch_context_fingerprint", sa.String(64), nullable=True),
        sa.Column("campaign_context_fingerprint", sa.String(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("founder_overridden", sa.Boolean(), nullable=False),
        sa.Column("founder_override_decision", _EDITORIAL_GATE_DECISION, nullable=True),
        sa.Column("founder_override_by", sa.BigInteger(), nullable=True),
        sa.Column("founder_override_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_director_editorial_decisions_story_id", "director_editorial_decisions", ["story_id"])
    op.create_index("ix_director_editorial_decisions_event_id", "director_editorial_decisions", ["event_id"])
    op.create_index("ix_director_editorial_decisions_platform", "director_editorial_decisions", ["platform"])
    op.create_index("ix_director_editorial_decisions_decision", "director_editorial_decisions", ["decision"])

    op.create_table(
        "director_editorial_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("proposed_topic", sa.Text(), nullable=False),
        sa.Column("why_now", sa.Text(), nullable=False),
        sa.Column("reason", _DIRECTOR_TASK_REASON, nullable=False),
        sa.Column("desired_format", sa.String(50), nullable=True),
        sa.Column("requires_research", sa.Boolean(), nullable=False),
        sa.Column("research_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content_draft_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("directive_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("director", sa.String(100), nullable=False),
        sa.Column("director_run_context_fingerprint", sa.String(64), nullable=True),
        sa.Column("status", _DIRECTOR_TASK_STATUS, nullable=False),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_director_editorial_tasks_platform", "director_editorial_tasks", ["platform"])
    op.create_index("ix_director_editorial_tasks_reason", "director_editorial_tasks", ["reason"])
    op.create_index("ix_director_editorial_tasks_status", "director_editorial_tasks", ["status"])

    op.create_table(
        "design_spec_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("platform", sa.String(20), nullable=True),
        sa.Column("surface", sa.String(50), nullable=True),
        sa.Column("presentation_type", sa.String(50), nullable=True),
        sa.Column("spec_type", _DESIGN_SPEC_TYPE, nullable=False),
        sa.Column("scope", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", _DESIGN_SPEC_STATUS, nullable=False),
        sa.Column("supersedes", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_asset_ref", sa.String(500), nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("active_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_design_spec_versions_platform", "design_spec_versions", ["platform"])
    op.create_index("ix_design_spec_versions_presentation_type", "design_spec_versions", ["presentation_type"])
    op.create_index("ix_design_spec_versions_spec_type", "design_spec_versions", ["spec_type"])
    op.create_index("ix_design_spec_versions_scope", "design_spec_versions", ["scope"])
    op.create_index("ix_design_spec_versions_status", "design_spec_versions", ["status"])

    op.create_table(
        "design_reference_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("platform", sa.String(20), nullable=True),
        sa.Column("presentation_type", sa.String(50), nullable=True),
        sa.Column("asset_path", sa.String(500), nullable=False, unique=True),
        sa.Column("reference_role", _DESIGN_REFERENCE_ROLE, nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_design_reference_assets_platform", "design_reference_assets", ["platform"])
    op.create_index("ix_design_reference_assets_presentation_type", "design_reference_assets", ["presentation_type"])
    op.create_index("ix_design_reference_assets_asset_path", "design_reference_assets", ["asset_path"])
    op.create_index("ix_design_reference_assets_reference_role", "design_reference_assets", ["reference_role"])


def downgrade() -> None:
    op.drop_index("ix_design_reference_assets_reference_role", table_name="design_reference_assets")
    op.drop_index("ix_design_reference_assets_asset_path", table_name="design_reference_assets")
    op.drop_index("ix_design_reference_assets_presentation_type", table_name="design_reference_assets")
    op.drop_index("ix_design_reference_assets_platform", table_name="design_reference_assets")
    op.drop_table("design_reference_assets")
    _DESIGN_REFERENCE_ROLE.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_design_spec_versions_status", table_name="design_spec_versions")
    op.drop_index("ix_design_spec_versions_scope", table_name="design_spec_versions")
    op.drop_index("ix_design_spec_versions_spec_type", table_name="design_spec_versions")
    op.drop_index("ix_design_spec_versions_presentation_type", table_name="design_spec_versions")
    op.drop_index("ix_design_spec_versions_platform", table_name="design_spec_versions")
    op.drop_table("design_spec_versions")
    _DESIGN_SPEC_TYPE.drop(op.get_bind(), checkfirst=True)
    _DESIGN_SPEC_STATUS.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_director_editorial_tasks_status", table_name="director_editorial_tasks")
    op.drop_index("ix_director_editorial_tasks_reason", table_name="director_editorial_tasks")
    op.drop_index("ix_director_editorial_tasks_platform", table_name="director_editorial_tasks")
    op.drop_table("director_editorial_tasks")
    _DIRECTOR_TASK_STATUS.drop(op.get_bind(), checkfirst=True)
    _DIRECTOR_TASK_REASON.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_director_editorial_decisions_decision", table_name="director_editorial_decisions")
    op.drop_index("ix_director_editorial_decisions_platform", table_name="director_editorial_decisions")
    op.drop_index("ix_director_editorial_decisions_event_id", table_name="director_editorial_decisions")
    op.drop_index("ix_director_editorial_decisions_story_id", table_name="director_editorial_decisions")
    op.drop_table("director_editorial_decisions")
    _EDITORIAL_GATE_DECISION.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_instagram_accounts_role", table_name="instagram_accounts")
    op.drop_index("ix_instagram_accounts_ig_user_id", table_name="instagram_accounts")
    op.drop_table("instagram_accounts")
    _INSTAGRAM_CONNECTION_STATE.drop(op.get_bind(), checkfirst=True)
    _INSTAGRAM_ACCOUNT_ROLE.drop(op.get_bind(), checkfirst=True)
