"""INSTAGRAM-TELEGRAM-EDITORIAL-DELIVERY-1 §21/§22: durable identity for "this Instagram package
version has been delivered to the Telegram editorial topic" - distinct from
`database/models/instagram_publication_job.py::InstagramPublicationJob`, which tracks the SEPARATE
(and, this phase, entirely unused) real-Instagram-publish lifecycle. Nothing in this module ever
reads or writes an `InstagramPublicationJob` row, and nothing here makes any Instagram API call.

One row per package VERSION. `package_identity` is stable across regenerations of the same
underlying story/opportunity (never the package's own random `package_id`, exactly the same
reasoning `instagram_publication_state.py::compute_idempotency_key()` already established);
`version` increments by one on every explicit regeneration. A partial unique index on
`(package_identity)` WHERE state is "current" (not yet superseded by a newer version) is the real,
DB-enforced guarantee behind §21's `DUPLICATE_TELEGRAM_PACKAGE_SENDS=0` and §12's "a regenerated
package must not silently overwrite editor context" - the SAME concurrency-safety pattern
`instagram_publication_job.py` and `recovery_job.py` already established, reused verbatim rather
than reinvented."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class InstagramEditorialDeliveryState(str, enum.Enum):
    """§10/§12's required distinctions - a small, closed vocabulary, never a second competing one."""

    PENDING = "PENDING"  # created, not yet successfully delivered to Telegram
    DELIVERED = "DELIVERED"  # media + control message sent to the instagram topic
    APPROVED = "APPROVED"  # editor pressed "Принять" - READY_FOR_MANUAL_PUBLICATION, terminal for THIS version
    REGENERATING_FULL = "REGENERATING_FULL"  # "Переделать" in progress - double-submit guard
    REGENERATING_TEXT = "REGENERATING_TEXT"  # "Текст" in progress
    REGENERATING_VISUAL = "REGENERATING_VISUAL"  # "Визуал" in progress
    SUPERSEDED = "SUPERSEDED"  # a newer version of the same package_identity now exists
    HOLD = "HOLD"  # QA gate returned HOLD - never delivered as if ready
    BLOCK = "BLOCK"  # QA gate returned BLOCK - never delivered as if ready


_REGENERATING_STATES = (
    InstagramEditorialDeliveryState.REGENERATING_FULL.value,
    InstagramEditorialDeliveryState.REGENERATING_TEXT.value,
    InstagramEditorialDeliveryState.REGENERATING_VISUAL.value,
)
_CURRENT_STATES = (
    InstagramEditorialDeliveryState.PENDING.value,
    InstagramEditorialDeliveryState.DELIVERED.value,
    InstagramEditorialDeliveryState.APPROVED.value,
    *_REGENERATING_STATES,
    InstagramEditorialDeliveryState.HOLD.value,
    InstagramEditorialDeliveryState.BLOCK.value,
)
"""Every state except SUPERSEDED - the partial unique index enforces "at most one non-superseded
row per package_identity" (i.e. at most one CURRENT version), which is exactly the invariant a
regenerate action must maintain: creating version N+1 must supersede version N in the same
transaction, never leave two rows simultaneously claiming to be current."""


class InstagramEditorialDelivery(Base):
    __tablename__ = "instagram_editorial_deliveries"
    __table_args__ = (
        Index(
            "ix_instagram_editorial_deliveries_current_identity", "package_identity",
            unique=True, postgresql_where=text(f"state IN ({', '.join(repr(s) for s in _CURRENT_STATES)})"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    package_identity: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_story_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_format: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[InstagramEditorialDeliveryState] = mapped_column(
        Enum(InstagramEditorialDeliveryState, name="instagram_editorial_delivery_state"), nullable=False,
        default=InstagramEditorialDeliveryState.PENDING, index=True,
    )

    # Telegram delivery coordinates - enough to edit/reply/dedupe without a second Telegram call.
    # `telegram_chat_id`/`decided_by_telegram_user_id` are BigInteger, not Integer: a real
    # supergroup chat id (e.g. -1004297182444) and a modern Telegram user id both routinely exceed
    # int32 range - confirmed the hard way, by a real asyncpg OverflowError during the production
    # canary (INSTAGRAM-TELEGRAM-EDITORIAL-DELIVERY-PRODUCTION-CANARY-1 §12), after the real
    # Telegram send had already succeeded. `telegram_topic_id`/message ids stay Integer - topic and
    # message ids are small, sequential, per-chat counters, never anywhere near int32 range.
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_topic_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    media_message_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    control_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # The final editorial package, snapshotted at delivery time - enough for a button handler to
    # act (approve / re-render a caption-only or visual-only regeneration) without re-deriving
    # strategy from scratch. Plain JSON only, never a live ORM/pydantic instance (mirrors
    # InstagramContentPackage.to_dict()'s own established convention).
    package_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)

    decided_by_telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
