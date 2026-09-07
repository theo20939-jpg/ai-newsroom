"""DIRECTOR-CONTROL-PLANE-1 §4/§6: InstagramAccount - the Instagram-side sibling of
database/models/telegram_surface.py::TelegramSurface, same shape/spirit (a real account is only
ever "ours" when a row here says so, never inferred). No row is ever inserted with a guessed/
fabricated Instagram user id (mirrors TelegramSurface's own "never a guessed/hardcoded chat_id"
rule) - this table starts empty and stays empty until a real operator connects a real NINJA PULSE
professional/business/creator account through an explicit future write path (out of scope here,
spec §6's own "if actual credentials are not currently available, implement the adapter/config/
readiness layer and return CONNECTION_REQUIRED - do not block the rest of the architecture").

Deliberately NOT merged into TelegramSurface (different platform, different native id shape,
different capability vocabulary) - spec §4's own "shared Directors receive one normalized context
layer while platform-specific adapters retain native fields" instruction is implemented by
services/platform_account_context.py building a PlatformAccountContext FROM this table, never by
forcing Telegram/Instagram into one physical table."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class InstagramAccountRole(str, enum.Enum):
    OWNED_BRAND_ACCOUNT = "owned_brand_account"
    OTHER = "other"


class InstagramConnectionState(str, enum.Enum):
    NOT_CONNECTED = "not_connected"
    CONNECTED = "connected"
    ERROR = "error"


class InstagramAccount(Base):
    __tablename__ = "instagram_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Instagram Graph API's own numeric IG user id - a plain string (never assumed int-sized),
    # nullable because a row may be pre-registered (role/name known) before a real connection
    # test has ever resolved the platform's own id (spec §6's own CONNECTION_REQUIRED case).
    ig_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role: Mapped[InstagramAccountRole] = mapped_column(
        Enum(InstagramAccountRole, name="instagram_account_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False, index=True,
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    connection_state: Mapped[InstagramConnectionState] = mapped_column(
        Enum(InstagramConnectionState, name="instagram_connection_state", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=InstagramConnectionState.NOT_CONNECTED,
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Mirrors TelegramSurface.analytics_enabled exactly - "a real, correctly-owned account may
    # still not be opted into feeding performance learning yet" (spec §38/§39's own launch-boundary
    # caution applies identically here).
    analytics_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
