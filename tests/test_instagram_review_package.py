"""INSTAGRAM-EXECUTION-FOUNDATION-1 section 27: InstagramReviewPackage creation."""
from __future__ import annotations

import json

from services.instagram_art_validator import validate_instagram_art
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import CreativeGenerationOutcome
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_platform_renderer import render_instagram_feed_image
from services.instagram_review_package import build_instagram_review_package
from services.instagram_shadow_pipeline import ShadowPlanResult
from schemas.instagram_creative import InstagramSingleCreative


def test_review_package_carries_reasoning_media_evidence_and_publish_readiness() -> None:
    opp = ContentOpportunity(
        id="opp-1", source_type=OpportunitySourceType.NEWS, story_id="s1", campaign_id="camp-1",
        product_mention_allowed=True,
    )
    sp = ShadowPlanResult(
        campaign_name="Launch", campaign_phase="LAUNCH", opportunity_description="NEWS opp", primary_objective="reach",
        audience_description="", recommended_format="single", hook_family="curiosity", creative_concept_summary=None,
        alternative_format=None, alternative_objective=None, product_mention_allowed=True,
        evidence=["real evidence bullet"], confidence=0.6,
    )
    single = InstagramSingleCreative(creative_angle="a", visual_concept="v", on_image_copy="500 MILLION", caption_direction="Big milestone", cta="Learn more")
    pkg = build_instagram_content_package(
        opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE, why="reach signal"),
        shadow_plan=sp, creative_outcome=CreativeGenerationOutcome(single=single),
    )
    result = render_instagram_feed_image(pkg)
    art = validate_instagram_art(pkg, [result])
    review = build_instagram_review_package(package=pkg, render_results=[result], art_result=art)

    assert review.package_id == pkg.package_id
    assert review.content_format == "single"
    assert "real evidence bullet" in review.director_reasoning_summary
    assert "reach signal" in review.director_reasoning_summary
    assert review.campaign_context == "Launch, LAUNCH, campaign_id=camp-1"
    assert review.source_refs == {"opportunity_id": "opp-1", "story_id": "s1", "trend_id": None, "campaign_id": "camp-1"}
    assert len(review.media_render_evidence) == 1
    assert review.publish_ready is True
    assert review.validation_failures == []

    # fully JSON-serializable
    json.dumps(review.to_dict())


def test_review_package_reports_failed_validation_honestly() -> None:
    opp = ContentOpportunity(id="opp-2", source_type=OpportunitySourceType.NEWS, story_id="s2", product_mention_allowed=True)
    sp = ShadowPlanResult(
        campaign_name=None, campaign_phase=None, opportunity_description="NEWS opp", primary_objective="reach",
        audience_description="", recommended_format="single", hook_family=None, creative_concept_summary="concept",
        alternative_format=None, alternative_objective=None, product_mention_allowed=True, evidence=[], confidence=0.4,
    )
    pkg = build_instagram_content_package(opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE), shadow_plan=sp)
    art = validate_instagram_art(pkg, [])  # no renders at all -> fails
    review = build_instagram_review_package(package=pkg, render_results=[], art_result=art)
    assert review.publish_ready is False
    assert review.validation_failures
    assert review.media_render_evidence == []
