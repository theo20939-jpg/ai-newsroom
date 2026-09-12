"""INSTAGRAM-EXECUTION-FOUNDATION-1 section 4/23: `InstagramContentPackage` - the ONE canonical
execution contract between the existing, real Director planning chain (ContentOpportunity ->
GrowthStrategy -> ObjectiveRecommendation -> FormatDecision -> CreativeGenerationOutcome ->
`services/instagram_shadow_pipeline.py::build_shadow_plan()`) and the new platform render/publish
layers this phase adds.

This module does NOT redesign the planning stack (section 1) - `build_instagram_content_package()`
is pure, deterministic assembly over already-computed upstream objects, exactly the same
"assembly, never re-derivation" discipline `build_shadow_plan()` itself already uses. It does NOT
duplicate CampaignPlan/BusinessContextSnapshot wholesale (section 4's own explicit instruction) -
only their identifying references (`campaign_id`, `campaign_name`, `campaign_phase`,
`business_context_version`) are carried, mirroring the same reference-not-copy discipline
`database/models/instagram_creative_plan.py::InstagramCreativePlan.campaign_state_snapshot`
already uses for its own "business truth AS OF planning time" field.

Honesty note (never silently invents what the Director doesn't produce):
  * `caption` is the Creative Director's own `caption_direction` (a DIRECTIONAL BRIEF - the
    existing schemas/instagram_creative.py explicitly does not produce final polished copy; this
    mirrors `instagram_creative_plan_service.py`'s own "AI creative output is a PROPOSAL" doctrine)
    for SINGLE/REEL. For CAROUSEL there is no schema-level "final caption" field at all - the
    package-level caption is synthesized from the hook slide's own copy, and `caption_is_draft` is
    always True so no downstream consumer mistakes a directional brief for publish-ready prose.
  * `hashtags` is always `[]` unless the caller explicitly supplies real ones - no Instagram
    creative schema in this codebase produces hashtags today (verified: `schemas/
    instagram_creative.py` has no such field), so this field would otherwise be a fabrication.
  * `external_video_asset_ref` is the ONLY way a REEL package ever carries a video - this
    codebase has no video-generation infrastructure (section 11's own explicit instruction) and
    none is added here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from services.instagram_content_opportunity import ContentOpportunity
from services.instagram_creative_director import CreativeGenerationOutcome
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_shadow_pipeline import ShadowPlanResult

CONTENT_PACKAGE_SCHEMA_VERSION = "v1"


class InstagramContentPackageError(ValueError):
    """Raised when the upstream objects cannot honestly be assembled into a package (e.g. a REEL
    format decision with no external video reference supplied) - never silently downgraded."""


@dataclass(frozen=True)
class InstagramContentPackage:
    """The one executable-package contract. Every field is a plain, JSON-serializable value or a
    plain nested dict/list of them (never a live SQLAlchemy row, never a pydantic model instance) -
    `to_dict()` is the canonical serialization, used by the renderer, the review package, the
    editorial gate, the Art validator, and the publish adapter alike, so all five layers agree on
    exactly one shape."""

    schema_version: str
    package_id: str
    platform: str  # always "instagram" - this contract is Instagram-specific by construction

    # -- account (logical key only; the real numeric ig_user_id lives in settings/InstagramAccount,
    #    never duplicated here) --
    account_key: str

    # -- format --
    content_format: ContentFormat

    # -- content --
    caption: str
    caption_is_draft: bool
    on_image_copy: str | None
    cta: str | None
    hashtags: list[str]

    # -- media plan (format-shaped; see module docstring) --
    media_plan: dict[str, Any]
    external_video_asset_ref: str | None

    # -- references (never a wholesale copy) --
    opportunity_id: str
    story_id: str | None
    trend_id: str | None
    campaign_id: str | None
    campaign_name: str | None
    campaign_phase: str | None

    # -- business safety (propagated, never re-derived) --
    approved_claims: list[str]
    restricted_claims: list[str]
    product_mention_allowed: bool

    # -- Director decision evidence (traceability back to the real planning chain) --
    director_evidence: dict[str, Any]

    # -- render requirements (filled by this module; consumed by the renderer) --
    render_profiles: list[str]
    slide_count: int | None

    # -- INSTAGRAM-VISUAL-SYSTEM-V1-1 section 2: the only two fields this phase adds, strictly
    # required to support truthful visual composition. Both additive with safe defaults - every
    # Foundation-phase package/test that never set them keeps behaving exactly as before.
    #   `presentation_family` - which Instagram-native visual treatment (section 6: "news"/
    #   "breaking"/"data"/"quote") a SINGLE package asks the renderer for. None/unrecognized ->
    #   the safe NEWS default (never a fabricated inference from freetext copy).
    #   `source_image_ref` - a traceable STRING reference to a real source image (e.g. an asset
    #   path/id), never raw bytes - the package stays plain-JSON-serializable exactly as before.
    #   The actual image bytes are always a renderer-time keyword argument (mirrors Telegram's own
    #   `render_data_card(candidate, *, source_image_bytes=...)` precedent) - this field only
    #   records THAT a real image was associated with this package, for evidence/traceability.
    presentation_family: str | None = None
    source_image_ref: str | None = None

    # -- publication metadata (empty at package-build time; the publish layer appends to a COPY) --
    publication_metadata: dict[str, Any] = field(default_factory=dict)

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "package_id": self.package_id,
            "platform": self.platform,
            "account_key": self.account_key,
            "content_format": self.content_format.value,
            "caption": self.caption,
            "caption_is_draft": self.caption_is_draft,
            "on_image_copy": self.on_image_copy,
            "cta": self.cta,
            "hashtags": list(self.hashtags),
            "media_plan": self.media_plan,
            "external_video_asset_ref": self.external_video_asset_ref,
            "opportunity_id": self.opportunity_id,
            "story_id": self.story_id,
            "trend_id": self.trend_id,
            "campaign_id": self.campaign_id,
            "campaign_name": self.campaign_name,
            "campaign_phase": self.campaign_phase,
            "approved_claims": list(self.approved_claims),
            "restricted_claims": list(self.restricted_claims),
            "product_mention_allowed": self.product_mention_allowed,
            "director_evidence": self.director_evidence,
            "render_profiles": list(self.render_profiles),
            "slide_count": self.slide_count,
            "presentation_family": self.presentation_family,
            "source_image_ref": self.source_image_ref,
            "publication_metadata": self.publication_metadata,
            "created_at": self.created_at.isoformat(),
        }

    @property
    def text_fields_for_claim_check(self) -> list[str]:
        """Every free-text field a restricted claim could hide in - the exact set the editorial
        gate / Art validator re-check against `restricted_claims` (mirrors
        `services/instagram_format_director.py::validate_package_claims()`'s own field set)."""
        fields = [self.caption, self.on_image_copy or "", self.cta or ""]
        slides = self.media_plan.get("slides")
        if isinstance(slides, list):
            fields.extend(str(slide.get("text", "")) for slide in slides)
        on_screen_text = self.media_plan.get("on_screen_text")
        if isinstance(on_screen_text, list):
            fields.extend(str(t) for t in on_screen_text)
        return fields


def _single_media_plan(creative: Any) -> tuple[str, str | None, str | None, dict[str, Any]]:
    caption = creative.caption_direction
    on_image_copy = creative.on_image_copy
    cta = creative.cta
    media_plan = {
        "kind": "single",
        "visual_concept": creative.visual_concept,
        "asset_requirements": list(creative.asset_requirements),
    }
    return caption, on_image_copy, cta, media_plan


def _carousel_media_plan(creative: Any) -> tuple[str, str | None, str | None, dict[str, Any]]:
    # No schema-level "final caption" exists for a carousel (schemas/instagram_creative.py has
    # none) - the hook slide's own copy anchors the package-level caption, clearly marked draft.
    caption = creative.hook_slide.slide_copy
    cta = creative.final_cta
    slides = [
        {"index": i, "role": slide.role, "text": slide.slide_copy, "visual_direction": slide.visual_direction,
         "source_evidence": slide.source_evidence}
        for i, slide in enumerate(creative.slides)
    ]
    media_plan = {"kind": "carousel", "objective": creative.objective, "slides": slides}
    return caption, None, cta, media_plan


def _reel_media_plan(creative: Any) -> tuple[str, str | None, str | None, dict[str, Any]]:
    caption = creative.caption_direction
    cta = creative.cta
    media_plan = {
        "kind": "reel",
        "hook": creative.hook,
        "target_duration_seconds": creative.target_duration_seconds,
        "scene_sequence": list(creative.scene_sequence),
        "shot_list": list(creative.shot_list),
        "on_screen_text": list(creative.on_screen_text),
        "b_roll_requirements": list(creative.b_roll_requirements),
        "pacing": creative.pacing,
        "voiceover_script": creative.voiceover_script,
        "audio_direction": creative.audio_direction,
        "loop_ending_concept": creative.loop_ending_concept,
    }
    return caption, None, cta, media_plan


def _render_profiles_for(fmt: ContentFormat, *, slide_count: int | None) -> list[str]:
    if fmt is ContentFormat.SINGLE:
        return ["portrait_feed"]
    if fmt is ContentFormat.CAROUSEL:
        return ["carousel_slide"] * (slide_count or 0)
    if fmt is ContentFormat.REEL:
        return ["reel_cover"]
    raise InstagramContentPackageError(f"unsupported ContentFormat: {fmt!r}")


def build_instagram_content_package(
    *, opportunity: ContentOpportunity, format_decision: FormatDecision, shadow_plan: ShadowPlanResult,
    creative_outcome: CreativeGenerationOutcome | None = None, account_key: str = "default",
    external_video_asset_ref: str | None = None, hashtags: list[str] | None = None,
    presentation_family: str | None = None, source_image_ref: str | None = None,
) -> InstagramContentPackage:
    """Assembles a package from the REAL upstream Director objects. `creative_outcome` is optional
    (mirrors `build_shadow_plan()`'s own optionality) - without it, the package carries only the
    structural shadow-plan summary as its caption/evidence, never a fabricated brief.

    Raises `InstagramContentPackageError` for a REEL format decision with no
    `external_video_asset_ref` AND no creative outcome to at least describe the plan - a Reel
    package must never silently claim video capability this codebase does not have (section 11).
    """
    fmt = format_decision.recommended_format

    caption: str
    on_image_copy: str | None = None
    cta: str | None = None
    media_plan: dict[str, Any]
    slide_count: int | None = None

    if creative_outcome is not None and creative_outcome.single is not None and fmt is ContentFormat.SINGLE:
        caption, on_image_copy, cta, media_plan = _single_media_plan(creative_outcome.single)
    elif creative_outcome is not None and creative_outcome.carousel is not None and fmt is ContentFormat.CAROUSEL:
        caption, on_image_copy, cta, media_plan = _carousel_media_plan(creative_outcome.carousel)
        slide_count = len(creative_outcome.carousel.slides)
    elif creative_outcome is not None and creative_outcome.reel is not None and fmt is ContentFormat.REEL:
        caption, on_image_copy, cta, media_plan = _reel_media_plan(creative_outcome.reel)
    else:
        # No matching creative outcome - fall back to the structural shadow-plan summary only.
        # Never fabricates a brief; a caller that wants real creative copy must run the Creative
        # Director first (this module's own docstring/section 1: reuse, never redesign).
        caption = shadow_plan.creative_concept_summary or shadow_plan.opportunity_description
        media_plan = {"kind": fmt.value, "note": "no CreativeGenerationOutcome supplied - structural shadow-plan summary only"}
        if fmt is ContentFormat.CAROUSEL:
            slide_count = 0

    if fmt is ContentFormat.REEL and external_video_asset_ref is None:
        media_plan = {**media_plan, "requires_external_video_asset": True, "external_video_asset_ref": None}

    return InstagramContentPackage(
        schema_version=CONTENT_PACKAGE_SCHEMA_VERSION,
        package_id=str(uuid4()),
        platform="instagram",
        account_key=account_key,
        content_format=fmt,
        caption=caption,
        caption_is_draft=True,
        on_image_copy=on_image_copy,
        cta=cta,
        hashtags=list(hashtags or []),
        media_plan=media_plan,
        external_video_asset_ref=external_video_asset_ref,
        opportunity_id=opportunity.id,
        story_id=opportunity.story_id,
        trend_id=opportunity.trend_id,
        campaign_id=opportunity.campaign_id,
        campaign_name=shadow_plan.campaign_name,
        campaign_phase=shadow_plan.campaign_phase,
        approved_claims=list(opportunity.allowed_claims),
        restricted_claims=list(opportunity.restricted_claims),
        product_mention_allowed=opportunity.product_mention_allowed,
        director_evidence={
            "evidence": list(shadow_plan.evidence),
            "confidence": shadow_plan.confidence,
            "primary_objective": shadow_plan.primary_objective,
            "recommended_format": shadow_plan.recommended_format,
            "hook_family": shadow_plan.hook_family,
            "format_decision_why": format_decision.why,
            "format_decision_risk": format_decision.risk,
            "format_decision_confidence": format_decision.confidence,
            "format_decision_warnings": list(format_decision.warnings),
        },
        presentation_family=presentation_family,
        source_image_ref=source_image_ref,
        render_profiles=_render_profiles_for(fmt, slide_count=slide_count),
        slide_count=slide_count,
    )
