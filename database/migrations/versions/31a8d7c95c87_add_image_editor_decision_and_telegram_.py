"""add image editor decision and telegram file id

Revision ID: 31a8d7c95c87
Revises: 893fa1b75748
Create Date: 2026-07-30 17:38:19.843836

Phase 16 M6 (docs/phase16_m6_telegram_editorial_preview_report.md §6): three new, purely additive
columns on the existing `image_candidates` table - no existing column is touched or rewritten.
`editor_decision`/`editor_decision_at` record the human's durable choice; `telegram_file_id` caches
the Telegram-issued reference for a candidate's already-uploaded photo so repeat sends never need
to re-read local storage.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '31a8d7c95c87'
down_revision: Union[str, None] = '893fa1b75748'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EDITOR_DECISION_ENUM = sa.Enum("selected", "rejected", name="image_editor_decision")


def upgrade() -> None:
    op.add_column("image_candidates", sa.Column("telegram_file_id", sa.String(), nullable=True))
    # Unlike op.create_table (which auto-creates any enum type it references), op.add_column
    # does not - the enum type must be created explicitly first.
    _EDITOR_DECISION_ENUM.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "image_candidates", sa.Column("editor_decision", _EDITOR_DECISION_ENUM, nullable=True)
    )
    op.add_column(
        "image_candidates", sa.Column("editor_decision_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_image_candidates_editor_decision", "image_candidates", ["editor_decision"]
    )


def downgrade() -> None:
    op.drop_index("ix_image_candidates_editor_decision", table_name="image_candidates")
    op.drop_column("image_candidates", "editor_decision_at")
    op.drop_column("image_candidates", "editor_decision")
    op.drop_column("image_candidates", "telegram_file_id")
    sa.Enum(name="image_editor_decision").drop(op.get_bind(), checkfirst=True)
