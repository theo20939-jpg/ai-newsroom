"""add competitor intelligence tables

Revision ID: 647aa0fe8a5a
Revises: f513705e3390
Create Date: 2026-09-05 06:30:00.000000

INSTAGRAM GROWTH ENGINE v2, spec §13/§62: two new, purely additive tables and one new enum type -
competitor_accounts, competitor_content_observations. No existing table/column/enum is touched.
See database/models/competitor.py for the full field-by-field reasoning.

Local/test database only - not applied to production as part of this phase.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "647aa0fe8a5a"
down_revision: Union[str, None] = "f513705e3390"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OBSERVATION_SOURCE = sa.Enum("manual", "public_data_import", "unknown", name="competitor_observation_source")


def upgrade() -> None:
    op.create_table(
        "competitor_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("platform", sa.String(length=50), nullable=False, server_default="instagram"),
        sa.Column("handle", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=300), nullable=True),
        sa.Column("niche", sa.String(length=300), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_competitor_accounts_platform", "competitor_accounts", ["platform"])
    op.create_index("ix_competitor_accounts_handle", "competitor_accounts", ["handle"])

    op.create_table(
        "competitor_content_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("competitor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("competitor_accounts.id"), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("format", sa.String(length=50), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("objective_inference", sa.String(length=100), nullable=True),
        sa.Column("hook_family", sa.String(length=100), nullable=True),
        sa.Column("creative_family", sa.String(length=100), nullable=True),
        sa.Column("series", sa.String(length=200), nullable=True),
        sa.Column("observable_metrics", sa.JSON(), nullable=True),
        sa.Column("observation_source", _OBSERVATION_SOURCE, nullable=False, server_default="manual"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.3"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_competitor_content_observations_competitor_id", "competitor_content_observations", ["competitor_id"]
    )
    op.create_index(
        "ix_competitor_content_observations_observed_at", "competitor_content_observations", ["observed_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_competitor_content_observations_observed_at", table_name="competitor_content_observations")
    op.drop_index("ix_competitor_content_observations_competitor_id", table_name="competitor_content_observations")
    op.drop_table("competitor_content_observations")
    op.drop_index("ix_competitor_accounts_handle", table_name="competitor_accounts")
    op.drop_index("ix_competitor_accounts_platform", table_name="competitor_accounts")
    op.drop_table("competitor_accounts")
    _OBSERVATION_SOURCE.drop(op.get_bind(), checkfirst=True)
