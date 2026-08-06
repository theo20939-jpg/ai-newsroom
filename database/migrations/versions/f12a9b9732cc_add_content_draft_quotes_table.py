"""add content draft quotes table

Revision ID: f12a9b9732cc
Revises: 0fac25b59455
Create Date: 2026-08-06 00:00:00.000000

Phase 18.10 M5 (docs/phase18_10_editorial_intelligence_report.md): one new, purely additive,
standalone table - `content_draft_quotes`. `ContentDraft` itself is never altered (same
hot-path-dependency lesson `c2bc6affb100`/`0fac25b59455` already established).

Written but NOT applied as part of Phase 18.10's implementation, per explicit instruction
(migration design only - the user applies it separately).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f12a9b9732cc"
down_revision: Union[str, None] = "0fac25b59455"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "content_draft_quotes",
        sa.Column("content_draft_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("content_drafts.id"), primary_key=True),
        sa.Column("quote_text", sa.Text(), nullable=False),
        sa.Column("translated_text", sa.Text(), nullable=True),
        sa.Column("speaker", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("content_draft_quotes")
