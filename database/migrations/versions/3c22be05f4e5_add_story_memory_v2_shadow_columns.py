"""add story memory v2 shadow columns

Revision ID: 3c22be05f4e5
Revises: 94fd27f7d129
Create Date: 2026-08-08 00:00:00.000000

Phase 20 (Story Memory V2): additive-only, three nullable columns on `news_event_story_links` -
`delta_classification` (services/story_delta_engine.py's own NO_NEW_FACTS/CONFIRMATION_ONLY/
MINOR_DELTA/MATERIAL_UPDATE/UNCERTAIN_DELTA taxonomy), `confidence_band` (services/
story_confidence.py's HIGH/MEDIUM/LOW), and `would_suppress` (services/story_suppression.py's
shadow-only duplicate-suppression recommendation). Mirrors `match_type`'s own existing
free-text-String convention on this table (not a Postgres enum - "expected to be refined during
shadow-mode calibration", see database/models/story_link.py) rather than inventing enum types for
values that are explicitly still being calibrated (Phase 20 M11's historical replay).

Every new column is nullable with no default and no backfill - existing rows (and every row
written while `story_memory_mode == "off"`, the unchanged real-`.env` default throughout this
phase) simply have all three as NULL. Nothing reads these columns yet; per Phase 20's own
shadow-neutrality requirement, this migration is created but deliberately NOT applied to any real
database as part of this phase - application requires separate explicit authorization, matching
the exact precedent of every other Phase 19/20 shadow-infra migration.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3c22be05f4e5"
down_revision: Union[str, None] = "94fd27f7d129"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("news_event_story_links", sa.Column("delta_classification", sa.String(), nullable=True))
    op.add_column("news_event_story_links", sa.Column("confidence_band", sa.String(), nullable=True))
    op.add_column("news_event_story_links", sa.Column("would_suppress", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("news_event_story_links", "would_suppress")
    op.drop_column("news_event_story_links", "confidence_band")
    op.drop_column("news_event_story_links", "delta_classification")
