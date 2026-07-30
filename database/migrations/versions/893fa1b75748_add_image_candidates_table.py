"""add image candidates table

Revision ID: 893fa1b75748
Revises: bbcfd4afc722
Create Date: 2026-07-29 16:29:11.050034

Phase 16 M5 (docs/phase16_m5_persistence_and_retention_report.md §6): one new, purely additive
table. No existing table, column, or enum is touched or rewritten. `source_type` reuses the
already-existing Postgres enum type (owned by the `sources` table's own migration) via
`create_type=False` - creating it again would fail with "type already exists".
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "893fa1b75748"
down_revision: Union[str, None] = "bbcfd4afc722"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SOURCE_TYPE_ENUM = postgresql.ENUM(
    "TELEGRAM", "RSS", "NEWS_API", "WEB", "SOCIAL", name="source_type", create_type=False
)
_QUALITY_STATUS_ENUM = sa.Enum(
    "accepted", "rejected_quality", "duplicate_exact", "duplicate_near", "review",
    name="image_quality_status",
)
_RELEVANCE_STATUS_ENUM = sa.Enum(
    "ranked", "insufficient_evidence", "ineligible", name="image_relevance_status",
)
_STORAGE_STATUS_ENUM = sa.Enum(
    "not_requested", "pending", "stored", "failed", "expired", "missing",
    name="image_storage_status",
)


def upgrade() -> None:
    op.create_table(
        "image_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("candidate_id", sa.String(), nullable=False),
        sa.Column("news_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("news_events.id"), nullable=False, index=True),
        sa.Column("editorial_task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("editorial_tasks.id"), nullable=True, index=True),
        sa.Column("content_draft_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("content_drafts.id"), nullable=True, index=True),
        sa.Column("source_type", _SOURCE_TYPE_ENUM, nullable=False),
        sa.Column("discovery_method", sa.String(), nullable=False),
        sa.Column("source_name", sa.String(), nullable=True),
        sa.Column("article_url", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("remote_url", sa.Text(), nullable=True),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("provenance_confidence", sa.Integer(), nullable=True),
        sa.Column("source_relationship", sa.String(), nullable=True),
        sa.Column("observed_mime", sa.String(), nullable=True),
        sa.Column("image_format", sa.String(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("pixel_count", sa.Integer(), nullable=True),
        sa.Column("aspect_ratio", sa.Float(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("animated", sa.Boolean(), nullable=True),
        sa.Column("frame_count", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True, index=True),
        sa.Column("perceptual_hash", sa.String(length=16), nullable=True),
        sa.Column("quality_status", _QUALITY_STATUS_ENUM, nullable=True, index=True),
        sa.Column("quality_score", sa.Integer(), nullable=True),
        sa.Column("quality_hard_rejection_reasons", sa.JSON(), nullable=True),
        sa.Column("quality_warnings", sa.JSON(), nullable=True),
        sa.Column("quality_components", sa.JSON(), nullable=True),
        sa.Column("exact_cluster_id", sa.String(), nullable=True),
        sa.Column("near_duplicate_cluster_id", sa.String(), nullable=True),
        sa.Column("duplicate_of_candidate_id", sa.String(), nullable=True),
        sa.Column("is_representative", sa.Boolean(), nullable=True),
        sa.Column("relevance_status", _RELEVANCE_STATUS_ENUM, nullable=True, index=True),
        sa.Column("relevance_score", sa.Integer(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True, index=True),
        sa.Column("eligible_for_editorial", sa.Boolean(), nullable=False),
        sa.Column("relevance_components", sa.JSON(), nullable=True),
        sa.Column("relevance_penalties", sa.JSON(), nullable=True),
        sa.Column("relevance_coverage", sa.JSON(), nullable=True),
        sa.Column("relevance_reason", sa.Text(), nullable=True),
        sa.Column("storage_status", _STORAGE_STATUS_ENUM, nullable=False, index=True),
        sa.Column("storage_key", sa.String(), nullable=True),
        sa.Column("stored_byte_size", sa.Integer(), nullable=True),
        sa.Column("stored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("storage_error_code", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("bytes_expire_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.CheckConstraint("rank IS NULL OR rank > 0", name="ck_image_candidates_rank_positive"),
        sa.CheckConstraint(
            "relevance_score IS NULL OR (relevance_score >= 0 AND relevance_score <= 100)",
            name="ck_image_candidates_relevance_score_range",
        ),
        sa.CheckConstraint(
            "quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 100)",
            name="ck_image_candidates_quality_score_range",
        ),
        sa.CheckConstraint("width IS NULL OR width >= 0", name="ck_image_candidates_width_non_negative"),
        sa.CheckConstraint("height IS NULL OR height >= 0", name="ck_image_candidates_height_non_negative"),
        sa.CheckConstraint("byte_size IS NULL OR byte_size >= 0", name="ck_image_candidates_byte_size_non_negative"),
        sa.CheckConstraint(
            "stored_byte_size IS NULL OR stored_byte_size >= 0",
            name="ck_image_candidates_stored_byte_size_non_negative",
        ),
        sa.CheckConstraint(
            "storage_status != 'stored' OR storage_key IS NOT NULL",
            name="ck_image_candidates_storage_key_required_when_stored",
        ),
        sa.UniqueConstraint("news_event_id", "candidate_id", name="uq_image_candidates_event_candidate"),
    )
    op.create_index(
        "ix_image_candidates_top_candidate", "image_candidates",
        ["news_event_id", "eligible_for_editorial", "rank"],
    )


def downgrade() -> None:
    op.drop_index("ix_image_candidates_top_candidate", table_name="image_candidates")
    op.drop_table("image_candidates")

    sa.Enum(name="image_storage_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="image_relevance_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="image_quality_status").drop(op.get_bind(), checkfirst=True)
    # source_type is NOT dropped - it is owned by an earlier migration (sources table) and remains
    # in use by that table after this downgrade.
