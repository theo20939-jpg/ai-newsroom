"""recovery_jobs concurrency safety + MEDIA_RESOLUTION_FAILED reason code

Revision ID: c48f6a1e9d02
Revises: a126e750c727
Create Date: 2026-09-13 16:10:00.000000

UNIFIED-EDITORIAL-PIPELINE-RUNTIME-CLOSURE-1 (S22/S23): purely additive, exactly two changes,
neither of which touches any existing row:

1. `MEDIA_RESOLUTION_FAILED` added to the existing `recovery_reason_code` enum (Postgres
   `ALTER TYPE ... ADD VALUE` - additive, cannot be run inside the same transaction as a
   statement that uses the new value, so this migration does nothing else in `upgrade()`).
   Existing rows and existing enum values are completely unaffected.

2. A new partial unique index `ix_recovery_jobs_open_lifecycle_identity` on
   `(content_draft_id, platform)` WHERE `state IN ('PENDING', 'RETRYING')` - the real, DB-level
   concurrency guarantee described in `database/models/recovery_job.py`'s own updated docstring.
   Only enforced going forward; since `RecoveryService.create_or_retry()` already only ever
   allows one OPEN row per draft today (its own `find_open_recovery()` query, now scoped to
   `content_draft_id` alone - platform-scoping added the SAME phase, see
   `services/editorial_pipeline/recovery_service.py`), no existing production data can violate
   this constraint at migration time - but the index is created with `postgresql_concurrently`
   disabled (plain `CREATE UNIQUE INDEX`, not `CONCURRENTLY`) inside the normal Alembic
   transaction, consistent with every other index migration already in this repo (this table is
   new and small; a `CONCURRENTLY` index cannot run inside a transaction block at all, and this
   repo's existing Alembic env does not disable transactional DDL).

Not applied to production by this phase (S48's own explicit "do NOT apply production DB
migration" - tested only against an isolated test DB, per S40).
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c48f6a1e9d02'
down_revision: Union[str, None] = 'a126e750c727'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE must be committed before the new value can be referenced by any
    # other statement in the same session - kept as its own, first, standalone statement.
    op.execute("ALTER TYPE recovery_reason_code ADD VALUE IF NOT EXISTS 'MEDIA_RESOLUTION_FAILED'")
    op.create_index(
        'ix_recovery_jobs_open_lifecycle_identity',
        'recovery_jobs',
        ['content_draft_id', 'platform'],
        unique=True,
        postgresql_where="state IN ('PENDING', 'RETRYING')",
    )


def downgrade() -> None:
    op.drop_index('ix_recovery_jobs_open_lifecycle_identity', table_name='recovery_jobs')
    # Postgres has no `ALTER TYPE ... DROP VALUE` - removing an enum value on downgrade would
    # require rebuilding the type (drop/recreate), which is unsafe if any row already uses it.
    # Consistent with this repo's own existing convention (a126e750c727's own downgrade recreates
    # the whole type only because it drops the entire table first) - here the table/type both
    # survive downgrade, so the added enum value is deliberately left in place rather than risking
    # a destructive type rebuild for a downgrade path. Documented, not silently skipped.
