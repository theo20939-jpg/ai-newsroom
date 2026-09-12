"""INSTAGRAM-EXECUTION-FOUNDATION-1 section 27: InstagramContentPackage assembly + serialization."""
from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import (
    build_instagram_content_package,
)
from services.instagram_creative_director import CreativeGenerationOutcome
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_shadow_pipeline import ShadowPlanResult
from schemas.instagram_creative import (
    InstagramCarouselCreative,
    InstagramCarouselSlideCreative,
    InstagramReelCreative,
    InstagramSingleCreative,
)

_BASE_OPPORTUNITY = ContentOpportunity(
    id="opp-1", source_type=OpportunitySourceType.NEWS, story_id="story-1", campaign_id="camp-1",
    product_mention_allowed=True, allowed_claims=["fast charging"], restricted_claims=["unreleased_v2_chip"],
)

_BASE_SHADOW_PLAN = ShadowPlanResult(
    campaign_name="Product Launch", campaign_phase="LAUNCH", opportunity_description="NEWS opportunity",
    primary_objective="reach", audience_description="tech enthusiasts", recommended_format="single",
    hook_family="curiosity", creative_concept_summary="a strong concept", alternative_format=None,
    alternative_objective=None, product_mention_allowed=True, evidence=["evidence bullet 1"], confidence=0.65,
)


def _opportunity(**overrides: Any) -> ContentOpportunity:
    return replace(_BASE_OPPORTUNITY, **overrides)


def _shadow_plan(**overrides: Any) -> ShadowPlanResult:
    return replace(_BASE_SHADOW_PLAN, **overrides)


def test_single_package_uses_real_creative_director_fields_verbatim() -> None:
    single = InstagramSingleCreative(
        creative_angle="angle", visual_concept="concept", on_image_copy="500 MILLION USERS",
        caption_direction="A real milestone worth sharing", cta="Learn more",
    )
    pkg = build_instagram_content_package(
        opportunity=_opportunity(), format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE, why="reach"),
        shadow_plan=_shadow_plan(), creative_outcome=CreativeGenerationOutcome(single=single),
    )
    assert pkg.content_format is ContentFormat.SINGLE
    assert pkg.on_image_copy == "500 MILLION USERS"
    assert pkg.caption == "A real milestone worth sharing"  # verbatim caption_direction, never rewritten
    assert pkg.cta == "Learn more"
    assert pkg.caption_is_draft is True
    assert pkg.render_profiles == ["portrait_feed"]
    assert pkg.slide_count is None
    assert pkg.hashtags == []  # never fabricated - no schema field produces them


def test_carousel_package_carries_every_slide_and_a_single_package_caption() -> None:
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Hook copy", visual_direction="v1"),
        InstagramCarouselSlideCreative(role="body", slide_copy="Body copy", visual_direction="v2"),
        InstagramCarouselSlideCreative(role="cta", slide_copy="CTA copy", visual_direction="v3"),
    ]
    carousel = InstagramCarouselCreative(objective="saves", slides=slides, final_cta="Swipe for more")
    pkg = build_instagram_content_package(
        opportunity=_opportunity(), format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL),
        shadow_plan=_shadow_plan(recommended_format="carousel"), creative_outcome=CreativeGenerationOutcome(carousel=carousel),
    )
    assert pkg.slide_count == 3
    assert pkg.render_profiles == ["carousel_slide", "carousel_slide", "carousel_slide"]
    assert pkg.caption == "Hook copy"  # single package-level caption, anchored on the hook slide
    assert len(pkg.media_plan["slides"]) == 3
    assert pkg.media_plan["slides"][0]["role"] == "hook"


def test_carousel_below_two_slides_is_rejected_upstream_not_silently_accepted() -> None:
    with pytest.raises(ValueError):
        InstagramCarouselCreative(objective="saves", slides=[InstagramCarouselSlideCreative(role="hook", slide_copy="x", visual_direction="y")])


def test_reel_package_requires_external_video_asset_flag() -> None:
    reel = InstagramReelCreative(
        objective="reach", hook="Watch this", target_duration_seconds=20, scene_sequence=["s1", "s2"],
        pacing="fast", caption_direction="Reel caption", cta="Watch now",
    )
    pkg = build_instagram_content_package(
        opportunity=_opportunity(), format_decision=FormatDecision(recommended_format=ContentFormat.REEL),
        shadow_plan=_shadow_plan(recommended_format="reel"), creative_outcome=CreativeGenerationOutcome(reel=reel),
    )
    assert pkg.external_video_asset_ref is None
    assert pkg.media_plan["requires_external_video_asset"] is True  # never silently claims video capability
    assert pkg.render_profiles == ["reel_cover"]

    pkg2 = build_instagram_content_package(
        opportunity=_opportunity(), format_decision=FormatDecision(recommended_format=ContentFormat.REEL),
        shadow_plan=_shadow_plan(recommended_format="reel"), creative_outcome=CreativeGenerationOutcome(reel=reel),
        external_video_asset_ref="s3://bucket/pre-rendered-reel.mp4",
    )
    assert pkg2.external_video_asset_ref == "s3://bucket/pre-rendered-reel.mp4"
    assert "requires_external_video_asset" not in pkg2.media_plan


def test_package_without_creative_outcome_uses_only_the_structural_shadow_summary() -> None:
    pkg = build_instagram_content_package(
        opportunity=_opportunity(), format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE),
        shadow_plan=_shadow_plan(creative_concept_summary="structural summary only"),
    )
    assert pkg.caption == "structural summary only"
    assert pkg.on_image_copy is None
    assert "no CreativeGenerationOutcome supplied" in pkg.media_plan["note"]


def test_package_never_duplicates_campaign_plan_or_business_context_wholesale() -> None:
    pkg = build_instagram_content_package(
        opportunity=_opportunity(), format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE),
        shadow_plan=_shadow_plan(),
    )
    d = pkg.to_dict()
    # only reference fields are present - no nested CampaignPlan/BusinessContextSnapshot object
    assert set(["campaign_id", "campaign_name", "campaign_phase"]).issubset(d.keys())
    assert "business_context_snapshot" not in d
    assert "campaign_plan" not in d


def test_to_dict_is_fully_json_serializable_and_deterministic() -> None:
    pkg = build_instagram_content_package(
        opportunity=_opportunity(), format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE, why="x"),
        shadow_plan=_shadow_plan(),
    )
    encoded = json.dumps(pkg.to_dict(), sort_keys=True)  # raises if anything is non-serializable
    decoded = json.loads(encoded)
    assert decoded["package_id"] == pkg.package_id
    assert decoded["content_format"] == "single"
    assert decoded["schema_version"] == "v1"


def test_claim_check_fields_cover_caption_on_image_copy_cta_and_slides() -> None:
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Never mention the unreleased chip", visual_direction="v1"),
        InstagramCarouselSlideCreative(role="body", slide_copy="Body copy", visual_direction="v2"),
    ]
    carousel = InstagramCarouselCreative(objective="saves", slides=slides, final_cta=None)
    pkg = build_instagram_content_package(
        opportunity=_opportunity(), format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL),
        shadow_plan=_shadow_plan(recommended_format="carousel"), creative_outcome=CreativeGenerationOutcome(carousel=carousel),
    )
    fields = pkg.text_fields_for_claim_check
    assert any("unreleased chip" in f for f in fields)
    assert "Body copy" in fields
