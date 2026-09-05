"""add visual design autonomy tables

Revision ID: 7176e2997b8b
Revises: afcd869550a7
Create Date: 2026-09-05 16:00:00.000000

VISUAL-DESIGN-AUTONOMY-1, spec §65: visual_designer_brief_versions, visual_design_attempts,
visual_regression_cases, visual_regression_runs, plus the additive 'telegram_visual_design' value
on the existing director_run_type enum (database/models/director_run.py).

Local/test database only - not applied to production as part of this phase.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "7176e2997b8b"
down_revision: Union[str, None] = "afcd869550a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BRIEF_STATUS = sa.Enum(
    "active", "candidate", "superseded", "rolled_back", "rejected", "frozen",
    name="visual_designer_brief_status",
)
_ATTEMPT_STATUS = sa.Enum(
    "created", "rendered", "passed", "rework", "failed", "budget_exhausted", "human_review",
    name="visual_design_attempt_status",
)
_ROOT_CAUSE = sa.Enum(
    "design_direction", "source_media", "generation_model", "renderer", "overlay", "factual", "unknown",
    name="visual_failure_root_cause",
)
_REGRESSION_OUTCOME = sa.Enum(
    "pass", "pass_with_notes", "rework", "block", name="visual_regression_outcome",
)


def upgrade() -> None:
    op.execute("ALTER TYPE director_run_type ADD VALUE IF NOT EXISTS 'telegram_visual_design'")

    op.create_table(
        "visual_designer_brief_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scope", sa.String(length=50), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", _BRIEF_STATUS, nullable=False, server_default="candidate"),
        sa.Column("parent_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("brief_text", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_visual_designer_brief_versions_scope", "visual_designer_brief_versions", ["scope"])
    op.create_index("ix_visual_designer_brief_versions_status", "visual_designer_brief_versions", ["status"])

    op.create_table(
        "visual_design_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("final_post_review_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("presentation_type", sa.String(length=50), nullable=True),
        sa.Column("brief_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("visual_designer_brief_versions.id"), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("creative_direction", sa.JSON(), nullable=True),
        sa.Column("prompt_text", sa.Text(), nullable=True),
        sa.Column("source_media_decision", sa.String(length=50), nullable=True),
        sa.Column("generation_model", sa.String(length=100), nullable=True),
        sa.Column("generation_cost", sa.Float(), nullable=True),
        sa.Column("art_director_cost", sa.Float(), nullable=True),
        sa.Column("creative_reasoning_cost", sa.Float(), nullable=True),
        sa.Column("total_cost", sa.Float(), nullable=True),
        sa.Column("render_reference", sa.String(length=300), nullable=True),
        sa.Column("art_decision", sa.String(length=30), nullable=True),
        sa.Column("issue_codes", sa.JSON(), nullable=True),
        sa.Column("root_cause", _ROOT_CAUSE, nullable=True),
        sa.Column("status", _ATTEMPT_STATUS, nullable=False, server_default="created"),
        sa.Column("publication_outcome", sa.String(length=50), nullable=True),
        sa.Column("performance_relationship", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_visual_design_attempts_story_id", "visual_design_attempts", ["story_id"])
    op.create_index("ix_visual_design_attempts_final_post_review_id", "visual_design_attempts", ["final_post_review_id"])
    op.create_index("ix_visual_design_attempts_platform", "visual_design_attempts", ["platform"])
    op.create_index("ix_visual_design_attempts_presentation_type", "visual_design_attempts", ["presentation_type"])
    op.create_index("ix_visual_design_attempts_brief_version_id", "visual_design_attempts", ["brief_version_id"])
    op.create_index("ix_visual_design_attempts_status", "visual_design_attempts", ["status"])

    op.create_table(
        "visual_regression_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scope", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("stress_condition", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("fixture_reference", sa.String(length=300), nullable=True),
        sa.Column("expected_facts", sa.JSON(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_visual_regression_cases_scope", "visual_regression_cases", ["scope"])

    op.create_table(
        "visual_regression_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("candidate_brief_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("visual_designer_brief_versions.id"), nullable=False),
        sa.Column("baseline_brief_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("visual_designer_brief_versions.id"), nullable=True),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("visual_regression_cases.id"), nullable=False),
        sa.Column("candidate_outcome", _REGRESSION_OUTCOME, nullable=False),
        sa.Column("baseline_outcome", _REGRESSION_OUTCOME, nullable=True),
        sa.Column("issue_codes", sa.JSON(), nullable=True),
        sa.Column("cost", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_visual_regression_runs_candidate_brief_version_id", "visual_regression_runs", ["candidate_brief_version_id"])


def downgrade() -> None:
    op.drop_index("ix_visual_regression_runs_candidate_brief_version_id", table_name="visual_regression_runs")
    op.drop_table("visual_regression_runs")
    op.drop_index("ix_visual_regression_cases_scope", table_name="visual_regression_cases")
    op.drop_table("visual_regression_cases")

    op.drop_index("ix_visual_design_attempts_status", table_name="visual_design_attempts")
    op.drop_index("ix_visual_design_attempts_brief_version_id", table_name="visual_design_attempts")
    op.drop_index("ix_visual_design_attempts_presentation_type", table_name="visual_design_attempts")
    op.drop_index("ix_visual_design_attempts_platform", table_name="visual_design_attempts")
    op.drop_index("ix_visual_design_attempts_final_post_review_id", table_name="visual_design_attempts")
    op.drop_index("ix_visual_design_attempts_story_id", table_name="visual_design_attempts")
    op.drop_table("visual_design_attempts")

    op.drop_index("ix_visual_designer_brief_versions_status", table_name="visual_designer_brief_versions")
    op.drop_index("ix_visual_designer_brief_versions_scope", table_name="visual_designer_brief_versions")
    op.drop_table("visual_designer_brief_versions")

    _REGRESSION_OUTCOME.drop(op.get_bind(), checkfirst=True)
    _ROOT_CAUSE.drop(op.get_bind(), checkfirst=True)
    _ATTEMPT_STATUS.drop(op.get_bind(), checkfirst=True)
    _BRIEF_STATUS.drop(op.get_bind(), checkfirst=True)
    # Note: PostgreSQL cannot remove a single value from an existing enum type (ALTER TYPE ...
    # DROP VALUE does not exist) - 'telegram_visual_design' intentionally remains on
    # director_run_type after downgrade, exactly like every other additive-only enum value in this
    # codebase's migration history.
