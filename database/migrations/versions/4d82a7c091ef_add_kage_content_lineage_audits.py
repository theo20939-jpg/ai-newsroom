"""add bounded KAGE content-lineage audit table

Revision ID: 4d82a7c091ef
Revises: a3f7c1e9b204
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4d82a7c091ef"
down_revision: Union[str, None] = "a3f7c1e9b204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kage_content_lineage_audits",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("audit", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["news_events.id"]),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"]),
        sa.ForeignKeyConstraint(["draft_id"], ["content_drafts.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["editorial_tasks.id"]),
        sa.PrimaryKeyConstraint("task_id"),
    )
    op.create_index("ix_kage_lineage_event_id", "kage_content_lineage_audits", ["event_id"])
    op.create_index("ix_kage_lineage_draft_id", "kage_content_lineage_audits", ["draft_id"])


def downgrade() -> None:
    op.drop_index("ix_kage_lineage_draft_id", table_name="kage_content_lineage_audits")
    op.drop_index("ix_kage_lineage_event_id", table_name="kage_content_lineage_audits")
    op.drop_table("kage_content_lineage_audits")
