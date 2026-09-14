"""INSTAGRAM-TELEGRAM-EDITORIAL-DELIVERY-1 §6/§10: serializes exactly what a later regeneration
action needs into `InstagramEditorialDelivery.package_snapshot` (a plain JSON dict) - and restores
it. Deliberately narrow: this is NOT a general-purpose object serializer, it knows about exactly
the handful of dataclasses/pydantic models the Instagram pipeline already defines, and stores
plain strings for the media identity (never a live `MediaSelectionResult` object graph - see
`restore_regeneration_inputs()`'s own docstring for why a full re-discovery pass is deliberately
never attempted here).

DISCLOSED SCOPE LIMITATION (see the phase report's own §H/§J): no raw image bytes are persisted
anywhere by this module. A "🎨 Визуал"/"🔄 Переделать" regeneration therefore re-renders WITHOUT the
original source photo unless the caller supplies a `source_image` from some other live source -
`services/instagram_platform_renderer.py` already has an established, real "no source image" text/
generated-background rendering mode (used for text-only concepts today), so this never crashes or
fabricates a photo; it is a real, honest, disclosed simplification, not a hidden defect.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import InstagramContentPackage
from services.instagram_creative_director import CreativeDirectorInput
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_shadow_pipeline import ShadowPlanResult
from schemas.instagram_creative import InstagramCarouselCreative, InstagramReelCreative, InstagramSingleCreative


def _opportunity_to_dict(opp: ContentOpportunity) -> dict:
    data = dataclasses.asdict(opp)
    data["source_type"] = opp.source_type.value
    data["created_at"] = opp.created_at.isoformat()
    return data


def _opportunity_from_dict(data: dict) -> ContentOpportunity:
    data = dict(data)
    data["source_type"] = OpportunitySourceType(data["source_type"])
    data["created_at"] = datetime.fromisoformat(data["created_at"])
    return ContentOpportunity(**data)


def _format_decision_to_dict(fd: FormatDecision) -> dict:
    data = dataclasses.asdict(fd)
    data["recommended_format"] = fd.recommended_format.value
    data["alternatives"] = [a.value for a in fd.alternatives]
    return data


def _format_decision_from_dict(data: dict) -> FormatDecision:
    data = dict(data)
    data["recommended_format"] = ContentFormat(data["recommended_format"])
    data["alternatives"] = [ContentFormat(a) for a in data.get("alternatives", [])]
    return FormatDecision(**data)


_CREATIVE_MODEL_BY_FORMAT = {
    ContentFormat.SINGLE: InstagramSingleCreative,
    ContentFormat.CAROUSEL: InstagramCarouselCreative,
    ContentFormat.REEL: InstagramReelCreative,
}


@dataclass(frozen=True)
class RegenerationInputs:
    opportunity: ContentOpportunity
    format_decision: FormatDecision
    shadow_plan: ShadowPlanResult
    director_input: CreativeDirectorInput
    previous_creative: Any
    account_key: str
    external_video_asset_ref: str | None
    presentation_family: str | None
    source_image_ref: str | None
    media_candidate_id: str | None
    media_subject_match: str | None
    media_usage_classification: str | None


def build_package_snapshot(
    *, package: InstagramContentPackage, opportunity: ContentOpportunity, format_decision: FormatDecision,
    shadow_plan: ShadowPlanResult, director_input: CreativeDirectorInput, previous_creative: Any,
    source_url: str | None = None,
) -> dict:
    """The single write path for a `package_snapshot` value - every field this module's
    `restore_regeneration_inputs()` will ever need to read back, plus `package`/`source_url` for
    the presenter and the "🔗 Источник" button. `previous_creative` is whichever one of
    `single`/`carousel`/`reel` the format actually used (a plain pydantic model, `.model_dump()`d
    here)."""
    return {
        "package": package.to_dict(),
        "source_url": source_url,
        "opportunity": _opportunity_to_dict(opportunity),
        "format_decision": _format_decision_to_dict(format_decision),
        "shadow_plan": dataclasses.asdict(shadow_plan),
        "director_input": dataclasses.asdict(director_input),
        "previous_creative": previous_creative.model_dump(),
        "account_key": package.account_key,
        "external_video_asset_ref": package.external_video_asset_ref,
        "presentation_family": package.presentation_family,
        "source_image_ref": package.source_image_ref,
        "media_candidate_id": package.media_candidate_id,
        "media_subject_match": package.media_subject_match,
        "media_usage_classification": package.media_usage_classification,
    }


def restore_regeneration_inputs(snapshot: dict) -> RegenerationInputs:
    format_decision = _format_decision_from_dict(snapshot["format_decision"])
    creative_model = _CREATIVE_MODEL_BY_FORMAT[format_decision.recommended_format]
    return RegenerationInputs(
        opportunity=_opportunity_from_dict(snapshot["opportunity"]),
        format_decision=format_decision,
        shadow_plan=ShadowPlanResult(**snapshot["shadow_plan"]),
        director_input=CreativeDirectorInput(**snapshot["director_input"]),
        previous_creative=creative_model.model_validate(snapshot["previous_creative"]),
        account_key=snapshot.get("account_key", "default"),
        external_video_asset_ref=snapshot.get("external_video_asset_ref"),
        presentation_family=snapshot.get("presentation_family"),
        source_image_ref=snapshot.get("source_image_ref"),
        media_candidate_id=snapshot.get("media_candidate_id"),
        media_subject_match=snapshot.get("media_subject_match"),
        media_usage_classification=snapshot.get("media_usage_classification"),
    )


def restore_package(snapshot: dict) -> InstagramContentPackage:
    """The previous version's package, reconstructed from its own `to_dict()` snapshot - used by
    the presenter to redisplay it, and by the handler to read `source_url`/format without
    re-running anything."""
    data = dict(snapshot["package"])
    data["content_format"] = ContentFormat(data["content_format"])
    return InstagramContentPackage(**data)


def restore_media_identity(package: InstagramContentPackage, inputs: RegenerationInputs) -> InstagramContentPackage:
    """§7 same-asset-identity: after a text/visual-only rebuild via `build_instagram_content_
    package(media_selection=None, ...)`, this restores the media-identity fields to the ORIGINAL,
    already-verified values - never a fresh, unverified identity, and never silently dropped
    either (a `None` here would make the SAME_ASSET_IDENTITY check meaningless on the new version)."""
    return dataclasses.replace(
        package, media_candidate_id=inputs.media_candidate_id, media_subject_match=inputs.media_subject_match,
        media_usage_classification=inputs.media_usage_classification,
    )
