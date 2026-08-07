"""MediaVisionReview ORM model (Phase 19 M13).

A standalone table, surrogate PK (not PK-reuse) - a review is produced once per manual harness
invocation, and a given image candidate could in principle be reviewed more than once (e.g. a
re-run after a prompt update), so this is 1:many against `image_candidates`, mirroring
`content_draft_editorial_plans`' own surrogate-PK convention. `image_candidates` itself is not
altered.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class MediaVisionReview(Base):
    __tablename__ = "media_vision_reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("image_candidates.id"), nullable=False, index=True
    )
    relevant_to_story: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source_logo_present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    watermark_present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    website_or_social_ui_present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    advertisement_or_banner_present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    readable_quality: Mapped[str] = mapped_column(String(16), nullable=False)
    recommended_role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
