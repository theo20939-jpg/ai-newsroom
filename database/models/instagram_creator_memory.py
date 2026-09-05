"""INSTAGRAM-GROWTH-3, item 2/15: minimal, honest Creator Radar persistence - "only promote beyond
contract level if it can be done honestly without credentials or invented data" (item 15). This
records MANUAL observations only (mirrors database/models/competitor.py::ObservationSource's own
MANUAL/PUBLIC_DATA_IMPORT/UNKNOWN discipline) - no scraping, no discovery API, no invented audience
numbers. `evidence` is required free text; there is no numeric "follower_count"/"engagement_rate"
column here precisely because this codebase has no honest way to observe one yet
(services/instagram_platform_capabilities.py::"creator_discovery" is UNKNOWN)."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class CreatorObservationSource(str, enum.Enum):
    MANUAL = "manual"
    PUBLIC_DATA_IMPORT = "public_data_import"


class InstagramCreatorObservation(Base):
    __tablename__ = "instagram_creator_observations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    handle: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False, default="instagram")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    observation_source: Mapped[CreatorObservationSource] = mapped_column(
        Enum(CreatorObservationSource, name="instagram_creator_observation_source", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=CreatorObservationSource.MANUAL,
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.2)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
