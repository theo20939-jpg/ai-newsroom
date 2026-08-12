"""add stories updated_at index

Revision ID: 3f37cf34109d
Revises: 3c22be05f4e5
Create Date: 2026-08-08 00:00:00.000001

Phase 20 M11.2 (Candidate Retrieval V2): `stories.updated_at` had no index at all - confirmed by
direct `\\d stories` against the real dev DB - despite `services/story_memory.py::
_fetch_candidate_stories()`'s own `WHERE updated_at >= :cutoff ORDER BY updated_at DESC` query
depending on it since Phase 18.10. Harmless at today's real row count (26), but M11's historical
replay widens this same query's effective fetch width (removing the artificial `LIMIT 150` at the
SQL level in favor of a Python-side two-tier preselection - see `_fetch_candidate_stories()`'s own
updated docstring) specifically to fix a measured 94.2% candidate-cap-saturation problem at real
production volume. A plain btree index, not a new datastore/technology - the smallest fix that
keeps the now-wider query cheap as the `stories` table grows past today's near-empty state.

Purely additive: one index, no data change, no application-code dependency beyond query planning.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f37cf34109d"
down_revision: Union[str, None] = "3c22be05f4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_stories_updated_at", "stories", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_stories_updated_at", table_name="stories")
