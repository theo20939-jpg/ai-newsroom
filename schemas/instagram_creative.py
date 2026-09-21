"""INSTAGRAM-GROWTH-3, item 4: Instagram Creative Director output schemas - mirrors
schemas/meme_copy.py's own discipline exactly (frozen, `extra="forbid"`, length ceilings enforced
structurally rather than left to prompt-only discretion). `evidence_used` on every schema is the
grounding mechanism spec item 5 requires: services/instagram_creative_director.py::
assert_evidence_grounded() rejects a draft whose `evidence_used` contains anything the caller did
not explicitly supply as allowed evidence - the Creative Director may transform PRESENTATION, it
may never invent a fact."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

INSTAGRAM_CREATIVE_SCHEMA_VERSION = "v1"

_SHORT_TEXT_MAX_LENGTH = 200
_MEDIUM_TEXT_MAX_LENGTH = 400
_LONG_TEXT_MAX_LENGTH = 1200


class InstagramEditorialDecision(BaseModel):
    """The pre-generation decision made by the existing Instagram Director.

    This is deliberately a decision contract, not another content pipeline or persisted business-
    truth model.  It is snapshotted with the existing ``ContentOpportunity``/Telegram delivery and
    gives the editor the reasoning that was previously missing before format-specific generation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_summary: str = Field(min_length=1, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    opportunity_type: Literal[
        "NEWS", "NEWS_X_TREND", "PRODUCT_X_TREND", "CULTURE", "PRODUCT", "EVERGREEN"
    ]
    why_now: str = Field(min_length=1, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    audience_value: str = Field(min_length=1, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    angle: str = Field(min_length=1, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    angle_intent: Literal[
        "BREAKING", "EXPLAINER", "IMPACT", "REACTION", "DEBATE", "COMPARISON",
        "HOW_TO", "MEME", "PRODUCT_USE_CASE", "EVERGREEN_VALUE",
    ]
    topic: str = Field(min_length=1, max_length=_SHORT_TEXT_MAX_LENGTH)
    purpose: Literal["REACH", "ENGAGEMENT", "VALUE", "BRAND", "PRODUCT"]
    origin: Literal["NEWS", "TREND", "PRODUCT", "CULTURE", "EVERGREEN"]
    recommended_format: Literal["single", "carousel", "reel"]
    format_reason: str = Field(min_length=1, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    creative_direction: str = Field(min_length=1, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    product_connection: str | None = Field(default=None, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    trend_rationale: str | None = Field(default=None, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    # Deterministic Phase A.1 metadata is attached after generation from the supplied normalized
    # signal; it is not authored by the model and therefore cannot invent provenance.
    trend_signal_type: str | None = Field(default=None, max_length=50)
    trend_signal_provenance: str | None = Field(default=None, max_length=50)
    supplementary_story_idea: str | None = Field(default=None, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    evidence_used: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_intersections(self) -> InstagramEditorialDecision:
        if self.opportunity_type in ("NEWS_X_TREND", "PRODUCT_X_TREND") and not self.trend_rationale:
            raise ValueError("a trend intersection requires an explicit trend_rationale")
        if self.opportunity_type not in ("NEWS_X_TREND", "PRODUCT_X_TREND") and self.trend_rationale:
            raise ValueError("trend_rationale is only valid for a real trend intersection")
        if self.opportunity_type in ("PRODUCT", "PRODUCT_X_TREND") and not self.product_connection:
            raise ValueError("a product opportunity requires a concrete product_connection")
        return self


class InstagramCreativeExecutionPlan(BaseModel):
    """Format-independent production decision authored by the existing Creative Director."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    main_idea: str = Field(min_length=1, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    focal_point: str = Field(min_length=1, max_length=_SHORT_TEXT_MAX_LENGTH)
    media_strategy: Literal["source_media", "generated_media", "typographic"]
    media_rationale: str = Field(min_length=1, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    composition_direction: str = Field(min_length=1, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    branding_treatment: str = Field(min_length=1, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    visual_treatment: str = Field(min_length=1, max_length=_SHORT_TEXT_MAX_LENGTH)
    avoid_recent_treatment: str | None = Field(default=None, max_length=_MEDIUM_TEXT_MAX_LENGTH)


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
    creative_execution_plan: InstagramCreativeExecutionPlan | None = None


# ---------------------------------------------------------------------------------------------
# Phase B.5: DECLARATIVE slide layout. The Creative Director describes composition RELATIONSHIPS
# (regions in normalized 0..1 canvas space); it never supplies fonts, hex colours, pixel sizes,
# code, CSS or SVG. Brand implementation (type family, sizes per token, colours, logo, margins)
# is renderer-owned - see services/instagram_declarative_layout.py. Coordinates are only loosely
# bounded here on purpose: out-of-range values must be adapted or rejected PER SLIDE by
# services/instagram_layout_validation.py, never fail the whole carousel at parse time.
# ---------------------------------------------------------------------------------------------

LayoutRegionKind = Literal["surface", "media", "text", "accent", "graphic"]
ScaleToken = Literal["NUMERAL", "DISPLAY", "HEADLINE_L", "HEADLINE_M", "HEADLINE_S", "BODY", "CAPTION"]
TEXT_CONTENT_REFS = ("copy", "copy_lead", "copy_rest", "number", "copy_no_number")
MEDIA_FUNCTIONS = ("hero", "detail", "evidence_photo", "ui_screenshot", "result", "before_after", "concept", "none")


class LayoutRegion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: LayoutRegionKind
    x: float = Field(ge=-1.0, le=2.0)
    y: float = Field(ge=-1.0, le=2.0)
    w: float = Field(ge=-1.0, le=2.0)
    h: float = Field(ge=-1.0, le=2.0)
    z: int = Field(default=0, ge=0, le=9)
    # text: one of TEXT_CONTENT_REFS (derived deterministically from the slide's own copy - the
    # model can never introduce new text here); media: a subject key the resolver listed.
    content_ref: str | None = Field(default=None, max_length=60)
    scale_token: ScaleToken | None = None
    align: Literal["left", "center", "right"] | None = None
    valign: Literal["top", "middle", "bottom"] | None = None
    max_lines: int | None = Field(default=None, ge=1, le=10)
    surface: Literal["paper", "soft", "red", "ink", "graphite"] | None = None
    crop_mode: Literal["cover", "contain"] | None = None
    focus_x: float | None = Field(default=None, ge=0.0, le=1.0)
    focus_y: float | None = Field(default=None, ge=0.0, le=1.0)
    frame: Literal["none", "hairline", "accent", "paper"] | None = None
    accent_type: Literal["rule_h", "rule_v", "block"] | None = None
    graphic_type: Literal["ui_frame", "flow_diagram", "poll_cards", "badge", "scribble"] | None = None
    # B.5R: renderer-resolved colour role (the palette itself is renderer-owned), text laid on a media
    # region (contrast is MEASURED on the unaltered pixels, never fixed with an overlay) and a small
    # collage tilt for media fragments.
    tone: Literal["primary", "accent", "accent2", "muted"] | None = None
    on_media: bool | None = None
    tilt_deg: float | None = Field(default=None, ge=-12.0, le=12.0)


class InstagramSlideLayout(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    background: Literal["paper", "soft", "ink", "graphite"] = "paper"
    palette: Literal["brand", "culture", "neo"] = "brand"
    density: Literal["LOW", "MEDIUM", "HIGH"]
    media_dominance: Literal["NONE", "SUPPORTING", "BALANCED", "DOMINANT"]
    visual_weight: Literal["TEXT", "MEDIA", "MIXED", "GRAPHIC"]
    show_progress: bool = True
    regions: list[LayoutRegion] = Field(min_length=1, max_length=10)


class InstagramVisualRhythm(BaseModel):
    """Carousel-level rhythm: how consecutive slides deliberately differ (density / media dominance /
    headline scale progression, and where a visual interruption is intended)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    arc: str = Field(min_length=1, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    interruption_slides: list[int] = Field(default_factory=list, max_length=6)
    repetition_note: str | None = Field(default=None, max_length=_SHORT_TEXT_MAX_LENGTH)


class InstagramCarouselSlideCreative(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _drop_removed_overlay_mode(cls, data):
        """Phase B.4.4 legacy-payload boundary: overlays were removed from the Instagram visual
        system. Persisted B.4/B.4.3 draft payloads (and any legacy model output) may still carry
        `overlay_mode`; it is discarded HERE, at parse time, so it can never reach the renderer.
        No DB migration - stored JSON keeps the old key, this boundary just ignores it."""
        if isinstance(data, dict) and "overlay_mode" in data:
            return {key: value for key, value in data.items() if key != "overlay_mode"}
        return data

    role: str = Field(min_length=1, max_length=50)
    slide_copy: str = Field(min_length=1, max_length=_SHORT_TEXT_MAX_LENGTH)
    visual_direction: str = Field(min_length=1, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    source_evidence: str | None = Field(default=None, max_length=_MEDIUM_TEXT_MAX_LENGTH)
    slide_purpose: str | None = Field(default=None, max_length=_SHORT_TEXT_MAX_LENGTH)
    media_need: str | None = Field(default=None, max_length=_SHORT_TEXT_MAX_LENGTH)
    # Phase B.4: bounded, EXECUTABLE art direction - the renderer reads these directly (see
    # services/instagram_carousel_layouts.py::select_composition_family/_render_generic_
    # composition), never re-parses prose to infer them. All optional/defaulted so every existing
    # B.3 caller/test/persisted draft is completely unaffected - role alone still decides the
    # composition family whenever a slide does not explicitly set one (the B.3-approved default
    # path is untouched code, not just untouched behavior).
    composition: Literal[
        "full_bleed_media", "contained_media", "split_compare", "typographic", "screenshot_ui", "collage",
    ] | None = None
    media_position: Literal["full", "top", "left", "right", "none"] | None = None
    media_scale: float | None = Field(default=None, ge=0.2, le=1.0)
    # NEWS_RECAP's own hard requirement (spec B.4 §10/§17): which real-world subject this
    # slide's asset must show, and whether the renderer/validator must refuse a fallback/shared
    # asset for it - never a free-text instruction the renderer has to interpret.
    media_subject: str | None = Field(default=None, max_length=_SHORT_TEXT_MAX_LENGTH)
    must_match_story: bool = False
    # Phase B.5: WHAT the slide's media is FOR (asset planning) and the declarative composition.
    # `layout` is the new primary art direction; the legacy composition/media_position/media_scale
    # above remain a compatibility path for persisted B.4 drafts (no DB migration).
    media_function: Literal[
        "hero", "detail", "evidence_photo", "ui_screenshot", "result", "before_after", "concept", "none",
    ] | None = None
    layout: InstagramSlideLayout | None = None
    # Phase B.4.1 section 7: deliberately NOT a field here. The model may state WHICH subject a
    # slide needs (media_subject) and WHETHER a shared/fallback asset is unacceptable
    # (must_match_story) - both real creative decisions - but never the actual resolved asset's
    # identity. An LLM cannot know what bytes a resolver will actually attach to a slide, so it
    # must never be trusted to declare that identity itself (services/instagram_platform_
    # renderer.py::render_instagram_carousel's own `asset_identities` parameter, supplied by
    # whatever real code resolves media, is the only source of truth the validator trusts).


class InstagramCarouselCreative(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = INSTAGRAM_CREATIVE_SCHEMA_VERSION
    objective: str = Field(min_length=1, max_length=50)
    slides: list[InstagramCarouselSlideCreative] = Field(min_length=2)
    final_cta: str | None = Field(default=None, max_length=_SHORT_TEXT_MAX_LENGTH)
    evidence_used: list[str] = Field(default_factory=list)
    final_caption: str | None = Field(default=None, max_length=_LONG_TEXT_MAX_LENGTH)
    # Phase B.4: WHAT kind of post this is (content strategy), never a rendering instruction and
    # never read by services/instagram_format_director_v2.py (ContentFormat stays the platform
    # SINGLE/CAROUSEL/REEL decision - a separate axis, per spec B.4 §3). Optional/defaulted: an
    # absent archetype is simply "unclassified", not an error, so every existing persisted
    # InstagramCreativeDraft.payload row remains a valid InstagramCarouselCreative.
    content_archetype: Literal["ai_hack", "news_insight", "news_recap", "trend_generative"] | None = None
    visual_rhythm: InstagramVisualRhythm | None = None
    creative_execution_plan: InstagramCreativeExecutionPlan | None = None

    @property
    def hook_slide(self) -> InstagramCarouselSlideCreative:
        return self.slides[0]

    @model_validator(mode="after")
    def validate_production_narrative(self) -> "InstagramCarouselCreative":
        if self.creative_execution_plan is None and self.final_caption is None:
            return self
        normalized = [" ".join(slide.slide_copy.lower().split()) for slide in self.slides]
        if len(normalized) != len(set(normalized)):
            raise ValueError("carousel slides must not duplicate or mechanically repeat copy")
        if self.slides[0].role.strip().lower() != "hook":
            raise ValueError("carousel production sequence must begin with a hook slide")
        roles = [slide.role.strip().lower() for slide in self.slides]
        if len(set(roles)) < 2:
            raise ValueError("carousel slides must have distinct narrative functions")
        if roles[-1] not in {"takeaway", "cta"}:
            raise ValueError("carousel production sequence must end with takeaway or cta")
        if any(not slide.slide_purpose for slide in self.slides):
            raise ValueError("every production carousel slide requires slide_purpose")
        return self


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
    creative_execution_plan: InstagramCreativeExecutionPlan | None = None
