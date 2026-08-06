"""add story memory tables

Revision ID: c2bc6affb100
Revises: 8b9d649bc69b
Create Date: 2026-08-06 00:00:00.000000

Phase 18.10 M1/M2 (docs/phase18_10_editorial_intelligence_report.md): two new, purely additive,
standalone tables - `stories` and `news_event_story_links`. No existing table, column, index, or
enum is touched or rewritten.

Revised from this migration's first draft, which added nullable `story_id`/`story_match_type`/
`story_match_score` columns directly to `news_events` (and similarly to `content_drafts`).
That approach was correct at the schema level but had an unacceptable operational consequence:
SQLAlchemy includes every mapped column of a table in every generated INSERT statement (even
with a None value), so those columns being present on the ORM model - regardless of whether this
migration was ever applied - would make the existing, always-run NewsEvent insert
(services/collector.py) fail against a database that hasn't had this migration applied, for
every single event, regardless of story_memory_mode. `news_event_story_links` is a wholly
separate table instead, only ever touched by code paths gated behind
story_memory_mode != "off" - mirrors `21177d5b859e_add_meme_candidates_table.py`'s own
shape/discipline exactly (a standalone table nothing outside its own feature ever references),
which is why that migration has always safely coexisted unapplied without breaking anything.

Written but NOT applied as part of Phase 18.10's implementation, per explicit instruction
(migration design only - the user applies it separately).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c2bc6affb100"
down_revision: Union[str, None] = "8b9d649bc69b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EVENT_CATEGORY_ENUM = postgresql.ENUM(
    "AI", "GADGETS", "TECH", "STARTUPS", "SOFTWARE", "HARDWARE", "CYBERSECURITY", "UNKNOWN",
    name="event_category", create_type=False,
)


def upgrade() -> None:
    op.create_table(
        "stories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("category", _EVENT_CATEGORY_ENUM, nullable=False),
        sa.Column("entities", sa.JSON(), nullable=True),
        sa.Column("keywords", sa.JSON(), nullable=True),
        sa.Column("topic_bucket", sa.String(), nullable=False),
        sa.Column("first_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("news_events.id"), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_stories_category", "stories", ["category"])

    op.create_table(
        "news_event_story_links",
        sa.Column("news_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("news_events.id"), primary_key=True),
        sa.Column("story_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stories.id"), nullable=False),
        sa.Column("match_type", sa.String(), nullable=False),
        sa.Column("match_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_news_event_story_links_story_id", "news_event_story_links", ["story_id"])


def downgrade() -> None:
    op.drop_index("ix_news_event_story_links_story_id", table_name="news_event_story_links")
    op.drop_table("news_event_story_links")

    op.drop_index("ix_stories_category", table_name="stories")
    op.drop_table("stories")
