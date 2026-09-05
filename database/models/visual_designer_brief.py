"""VISUAL-DESIGN-AUTONOMY-1, spec §6-8/§16-20: VisualDesignerBriefVersion - the persistent,
versioned creative brief given to the Visual Design Director (services/visual_design_director.py).
Distinct from a per-post creative prompt (services/visual_creative_direction.py's own
VisualCreativeDirection/prompt_text), which is expected to change on every call - this table only
ever changes rarely, gated by repeated-pattern evidence (services/visual_brief_adaptation_service.py).

`scope` is a plain string, not an enum (spec §8's own "prefer global identity + specialized scope
only where needed" - a caller is never forced to pre-declare every presentation type as its own
scope; "global" is the only scope this phase ever creates by default, and a caller may create
"NEWS"/"DATA"/etc. on demand without a schema change).

History is NEVER deleted (spec §20/§56) - SUPERSEDED/ROLLED_BACK/REJECTED rows remain queryable
forever; only one ACTIVE row may exist per scope at a time (enforced in
services/visual_designer_brief_service.py, not at the DB constraint level, mirroring
database/models/business_context_proposal.py's own "application-level single-active invariant,
not a partial unique index" precedent elsewhere in this codebase)."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class VisualDesignerBriefStatus(str, enum.Enum):
    ACTIVE = "active"
    CANDIDATE = "candidate"
    SUPERSEDED = "superseded"
    ROLLED_BACK = "rolled_back"
    REJECTED = "rejected"
    FROZEN = "frozen"


class VisualDesignerBriefVersion(Base):
    __tablename__ = "visual_designer_brief_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[VisualDesignerBriefStatus] = mapped_column(
        Enum(VisualDesignerBriefStatus, name="visual_designer_brief_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=VisualDesignerBriefStatus.CANDIDATE, index=True,
    )
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    brief_text: Mapped[str] = mapped_column(Text, nullable=False)

    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[int | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
