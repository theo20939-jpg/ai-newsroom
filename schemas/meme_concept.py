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


# MEME PRODUCTION PIPELINE (overnight phase): `MemeFormat`'s original 3-value closed enum is
# retired in favor of a free-text `meme_format: str` field on `MemeConcept` below - the explicit
# product requirement is format DIVERSITY ("do not hardcode this as a closed list"), and M5/M6's
# own real rendering mechanics never actually depended on the *enum value* itself: `services.
# meme_image_generation.py::build_image_prompt()` only ever reads `concept.visual_scene`/
# `.characters_objects` (free text, already model-authored), and `services.meme_render.py::
# render_meme()` only ever overlays `MemeCopy.top_text`/`.bottom_text` in fixed top/bottom bands
# regardless of what the underlying generated image depicts. A "two-panel Drake-style comparison"
# or "fake corporate presentation" concept is therefore already fully renderable TODAY through the
# exact same unmodified image-generation + text-overlay mechanics that "classic_top_bottom" always
# used - the format diversity lives entirely in the DESCRIBED visual scene (what the image model
# is asked to depict) and the joke structure, never in a distinct Python rendering template per
# format. `MemeFormat` is kept as a class (not deleted) purely to preserve any existing import
# call site's ability to reference a few well-known example values by name; it is no longer used
# as a Pydantic field type anywhere.
class MemeFormat(str, Enum):
    """A short, NON-exhaustive list of example format names for prompt guidance only - the actual
    `MemeConcept.meme_format` field is free text (below), so the model may name any format,
    including ones not listed here. Never validated against this enum at the schema level."""

    CLASSIC_TOP_BOTTOM = "classic_top_bottom"
    SINGLE_CAPTION = "single_caption"
    TWO_PANEL_CONTRAST = "two_panel_contrast"
    REACTION_MEME = "reaction_meme"
    FAKE_SCREENSHOT_CHAT = "fake_screenshot_chat"
    WOJAK_STYLE = "wojak_style"
    DRAKE_COMPARISON = "drake_comparison"
    FOUR_PANEL_ESCALATION = "four_panel_escalation"
    FAKE_CORPORATE_PRESENTATION = "fake_corporate_presentation"
    FAKE_PRODUCT_AD = "fake_product_ad"
    ABSURD_PHOTOREALISTIC_SCENE = "absurd_photorealistic_scene"
    GAMING_HUD = "gaming_hud"
    NOTIFICATION_UI_PARODY = "notification_ui_parody"
    ANIME_REACTION = "anime_reaction"
    NEWS_SCREENSHOT_PARODY = "news_screenshot_parody"
    MINIMALIST_TEXT_MEME = "minimalist_text_meme"
    SURREAL_VISUAL_METAPHOR = "surreal_visual_metaphor"


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
    # MEME PRODUCTION PIPELINE: free text, not `MemeFormat` (see that class's own updated
    # docstring for why) - a short format/style label the model itself names (e.g.
    # "drake_comparison", "fake_screenshot_chat", or a genuinely new one it invents), never
    # validated against a closed list. `services/meme_diversity.py` reads this field verbatim from
    # recent MemeCandidate rows to build the recent-repetition-avoidance context fed back into the
    # next concept-generation call - a free-text field lets that diversity signal track whatever
    # format vocabulary the model actually uses over time, rather than being capped at whatever
    # enum values existed when this schema was written.
    meme_format: str = Field(min_length=1, max_length=64)
