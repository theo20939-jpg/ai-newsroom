"""add story memory v2 phase 1 columns

Revision ID: af2aeb69cf67
Revises: e0da237ec184
Create Date: 2026-09-02 00:00:00.000000

PHASE STORY-MEMORY-V2-2, rollout step 1 (approved design: PHASE STORY-MEMORY-V2-1). Purely
additive, nullable-only schema for the future AI Story Judge / final_decision layer - no runtime
code in this phase reads or writes any of these columns yet (see the corresponding model
docstrings). No backfill: historical reader-visible factual state is unproven and stays NULL.

Preflight finding (PHASE STORY-MEMORY-V2-2 §A): database/migrations/versions/
3c22be05f4e5_add_story_memory_v2_shadow_columns.py - which its own docstring described as
"deliberately NOT applied to any real database" - is confirmed, both by its position in the
linear alembic history (an ancestor of this repository's current HEAD, e0da237ec184) and by
direct inspection of a live database's information_schema, to already be applied. That migration
is therefore NOT re-created or duplicated here; this migration only adds the columns genuinely new
to the approved Phase 1 scope, chained on top of the current HEAD.

Mirrors 8b9d649bc69b_add_engagement_value_to_ai_capability_.py's own exact shape for the
AICapability enum addition (STORY_JUDGE) - additive-only, ADD VALUE IF NOT EXISTS, downgrade
raises NotImplementedError (PostgreSQL cannot drop an enum value).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "af2aeb69cf67"
down_revision: Union[str, None] = "e0da237ec184"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # news_event_story_links: the final, actionable Story Memory V2 decision - distinct from the
    # existing, retrieval-only `match_type` (six legacy values) and from the existing V2 shadow
    # columns (delta_classification/confidence_band/would_suppress, 3c22be05f4e5) - see
    # database/models/story_link.py's own updated docstring.
    op.add_column("news_event_story_links", sa.Column("final_decision", sa.String(), nullable=True))
    op.add_column("news_event_story_links", sa.Column("decision_source", sa.String(), nullable=True))
    op.add_column("news_event_story_links", sa.Column("decision_confidence", sa.Float(), nullable=True))
    op.add_column("news_event_story_links", sa.Column("judge_error_category", sa.String(), nullable=True))
    op.add_column("news_event_story_links", sa.Column("new_facts", sa.JSON(), nullable=True))
    op.add_column("news_event_story_links", sa.Column("material_delta", sa.JSON(), nullable=True))
    op.add_column("news_event_story_links", sa.Column("decision_reason", sa.Text(), nullable=True))

    # stories: the observed/published factual-state split (PHASE STORY-MEMORY-V2-1 §F and its
    # correction rounds) - observed_facts is Judge/candidate-evidence state; published_facts is
    # reader-visible state, advanced only on confirmed delivery. Both stay NULL until a future,
    # separately-authorized phase actually computes and writes them.
    op.add_column("stories", sa.Column("observed_facts", sa.JSON(), nullable=True))
    op.add_column(
        "stories", sa.Column("observed_facts_updated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("stories", sa.Column("published_facts", sa.JSON(), nullable=True))
    op.add_column(
        "stories", sa.Column("published_facts_updated_at", sa.DateTime(timezone=True), nullable=True)
    )

    # story_telegram_deliveries: self-contained per-delivery audit fields (denormalized decision
    # snapshot + reader-visible communicated-fact record) - all stay NULL until a future phase's
    # durable-write mechanism actually populates them; today's record_delivery() is unchanged.
    op.add_column(
        "story_telegram_deliveries",
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "story_telegram_deliveries_source_event_id_fkey",
        "story_telegram_deliveries", "news_events", ["source_event_id"], ["id"],
    )
    op.add_column("story_telegram_deliveries", sa.Column("final_decision", sa.String(), nullable=True))
    op.add_column("story_telegram_deliveries", sa.Column("decision_source", sa.String(), nullable=True))
    op.add_column("story_telegram_deliveries", sa.Column("topic_id", sa.Integer(), nullable=True))
    op.add_column(
        "story_telegram_deliveries", sa.Column("communicated_facts", sa.JSON(), nullable=True)
    )

    # content_draft_story_links: whether this draft was generated with no prior published_facts
    # context (standalone) - drives which candidate fact set a future phase's publish-time
    # extraction step compares against. NULL for every row until that phase exists.
    op.add_column(
        "content_draft_story_links", sa.Column("generated_as_standalone", sa.Boolean(), nullable=True)
    )

    # ai_capability enum: reserves the STORY_JUDGE value for a future, separately-authorized
    # capability implementation - adding the enum value itself has no runtime execution effect
    # (mirrors 8b9d649bc69b's own precedent exactly; no capability/executor/prompt is added here).
    op.execute("ALTER TYPE ai_capability ADD VALUE IF NOT EXISTS 'STORY_JUDGE'")


def downgrade() -> None:
    op.drop_column("content_draft_story_links", "generated_as_standalone")

    op.drop_column("story_telegram_deliveries", "communicated_facts")
    op.drop_column("story_telegram_deliveries", "topic_id")
    op.drop_column("story_telegram_deliveries", "decision_source")
    op.drop_column("story_telegram_deliveries", "final_decision")
    op.drop_constraint(
        "story_telegram_deliveries_source_event_id_fkey", "story_telegram_deliveries", type_="foreignkey"
    )
    op.drop_column("story_telegram_deliveries", "source_event_id")

    op.drop_column("stories", "published_facts_updated_at")
    op.drop_column("stories", "published_facts")
    op.drop_column("stories", "observed_facts_updated_at")
    op.drop_column("stories", "observed_facts")

    op.drop_column("news_event_story_links", "decision_reason")
    op.drop_column("news_event_story_links", "material_delta")
    op.drop_column("news_event_story_links", "new_facts")
    op.drop_column("news_event_story_links", "judge_error_category")
    op.drop_column("news_event_story_links", "decision_confidence")
    op.drop_column("news_event_story_links", "decision_source")
    op.drop_column("news_event_story_links", "final_decision")

    # ai_capability.STORY_JUDGE is intentionally NOT reverted here - PostgreSQL cannot drop a
    # value from an enum type (identical, already-established precedent: 8b9d649bc69b's own
    # downgrade() for ENGAGEMENT). If this migration is ever downgraded, STORY_JUDGE simply
    # remains a valid, unused enum value - harmless, matching that exact prior precedent.
