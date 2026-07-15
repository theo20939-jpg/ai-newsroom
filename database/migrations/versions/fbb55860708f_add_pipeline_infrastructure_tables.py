"""add pipeline infrastructure tables

Revision ID: fbb55860708f
Revises: ef37f4253252
Create Date: 2026-07-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "fbb55860708f"
down_revision: Union[str, None] = "ef37f4253252"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "news_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sources.id"), nullable=False, index=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column(
            "category",
            sa.Enum("AI", "GADGETS", "TECH", "STARTUPS", "SOFTWARE", "HARDWARE", "CYBERSECURITY", name="event_category"),
            nullable=False,
            index=True,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("hash", sa.String(), nullable=False, unique=True),
        sa.Column(
            "status",
            sa.Enum("NEW", "PROCESSING", "ANALYZED", "REJECTED", "ARCHIVED", name="event_status"),
            nullable=False,
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "editorial_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("news_events.id"), nullable=False),
        sa.Column("priority", sa.Enum("S", "A", "B", "C", name="task_priority"), nullable=False, index=True),
        sa.Column("workflow", sa.JSON(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("CREATED", "RUNNING", "WAITING", "COMPLETED", "FAILED", name="task_status"),
            nullable=False,
            index=True,
        ),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, index=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "ai_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("editorial_tasks.id"), nullable=False),
        sa.Column(
            "capability",
            sa.Enum("RESEARCH", "INTELLIGENCE", "TREND", "SCORING", "COPYWRITING", "CREATIVE", "QUALITY", name="ai_capability"),
            nullable=False,
        ),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("response", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "content_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("editorial_tasks.id"), nullable=False),
        sa.Column(
            "type",
            sa.Enum("POST", "SHORT", "ANALYSIS", "MEME", "VIDEO_SCRIPT", name="content_type"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("hashtags", sa.JSON(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("content_drafts")
    op.drop_table("ai_executions")
    op.drop_table("editorial_tasks")
    op.drop_table("news_events")

    sa.Enum(name="content_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="ai_capability").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="task_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="task_priority").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="event_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="event_category").drop(op.get_bind(), checkfirst=True)
