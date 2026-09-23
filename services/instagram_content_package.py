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
  * `caption` is the Creative Director's finished `final_caption` for SINGLE/REEL. Older
    creative rows without it assemble with an empty caption marked draft; a directional
    `caption_direction` is never promoted to final copy. CAROUSEL still uses the hook slide's
    copy and remains draft until a real final caption is supplied.
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

    # -- INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1 §7/§9: the real media-truthfulness/rights
    # identity for `source_image_ref`, carried from the SAME unified `MediaSelectionResult`
    # `services.instagram_media_safety.resolve_instagram_media()` produces (never re-derived or
    # independently guessed here - `build_instagram_content_package()` is the only writer). All
    # three additive with safe `None` defaults so every pre-existing caller/test that never passed
    # a `media_selection` keeps behaving exactly as before. `media_candidate_id` is the SAME id
    # `source_image_ref` already carries when a `media_selection` was supplied - kept as an
    # explicit, separately-named field so a same-asset-identity check never has to guess which of
    # several string fields is the authoritative one.
    media_candidate_id: str | None = None
    media_subject_match: str | None = None  # a real SubjectMatchClassification value, e.g.
    # "exact_subject"/"strong_context"/"generic_context" - "mismatch"/"editorial_review_required"-
    # equivalent candidates can never reach here, because `is_selectable()` already excluded them
    # from ever becoming `MediaSelectionResult.selected` in the first place (§7's own point).
    media_usage_classification: str | None = None  # a real MediaUsageClassification value.

    # -- INSTAGRAM-CONTENT-STRATEGY-V2 Phase 3: REEL script-readiness axis, ORTHOGONAL to the
    # existing QA/truthfulness gate (InstagramGateDecision READY_FOR_EDITOR/HOLD/BLOCK) - this is
    # about SCRIPT COMPLETENESS (are all required facts/assets known), not media/art quality.
    # `None` for every non-REEL package and every REEL built before this phase (safe default, no
    # pre-existing caller/test affected). One of "concept_script" (the premise is fact-grounded but
    # production assets/execution details are still missing) or "production_script" (required
    # facts confirmed AND required production inputs known/satisfiable) - computed by the CALLER
    # (services/instagram_reel_script_readiness.py), never by the Creative Director itself and
    # never inferred here from creative content alone.
    reel_script_readiness: str | None = None

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
            "media_candidate_id": self.media_candidate_id,
            "media_subject_match": self.media_subject_match,
            "media_usage_classification": self.media_usage_classification,
            "reel_script_readiness": self.reel_script_readiness,
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
        for key in ("hook", "voiceover_script", "source_subject"):
            fields.append(str(self.media_plan.get(key) or ""))
        for scene in self.media_plan.get("scenes") or []:
            if isinstance(scene, dict):
                fields.extend(str(scene.get(key) or "") for key in ("spoken_line", "on_screen_text"))
        return fields


def _single_media_plan(creative: Any) -> tuple[str, str | None, str | None, dict[str, Any]]:
    caption = getattr(creative, "final_caption", None) or ""
    on_image_copy = creative.on_image_copy
    cta = creative.cta
    media_plan = {
        "kind": "single",
        "source_subject": getattr(creative, "source_subject", None),
        "visual_concept": creative.visual_concept,
        "asset_requirements": list(creative.asset_requirements),
        "creative_execution_plan": (
            creative.creative_execution_plan.model_dump()
            if getattr(creative, "creative_execution_plan", None) is not None else None
        ),
    }
    return caption, on_image_copy, cta, media_plan


def _carousel_media_plan(creative: Any) -> tuple[str, str | None, str | None, dict[str, Any]]:
    caption = getattr(creative, "final_caption", None) or creative.hook_slide.slide_copy
    cta = creative.final_cta
    slides = [
        {"index": i, "role": slide.role, "text": slide.slide_copy, "body": getattr(slide, "slide_body", None), "visual_direction": slide.visual_direction,
         "source_evidence": slide.source_evidence, "slide_purpose": getattr(slide, "slide_purpose", None),
         "media_need": getattr(slide, "media_need", None),
         # Phase B.4: bounded structured art direction, passed through verbatim - never
         # re-derived or re-parsed here. None on every field for any pre-B.4 slide/persisted
         # draft, so the B.3 default path is exercised exactly as before.
         "composition": getattr(slide, "composition", None),
         "media_position": getattr(slide, "media_position", None),
         "media_scale": getattr(slide, "media_scale", None),
         "media_subject": getattr(slide, "media_subject", None),
         "must_match_story": getattr(slide, "must_match_story", False),
         # Phase B.5: declarative layout + media function, passed through verbatim.
         "media_function": getattr(slide, "media_function", None),
         # Phase B.5.1: the chosen visual family and its reason, persisted for audit (None on every pre-B.5.1 slide).
         "visual_family": getattr(slide, "visual_family", None),
         "visual_family_reason": getattr(slide, "visual_family_reason", None),
         # Phase B.6: where this slide's visual idea comes from (source / generated / graphic) and the generated picture's brief.
         "media_source": getattr(slide, "media_source", None),
         "generation_brief": getattr(slide, "generation_brief", None),
         "hook_emotion": getattr(slide, "hook_emotion", None),
         "hook_mechanic": getattr(slide, "hook_mechanic", None),
         "story_anchor": getattr(slide, "story_anchor", None),
         "layout": (slide.layout.model_dump() if getattr(slide, "layout", None) is not None else None)}
        for i, slide in enumerate(creative.slides)
    ]
    media_plan = {
        "kind": "carousel", "objective": creative.objective, "slides": slides,
        "content_archetype": getattr(creative, "content_archetype", None),
        # Phase B.6: a media-first plan (every slide names its visual source); the art validator then refuses a slide with no meaningful visual.
        "media_first": bool(slides) and all(sl.get("media_source") for sl in slides),
        "visual_rhythm": (
            creative.visual_rhythm.model_dump() if getattr(creative, "visual_rhythm", None) is not None else None
        ),
        "creative_execution_plan": (
            creative.creative_execution_plan.model_dump()
            if getattr(creative, "creative_execution_plan", None) is not None else None
        ),
    }
    return caption, None, cta, media_plan


def _reel_media_plan(creative: Any) -> tuple[str, str | None, str | None, dict[str, Any]]:
    caption = getattr(creative, "final_caption", None) or ""
    cta = creative.cta
    media_plan = {
        "kind": "reel",
        "source_subject": getattr(creative, "source_subject", None),
        "scenes": [scene.model_dump() if hasattr(scene, "model_dump") else scene for scene in (getattr(creative, "scenes", None) or [])],
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
        # INSTAGRAM-CONTENT-STRATEGY-V2 Phase 3: additive - `getattr(..., default)` so a
        # pre-Phase-3 InstagramReelCreative-shaped test double (missing these attrs entirely)
        # still builds a package exactly as before.
        "visual_direction": getattr(creative, "visual_direction", None),
        "asset_requirements": list(getattr(creative, "asset_requirements", []) or []),
        "adaptation_notes": getattr(creative, "adaptation_notes", None),
        "creative_execution_plan": (
            creative.creative_execution_plan.model_dump()
            if getattr(creative, "creative_execution_plan", None) is not None else None
        ),
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
    media_candidate_id: str | None = None, media_selection: Any | None = None, reel_script_readiness: str | None = None,
) -> InstagramContentPackage:
    """Assembles a package from the REAL upstream Director objects. `creative_outcome` is optional
    (mirrors `build_shadow_plan()`'s own optionality) - without it, the package carries only the
    structural shadow-plan summary as its caption/evidence, never a fabricated brief.

    Raises `InstagramContentPackageError` for a REEL format decision with no
    `external_video_asset_ref` AND no creative outcome to at least describe the plan - a Reel
    package must never silently claim video capability this codebase does not have (section 11).

    INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1 §7/§9: `media_selection` (a `schemas.media_subject_
    match.MediaSelectionResult`, typed `Any` here to avoid this platform-neutral-by-design contract
    module importing the media-research schema for a single optional parameter) is the SAME real
    result `services.instagram_media_safety.resolve_instagram_media()` produces. When supplied and
    it has a `.selected` candidate, `source_image_ref`/`media_candidate_id`/`media_subject_match`/
    `media_usage_classification` are all populated from IT - never independently guessed, and the
    explicit `source_image_ref`/nothing-supplied path below is used only when no media_selection is
    given at all (back-compat with every pre-existing caller/test)."""
    if media_selection is not None and getattr(media_selection, "selected", None) is not None:
        selected = media_selection.selected
        source_image_ref = selected.candidate_id
        media_candidate_id = selected.candidate_id
        media_subject_match = selected.subject_match.subject_match.value if selected.subject_match else None
        media_usage_classification = selected.usage_classification.value
    else:
        media_subject_match = None
        media_usage_classification = None
    fmt = format_decision.recommended_format

    caption: str
    on_image_copy: str | None = None
    cta: str | None = None
    media_plan: dict[str, Any]
    slide_count: int | None = None
    caption_is_draft = True

    if creative_outcome is not None and creative_outcome.single is not None and fmt is ContentFormat.SINGLE:
        caption, on_image_copy, cta, media_plan = _single_media_plan(creative_outcome.single)
        caption_is_draft = not bool(caption.strip())
    elif creative_outcome is not None and creative_outcome.carousel is not None and fmt is ContentFormat.CAROUSEL:
        caption, on_image_copy, cta, media_plan = _carousel_media_plan(creative_outcome.carousel)
        slide_count = len(creative_outcome.carousel.slides)
        caption_is_draft = not bool(getattr(creative_outcome.carousel, "final_caption", None))
    elif creative_outcome is not None and creative_outcome.reel is not None and fmt is ContentFormat.REEL:
        caption, on_image_copy, cta, media_plan = _reel_media_plan(creative_outcome.reel)
        caption_is_draft = not bool(caption.strip())
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
        caption_is_draft=caption_is_draft,
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
            "editorial_decision": dict(opportunity.editorial_decision),
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
        media_candidate_id=media_candidate_id,
        media_subject_match=media_subject_match,
        media_usage_classification=media_usage_classification,
        reel_script_readiness=reel_script_readiness,
        render_profiles=_render_profiles_for(fmt, slide_count=slide_count),
        slide_count=slide_count,
    )
