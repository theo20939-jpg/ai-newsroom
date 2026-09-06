"""VISUAL-DESIGN-AUTONOMY-1, spec §9-10/§30: VisualCreativeDirection - the per-post structured
creative output, and VisualDirectorContext - the compact, bounded input the Visual Design Director
actually sees (spec §30's own "do not send the entire Newsroom history" instruction).

Both are plain dataclasses; MOST VisualCreativeDirection fields are free text on purpose (spec
§10's own "do not force every creative choice into enums" instruction) - only `media_strategy`
is a fixed enum, since it drives a real branching decision downstream (services/visual_design_
loop.py chooses whether to call image generation at all)."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime


class MediaStrategy(str, enum.Enum):
    """Spec §33's own five options."""

    USE_SOURCE_MEDIA = "use_source_media"
    GENERATE_NEW = "generate_new"
    RESELECT_SOURCE_MEDIA = "reselect_source_media"
    COMPOSE_FROM_SOURCE = "compose_from_source"
    HUMAN_DESIGN = "human_design"


@dataclass(frozen=True)
class VisualCreativeDirection:
    story_id: str
    platform: str
    presentation_type: str | None

    creative_intent: str
    visual_angle: str
    composition: str
    subject_priority: str
    palette_direction: str
    lighting_direction: str
    background_direction: str
    visual_density: str
    negative_space_strategy: str
    overlay_strategy: str
    style_direction: str

    media_strategy: MediaStrategy

    # Spec §25: preferences only - services/nnj_master_news_overlay.py's own placement scoring
    # remains the final authority; nothing in this phase wires these into the renderer.
    preferred_overlay_zone: str | None = None
    preferred_overlay_variant: str | None = None
    preferred_overlay_contrast: str | None = None

    risks: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    prompt_text: str = ""

    @property
    def generation_needed(self) -> bool:
        return self.media_strategy in (MediaStrategy.GENERATE_NEW, MediaStrategy.COMPOSE_FROM_SOURCE)

    @property
    def source_media_preferred(self) -> bool:
        return self.media_strategy in (MediaStrategy.USE_SOURCE_MEDIA, MediaStrategy.RESELECT_SOURCE_MEDIA)

    @property
    def generated_scene_preferred(self) -> bool:
        return self.media_strategy == MediaStrategy.GENERATE_NEW

    @property
    def hybrid_preferred(self) -> bool:
        return self.media_strategy == MediaStrategy.COMPOSE_FROM_SOURCE


@dataclass(frozen=True)
class PreviousAttemptFeedback:
    """Spec §49: what the Visual Design Director sees on a REWORK retry - real Art Director
    output, never a synthesized summary that could lose information the director needs to decide
    whether to refine or completely redesign."""

    attempt_number: int
    previous_creative_direction_summary: str
    previous_prompt_text: str
    art_decision: str
    issue_codes: list[str]
    instructions: str
    root_cause: str
    attempts_remaining: int


@dataclass(frozen=True)
class VisualDirectorContext:
    """Spec §30: bounded, compact, deterministic-summary-only. No raw DB rows, no full Newsroom
    history - every field here is already a short string/list a caller assembled deliberately."""

    as_of: datetime
    story_id: str
    platform: str
    presentation_type: str | None

    story_facts_summary: str
    brand_core_rules: list[str]
    designer_brief_text: str
    designer_brief_scope: str
    designer_brief_version: int

    feed_context_summary: list[str]
    recent_failure_summary: list[str]
    available_media_summary: str
    renderer_constraints_summary: str

    attempts_used: int
    max_attempts: int
    budget_state_summary: str

    restricted_claims: list[str] = field(default_factory=list)
    previous_attempt: PreviousAttemptFeedback | None = None
    # SOCIAL-INTELLIGENCE-PRELAUNCH-1A §16: INFORMATION ONLY, mirroring feed_context_summary's own
    # "already a short string a caller assembled deliberately" discipline - "" (the default) for
    # every caller that never wires launch context, so this field existing changes nothing about
    # attempts/budget/renderer behavior for any existing caller.
    launch_context_summary: str = ""
