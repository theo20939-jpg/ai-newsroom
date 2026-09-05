"""INSTAGRAM-GROWTH-3, item 2/12: persisted Reference Deconstruction. `must_not_copy` is
NOT NULL/non-empty at the application layer (services/instagram_reference_deconstruction.py's own
`ReferenceDeconstruction.__post_init__` already enforces this for the in-memory dataclass; the
persistence service re-validates before insert, since a DB CHECK constraint cannot easily express
"JSON array is non-empty" portably) - the system learns mechanics, it never stores permission to
reproduce a reference's actual expression."""
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class InstagramReferenceDeconstruction(Base):
    __tablename__ = "instagram_reference_deconstructions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reference_description: Mapped[str] = mapped_column(Text, nullable=False)

    hook_mechanics: Mapped[str | None] = mapped_column(Text, nullable=True)
    pacing: Mapped[str | None] = mapped_column(Text, nullable=True)
    scene_structure: Mapped[str | None] = mapped_column(Text, nullable=True)
    narrative_progression: Mapped[str | None] = mapped_column(Text, nullable=True)
    typography_behavior: Mapped[str | None] = mapped_column(Text, nullable=True)
    visual_rhythm: Mapped[str | None] = mapped_column(Text, nullable=True)
    editing_rhythm: Mapped[str | None] = mapped_column(Text, nullable=True)
    cta_mechanics: Mapped[str | None] = mapped_column(Text, nullable=True)
    interaction_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)

    what_appears_effective: Mapped[list | None] = mapped_column(JSON, nullable=True)
    why_hypothesis_only: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Enforced non-empty by services/instagram_reference_deconstruction_memory.py before insert -
    # never relaxed here even though the column itself is technically nullable JSON.
    must_not_copy: Mapped[list] = mapped_column(JSON, nullable=False)
    originality_constraints: Mapped[list | None] = mapped_column(JSON, nullable=True)

    ai_assisted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
