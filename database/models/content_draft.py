"""ContentDraft ORM model."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class ContentType(str, enum.Enum):
    """Format of a generated content draft."""

    POST = "POST"
    SHORT = "SHORT"
    ANALYSIS = "ANALYSIS"
    MEME = "MEME"
    VIDEO_SCRIPT = "VIDEO_SCRIPT"


class ContentDraft(Base):
    """A generated content draft awaiting editorial review.

    The `status` values are not enumerated in the project documentation
    (docs/08, section 15), so it is stored as free-form text rather than
    a constrained enum to avoid inventing business rules.
    """

    __tablename__ = "content_drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("editorial_tasks.id"), nullable=False
    )
    type: Mapped[ContentType] = mapped_column(Enum(ContentType, name="content_type"), nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Phase 18.10 M4: no longer populated on new drafts (kept, nullable, for backward
    # compatibility with historical rows - see services/content_draft_service.py).
    hashtags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    # Phase 18.10 M3 (Telegram reply context): deliberately NOT added as a column on this model
    # yet - see database/models/news_event.py's own comment on the identical reasoning
    # (database/models/story_link.py::NewsEventStoryLink). Stage 6 introduces its own standalone
    # content_draft_story_links table when this is actually needed, rather than adding an unused
    # column now that would make every ContentDraft insert depend on an unapplied migration.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
