"""SOCIAL-INTELLIGENCE-OPS-1, spec §21/§22/§23: TelegramContentCalendarItem - the real,
Telegram-specific calendar model /calendar previously had to honestly report as "not implemented".
Deliberately its OWN table (spec §21's own explicit "do NOT reuse InstagramContentCalendarItem
table - shared business truth, separate platform execution" instruction) - mirrors
database/models/instagram_calendar_item.py's own STATUS semantics and context-versioning fields
(depends_on_campaign_phase / planned_against_campaign_status / planned_against_campaign_phase)
exactly, since those are genuinely shared SEMANTICS, but is a structurally separate model with its
own Telegram-specific fields (content_role, surface_id) - never a shared row two platforms write to.

Reference columns (story_id/campaign_id/product_id/surface_id/director_run_id) are all nullable
with NO FK constraint except campaign_id/product_id (which DO reference real shared canonical
tables, matching database/models/instagram_calendar_item.py's own precedent) - story_id and
director_run_id mirror database/models/telegram_channel_memory.py's own "no FK, this table's own
purpose must survive independently of whether the referenced row still exists" convention."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class TelegramCalendarItemStatus(str, enum.Enum):
    ACTIVE = "active"
    STALE = "stale"
    INVALIDATED = "invalidated"
    RESCHEDULED = "rescheduled"
    DONE = "done"
    CANCELLED = "cancelled"


class TelegramContentRole(str, enum.Enum):
    NEWS = "news"
    UPDATE = "update"
    DATA = "data"
    QUOTE = "quote"
    RECAP = "recap"
    CAMPAIGN = "campaign"
    EVERGREEN = "evergreen"
    OTHER = "other"


class TelegramContentCalendarItem(Base):
    __tablename__ = "telegram_content_calendar_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    planned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[TelegramCalendarItemStatus] = mapped_column(
        Enum(TelegramCalendarItemStatus, name="telegram_calendar_item_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=TelegramCalendarItemStatus.ACTIVE, index=True,
    )

    story_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("launch_campaigns.id"), nullable=True, index=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=True, index=True
    )
    surface_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telegram_surfaces.id"), nullable=True, index=True
    )

    content_role: Mapped[TelegramContentRole] = mapped_column(
        Enum(TelegramContentRole, name="telegram_content_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    objective: Mapped[str] = mapped_column(String(50), nullable=False)
    presentation_hint: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_opportunity_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Context-versioning (spec §22/§27) - identical semantics to
    # database/models/instagram_calendar_item.py's own fields.
    business_context_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    depends_on_campaign_phase: Mapped[str | None] = mapped_column(String(50), nullable=True)
    planned_against_campaign_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    planned_against_campaign_phase: Mapped[str | None] = mapped_column(String(50), nullable=True)

    director_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    invalidation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
