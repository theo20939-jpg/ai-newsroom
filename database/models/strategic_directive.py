"""NINJA Social Intelligence Foundation, Part I §12/§14: StrategicDirective - explicit human
business intent that takes precedence over platform-level optimization (§14 precedence tier 1).
`scope`/`products`/`platforms` let a directive be as narrow ("VPN, Telegram only") or broad ("all
products, all platforms") as the founder actually said - never inferred beyond that."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Enum, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class DirectiveStatus(str, enum.Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


class StrategicDirective(Base):
    """One row per founder/high-authority directive. `products`/`platforms` are plain JSON string
    lists (product slugs / platform names) rather than FK join tables - a directive is a scoped
    instruction, not a structural relationship the way ProductEvent.product_id is."""

    __tablename__ = "strategic_directives"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str | None] = mapped_column(String(300), nullable=True)
    products: Mapped[list | None] = mapped_column(JSON, nullable=True)
    platforms: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="telegram")
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[DirectiveStatus] = mapped_column(
        Enum(DirectiveStatus, name="directive_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=DirectiveStatus.ACTIVE, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
