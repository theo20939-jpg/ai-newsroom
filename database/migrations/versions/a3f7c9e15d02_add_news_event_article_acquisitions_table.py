"""add news event article acquisitions table

Revision ID: a3f7c9e15d02
Revises: f12a9b9732cc
Create Date: 2026-08-07 00:00:00.000000

Phase 19 M1/M2 (docs/phase19_m0_audit.md): one new, purely additive, standalone table -
`news_event_article_acquisitions`. `NewsEvent` itself is never altered (same hot-path-dependency
lesson `c2bc6affb100`/`0fac25b59455`/`f12a9b9732cc` already established) - `NewsEvent.content` is
never overwritten by this or any later Phase 19 migration.

Depends on: `article_acquisition_mode` (core/config.py). Written but NOT applied as part of Phase
19's implementation, per explicit instruction (migration design only - the user applies it
separately).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a3f7c9e15d02"
down_revision: Union[str, None] = "f12a9b9732cc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "news_event_article_acquisitions",
        sa.Column("news_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("news_events.id"), primary_key=True),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("reused_from_news_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("news_events.id"), nullable=True),
        sa.Column("acquisition_status", sa.String(), nullable=False),
        sa.Column("raw_extracted_text", sa.Text(), nullable=True),
        sa.Column("cleaned_text", sa.Text(), nullable=True),
        sa.Column("effective_completeness_status", sa.String(), nullable=False),
        sa.Column("selected_editorial_text_hash", sa.String(length=64), nullable=True),
        sa.Column("extracted_char_count", sa.Integer(), nullable=True),
        sa.Column("cleaned_char_count", sa.Integer(), nullable=True),
        sa.Column("removed_block_count", sa.Integer(), nullable=True),
        sa.Column("cleaning_reasons", postgresql.JSON(), nullable=True),
        sa.Column("cleaning_version", sa.String(), nullable=False, server_default="unset"),
        sa.Column("source_html_bytes", sa.Integer(), nullable=True),
        sa.Column("fetch_duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("triggered_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_news_event_article_acquisitions_reused_from",
        "news_event_article_acquisitions",
        ["reused_from_news_event_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_news_event_article_acquisitions_reused_from", table_name="news_event_article_acquisitions")
    op.drop_table("news_event_article_acquisitions")
