"""INSTAGRAM-EXECUTION-FOUNDATION-1 section 29/30 - the offline end-to-end shadow canary + local
review package for Founder inspection.

Renders representative outputs for every MVP format (FEED_IMAGE, CAROUSEL, REEL cover) from a
synthetic ContentOpportunity, through the real Director planning chain (fixture Creative Director
output - no live AI Gateway call), the new Instagram renderer, Art validation, the editorial gate,
and a SHADOW publish (zero real network writes). Writes everything to
artifacts/instagram_execution_foundation_1/ - never published, never a real Instagram write.

    python scripts/_instagram_execution_foundation_1_canary.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.instagram_art_validator import validate_instagram_art  # noqa: E402
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType  # noqa: E402
from services.instagram_content_package import build_instagram_content_package  # noqa: E402
from services.instagram_creative_director import CreativeGenerationOutcome  # noqa: E402
from services.instagram_editorial_gate import evaluate_instagram_editorial_gate  # noqa: E402
from services.instagram_format_director import ContentFormat, FormatDecision  # noqa: E402
from services.instagram_objective_selection import recommend_objective  # noqa: E402
from services.instagram_platform_renderer import (  # noqa: E402
    render_instagram_carousel,
    render_instagram_feed_image,
    render_instagram_reel_cover,
)
from services.instagram_publication_audit import append_publication_audit_record  # noqa: E402
from services.instagram_publish_adapter import ShadowInstagramPublishClient, publish_instagram_content  # noqa: E402
from services.instagram_review_package import build_instagram_review_package  # noqa: E402
from services.instagram_shadow_pipeline import build_shadow_plan, render_shadow_plan_text  # noqa: E402
from schemas.instagram_creative import (  # noqa: E402
    InstagramCarouselCreative,
    InstagramCarouselSlideCreative,
    InstagramReelCreative,
    InstagramSingleCreative,
)

REPO = Path(__file__).resolve().parents[1]
ART = REPO / "artifacts" / "instagram_execution_foundation_1"


async def _run_one(*, tag: str, opportunity: ContentOpportunity, fmt: ContentFormat, creative_outcome, external_video_asset_ref=None):
    objective_recommendation = recommend_objective(opportunity=opportunity)
    format_decision = FormatDecision(recommended_format=fmt, why=f"canary fixture for {fmt.value}", confidence=0.5)
    shadow_plan = build_shadow_plan(
        opportunity=opportunity, campaign_name="NINJA Launch 2026", objective_recommendation=objective_recommendation,
        format_decision=format_decision, audience_description="AI-curious tech audience, 18-34",
        creative_outcome=creative_outcome,
    )
    (ART / f"{tag}_shadow_plan.txt").write_text(render_shadow_plan_text(shadow_plan), encoding="utf-8")

    package = build_instagram_content_package(
        opportunity=opportunity, format_decision=format_decision, shadow_plan=shadow_plan,
        creative_outcome=creative_outcome, external_video_asset_ref=external_video_asset_ref,
    )

    if fmt is ContentFormat.SINGLE:
        renders = [render_instagram_feed_image(package)]
    elif fmt is ContentFormat.CAROUSEL:
        renders = render_instagram_carousel(package)
    else:
        renders = [render_instagram_reel_cover(package)]

    for i, r in enumerate(renders):
        suffix = f"_slide{i}" if len(renders) > 1 else ""
        (ART / f"{tag}{suffix}.jpg").write_bytes(r.image_bytes)

    art_result = validate_instagram_art(package, renders)
    gate_outcome = evaluate_instagram_editorial_gate(package, art_result, launch_state="live")
    review_package = build_instagram_review_package(package=package, render_results=renders, art_result=art_result)
    (ART / f"{tag}_review_package.json").write_text(json.dumps(review_package.to_dict(), indent=2, sort_keys=True), encoding="utf-8")

    publish_result = await publish_instagram_content(
        package, gate_outcome, client=ShadowInstagramPublishClient(), account_id="canary_shadow_account", shadow=True,
        sleep_fn=lambda seconds: asyncio.sleep(0),
    )
    append_publication_audit_record(publish_result, package, path=ART / f"{tag}_publication_audit.jsonl")

    print(
        f"{tag:10s} format={fmt.value:9s} gate={gate_outcome.decision.value:16s} "
        f"art_passed={art_result.passed!s:5s} publish={publish_result.status.value}"
    )
    return package, art_result, gate_outcome, publish_result


async def main() -> None:
    ART.mkdir(parents=True, exist_ok=True)

    # -- FEED_IMAGE ---------------------------------------------------------------------------
    feed_opp = ContentOpportunity(
        id="canary-feed-1", source_type=OpportunitySourceType.NEWS, story_id="canary-story-1", campaign_id="canary-campaign-1",
        news_value=0.7, campaign_phase="LAUNCH", allowed_claims=["fast on-device inference"],
        restricted_claims=["unreleased_v2_chip"], product_mention_allowed=True,
    )
    feed_creative = InstagramSingleCreative(
        creative_angle="A milestone worth telling", visual_concept="Bold number, dark background, minimal type",
        on_image_copy="500 MILLION USERS", caption_direction="We just reached a huge milestone together - thank you for being part of it.",
        cta="Learn more",
    )
    await _run_one(tag="01_feed", opportunity=feed_opp, fmt=ContentFormat.SINGLE, creative_outcome=CreativeGenerationOutcome(single=feed_creative))

    # -- CAROUSEL -------------------------------------------------------------------------------
    carousel_opp = ContentOpportunity(
        id="canary-carousel-1", source_type=OpportunitySourceType.NEWS, story_id="canary-story-2", campaign_id="canary-campaign-1",
        news_value=0.5, campaign_phase="AWARENESS", product_mention_allowed=True,
    )
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="Why this launch matters", visual_direction="bold headline, dark bg"),
        InstagramCarouselSlideCreative(role="context", slide_copy="The problem we set out to solve", visual_direction="supporting copy"),
        InstagramCarouselSlideCreative(role="data", slide_copy="The numbers behind the launch", visual_direction="stat callout"),
        InstagramCarouselSlideCreative(role="cta", slide_copy="Follow along for what's next", visual_direction="closing frame"),
    ]
    carousel_creative = InstagramCarouselCreative(objective="saves", slides=slides, final_cta="Swipe to learn more")
    await _run_one(tag="02_carousel", opportunity=carousel_opp, fmt=ContentFormat.CAROUSEL, creative_outcome=CreativeGenerationOutcome(carousel=carousel_creative))

    # -- REEL (cover only - no video generator; external pre-rendered asset reference supplied) --
    reel_opp = ContentOpportunity(
        id="canary-reel-1", source_type=OpportunitySourceType.NEWS, story_id="canary-story-3", campaign_id="canary-campaign-1",
        news_value=0.6, campaign_phase="LAUNCH", product_mention_allowed=True,
    )
    reel_creative = InstagramReelCreative(
        objective="reach", hook="This changes everything", target_duration_seconds=18,
        scene_sequence=["open on product", "reveal the number", "close on the brand mark"],
        pacing="fast, three beats", caption_direction="A fast look at the milestone.", cta="Watch to the end",
    )
    await _run_one(
        tag="03_reel_cover", opportunity=reel_opp, fmt=ContentFormat.REEL, creative_outcome=CreativeGenerationOutcome(reel=reel_creative),
        external_video_asset_ref="external://pre-rendered/reel-canary-1.mp4",
    )

    print(f"\nwrote review package to {ART}")


if __name__ == "__main__":
    asyncio.run(main())
