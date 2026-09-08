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

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID
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

    # DIRECTOR-CONTROL-PLANE-1C §13/§16/§19: non-secret profile-presentation + read-health metadata
    # cached from the last successful official read, so /accounts and the Directors can see the
    # real account state WITHOUT this table having any live-network side effect (§19: /accounts
    # performs 0 network calls). None of these is a secret: there is deliberately NO token / app-
    # secret column anywhere on this model (§7/§24 - the token lives only in settings.SecretStr and
    # is never persisted). Every column is nullable and additive (migration 4a1b7c9d2e3f).
    #
    # Why a migration was needed (§27): the pre-1C table stored only identity (ig_user_id/username)
    # + connection_state + last_sync_at. It had NO column for profile presentation (biography,
    # profile_picture_url, account_type), audience counts, per-capability detection results, or
    # read-health (last_successful_read_at / last_read_error / token status). §13 requires the
    # first group to reach Directors from cache and §19 requires all of it to render in /accounts
    # without a live call - neither is representable in the existing schema, and no generic
    # account-metadata store exists to reuse.
    biography: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_picture_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    account_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    followers_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    follows_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    media_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_successful_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # A short, curated, token-free string (InstagramReadError.code + safe detail) - never a raw
    # provider body.
    last_read_error: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # "VALID" | "EXPIRED" | "UNKNOWN" - derived from settings.instagram_access_token_expires_at,
    # never from the token itself.
    access_token_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # {"read_profile": "AVAILABLE", "read_media": "AVAILABLE", "read_insights": "UNAVAILABLE"} -
    # populated from a REAL probe by services/instagram_connection_service.py, never assumed (§14).
    capabilities: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
