"""CROSS-PLATFORM-MEDIA-RESEARCH-SELECTION-1 section 3: `MediaIntent` - a structured statement of
what a piece of content actually needs a visual to depict, produced BEFORE any candidate is
discovered, scored, or selected. Mirrors `schemas/image_candidate.py`'s own "adapters only know how
to produce this shape" discipline: nothing here is Instagram- or Telegram-specific, and nothing
here is hardcoded to any one story - every field is filled in by whatever caller (an Instagram
carousel planner, a Telegram NEWS post, a future platform) actually has that information.

Why this exists (section 0/1's own root-cause framing): the existing Image Intelligence pipeline
(services/image_relevance.py, Phase 16 M4) ranks candidates by provenance/lexical-overlap - "how
confidently is this image tied to the original publication" - and explicitly, by its own docstring,
never asks "does it depict the exact subject." `MediaIntent` is the missing structured input that
makes that second question askable at all: without a `product_name`/`model_name` to check against,
no amount of ranking can tell "a photo of an ordinary iPhone" apart from "a photo of the specific
newly-announced foldable iPhone" - both are, lexically, "an iPhone photo."""
from __future__ import annotations

import enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MediaSubjectType(str, enum.Enum):
    PRODUCT = "product"
    PERSON = "person"
    EVENT = "event"
    PLACE = "place"
    SCREENSHOT_OR_INTERFACE = "screenshot_or_interface"
    CONCEPT = "concept"  # no single concrete real-world subject (e.g. "AI regulation") - imagery
    # for this type is expected to be contextual/graphic by construction, never "exact."


class DesiredVisualType(str, enum.Enum):
    PRODUCT_PHOTO = "product_photo"
    PRESS_PHOTO = "press_photo"
    PORTRAIT = "portrait"
    EVENT_PHOTO = "event_photo"
    SCREENSHOT = "screenshot"
    CHART_OR_DIAGRAM = "chart_or_diagram"
    LOGO_OR_BRAND_MARK = "logo_or_brand_mark"
    GRAPHIC_LAYOUT = "graphic_layout"  # an intentional no-photo treatment, not a discovery target


class OrientationPreference(str, enum.Enum):
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"
    SQUARE = "square"
    ANY = "any"


class FreshnessRequirement(str, enum.Enum):
    """How strictly a candidate's own age matters, independent of the story's age - a product
    photo for a brand-new device should usually be recent; a historical-context photo may not
    need to be."""

    MUST_BE_CURRENT = "must_be_current"  # e.g. the exact announced product - an old photo of a
    # DIFFERENT generation is a mismatch, not merely "stale"
    PREFER_RECENT = "prefer_recent"
    NOT_TIME_SENSITIVE = "not_time_sensitive"


class MediaIntent(BaseModel):
    """One structured media need. `primary_entity` is the single most important field - the exact
    thing the image must (or must not, falsely) depict; every other identity field narrows it
    further. `must_not_imply` is a list of specific false impressions a selected image must never
    create (section 0's own "never silently imply that an unrelated product image depicts the
    subject") - not a generic safety list, always specific to this intent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject_type: MediaSubjectType
    primary_entity: str = Field(min_length=1, max_length=200)

    product_name: str | None = Field(default=None, max_length=200)
    model_name: str | None = Field(default=None, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    person: str | None = Field(default=None, max_length=200)
    event: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    time_context: str | None = Field(default=None, max_length=200)  # e.g. "announced 2026-09-09"

    desired_visual_type: DesiredVisualType
    slide_role: str | None = Field(default=None, max_length=50)  # e.g. "hook", "comparison" - the
    # carousel/card role this image would fill, informational for scoring only

    must_show: list[str] = Field(default_factory=list, max_length=10)
    must_not_imply: list[str] = Field(default_factory=list, max_length=10)

    orientation_preference: OrientationPreference = OrientationPreference.ANY
    platform: Literal["instagram", "telegram", "generic"] = "generic"
    freshness_requirement: FreshnessRequirement = FreshnessRequirement.PREFER_RECENT

    # Free-text context a query-generator/vision-classifier can use verbatim - never a substitute
    # for the structured fields above, but useful for genuinely ambiguous cases.
    context_summary: str | None = Field(default=None, max_length=1000)

    @property
    def identity_terms(self) -> list[str]:
        """The real, non-empty identity fields, in specificity order (most exact first) - the
        single list every query-generator and subject-match prompt should anchor on."""
        ordered = [self.model_name, self.product_name, self.person, self.event, self.company]
        return [t for t in ordered if t]
