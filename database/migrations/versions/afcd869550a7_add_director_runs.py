"""add director runs table

Revision ID: afcd869550a7
Revises: aa42c5f27ff1
Create Date: 2026-09-05 13:00:00.000000

SOCIAL-INTELLIGENCE-OPS-1, spec §29-§34: director_runs - a durable record of what a director
decided and why, cross-platform (see database/models/director_run.py for the full reasoning).

Local/test database only - not applied to production as part of this phase.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "afcd869550a7"
down_revision: Union[str, None] = "aa42c5f27ff1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DIRECTOR_TYPE = sa.Enum(
    "telegram_channel", "telegram_art", "telegram_growth", "telegram_strategy",
    "instagram_growth", "instagram_format", "instagram_creative", "campaign_director",
    name="director_run_type",
)
_RUN_STATUS = sa.Enum(
    "ok", "waiting_for_data", "insufficient_evidence", "blocked", name="director_run_status",
)
_EVIDENCE_STAGE = sa.Enum(
    "observation", "hypothesis", "possible_signal", "repeated_pattern", "stable_working_rule",
    name="director_run_evidence_stage",
)


def upgrade() -> None:
    op.create_table(
        "director_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("director_type", _DIRECTOR_TYPE, nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("subject_type", sa.String(length=30), nullable=True),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("launch_campaigns.id"), nullable=True),
        sa.Column("campaign_status_at_run", sa.String(length=30), nullable=True),
        sa.Column("campaign_phase_at_run", sa.String(length=50), nullable=True),
        sa.Column("business_context_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", _RUN_STATUS, nullable=False, server_default="ok"),
        sa.Column("decision", sa.String(length=100), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("evidence_stage", _EVIDENCE_STAGE, nullable=True),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        sa.Column("model_provider", sa.String(length=50), nullable=True),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("stale_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stale_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_director_runs_director_type", "director_runs", ["director_type"])
    op.create_index("ix_director_runs_platform", "director_runs", ["platform"])
    op.create_index("ix_director_runs_subject_id", "director_runs", ["subject_id"])
    op.create_index("ix_director_runs_campaign_id", "director_runs", ["campaign_id"])
    op.create_index("ix_director_runs_generated_at", "director_runs", ["generated_at"])


def downgrade() -> None:
    op.drop_index("ix_director_runs_generated_at", table_name="director_runs")
    op.drop_index("ix_director_runs_campaign_id", table_name="director_runs")
    op.drop_index("ix_director_runs_subject_id", table_name="director_runs")
    op.drop_index("ix_director_runs_platform", table_name="director_runs")
    op.drop_index("ix_director_runs_director_type", table_name="director_runs")
    op.drop_table("director_runs")
    _EVIDENCE_STAGE.drop(op.get_bind(), checkfirst=True)
    _RUN_STATUS.drop(op.get_bind(), checkfirst=True)
    _DIRECTOR_TYPE.drop(op.get_bind(), checkfirst=True)
