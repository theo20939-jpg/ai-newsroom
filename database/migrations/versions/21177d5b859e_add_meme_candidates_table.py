"""add meme candidates table

Revision ID: 21177d5b859e
Revises: 31a8d7c95c87
Create Date: 2026-08-05 00:00:00.000000

Phase 18 M2 (docs/phase18_m0_meme_discovery_report.md §7, docs/phase18_m2_meme_concept_report.md):
one new, purely additive table - the single migration this phase needs. No existing table,
column, or enum is touched or rewritten. Mirrors `893fa1b75748_add_image_candidates_table.py`'s
own shape/discipline: one evolving row per meme attempt, most columns nullable and reserved for a
later milestone to populate (documented per-column in `database/models/meme_candidate.py`).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "21177d5b859e"
down_revision: Union[str, None] = "31a8d7c95c87"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUS_ENUM = sa.Enum(
    "concept_generated", "safety_blocked", "safety_review", "copy_generated",
    "image_generated", "image_failed", "rendered", "quality_ready", "quality_review",
    "quality_rejected", "pending_editor", "approved", "rejected",
    name="meme_candidate_status",
)


def upgrade() -> None:
    op.create_table(
        "meme_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("news_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("news_events.id"), nullable=False, index=True),
        sa.Column("editorial_task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("editorial_tasks.id"), nullable=True, index=True),
        sa.Column("content_draft_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("content_drafts.id"), nullable=True, index=True),
        sa.Column("status", _STATUS_ENUM, nullable=False, server_default="concept_generated"),
        sa.Column("concept_schema_version", sa.String(), nullable=False),
        sa.Column("concept_data", sa.JSON(), nullable=False),
        sa.Column("concept_regeneration_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("safety_status", sa.String(), nullable=True),
        sa.Column("safety_reason_codes", sa.JSON(), nullable=True),
        sa.Column("originality_status", sa.String(), nullable=True),
        sa.Column("originality_reason_codes", sa.JSON(), nullable=True),
        sa.Column("copy_schema_version", sa.String(), nullable=True),
        sa.Column("copy_data", sa.JSON(), nullable=True),
        sa.Column("copy_regeneration_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("image_status", sa.String(), nullable=True),
        sa.Column("image_storage_key", sa.String(), nullable=True),
        sa.Column("image_provider", sa.String(), nullable=True),
        sa.Column("image_model", sa.String(), nullable=True),
        sa.Column("image_regeneration_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("render_storage_key", sa.String(), nullable=True),
        sa.Column("quality_decision", sa.String(), nullable=True),
        sa.Column("quality_reason_codes", sa.JSON(), nullable=True),
        sa.Column("quality_score", sa.Integer(), nullable=True),
        sa.Column("editor_decision", sa.String(), nullable=True),
        sa.Column("editor_decision_reasons", sa.JSON(), nullable=True),
        sa.Column("editor_decision_notes", sa.Text(), nullable=True),
        sa.Column("editor_decision_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cumulative_cost_usd", sa.Numeric(precision=12, scale=6), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 100)",
            name="ck_meme_candidates_quality_score_range",
        ),
        sa.CheckConstraint("concept_regeneration_count >= 0", name="ck_meme_candidates_concept_regen_non_negative"),
        sa.CheckConstraint("copy_regeneration_count >= 0", name="ck_meme_candidates_copy_regen_non_negative"),
        sa.CheckConstraint("image_regeneration_count >= 0", name="ck_meme_candidates_image_regen_non_negative"),
        sa.CheckConstraint("cumulative_cost_usd >= 0", name="ck_meme_candidates_cost_non_negative"),
    )
    op.create_index("ix_meme_candidates_status", "meme_candidates", ["status"])
    op.create_index("ix_meme_candidates_editor_decision", "meme_candidates", ["editor_decision"])


def downgrade() -> None:
    op.drop_index("ix_meme_candidates_editor_decision", table_name="meme_candidates")
    op.drop_index("ix_meme_candidates_status", table_name="meme_candidates")
    op.drop_table("meme_candidates")
    _STATUS_ENUM.drop(op.get_bind(), checkfirst=True)
