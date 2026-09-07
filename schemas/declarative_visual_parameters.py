"""DIRECTOR-CONTROL-PLANE-1 §20/§22/§52: DeclarativeVisualParameters - the validated schema a
Visual Director CANDIDATE spec's own `parameters` field must satisfy before
services/design_spec_registry.py will ever persist it. Pydantic, `extra="forbid"`: only the
explicitly declared fields below can ever be set - there is no way to smuggle a code string, a
shell command, a filesystem path, or a dynamic import target through this schema (spec §22's own
hard boundary), since Pydantic parses only declared, typed fields and rejects anything else.

Only parameters judged safe and semantically meaningful are exposed (spec §20's own "do not
blindly externalize every renderer constant" instruction) - this is deliberately a SUBSET of
services/nnj_master_news_overlay.py's/services/brand_renderer.py's own real constants, not a
mirror of every internal fraction. Ranges are bounded to values that cannot produce a broken/
illegible render (e.g. a font size of 2px or a negative margin), not merely "any float"."""
from __future__ import annotations

import enum

from pydantic import BaseModel, ConfigDict, Field


class Alignment(str, enum.Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class PlacementZone(str, enum.Enum):
    LOWER_RIGHT = "lower_right"
    LOWER_LEFT = "lower_left"
    UPPER_RIGHT = "upper_right"
    UPPER_LEFT = "upper_left"


class ScrimTreatment(str, enum.Enum):
    NONE = "none"
    LIGHT = "light"
    STRONG = "strong"


class SourceImageTreatment(str, enum.Enum):
    PRESERVE = "preserve"
    RECOMPOSE = "recompose"
    CROP = "crop"


class PresentationMode(str, enum.Enum):
    """Spec §25's own three DATA modes, reused verbatim here so a Design Spec candidate can express
    a presentation-mode preference through the SAME validated vocabulary services/
    data_source_classification.py::DataPresentationMode defines - see that module for the real
    enforcement path; this field is advisory input to it, never a second competing definition."""

    FULL_DATA_CARD = "full_data_card"
    MINIMAL_SOURCE_PRESERVING = "minimal_source_preserving"
    NO_OVERLAY_SAFETY = "no_overlay_safety"


class DeclarativeVisualParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    font_size_max: int | None = Field(default=None, ge=20, le=200)
    font_size_min: int | None = Field(default=None, ge=12, le=120)
    max_line_count: int | None = Field(default=None, ge=1, le=10)
    text_box_width_frac: float | None = Field(default=None, ge=0.1, le=1.0)
    safe_margin_frac: float | None = Field(default=None, ge=0.0, le=0.3)
    alignment: Alignment | None = None
    placement_zone: PlacementZone | None = None
    logo_zone: PlacementZone | None = None
    scrim_treatment: ScrimTreatment | None = None
    scrim_opacity: float | None = Field(default=None, ge=0.0, le=1.0)
    metric_placement: PlacementZone | None = None
    caption_placement: Alignment | None = None
    source_image_treatment: SourceImageTreatment | None = None
    presentation_mode: PresentationMode | None = None
