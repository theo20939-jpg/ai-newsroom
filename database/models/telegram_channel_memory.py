"""NINJA Social Intelligence Foundation, Part III §39: TelegramChannelMemory - one row per real
channel post. References existing canonical IDs (content_draft_id/story_id/event_id/campaign_id)
rather than duplicating their data (spec §39's own "Do not duplicate existing canonical data
unnecessarily" instruction) - all nullable UUID columns with no FK constraint, since this table's
own purpose (feed-strategy/performance memory) must survive independently of whether the
referenced row still exists, and must not force a migration-ordering dependency on tables owned by
other subsystems.

The ONE new DB table this platform branch introduces - services/telegram_feed_state.py's own
FeedState derivation reads directly from this table. Everything else in Part III
(EditorialNeed/ChannelDirectorResult/ArtDirectorResult/RevisionAction/VisualFailureRecord/
PerformancePattern) is a plain dataclass/contract, not yet persisted - see this phase's own final
report for the honest scope line between "real" and "contract only"."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class StoryRole(str, enum.Enum):
    FIRST = "first"
    UPDATE = "update"
    FOLLOW_UP = "follow_up"
    RECAP = "recap"


class TelegramChannelMemory(Base):
    __tablename__ = "telegram_channel_memory"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    post_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_draft_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    story_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    topics: Mapped[list | None] = mapped_column(JSON, nullable=True)
    entities: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str | None] = mapped_column(String(300), nullable=True)

    presentation_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    visual_family: Mapped[str | None] = mapped_column(String(100), nullable=True)
    template: Mapped[str | None] = mapped_column(String(100), nullable=True)
    renderer_version: Mapped[str | None] = mapped_column(String(50), nullable=True)

    headline: Mapped[str | None] = mapped_column(String(500), nullable=True)
    story_role: Mapped[StoryRole | None] = mapped_column(
        Enum(StoryRole, name="telegram_channel_memory_story_role", values_callable=lambda e: [m.value for m in e]),
        nullable=True,
    )
    content_objective: Mapped[str | None] = mapped_column(String(100), nullable=True)

    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    experiment_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    performance_snapshots: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
