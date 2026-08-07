"""add content draft editorial plans table

Revision ID: b4d92a7f6e13
Revises: a3f7c9e15d02
Create Date: 2026-08-07 00:00:00.000000

Phase 19 M3 (docs/phase19_m0_audit.md): one new, purely additive, standalone table -
`content_draft_editorial_plans`. Surrogate PK (not PK-reuse) since a plan is produced once per
content-generation attempt, before a ContentDraft row necessarily exists. Neither `news_events`
nor `content_drafts` is altered.

Depends on: `editorial_planning_mode` (core/config.py). Written but NOT applied as part of
Phase 19's implementation, per explicit instruction (migration design only - the user applies it
separately).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b4d92a7f6e13"
down_revision: Union[str, None] = "a3f7c9e15d02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "content_draft_editorial_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("news_events.id"), nullable=False),
        sa.Column("content_draft_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("content_drafts.id"), nullable=True),
        sa.Column("plan", postgresql.JSON(), nullable=False),
        sa.Column("is_deterministic_scaffold", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("safety_passed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("safety_failed_checks", postgresql.JSON(), nullable=True),
        sa.Column("selected_editorial_text_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_content_draft_editorial_plans_event_id", "content_draft_editorial_plans", ["event_id"],
    )
    op.create_index(
        "ix_content_draft_editorial_plans_content_draft_id", "content_draft_editorial_plans", ["content_draft_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_content_draft_editorial_plans_content_draft_id", table_name="content_draft_editorial_plans")
    op.drop_index("ix_content_draft_editorial_plans_event_id", table_name="content_draft_editorial_plans")
    op.drop_table("content_draft_editorial_plans")
