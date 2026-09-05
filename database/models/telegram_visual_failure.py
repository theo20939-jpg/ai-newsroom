"""NINJA Social Intelligence Foundation, Telegram Directors Phase 2 §19: TelegramVisualFailure -
promotes VisualFailureRecord (Phase 1, contract-only) to real persisted storage. One row per Art
Director shadow evaluation that found at least one issue (a clean PASS is not persisted here -
this table is specifically operational evidence of FAILURES/notes, not a log of every evaluation;
see services/telegram_art_director_vision.py for the full evaluation log if ever needed)."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class ArtDirectorDecisionEnum(str, enum.Enum):
    PASS = "pass"
    PASS_WITH_NOTES = "pass_with_notes"
    REWORK = "rework"
    BLOCK = "block"


class TelegramVisualFailure(Base):
    __tablename__ = "telegram_visual_failures"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    final_post_review_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    story_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    presentation_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    renderer_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    template: Mapped[str | None] = mapped_column(String(100), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    issue_codes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    art_director_decision: Mapped[ArtDirectorDecisionEnum] = mapped_column(
        Enum(ArtDirectorDecisionEnum, name="telegram_visual_failure_decision", values_callable=lambda e: [m.value for m in e]),
        nullable=False, index=True,
    )
    confidence: Mapped[float] = mapped_column(nullable=False, default=0.0)

    revision_action: Mapped[str | None] = mapped_column(String(50), nullable=True)
    revision_round: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolution_result: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
