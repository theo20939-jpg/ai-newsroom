"""add telegraph proposal research task link

Revision ID: 6025a320a45c
Revises: 863a064f8ee3
Create Date: 2026-08-16 00:00:00.000000

TELEGRAPH Checkpoint 3 (docs/telegraph_checkpoint_3_research_report.md): one purely additive,
nullable column - `telegraph_topic_proposals.research_task_id`, a FK to `editorial_tasks.id`.
Links a claimed proposal to the EditorialTask running its TELEGRAPH_RESEARCH workflow (see
database/models/telegraph_shortlist.py's own docstring for the full linkage reasoning - a tiny FK
was chosen over free-text/JSON matching inside EditorialTask.workflow). No existing table,
column, or enum is touched or rewritten.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "6025a320a45c"
down_revision: Union[str, None] = "863a064f8ee3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "telegraph_topic_proposals",
        sa.Column(
            "research_task_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("editorial_tasks.id"), nullable=True,
        ),
    )
    op.create_index(
        "ix_telegraph_topic_proposals_research_task_id",
        "telegraph_topic_proposals", ["research_task_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_telegraph_topic_proposals_research_task_id", table_name="telegraph_topic_proposals"
    )
    op.drop_column("telegraph_topic_proposals", "research_task_id")
