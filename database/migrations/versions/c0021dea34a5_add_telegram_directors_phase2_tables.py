"""add telegram directors phase 2 tables

Revision ID: c0021dea34a5
Revises: 97233eb2e1e9
Create Date: 2026-09-05 00:00:00.000000

NINJA Social Intelligence Foundation, Telegram Directors Phase 2 §5/§19/§25: three new, purely
additive tables - telegram_post_performance_snapshots, telegram_visual_failures,
telegram_experiments. No existing table, column, or enum is touched or rewritten. Local/test
database only - not applied to production as part of this phase.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c0021dea34a5"
down_revision: Union[str, None] = "97233eb2e1e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SNAPSHOT_WINDOW = sa.Enum(
    "5m", "30m", "1h", "3h", "6h", "24h", "72h", name="telegram_snapshot_window",
)
_VISUAL_FAILURE_DECISION = sa.Enum(
    "pass", "pass_with_notes", "rework", "block", name="telegram_visual_failure_decision",
)
_EXPERIMENT_STATUS = sa.Enum(
    "planned", "running", "completed", "abandoned", name="telegram_experiment_status",
)


def upgrade() -> None:
    op.create_table(
        "telegram_post_performance_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel_memory_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("window", _SNAPSHOT_WINDOW, nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("age_seconds", sa.Integer(), nullable=False),
        sa.Column("views", sa.Integer(), nullable=True),
        sa.Column("forwards", sa.Integer(), nullable=True),
        sa.Column("reactions_total", sa.Integer(), nullable=True),
        sa.Column("comments_total", sa.Integer(), nullable=True),
        sa.Column("subscriber_count", sa.Integer(), nullable=True),
        sa.Column("subscriber_delta", sa.Integer(), nullable=True),
        sa.Column("capability_version", sa.String(50), nullable=False),
        sa.Column("collector", sa.String(100), nullable=False),
        sa.Column("raw_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_telegram_post_performance_snapshots_channel_memory_id",
        "telegram_post_performance_snapshots", ["channel_memory_id"],
    )
    op.create_index(
        "ix_telegram_post_performance_snapshots_telegram_message_id",
        "telegram_post_performance_snapshots", ["telegram_message_id"],
    )
    op.create_index(
        "ix_telegram_post_performance_snapshots_window",
        "telegram_post_performance_snapshots", ["window"],
    )
    op.create_index(
        "ix_telegram_post_performance_snapshots_captured_at",
        "telegram_post_performance_snapshots", ["captured_at"],
    )

    op.create_table(
        "telegram_visual_failures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("final_post_review_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("presentation_type", sa.String(50), nullable=True),
        sa.Column("renderer_version", sa.String(50), nullable=True),
        sa.Column("template", sa.String(100), nullable=True),
        sa.Column("media_type", sa.String(50), nullable=True),
        sa.Column("issue_codes", sa.JSON(), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("art_director_decision", _VISUAL_FAILURE_DECISION, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("revision_action", sa.String(50), nullable=True),
        sa.Column("revision_round", sa.Integer(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.Column("resolution_result", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_telegram_visual_failures_final_post_review_id", "telegram_visual_failures", ["final_post_review_id"],
    )
    op.create_index("ix_telegram_visual_failures_story_id", "telegram_visual_failures", ["story_id"])
    op.create_index(
        "ix_telegram_visual_failures_art_director_decision", "telegram_visual_failures", ["art_director_decision"],
    )

    op.create_table(
        "telegram_experiments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("hypothesis", sa.String(500), nullable=False),
        sa.Column("dimension", sa.String(100), nullable=False),
        sa.Column("variant", sa.String(200), nullable=False),
        sa.Column("baseline", sa.String(200), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sample_target", sa.Integer(), nullable=False),
        sa.Column("status", _EXPERIMENT_STATUS, nullable=False),
        sa.Column("result", sa.String(500), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("telegram_experiments")

    op.drop_index("ix_telegram_visual_failures_art_director_decision", table_name="telegram_visual_failures")
    op.drop_index("ix_telegram_visual_failures_story_id", table_name="telegram_visual_failures")
    op.drop_index("ix_telegram_visual_failures_final_post_review_id", table_name="telegram_visual_failures")
    op.drop_table("telegram_visual_failures")
    _VISUAL_FAILURE_DECISION.drop(op.get_bind(), checkfirst=True)

    op.drop_index(
        "ix_telegram_post_performance_snapshots_captured_at", table_name="telegram_post_performance_snapshots",
    )
    op.drop_index(
        "ix_telegram_post_performance_snapshots_window", table_name="telegram_post_performance_snapshots",
    )
    op.drop_index(
        "ix_telegram_post_performance_snapshots_telegram_message_id",
        table_name="telegram_post_performance_snapshots",
    )
    op.drop_index(
        "ix_telegram_post_performance_snapshots_channel_memory_id",
        table_name="telegram_post_performance_snapshots",
    )
    op.drop_table("telegram_post_performance_snapshots")
    _SNAPSHOT_WINDOW.drop(op.get_bind(), checkfirst=True)
    _EXPERIMENT_STATUS.drop(op.get_bind(), checkfirst=True)
