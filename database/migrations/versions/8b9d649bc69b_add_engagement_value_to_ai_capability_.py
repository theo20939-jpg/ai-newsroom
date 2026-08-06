"""add ENGAGEMENT value to ai_capability enum

Revision ID: 8b9d649bc69b
Revises: 21177d5b859e
Create Date: 2026-08-06 00:00:00.000000

Phase 18.10 M9 (docs/phase18_10_editorial_intelligence_report.md): closes the cost-attribution
gap Phase 18.9's live test quantified - engagement-capability spend was being persisted under
AICapability.INTELLIGENCE via a deliberate, documented alias in
capabilities/capability_mapping.py ("Amendment A"), because the ai_capability enum had no
ENGAGEMENT value. Dollar amounts were never wrong (Postgres and the Redis cost ledger always
agreed on cost, only the Postgres capability *label* was wrong) - this migration is purely
additive, no data rewrite. Mirrors 8941ebf13fb0_add_unknown_event_category.py's own exact
shape/discipline for adding a value to an existing native Postgres enum type.

Note: PostgreSQL does not support removing a value from an enum type, so downgrade() cannot
cleanly reverse this migration. Any AIExecution rows written with capability=ENGAGEMENT after
this migration would need to be reassigned before the value could be dropped by recreating the
type - out of scope for this migration.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8b9d649bc69b"
down_revision: Union[str, None] = "21177d5b859e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE ai_capability ADD VALUE IF NOT EXISTS 'ENGAGEMENT'")


def downgrade() -> None:
    raise NotImplementedError(
        "PostgreSQL does not support dropping a value from an enum type; "
        "reverting this migration requires a manual data migration."
    )
