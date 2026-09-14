"""add instagram_editorial_deliveries table

Revision ID: a3f7c1e9b204
Revises: d7e4a92f1b83
Create Date: 2026-09-14 20:00:00.000000

INSTAGRAM-TELEGRAM-EDITORIAL-DELIVERY-1 §21/§22: purely additive - one new table, its own new enum
type, two indexes (one plain, one partial-unique for current-version-identity concurrency safety,
mirroring the exact pattern `d7e4a92f1b83`/`c48f6a1e9d02` already established). No existing table,
column, or row is touched. Not applied to production this phase - tested only against the isolated
local test DB.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a3f7c1e9b204'
down_revision: Union[str, None] = 'd7e4a92f1b83'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CURRENT_STATES = (
    'PENDING', 'DELIVERED', 'APPROVED', 'REGENERATING_FULL', 'REGENERATING_TEXT',
    'REGENERATING_VISUAL', 'HOLD', 'BLOCK',
)


def upgrade() -> None:
    op.create_table(
        'instagram_editorial_deliveries',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('package_identity', sa.String(length=255), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('source_story_id', sa.String(length=255), nullable=True),
        sa.Column('content_format', sa.String(length=32), nullable=False),
        sa.Column(
            'state',
            sa.Enum(
                'PENDING', 'DELIVERED', 'APPROVED', 'REGENERATING_FULL', 'REGENERATING_TEXT',
                'REGENERATING_VISUAL', 'SUPERSEDED', 'HOLD', 'BLOCK',
                name='instagram_editorial_delivery_state',
            ),
            nullable=False,
        ),
        sa.Column('telegram_chat_id', sa.Integer(), nullable=True),
        sa.Column('telegram_topic_id', sa.Integer(), nullable=True),
        sa.Column('media_message_ids', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('control_message_id', sa.Integer(), nullable=True),
        sa.Column('package_snapshot', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('decided_by_telegram_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_instagram_editorial_deliveries_package_identity'), 'instagram_editorial_deliveries',
        ['package_identity'], unique=False,
    )
    op.create_index(
        op.f('ix_instagram_editorial_deliveries_state'), 'instagram_editorial_deliveries', ['state'], unique=False,
    )
    op.create_index(
        'ix_instagram_editorial_deliveries_current_identity', 'instagram_editorial_deliveries', ['package_identity'],
        unique=True,
        postgresql_where=(
            "state IN (" + ", ".join(f"'{s}'" for s in _CURRENT_STATES) + ")"
        ),
    )


def downgrade() -> None:
    op.drop_index('ix_instagram_editorial_deliveries_current_identity', table_name='instagram_editorial_deliveries')
    op.drop_index(op.f('ix_instagram_editorial_deliveries_state'), table_name='instagram_editorial_deliveries')
    op.drop_index(op.f('ix_instagram_editorial_deliveries_package_identity'), table_name='instagram_editorial_deliveries')
    op.drop_table('instagram_editorial_deliveries')
    op.execute('DROP TYPE IF EXISTS instagram_editorial_delivery_state')
