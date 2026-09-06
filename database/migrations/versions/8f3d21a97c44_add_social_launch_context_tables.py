"""add social launch context tables

Revision ID: 8f3d21a97c44
Revises: 7176e2997b8b
Create Date: 2026-09-06 12:00:00.000000

SOCIAL-INTELLIGENCE-PRELAUNCH-1, spec §3/§12/§16/§27: social_launch_contexts,
social_launch_proposals, plus one additive `launch_context_fingerprint` column on the existing
director_runs table (database/models/director_run.py).

Local/test database only - not applied to production as part of this phase.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "8f3d21a97c44"
down_revision: Union[str, None] = "7176e2997b8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PLATFORM = sa.Enum("telegram", "instagram", name="social_launch_platform")
_LAUNCH_STATE = sa.Enum("pre_launch", "transition", "live", "paused", name="social_launch_state")
_LAUNCH_DATE_STATUS = sa.Enum("unscheduled", "tentative", "confirmed", name="social_launch_date_status")
_BASELINE_POLICY = sa.Enum(
    "from_explicit_date", "from_first_post_after_launch", "from_first_publication",
    name="social_launch_baseline_policy",
)
_HISTORICAL_CONTENT_POLICY = sa.Enum(
    "ignore", "legacy_context_only", "include_in_learning", name="social_launch_historical_content_policy",
)
_PROPOSAL_STATUS = sa.Enum(
    "pending", "confirmed", "cancelled", "expired", name="social_launch_proposal_status",
)


def upgrade() -> None:
    op.add_column("director_runs", sa.Column("launch_context_fingerprint", sa.String(length=64), nullable=True))
    op.execute("ALTER TYPE director_run_type ADD VALUE IF NOT EXISTS 'telegram_prelaunch'")
    op.execute("ALTER TYPE director_run_type ADD VALUE IF NOT EXISTS 'instagram_prelaunch'")

    op.create_table(
        "social_launch_contexts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("platform", _PLATFORM, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("target_identity", sa.String(length=200), nullable=False),
        sa.Column("current_identity", sa.String(length=200), nullable=True),
        sa.Column("launch_state", _LAUNCH_STATE, nullable=False, server_default="pre_launch"),
        sa.Column("planned_launch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("launch_date_status", _LAUNCH_DATE_STATUS, nullable=False, server_default="unscheduled"),
        sa.Column("learning_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("baseline_policy", _BASELINE_POLICY, nullable=False),
        sa.Column("historical_content_policy", _HISTORICAL_CONTENT_POLICY, nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("launch_campaigns.id"), nullable=True),
        sa.Column("surface_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("telegram_surfaces.id"), nullable=True),
        sa.Column("raw_instruction", sa.Text(), nullable=False),
        sa.Column("confirmed_structure", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_social_launch_contexts_platform", "social_launch_contexts", ["platform"])

    op.create_table(
        "social_launch_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", _PROPOSAL_STATUS, nullable=False, server_default="pending"),
        sa.Column("platform", _PLATFORM, nullable=False),
        sa.Column("raw_instruction", sa.Text(), nullable=False),
        sa.Column("parsed_structure", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_topic_id", sa.Integer(), nullable=True),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.BigInteger(), nullable=True),
        sa.Column("resulting_context_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_social_launch_proposals_status", "social_launch_proposals", ["status"])
    op.create_index("ix_social_launch_proposals_platform", "social_launch_proposals", ["platform"])


def downgrade() -> None:
    op.drop_index("ix_social_launch_proposals_platform", table_name="social_launch_proposals")
    op.drop_index("ix_social_launch_proposals_status", table_name="social_launch_proposals")
    op.drop_table("social_launch_proposals")

    op.drop_index("ix_social_launch_contexts_platform", table_name="social_launch_contexts")
    op.drop_table("social_launch_contexts")

    op.drop_column("director_runs", "launch_context_fingerprint")
    # Note: PostgreSQL cannot remove a single value from an existing enum type - 'telegram_prelaunch'
    # and 'instagram_prelaunch' intentionally remain on director_run_type after downgrade, exactly
    # like every other additive-only enum value in this codebase's migration history.

    _PROPOSAL_STATUS.drop(op.get_bind(), checkfirst=True)
    _HISTORICAL_CONTENT_POLICY.drop(op.get_bind(), checkfirst=True)
    _BASELINE_POLICY.drop(op.get_bind(), checkfirst=True)
    _LAUNCH_DATE_STATUS.drop(op.get_bind(), checkfirst=True)
    _LAUNCH_STATE.drop(op.get_bind(), checkfirst=True)
    _PLATFORM.drop(op.get_bind(), checkfirst=True)
