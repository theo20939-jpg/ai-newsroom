"""INSTAGRAM-GROWTH-3, item 4: Instagram Creative Director output schemas - mirrors
schemas/meme_copy.py's own discipline exactly (frozen, `extra="forbid"`, length ceilings enforced
structurally rather than left to prompt-only discretion). `evidence_used` on every schema is the
grounding mechanism spec item 5 requires: services/instagram_creative_director.py::
assert_evidence_grounded() rejects a draft whose `evidence_used` contains anything the caller did
not explicitly supply as allowed evidence - the Creative Director may transform PRESENTATION, it
may never invent a fact."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

INSTAGRAM_CREATIVE_SCHEMA_VERSION = "v1"

_SHORT_TEXT_MAX_LENGTH = 200
_MEDIUM_TEXT_MAX_LENGTH = 400
_LONG_TEXT_MAX_LENGTH = 1200


class InstagramSingleCreative(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = INSTAGRAM_CREATIVE_SCHEMA_VERSION
    creative_angle: str = Field(min_length=1, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    visual_concept: str = Field(min_length=1, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    on_image_copy: str = Field(min_length=1, max_length=_SHORT_TEXT_MAX_LENGTH)
    caption_direction: str = Field(min_length=1, max_length=_LONG_TEXT_MAX_LENGTH)
    # Optional in Python for old stored/test creative rows; required by the versioned live prompt.
    final_caption: str | None = Field(default=None, max_length=_LONG_TEXT_MAX_LENGTH)
    source_subject: str | None = Field(default=None, max_length=_SHORT_TEXT_MAX_LENGTH)
    cta: str | None = Field(default=None, max_length=_SHORT_TEXT_MAX_LENGTH)
    asset_requirements: list[str] = Field(default_factory=list)
    evidence_used: list[str] = Field(default_factory=list)


class InstagramCarouselSlideCreative(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str = Field(min_length=1, max_length=50)
    slide_copy: str = Field(min_length=1, max_length=_SHORT_TEXT_MAX_LENGTH)
    visual_direction: str = Field(min_length=1, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    source_evidence: str | None = Field(default=None, max_length=_MEDIUM_TEXT_MAX_LENGTH)


class InstagramCarouselCreative(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = INSTAGRAM_CREATIVE_SCHEMA_VERSION
    objective: str = Field(min_length=1, max_length=50)
    slides: list[InstagramCarouselSlideCreative] = Field(min_length=2)
    final_cta: str | None = Field(default=None, max_length=_SHORT_TEXT_MAX_LENGTH)
    evidence_used: list[str] = Field(default_factory=list)

    @property
    def hook_slide(self) -> InstagramCarouselSlideCreative:
        return self.slides[0]


class InstagramReelSceneCreative(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    start_seconds: int = Field(ge=0, le=180)
    end_seconds: int = Field(gt=0, le=180)
    spoken_line: str = Field(min_length=1, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    on_screen_text: str | None = Field(default=None, max_length=_SHORT_TEXT_MAX_LENGTH)
    visual_direction: str = Field(min_length=1, max_length=_MEDIUM_TEXT_MAX_LENGTH)


class InstagramReelCreative(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = INSTAGRAM_CREATIVE_SCHEMA_VERSION
    objective: str = Field(min_length=1, max_length=50)
    hook: str = Field(min_length=1, max_length=_SHORT_TEXT_MAX_LENGTH)
    target_duration_seconds: int = Field(gt=0, le=180)
    scene_sequence: list[str] = Field(min_length=1)
    shot_list: list[str] = Field(default_factory=list)
    voiceover_script: str | None = Field(default=None, max_length=_LONG_TEXT_MAX_LENGTH)
    on_screen_text: list[str] = Field(default_factory=list)
    b_roll_requirements: list[str] = Field(default_factory=list)
    pacing: str = Field(min_length=1, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    audio_direction: str | None = Field(default=None, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    cta: str | None = Field(default=None, max_length=_SHORT_TEXT_MAX_LENGTH)
    loop_ending_concept: str | None = Field(default=None, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    caption_direction: str = Field(min_length=1, max_length=_LONG_TEXT_MAX_LENGTH)
    evidence_used: list[str] = Field(default_factory=list)
    # INSTAGRAM-CONTENT-STRATEGY-V2 Phase 3: optional/defaulted, so every pre-existing construction
    # call site (real and test) stays byte-identical. `visual_direction` mirrors
    # InstagramCarouselSlideCreative.visual_direction's own field name/concept above;
    # `asset_requirements` mirrors InstagramSingleCreative.asset_requirements's own field above -
    # reused naming conventions, not invented ones.
    visual_direction: str | None = Field(default=None, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    asset_requirements: list[str] = Field(default_factory=list)
    # TREND-origin Reels only (None for PRODUCT/NEWS-origin Reels): what makes this an ORIGINAL
    # NINJA adaptation of the detected trend mechanic, and what was deliberately NOT copied from
    # the source creators/format.
    adaptation_notes: str | None = Field(default=None, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    # Versioned production-script fields; defaults preserve old concept rows and test doubles.
    source_subject: str | None = Field(default=None, max_length=_SHORT_TEXT_MAX_LENGTH)
    final_caption: str | None = Field(default=None, max_length=_LONG_TEXT_MAX_LENGTH)
    scenes: list[InstagramReelSceneCreative] = Field(default_factory=list)
