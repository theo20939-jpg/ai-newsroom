"""add recovery_jobs table

Revision ID: a126e750c727
Revises: 4a1b7c9d2e3f
Create Date: 2026-09-13 08:10:21.587063

Manually cleaned (UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-CUTOVER-1, S9/S24): the raw
`alembic revision --autogenerate` output detected a large amount of pre-existing schema
drift between the shared local dev database and the current (reconciled) model set that
has nothing to do with this phase (table drops/constraint changes across roughly a dozen
unrelated tables: telegraph_topic_proposals, event_recap_reviews, story_telegram_deliveries,
news_event_story_links, content_draft_story_links, stories, telegraph_shortlist_batches,
media_vision_reviews, ai_executions indexes, and unique-constraint/index changes on
design_reference_assets/instagram_accounts/instagram_series/products/telegram_surfaces).
None of that is in scope for this phase and none of it should ever be proposed for removal
by this migration - it has been stripped out by hand so this file contains ONLY the new
`recovery_jobs` table, its three new enum types, and its two indexes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a126e750c727'
down_revision: Union[str, None] = '4a1b7c9d2e3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'recovery_jobs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('content_draft_id', sa.UUID(), nullable=False),
        sa.Column('platform', sa.Enum('TELEGRAM', 'INSTAGRAM', name='recovery_platform'), nullable=False),
        sa.Column(
            'reason_code',
            sa.Enum(
                'NO_SUITABLE_MEDIA',
                'MEDIA_RESEARCH_TIMEOUT',
                'MEDIA_SEND_FAILED',
                'AMBIGUOUS_TRANSPORT_RESULT',
                'CAPTION_BUDGET_FAILED',
                'RENDER_FAILED',
                'QUALITY_GATE_FAILED',
                name='recovery_reason_code',
            ),
            nullable=False,
        ),
        sa.Column('failed_stage', sa.String(length=100), nullable=False),
        sa.Column(
            'state',
            sa.Enum('PENDING', 'RETRYING', 'RECOVERED', 'TERMINAL_HOLD', name='recovery_job_state'),
            nullable=False,
        ),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error_summary', sa.String(length=500), nullable=True),
        sa.Column('candidate_diagnostics', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['content_draft_id'], ['content_drafts.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_recovery_jobs_content_draft_id'), 'recovery_jobs', ['content_draft_id'], unique=False)
    op.create_index(op.f('ix_recovery_jobs_state'), 'recovery_jobs', ['state'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_recovery_jobs_state'), table_name='recovery_jobs')
    op.drop_index(op.f('ix_recovery_jobs_content_draft_id'), table_name='recovery_jobs')
    op.drop_table('recovery_jobs')
    op.execute('DROP TYPE IF EXISTS recovery_job_state')
    op.execute('DROP TYPE IF EXISTS recovery_reason_code')
    op.execute('DROP TYPE IF EXISTS recovery_platform')
