"""SOCIAL-INTELLIGENCE-INTEGRATION-1, spec §14/§15: TelegramSurface - corrects the semantic issue
Telegram Directors Phase 2 left open (services/telegram_own_channel.py's own docstring already
names it: `owned_chat_id()` falls back to `newsroom_telegram_chat_id`, the INTERNAL editorial
supergroup, whenever no distinct `telegram_owned_channel_id` is configured - so "our own channel"
and "the internal newsroom chat" are silently the same thing today unless a founder configures
otherwise). This table makes that distinction EXPLICIT and queryable: a chat is only ever a real
public audience surface when a row here says so, with `role` naming exactly which kind.

CRITICAL (spec §15, mandatory): only `PUBLIC_*` roles may ever feed audience Growth/Strategy
performance learning by default - services/telegram_surface_registry.py::
list_public_analytics_surfaces() is the ONE function that draws this line, and every console/
performance consumer must call it rather than re-deriving "is this a public surface" itself.

No row is ever inserted here with a guessed/hardcoded chat_id (spec §14's own explicit
instruction) - this table starts empty and stays empty until a real operator configures a real
surface through a future write path (out of scope for this read-only console phase)."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class TelegramSurfaceRole(str, enum.Enum):
    INTERNAL_EDITORIAL = "internal_editorial"
    PUBLIC_NEWS_CHANNEL = "public_news_channel"
    PUBLIC_GAMING_CHANNEL = "public_gaming_channel"
    PUBLIC_PRODUCT_CHANNEL = "public_product_channel"
    OTHER = "other"


PUBLIC_SURFACE_ROLES = frozenset({
    TelegramSurfaceRole.PUBLIC_NEWS_CHANNEL, TelegramSurfaceRole.PUBLIC_GAMING_CHANNEL,
    TelegramSurfaceRole.PUBLIC_PRODUCT_CHANNEL,
})


class TelegramSurface(Base):
    __tablename__ = "telegram_surfaces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role: Mapped[TelegramSurfaceRole] = mapped_column(
        Enum(TelegramSurfaceRole, name="telegram_surface_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # A surface may be a real, correctly-classified PUBLIC_* surface yet still not be opted into
    # feeding performance learning (e.g. newly added, not yet trusted) - `role` alone is necessary
    # but not sufficient; spec §15's gate checks BOTH.
    analytics_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
