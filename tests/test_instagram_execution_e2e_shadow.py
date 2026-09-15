"""INSTAGRAM-EXECUTION-FOUNDATION-1 section 29: ONE deterministic, offline, end-to-end shadow
canary - the full chain from a synthetic/fixture ContentOpportunity through to a shadow
PublicationResult, entirely offline (no AI Gateway call, no network call, no real credential).

    synthetic ContentOpportunity
      -> recommend_objective()                    (real Objective Director)
      -> evaluate_format_shadow()                  (real Format Director)
      -> CreativeGenerationOutcome (FIXTURE - no live Gateway call in a test)
      -> build_shadow_plan()                        (real shadow-plan assembly)
      -> InstagramContentPackage                    (this phase)
      -> render_instagram_feed_image()               (this phase)
      -> InstagramReviewPackage                     (this phase)
      -> validate_instagram_art() + evaluate_instagram_editorial_gate()  (this phase)
      -> publish_instagram_content(shadow=True)      (this phase)
      -> PublicationResult + audit record            (this phase)
"""
from __future__ import annotations

from PIL import Image

import asyncio

import pytest

from services.instagram_art_validator import validate_instagram_art
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import CreativeGenerationOutcome
from services.instagram_editorial_gate import InstagramGateDecision, evaluate_instagram_editorial_gate
from services.instagram_format_director import evaluate_format_shadow
from services.instagram_objective_selection import recommend_objective
from services.instagram_platform_renderer import render_instagram_feed_image
from services.instagram_publication_audit import build_audit_record
from services.instagram_publish_adapter import PublicationStatus, ShadowInstagramPublishClient, publish_instagram_content
from services.instagram_review_package import build_instagram_review_package
from services.instagram_shadow_pipeline import build_shadow_plan
from schemas.instagram_creative import InstagramSingleCreative


@pytest.mark.asyncio
async def test_end_to_end_instagram_shadow_execution() -> None:
    # 1. synthetic/fixture ContentOpportunity - the real, validated dataclass
    opportunity = ContentOpportunity(
        id="e2e-opp-1", source_type=OpportunitySourceType.NEWS, story_id="e2e-story-1", campaign_id="e2e-campaign-1",
        news_value=0.7, campaign_phase="LAUNCH", allowed_claims=["fast charging"],
        restricted_claims=["unreleased_v2_chip"], product_mention_allowed=True,
    )

    # 2. real Objective Director
    objective_recommendation = recommend_objective(opportunity=opportunity)
    assert objective_recommendation.primary_objective.value  # a real decision was made

    # 3. real Format Director (deterministic, structural)
    format_decision = evaluate_format_shadow(objective=objective_recommendation.primary_objective, has_video_asset=False, has_multi_step_narrative=False)

    # 4. Creative Director output - a FIXTURE (no live AI Gateway call in a test; this mirrors the
    #    existing test suite's own convention for this exact reason).
    creative = InstagramSingleCreative(
        creative_angle="A milestone worth telling", visual_concept="Bold number on dark background",
        on_image_copy="500 MILLION USERS", caption_direction="Explain milestone internally", final_caption="Company X reached 500 million users. Here is why it matters.", source_subject="Company X",
        cta="Learn more", evidence_used=[],
    )
    creative_outcome = CreativeGenerationOutcome(single=creative)

    # 5. real shadow-plan assembly (existing, reused verbatim - section 1/23)
    shadow_plan = build_shadow_plan(
        opportunity=opportunity, campaign_name="Product Launch 2026", objective_recommendation=objective_recommendation,
        format_decision=format_decision, audience_description="tech enthusiasts, 18-34", creative_outcome=creative_outcome,
    )
    assert shadow_plan.recommended_format == "single"

    # 6. InstagramContentPackage (this phase)
    package = build_instagram_content_package(
        opportunity=opportunity, format_decision=format_decision, shadow_plan=shadow_plan, creative_outcome=creative_outcome,
        source_image_ref="fixture-source-image",
    )
    assert package.content_format.value == "single"

    # 7. Instagram platform renderer (this phase) - the FIRST previously-missing stage
    render_result = render_instagram_feed_image(package, source_image=Image.new("RGB", (512, 512), "navy"))
    assert render_result.evidence.canvas_width == 1080 and render_result.evidence.canvas_height == 1350
    assert render_result.evidence.visible_brand_mark_count == 1

    # 8. Art validation (this phase)
    art_result = validate_instagram_art(package, [render_result])
    assert art_result.passed is True, art_result.blocking_issues

    # 9. Editorial gate (this phase)
    gate_outcome = evaluate_instagram_editorial_gate(package, art_result, launch_state="live")
    assert gate_outcome.decision is InstagramGateDecision.READY_FOR_EDITOR

    # 10. Review package (this phase) - the real handoff boundary
    review_package = build_instagram_review_package(package=package, render_results=[render_result], art_result=art_result)
    assert review_package.publish_ready is True

    # 11. Shadow publication request + shadow PublicationResult (this phase) - ZERO real network writes
    result = await publish_instagram_content(
        package, gate_outcome, client=ShadowInstagramPublishClient(), account_id="e2e-shadow-account", shadow=True,
        sleep_fn=lambda seconds: asyncio.sleep(0),
    )
    assert result.status is PublicationStatus.SHADOW_SUCCESS
    assert result.shadow is True
    assert result.media_id is not None

    # 12. audit record shape (never written to disk by the test itself - see the canary script for
    #     the on-disk artifact; this proves the record is buildable and serializable)
    record = build_audit_record(result, package)
    assert record["publication_result"]["status"] == "shadow_success"
    assert record["package_summary"]["package_id"] == package.package_id


def test_end_to_end_shadow_execution_makes_zero_real_network_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    def _explode(*args, **kwargs):
        raise AssertionError("the end-to-end SHADOW canary must never perform a real network call")

    monkeypatch.setattr(httpx.AsyncClient, "post", _explode)
    monkeypatch.setattr(httpx.AsyncClient, "get", _explode)
    asyncio.run(test_end_to_end_instagram_shadow_execution())
