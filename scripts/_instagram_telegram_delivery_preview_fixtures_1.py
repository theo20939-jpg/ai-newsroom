"""INSTAGRAM-TELEGRAM-EDITORIAL-DELIVERY-1 §24: production-shaped fixture previews. Never
auto-run (not wired into any worker/scheduler/CI) - a one-off, manually-invoked generator that
builds one single-image NEWS package, one approved carousel package, and one Reel-package fixture
through the REAL pipeline (build_instagram_content_package -> render -> art validation -> gate ->
presenter), then writes each fixture's rendered image(s) + exact Telegram control-message text to
`artifacts/instagram_telegram_editorial_delivery_1/` so a reviewer can see exactly what an editor
would receive in the "instagram" Telegram topic, without needing a live bot/topic id configured.

Zero network writes, zero Telegram API calls, zero Instagram API calls."""
from __future__ import annotations

import json
from pathlib import Path

from schemas.instagram_creative import InstagramCarouselCreative, InstagramCarouselSlideCreative, InstagramReelCreative, InstagramSingleCreative
from services.instagram_art_validator import validate_instagram_art
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import CreativeGenerationOutcome
from services.instagram_editorial_gate import evaluate_instagram_editorial_gate
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_platform_renderer import render_instagram_carousel, render_instagram_feed_image, render_instagram_reel_cover
from services.instagram_shadow_pipeline import ShadowPlanResult
from services.instagram_telegram_package_presenter import present_carousel, present_reel, present_single

_OUT_DIR = Path(__file__).resolve().parent.parent / "artifacts" / "instagram_telegram_editorial_delivery_1"

_SP = ShadowPlanResult(
    campaign_name=None, campaign_phase=None, opportunity_description="real-shaped NEWS opportunity",
    primary_objective="reach", audience_description="tech-interested Russian-speaking audience",
    recommended_format="single", hook_family=None, creative_concept_summary="concept", alternative_format=None,
    alternative_objective=None, product_mention_allowed=False, evidence=[], confidence=0.6,
)


def _write_fixture(name: str, presentation, summary: dict) -> None:
    fixture_dir = _OUT_DIR / name
    fixture_dir.mkdir(parents=True, exist_ok=True)
    for i, media_bytes in enumerate(presentation.media):
        (fixture_dir / f"media_{i + 1}.jpg").write_bytes(media_bytes)
    (fixture_dir / "control_message.html.txt").write_text(presentation.control_text, encoding="utf-8")
    if presentation.overflow_text:
        (fixture_dir / "overflow_message.html.txt").write_text(presentation.overflow_text, encoding="utf-8")
    summary["media_count"] = len(presentation.media)
    summary["kind"] = presentation.kind
    (fixture_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote fixture: {fixture_dir}")


def build_single_news_fixture() -> None:
    opp = ContentOpportunity(id="fixture-single-news", source_type=OpportunitySourceType.NEWS, story_id="story-fixture-1", product_mention_allowed=False)
    single = InstagramSingleCreative(
        creative_angle="Big product announcement", visual_concept="Bold headline over dark gradient",
        on_image_copy="ASML Books EUV Capacity Through 2027", caption_direction=(
            "ASML's newest lithography order book is full through 2027, as chip demand from AI "
            "accelerators keeps outpacing supply. The company says a new fab is already under construction."
        ), cta="Read more in comments",
    )
    pkg = build_instagram_content_package(
        opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(single=single), hashtags=["semiconductors", "AI", "ASML"],
        media_selection=None, source_image_ref="fixture:asml-euv-scanner-photo",
    )
    render = render_instagram_feed_image(pkg)
    art = validate_instagram_art(pkg, [render])
    gate = evaluate_instagram_editorial_gate(pkg, art)
    presentation = present_single(pkg, render, version=1)
    _write_fixture("single_news", presentation, {"gate_decision": gate.decision.value, "package_id": pkg.package_id})


def build_carousel_fixture() -> None:
    opp = ContentOpportunity(id="fixture-carousel", source_type=OpportunitySourceType.NEWS, story_id="story-fixture-2", product_mention_allowed=False)
    slides = [
        InstagramCarouselSlideCreative(role="hook", slide_copy="China warns AI is the new great-power battleground", visual_direction="dark hook slide"),
        InstagramCarouselSlideCreative(role="body", slide_copy="State Security says AI poses risks to political stability", visual_direction="data slide"),
        InstagramCarouselSlideCreative(role="cta", slide_copy="Swipe for the full picture", visual_direction="cta slide"),
    ]
    carousel = InstagramCarouselCreative(objective="saves", slides=slides, final_cta="Follow for daily AI geopolitics")
    pkg = build_instagram_content_package(
        opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(carousel=carousel), hashtags=["AI", "geopolitics", "China"],
    )
    renders = render_instagram_carousel(pkg)
    art = validate_instagram_art(pkg, renders)
    gate = evaluate_instagram_editorial_gate(pkg, art)
    presentation = present_carousel(pkg, renders, version=1)
    _write_fixture("carousel", presentation, {"gate_decision": gate.decision.value, "package_id": pkg.package_id, "slide_count": len(renders)})


def build_reel_package_fixture() -> None:
    opp = ContentOpportunity(id="fixture-reel", source_type=OpportunitySourceType.NEWS, story_id="story-fixture-3", product_mention_allowed=False)
    reel = InstagramReelCreative(
        objective="reach", hook="They raced to build AI. Now it's moving too fast even for them.",
        target_duration_seconds=25, scene_sequence=[
            "Open on a fast-cut montage of AI headlines",
            "Cut to a researcher looking concerned",
            "Text overlay: 'Even insiders are worried'",
            "End on the NINJA PULSE logo card",
        ], shot_list=["stock AI b-roll", "talking-head reaction clip", "text-overlay card"],
        voiceover_script="They raced to build it. Now they say it's going too fast.",
        pacing="fast cuts, sub-2s per shot", cta="Follow for the full story",
        caption_direction="Even the people building AI are starting to worry about the pace. Full story in the next post.",
    )
    pkg = build_instagram_content_package(
        opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.REEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(reel=reel),
    )
    cover = render_instagram_reel_cover(pkg)
    art = validate_instagram_art(pkg, [cover])
    gate = evaluate_instagram_editorial_gate(pkg, art)
    presentation = present_reel(pkg, cover, version=1)
    _write_fixture("reel_package", presentation, {"gate_decision": gate.decision.value, "package_id": pkg.package_id})


if __name__ == "__main__":
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    build_single_news_fixture()
    build_carousel_fixture()
    build_reel_package_fixture()
