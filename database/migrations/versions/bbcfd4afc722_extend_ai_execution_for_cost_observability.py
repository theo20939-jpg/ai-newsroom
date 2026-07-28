"""extend ai_executions for cost observability

Revision ID: bbcfd4afc722
Revises: c2a4e6f9b3d1
Create Date: 2026-07-26 00:00:00.000000

API cost optimization: additive-only. The `ai_executions` table already had the right shape for
per-call cost audit (task_id, capability, model, input_tokens, output_tokens, cost) but was
never actually written to (services.cost_tracker.CostTracker.record() was never called by any
production code path - see docs/api_cost_audit_report.md §0). This adds the remaining fields
needed for full per-call observability: event_id, workflow_name, retry_number, and the two
usage fields the OpenAI Responses API can report (cached_input_tokens, reasoning_tokens) that
schemas.capability.CapabilityUsage did not previously carry. Every new column is nullable or
has a safe default - existing (currently zero) rows remain valid, no backfill, no data rewrite.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "bbcfd4afc722"
down_revision: Union[str, None] = "c2a4e6f9b3d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ai_executions", sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "ai_executions",
        sa.Column("workflow_name", sa.String(), nullable=False, server_default="UNKNOWN"),
    )
    op.add_column(
        "ai_executions", sa.Column("retry_number", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("ai_executions", sa.Column("cached_input_tokens", sa.Integer(), nullable=True))
    op.add_column("ai_executions", sa.Column("reasoning_tokens", sa.Integer(), nullable=True))
    op.add_column(
        "ai_executions",
        sa.Column("usage_source", sa.String(), nullable=False, server_default="provider_response"),
    )
    op.create_index("ix_ai_executions_event_id", "ai_executions", ["event_id"])
    op.create_index("ix_ai_executions_created_at", "ai_executions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_executions_created_at", table_name="ai_executions")
    op.drop_index("ix_ai_executions_event_id", table_name="ai_executions")
    op.drop_column("ai_executions", "usage_source")
    op.drop_column("ai_executions", "reasoning_tokens")
    op.drop_column("ai_executions", "cached_input_tokens")
    op.drop_column("ai_executions", "retry_number")
    op.drop_column("ai_executions", "workflow_name")
    op.drop_column("ai_executions", "event_id")
