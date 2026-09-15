"""add trend radar persistence (Migration 3)

Revision ID: 9b2e4f7c1a83
Revises: d84b1e6f3a52
Create Date: 2026-09-15 00:00:00.000000

INSTAGRAM-CONTENT-STRATEGY-V2 Phase 5 (Trend Radar core, SHADOW ONLY). Two new, purely additive
tables - `trend_observations` (append-only, one row per source/source_item_id/observed_at) and
`trend_clusters` - kept as their own migration, separate from Migration 1 (Director extension) and
Migration 2 (Digest durable state), so the Trend lane's schema never blocks or couples to either
of those already-shipped rollout steps.

Local/test database only - this migration is NOT applied to production as part of this phase.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "9b2e4f7c1a83"
down_revision: Union[str, None] = "d84b1e6f3a52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TREND_CLUSTER_TYPE = sa.Enum("topic", "format", "hybrid", name="trend_cluster_type")
_TREND_CLUSTER_STATUS = sa.Enum("active", "stale", name="trend_cluster_status")


def upgrade() -> None:
    op.create_table(
        "trend_clusters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("representative_text", sa.Text(), nullable=False),
        sa.Column("cluster_type", _TREND_CLUSTER_TYPE, nullable=False),
        sa.Column("trend_fingerprint", sa.JSON(), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", _TREND_CLUSTER_STATUS, nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "trend_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("source_item_id", sa.String(300), nullable=False),
        sa.Column("canonical_url", sa.String(1000), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_topic_text", sa.Text(), nullable=False),
        sa.Column("trend_fingerprint", sa.JSON(), nullable=True),
        sa.Column("engagement_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("cluster_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("trend_clusters.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "source", "source_item_id", "observed_at", name="uq_trend_observations_source_item_observed",
        ),
    )
    op.create_index("ix_trend_observations_source", "trend_observations", ["source"])
    op.create_index("ix_trend_observations_observed_at", "trend_observations", ["observed_at"])
    op.create_index("ix_trend_observations_cluster_id", "trend_observations", ["cluster_id"])


def downgrade() -> None:
    op.drop_index("ix_trend_observations_cluster_id", table_name="trend_observations")
    op.drop_index("ix_trend_observations_observed_at", table_name="trend_observations")
    op.drop_index("ix_trend_observations_source", table_name="trend_observations")
    op.drop_table("trend_observations")

    op.drop_table("trend_clusters")
    _TREND_CLUSTER_STATUS.drop(op.get_bind(), checkfirst=True)
    _TREND_CLUSTER_TYPE.drop(op.get_bind(), checkfirst=True)
