"""add telegram surfaces table

Revision ID: b0647b642864
Revises: b3817f7c6074
Create Date: 2026-09-05 10:15:00.000000

SOCIAL-INTELLIGENCE-INTEGRATION-1, spec §14: one new, purely additive table -
telegram_surfaces - explicit Telegram surface identity (INTERNAL_EDITORIAL vs PUBLIC_*). See
database/models/telegram_surface.py for the full reasoning. Starts empty - no row is inserted by
this migration, no chat_id is ever guessed/hardcoded.

Local/test database only - not applied to production as part of this phase.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b0647b642864"
down_revision: Union[str, None] = "b3817f7c6074"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SURFACE_ROLE = sa.Enum(
    "internal_editorial", "public_news_channel", "public_gaming_channel", "public_product_channel", "other",
    name="telegram_surface_role",
)


def upgrade() -> None:
    op.create_table(
        "telegram_surfaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=200), nullable=True),
        sa.Column("role", _SURFACE_ROLE, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("analytics_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("chat_id", name="uq_telegram_surfaces_chat_id"),
    )
    op.create_index("ix_telegram_surfaces_chat_id", "telegram_surfaces", ["chat_id"])
    op.create_index("ix_telegram_surfaces_role", "telegram_surfaces", ["role"])


def downgrade() -> None:
    op.drop_index("ix_telegram_surfaces_role", table_name="telegram_surfaces")
    op.drop_index("ix_telegram_surfaces_chat_id", table_name="telegram_surfaces")
    op.drop_table("telegram_surfaces")
    _SURFACE_ROLE.drop(op.get_bind(), checkfirst=True)
