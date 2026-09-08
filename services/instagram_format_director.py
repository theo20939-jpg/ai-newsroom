"""NINJA Social Intelligence Foundation, Part IV §71-76: Format Director + production packages.
Structured contracts only in this phase (instagram_format_director_shadow_enabled=False,
core/config.py) - no real creative generation logic, no publication (spec §59/§111).

CRITICAL (spec §65/§95): every production package carries `approved_claims`/`restricted_claims`
propagated from the real CampaignPlan that produced it - a package must never assert a restricted
claim, and `validate_package_claims()` below is the one enforcement point every package
constructor is expected to run through."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field

from services.instagram_feed_context import InstagramFeedContext
from services.instagram_objectives import ContentObjective


class ContentFormat(str, enum.Enum):
    SINGLE = "single"
    CAROUSEL = "carousel"
    REEL = "reel"


class SlideRole:
    """Spec §34's own suggested carousel slide role vocabulary - a plain str-constants namespace
    (mirrors services/campaign_planner.py::CampaignPhase's own style), NOT an enforced enum on
    `CarouselSlide.role`: not every carousel needs every role (spec's own explicit instruction),
    and existing packages already use free-text roles like "body" - this namespace documents the
    common vocabulary without narrowing what `CarouselSlide.role` accepts."""

    HOOK = "hook"
    CONTEXT = "context"
    PROBLEM = "problem"
    EXPLANATION = "explanation"
    DATA = "data"
    COMPARISON = "comparison"
    TAKEAWAY = "takeaway"
    CTA = "cta"


class ClaimViolationError(ValueError):
    """Raised when a production package's own body text asserts a claim listed in
    `restricted_claims` - never silently dropped or auto-corrected (mirrors services/claim_policy_
    service.py's own fail-closed discipline: a restriction is enforced, not advisory)."""


def validate_package_claims(*, text_fields: list[str], restricted_claims: list[str]) -> None:
    for claim in restricted_claims:
        for text in text_fields:
            if claim and claim.lower() in text.lower():
                raise ClaimViolationError(f"restricted claim asserted in package text: {claim!r}")


@dataclass(frozen=True)
class SinglePostPackage:
    objective: ContentObjective
    visual_concept: str
    copy: str
    caption: str
    cta: str | None
    asset_requirements: list[str] = field(default_factory=list)
    source_attribution: str | None = None
    campaign_id: str | None = None
    approved_claims: list[str] = field(default_factory=list)
    restricted_claims: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        validate_package_claims(text_fields=[self.copy, self.caption], restricted_claims=self.restricted_claims)


@dataclass(frozen=True)
class CarouselSlide:
    role: str  # e.g. "hook", "body", "cta"
    text: str
    visual_concept: str


@dataclass(frozen=True)
class CarouselPackage:
    objective: ContentObjective
    slides: list[CarouselSlide]
    final_cta: str | None
    source_evidence_map: dict[int, str] = field(default_factory=dict)  # slide index -> source ref
    campaign_id: str | None = None
    approved_claims: list[str] = field(default_factory=list)
    restricted_claims: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if len(self.slides) < 2:
            raise ValueError("a carousel must have at least 2 slides")
        if not any(slide.role == "hook" for slide in self.slides):
            raise ValueError("a carousel must have a hook slide (spec §73)")
        validate_package_claims(
            text_fields=[s.text for s in self.slides], restricted_claims=self.restricted_claims,
        )


@dataclass(frozen=True)
class ReelPackage:
    objective: ContentObjective
    hook: str
    duration_target_seconds: int
    scene_sequence: list[str]
    on_screen_text: list[str] = field(default_factory=list)
    voiceover_script: str | None = None
    b_roll_needs: list[str] = field(default_factory=list)
    shot_list: list[str] = field(default_factory=list)
    visual_transitions: list[str] = field(default_factory=list)
    audio_strategy: str | None = None
    cta: str | None = None
    loop_ending_concept: str | None = None
    caption: str = ""
    source_evidence: list[str] = field(default_factory=list)
    campaign_id: str | None = None
    approved_claims: list[str] = field(default_factory=list)
    restricted_claims: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.scene_sequence:
            raise ValueError("a Reel package must have at least one scene")
        if self.duration_target_seconds <= 0:
            raise ValueError("duration_target_seconds must be positive")
        validate_package_claims(
            text_fields=[self.hook, self.caption, *self.on_screen_text],
            restricted_claims=self.restricted_claims,
        )


@dataclass(frozen=True)
class FormatDecision:
    recommended_format: ContentFormat
    alternatives: list[ContentFormat] = field(default_factory=list)
    why: str = ""
    expected_role: str = ""
    asset_requirements: list[str] = field(default_factory=list)
    risk: str = "low"
    confidence: float = 0.3
    warnings: list[str] = field(default_factory=list)


def evaluate_format_shadow(
    *, objective: ContentObjective, has_video_asset: bool, has_multi_step_narrative: bool,
    feed_context: InstagramFeedContext | None = None,
) -> FormatDecision:
    """Deterministic, structural evaluator only (no learned model yet - spec §71's own "do not
    default everything to Reels" instruction is enforced here by NEVER recommending REEL merely
    because it exists; a Reel is only recommended when a real video asset is actually available).

    DIRECTOR-CONTROL-PLANE-1A §13: `feed_context` (optional, None-default - every pre-existing call
    site is unaffected) only ever appends a `warnings` entry, never changes `recommended_format`
    (computed before this block, same as every other field) - format repetition is advisory
    information for a human/future learned model, not an automatic override."""
    if objective in (ContentObjective.SAVES, ContentObjective.COMMENTS) and has_multi_step_narrative:
        decision = FormatDecision(
            recommended_format=ContentFormat.CAROUSEL, alternatives=[ContentFormat.SINGLE],
            why="save/education objective with a multi-step narrative fits a carousel best",
            expected_role="education/reference", risk="low", confidence=0.4,
        )
    elif objective in (ContentObjective.REACH, ContentObjective.FOLLOWS) and has_video_asset:
        decision = FormatDecision(
            recommended_format=ContentFormat.REEL, alternatives=[ContentFormat.CAROUSEL],
            why="reach/follow objective with a real video asset available", expected_role="discovery",
            risk="medium", confidence=0.4,
        )
    else:
        decision = FormatDecision(
            recommended_format=ContentFormat.SINGLE, alternatives=[ContentFormat.CAROUSEL],
            why="no strong signal for carousel/reel - single post is the safe default",
            expected_role="general", risk="low", confidence=0.2,
        )

    if feed_context is not None and feed_context.readiness_state.value != "CONNECTED":
        return decision
    if feed_context is not None and feed_context.media_type_distribution:
        dominant_type, dominant_count = max(feed_context.media_type_distribution.items(), key=lambda kv: kv[1])
        if dominant_count >= max(3, len(feed_context.posts) // 2):
            decision = FormatDecision(
                recommended_format=decision.recommended_format, alternatives=decision.alternatives,
                why=decision.why, expected_role=decision.expected_role,
                asset_requirements=decision.asset_requirements, risk=decision.risk,
                confidence=decision.confidence,
                warnings=[f"recent feed dominated by media_type={dominant_type!r} ({dominant_count} posts) - consider format variety"],
            )
    return decision
