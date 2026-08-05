"""MemeConcept (Phase 18 M2): the creative concept a meme is built from, produced by
`capabilities/meme_concept_capability.py::MemeConceptCapability` (docs/
phase18_m2_meme_concept_report.md).

Mirrors `schemas/capability_definition.py`'s established "frozen, versioned Pydantic contract"
shape. Every field name is taken directly from the Phase 18 brief's own M2 list (premise/setup/
punchline/humor mechanism/visual scene/characters-objects/text overlay intent/source fact links/
forbidden interpretations/meme format) - no field invented beyond that list.

`source_fact_links` and `forbidden_interpretations` exist specifically so M3 (Safety &
Originality Gate) and a human editor can audit *why* the concept is grounded and what it must
never be read as - the brief's own "нельзя превращать неподтверждённый слух в факт ради шутки"
requirement is enforced downstream (M3), not by this schema alone; this schema only requires the
capability to *state* its grounding and exclusions, never silently omit them.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

MEME_CONCEPT_SCHEMA_VERSION = "v1"


class MemeFormat(str, Enum):
    """MVP note (docs/phase18_m0_meme_discovery_report.md §8/§10, M5's own "one visual format"
    requirement): every value is representable in this schema now (a concept should not be
    artificially constrained to formats M5/M6 cannot yet render), but only `CLASSIC_TOP_BOTTOM`
    has an implemented image-generation/render path as of M2 - `capabilities/meme_concept_
    capability.py`'s prompt instructs the model to prefer it unless the story genuinely demands
    otherwise; M5/M6 reject any other value until they are extended."""

    CLASSIC_TOP_BOTTOM = "classic_top_bottom"
    SINGLE_CAPTION = "single_caption"
    TWO_PANEL_CONTRAST = "two_panel_contrast"


class MemeConcept(BaseModel):
    """Frozen - a concept is a completed creative decision, never mutated in place. A
    regeneration (bounded by M7's quality gate / M2's own cost-discipline requirement) produces a
    brand-new `MemeConcept`, never edits an existing one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = MEME_CONCEPT_SCHEMA_VERSION
    premise: str = Field(min_length=1)
    setup: str = Field(min_length=1)
    punchline: str = Field(min_length=1)
    humor_mechanism: str = Field(min_length=1)
    visual_scene: str = Field(min_length=1)
    characters_objects: list[str] = Field(default_factory=list)
    text_overlay_intent: str = Field(min_length=1)
    source_fact_links: list[str] = Field(
        min_length=1,
        description="Verbatim or near-verbatim facts (from Research's own output) this concept "
        "is grounded in - never empty (the brief's own 'built on confirmed facts' requirement).",
    )
    forbidden_interpretations: list[str] = Field(
        default_factory=list,
        description="Explicit readings this concept must never be interpreted as - consumed by "
        "M3's Safety & Originality Gate as additional review context, never self-enforced here.",
    )
    meme_format: MemeFormat
