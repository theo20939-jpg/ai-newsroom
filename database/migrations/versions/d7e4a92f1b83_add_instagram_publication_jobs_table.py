"""add instagram_publication_jobs table

Revision ID: d7e4a92f1b83
Revises: c48f6a1e9d02
Create Date: 2026-09-14 15:00:00.000000

INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1 §8/§12: purely additive - one new table, its own new enum
type, two indexes (one plain, one partial-unique for open-lifecycle-identity concurrency safety,
mirroring the exact pattern `a126e750c727`/`c48f6a1e9d02` already established for
`recovery_jobs`). No existing table, column, or row is touched. Not applied to production this
phase (§19's own explicit "no deploy, no real Instagram write" - tested only against the isolated
local test DB).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd7e4a92f1b83'
down_revision: Union[str, None] = 'c48f6a1e9d02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'instagram_publication_jobs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('idempotency_key', sa.String(length=64), nullable=False),
        sa.Column('package_id', sa.String(length=64), nullable=False),
        sa.Column('package_identity', sa.String(length=255), nullable=False),
        sa.Column('content_format', sa.String(length=32), nullable=False),
        sa.Column('account_key', sa.String(length=64), nullable=False),
        sa.Column(
            'state',
            sa.Enum(
                'NOT_ATTEMPTED', 'CREATING_CONTAINER', 'CONTAINER_CREATED', 'PUBLISHING',
                'PUBLISHED', 'FAILED', 'AMBIGUOUS', 'HOLD',
                name='instagram_publication_state',
            ),
            nullable=False,
        ),
        sa.Column('container_ids', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('media_id', sa.String(length=64), nullable=True),
        sa.Column('permalink', sa.String(length=500), nullable=True),
        sa.Column('failure_class', sa.String(length=64), nullable=True),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_instagram_publication_jobs_idempotency_key'), 'instagram_publication_jobs',
        ['idempotency_key'], unique=False,
    )
    op.create_index(
        op.f('ix_instagram_publication_jobs_state'), 'instagram_publication_jobs', ['state'], unique=False,
    )
    op.create_index(
        'ix_instagram_publication_jobs_open_identity', 'instagram_publication_jobs', ['idempotency_key'],
        unique=True,
        postgresql_where=(
            "state IN ('NOT_ATTEMPTED', 'CREATING_CONTAINER', 'CONTAINER_CREATED', 'PUBLISHING', 'AMBIGUOUS')"
        ),
    )


def downgrade() -> None:
    op.drop_index('ix_instagram_publication_jobs_open_identity', table_name='instagram_publication_jobs')
    op.drop_index(op.f('ix_instagram_publication_jobs_state'), table_name='instagram_publication_jobs')
    op.drop_index(op.f('ix_instagram_publication_jobs_idempotency_key'), table_name='instagram_publication_jobs')
    op.drop_table('instagram_publication_jobs')
    op.execute('DROP TYPE IF EXISTS instagram_publication_state')
