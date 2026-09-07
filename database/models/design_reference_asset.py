"""DIRECTOR-CONTROL-PLANE-1 §17-18: DesignReferenceAsset - canonical metadata for a visual
reference file already in the project (assets/brand/newsroom_visuals/...). Never auto-labels an
asset APPROVED (spec §17's own explicit "do not treat every image in assets/ as approved"
instruction, spec §29's own "ambiguous items -> NEEDS_FOUNDER_REVIEW, do not auto-label" rule) -
services/design_reference_registry.py::import_known_manifests() only ever sets a role when the
project's OWN existing manifest (assets/brand/newsroom_visuals/v1/manifests/overlays.yaml,
references/data/data_template_manifest.json) already states it explicitly; everything else lands
as NEEDS_FOUNDER_REVIEW."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class DesignReferenceRole(str, enum.Enum):
    APPROVED_REFERENCE = "approved_reference"
    REJECTED_REFERENCE = "rejected_reference"
    ACCOUNT_FEED_REFERENCE = "account_feed_reference"
    LAYOUT_REFERENCE = "layout_reference"
    TYPOGRAPHY_REFERENCE = "typography_reference"
    COLOR_REFERENCE = "color_reference"
    PROFILE_REFERENCE = "profile_reference"
    # Spec §18/§29/§43: the honest default for any asset the project's own manifests do not
    # explicitly classify - never silently promoted to APPROVED_REFERENCE.
    NEEDS_FOUNDER_REVIEW = "needs_founder_review"


class DesignReferenceAsset(Base):
    __tablename__ = "design_reference_assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    platform: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    presentation_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    asset_path: Mapped[str] = mapped_column(String(500), nullable=False, unique=True, index=True)
    reference_role: Mapped[DesignReferenceRole] = mapped_column(
        Enum(DesignReferenceRole, name="design_reference_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False, index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(300), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
