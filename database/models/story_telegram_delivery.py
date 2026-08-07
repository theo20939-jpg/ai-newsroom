"""StoryTelegramDelivery ORM model (Phase 18.10 M3): durable record of every attempted Telegram
delivery for a story-linked ContentDraft - a deliberately standalone table (same hot-path
reasoning as database/models/story_link.py / content_draft_story_link.py).

"A send is not successful unless telegram_message_id is persisted" (explicit requirement): the
CHECK constraint in the migration enforces this at the database level, not just in application
code - `delivery_status = 'sent'` is structurally impossible with a NULL `telegram_message_id`.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    """SQLAlchemy's `Enum(python_enum_cls)` stores each member's `.name` (e.g. "ROOT") by
    default, not `.value` ("root") - but the native Postgres enum types this table's own
    migration (0fac25b859455) created use the lowercase `.value` labels. `values_callable` makes
    the DB-stored/compared string match `.value`, exactly mirroring database/models/
    image_candidate_record.py's own established fix for the identical class of bug (a real,
    previously-undiscovered instance of it: story_telegram_deliveries.delivery_type/
    delivery_status were never exercised against a real migrated database until Phase 19 M7,
    since the integration tests that would have caught it were skipped pending this migration)."""
    return [member.value for member in enum_cls]


class DeliveryType(str, enum.Enum):
    """ROOT: the first message posted about a story (nothing to reply to yet). REPLY: a
    story-update message sent as a reply to that story's own root message."""

    ROOT = "root"
    REPLY = "reply"


class DeliveryStatus(str, enum.Enum):
    """SENT: the live Telegram call succeeded AND telegram_message_id was durably persisted -
    the only status that counts as "successful" per this phase's own explicit requirement.
    FAILED: the live Telegram call itself failed (TelegramAPIError) - never sent.
    UNCONFIRMED: the live Telegram call reported success, but persisting telegram_message_id
    failed immediately after (a real, physically-sent message this system cannot fully account
    for) - a distinct, honestly-labeled state, never silently upgraded to SENT.
    SKIPPED_REVIEW: fail-closed routing - an update with no discoverable root message was never
    sent at all, by design (see services/story_telegram_delivery.py::determine_reply_target())."""

    SENT = "sent"
    FAILED = "failed"
    UNCONFIRMED = "unconfirmed"
    SKIPPED_REVIEW = "skipped_review"


class StoryTelegramDelivery(Base):
    __tablename__ = "story_telegram_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stories.id"), nullable=False, index=True)
    content_draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_drafts.id"), nullable=False, index=True
    )
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reply_to_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    delivery_type: Mapped[DeliveryType] = mapped_column(
        Enum(DeliveryType, name="telegram_delivery_type", values_callable=_enum_values), nullable=False
    )
    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, name="telegram_delivery_status", values_callable=_enum_values), nullable=False
    )
    # Deterministic, derived from content_draft_id (services/story_telegram_delivery.py) - a
    # unique constraint enforces "at most one delivery attempt is ever recorded as authoritative
    # per draft," the DB-level backstop for "never send the same draft twice."
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
