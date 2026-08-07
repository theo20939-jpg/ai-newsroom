"""add media vision reviews table

Revision ID: 94fd27f7d129
Revises: f2654fa00185
Create Date: 2026-08-07 00:00:00.000000

Phase 19 M13 (docs/phase19_m13_vision_review.md): one new, purely additive, standalone table -
`media_vision_reviews`. Surrogate PK (not PK-reuse) since a given image candidate could in
principle be reviewed more than once. `image_candidates` is not altered.

Depends on: `media_vision_review_mode` (core/config.py). Written but NOT applied as part of
Phase 19's implementation, per explicit instruction (migration design only - the user applies it
separately).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "94fd27f7d129"
down_revision: Union[str, None] = "f2654fa00185"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "media_vision_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("image_candidate_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("image_candidates.id"), nullable=False),
        sa.Column("relevant_to_story", sa.Boolean(), nullable=False),
        sa.Column("source_logo_present", sa.Boolean(), nullable=False),
        sa.Column("watermark_present", sa.Boolean(), nullable=False),
        sa.Column("website_or_social_ui_present", sa.Boolean(), nullable=False),
        sa.Column("advertisement_or_banner_present", sa.Boolean(), nullable=False),
        sa.Column("readable_quality", sa.String(length=16), nullable=False),
        sa.Column("recommended_role", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_media_vision_reviews_image_candidate_id", "media_vision_reviews", ["image_candidate_id"])


def downgrade() -> None:
    op.drop_index("ix_media_vision_reviews_image_candidate_id", table_name="media_vision_reviews")
    op.drop_table("media_vision_reviews")
