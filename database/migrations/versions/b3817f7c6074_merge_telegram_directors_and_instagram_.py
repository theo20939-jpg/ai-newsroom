"""merge telegram directors and instagram growth engine heads

Revision ID: b3817f7c6074
Revises: c0021dea34a5, 2fb7d650c68b
Create Date: 2026-09-05 09:44:38.744178

SOCIAL-INTELLIGENCE-INTEGRATION-1, spec §2: pure Alembic merge point, no schema changes of its
own. Both parent heads forked independently from f513705e3390 (the shared Business Context
foundation, feature/social-business-context-v1 @ bed4ffa):

  f513705e3390 -> 97233eb2e1e9 -> c0021dea34a5           (feature/telegram-directors-2)
  f513705e3390 -> 647aa0fe8a5a -> ... -> 2fb7d650c68b    (feature/instagram-growth-engine-v1)

No table/model name collision exists between the two lines (verified: 34 distinct tables in
Base.metadata after both are imported together) - this merge revision only needed to give
Alembic a single linear head to run upgrade/downgrade against, never a data/schema reconciliation.

Local/test database only - not applied to production as part of this phase.
"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = 'b3817f7c6074'
down_revision: Union[str, None] = ('c0021dea34a5', '2fb7d650c68b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
