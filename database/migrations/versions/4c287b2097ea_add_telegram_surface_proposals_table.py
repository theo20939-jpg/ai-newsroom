"""add telegram surface proposals table

Revision ID: 4c287b2097ea
Revises: b0647b642864
Create Date: 2026-09-05 11:00:00.000000

SOCIAL-INTELLIGENCE-OPS-1, spec §3/§4: one new, purely additive table - telegram_surface_proposals
- the pending-confirmation staging area for /surface. See
database/models/telegram_surface_proposal.py for the full reasoning.

Local/test database only - not applied to production as part of this phase.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "4c287b2097ea"
down_revision: Union[str, None] = "b0647b642864"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PROPOSAL_STATUS = sa.Enum("pending", "confirmed", "cancelled", "expired", name="telegram_surface_proposal_status")
# telegram_surface_role already exists (created by migration b0647b642864) - create_type=False so
# this table's own creation never tries to CREATE (or, on downgrade, DROP) that shared enum type.
# postgresql.ENUM (not the generic sa.Enum proxy) is required here for create_type=False to
# actually suppress the emitted DDL through Alembic's op.create_table path.
_SURFACE_ROLE = postgresql.ENUM(
    "internal_editorial", "public_news_channel", "public_gaming_channel", "public_product_channel", "other",
    name="telegram_surface_role", create_type=False,
)


def upgrade() -> None:
    op.create_table(
        "telegram_surface_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", _PROPOSAL_STATUS, nullable=False, server_default="pending"),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=200), nullable=True),
        sa.Column("role", _SURFACE_ROLE, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("analytics_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("raw_instruction", sa.Text(), nullable=False),
        sa.Column("parsed_structure", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_topic_id", sa.Integer(), nullable=True),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.BigInteger(), nullable=True),
        sa.Column("resulting_surface_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_telegram_surface_proposals_status", "telegram_surface_proposals", ["status"])
    op.create_index("ix_telegram_surface_proposals_chat_id", "telegram_surface_proposals", ["chat_id"])


def downgrade() -> None:
    op.drop_index("ix_telegram_surface_proposals_chat_id", table_name="telegram_surface_proposals")
    op.drop_index("ix_telegram_surface_proposals_status", table_name="telegram_surface_proposals")
    op.drop_table("telegram_surface_proposals")
    _PROPOSAL_STATUS.drop(op.get_bind(), checkfirst=True)
