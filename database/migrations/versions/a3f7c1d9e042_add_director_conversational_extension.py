"""add director conversational extension (Migration 1)

Revision ID: a3f7c1d9e042
Revises: b7d1f92a4e6c
Create Date: 2026-09-15 00:00:00.000000

INSTAGRAM-CONTENT-STRATEGY-V2 Phase 1 (Conversational Active Director + Product Truth). Purely
additive - four new nullable columns on two existing tables, no existing column/table/enum
touched or rewritten:

- business_context_proposals: question_text, origin, origin_context - lets a proposal represent
  a Director-initiated information need (not just a human-typed mutation command), and lets a
  later Founder answer be correlated back to exactly which product/fact/opportunity it concerns.
- products: undecided_facts - lets "Founder explicitly said this specific fact is not decided
  yet" be recorded as a real, confirmed fact distinct from mere absence (UNKNOWN).

Local/test database only - this migration is NOT applied to production as part of this phase.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a3f7c1d9e042"
down_revision: Union[str, None] = "b7d1f92a4e6c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("business_context_proposals", sa.Column("question_text", sa.Text(), nullable=True))
    op.add_column("business_context_proposals", sa.Column("origin", sa.String(30), nullable=True))
    op.add_column("business_context_proposals", sa.Column("origin_context", sa.JSON(), nullable=True))
    op.create_index("ix_business_context_proposals_origin", "business_context_proposals", ["origin"])

    op.add_column("products", sa.Column("undecided_facts", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "undecided_facts")

    op.drop_index("ix_business_context_proposals_origin", table_name="business_context_proposals")
    op.drop_column("business_context_proposals", "origin_context")
    op.drop_column("business_context_proposals", "origin")
    op.drop_column("business_context_proposals", "question_text")
