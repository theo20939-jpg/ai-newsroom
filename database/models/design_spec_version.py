"""DIRECTOR-CONTROL-PLANE-1 §16/§20-21: DesignSpecVersion - the canonical Design Spec Registry.
Status vocabulary DELIBERATELY mirrors database/models/visual_designer_brief.py::
VisualDesignerBriefStatus value-for-value (spec §16's own "reuse existing VisualDesignerBriefVersion
semantics where appropriate" instruction) - kept as its own enum rather than importing that one
directly, matching this codebase's own established per-table enum-duplication convention (e.g.
database/models/telegram_visual_failure.py::ArtDirectorDecisionEnum vs. services/
telegram_art_director.py::ArtDirectorDecision) so this table's own migration/lifecycle never
couples to VisualDesignerBriefVersion's.

ONE table serves BOTH spec §16 (reference-direction specs: platform/surface/presentation-type
design boards) AND spec §20-21 (declarative rendering PARAMETERS) - both need the identical
version/status/supersedes lifecycle, and spec §16's own "avoid duplicate version systems" applies
just as much to these two concepts as it does to VisualDesignerBriefVersion. `spec_type`
distinguishes them; `parameters` (validated via schemas/declarative_visual_parameters.py) is only
ever populated for spec_type=declarative_visual_params."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Enum, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class DesignSpecStatus(str, enum.Enum):
    ACTIVE = "active"
    CANDIDATE = "candidate"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    FROZEN = "frozen"


class DesignSpecType(str, enum.Enum):
    DESIGN_DIRECTION_REFERENCE = "design_direction_reference"
    DECLARATIVE_VISUAL_PARAMS = "declarative_visual_params"
    ACCOUNT_PRESENTATION = "account_presentation"


class DesignSpecVersion(Base):
    __tablename__ = "design_spec_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    platform: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    surface: Mapped[str | None] = mapped_column(String(50), nullable=True)
    presentation_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    spec_type: Mapped[DesignSpecType] = mapped_column(
        Enum(DesignSpecType, name="design_spec_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False, index=True,
    )
    # Groups versions the same way VisualDesignerBriefVersion.scope does - "only one ACTIVE row per
    # scope at a time" (enforced in services/design_spec_registry.py, application-level, mirroring
    # that table's own identical precedent, never a DB constraint). Distinct from `spec_type`:
    # e.g. spec_type=declarative_visual_params may have separate scopes per presentation_type.
    scope: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[DesignSpecStatus] = mapped_column(
        Enum(DesignSpecStatus, name="design_spec_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=DesignSpecStatus.CANDIDATE, index=True,
    )
    supersedes: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    source_asset_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Validated via schemas/declarative_visual_parameters.py::DeclarativeVisualParameters before
    # ever being written here (services/design_spec_registry.py's own only write path) - never an
    # arbitrary dict accepted straight from a Director's own free text.
    parameters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    active_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
