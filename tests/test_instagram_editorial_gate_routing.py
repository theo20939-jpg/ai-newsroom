"""INSTAGRAM-EXECUTION-FOUNDATION-1 section 27: editorial gate routing (READY_FOR_EDITOR / HOLD /
BLOCK)."""
from __future__ import annotations

from dataclasses import replace
from PIL import Image

from services.instagram_art_validator import validate_instagram_art
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import CreativeGenerationOutcome
from services.instagram_editorial_gate import InstagramGateDecision, evaluate_instagram_editorial_gate
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_platform_renderer import render_instagram_feed_image, render_instagram_reel_cover
from services.instagram_shadow_pipeline import ShadowPlanResult
from schemas.instagram_creative import InstagramSingleCreative, InstagramReelCreative, InstagramReelSceneCreative
from services.instagram_telegram_package_presenter import present_reel

_SOURCE_IMAGE = Image.new("RGB", (512, 512), "navy")

_SP = ShadowPlanResult(
    campaign_name=None, campaign_phase=None, opportunity_description="NEWS opp", primary_objective="reach",
    audience_description="", recommended_format="single", hook_family=None, creative_concept_summary="concept",
    alternative_format=None, alternative_objective=None, product_mention_allowed=True, evidence=[], confidence=0.5,
)


def _clean_package(**opp_overrides) -> tuple:
    opp = ContentOpportunity(id="opp-1", source_type=OpportunitySourceType.NEWS, story_id="s1", product_mention_allowed=True, **opp_overrides)
    single = InstagramSingleCreative(creative_angle="a", visual_concept="v", on_image_copy="A clean headline", caption_direction="Explain the story", final_caption="Company X announced a safe update.", source_subject="Company X", cta="Learn more")
    pkg = build_instagram_content_package(
        opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(single=single), source_image_ref="test-source",
    )
    result = render_instagram_feed_image(pkg, source_image=_SOURCE_IMAGE)
    art = validate_instagram_art(pkg, [result])
    return pkg, art


def test_clean_package_routes_ready_for_editor() -> None:
    pkg, art = _clean_package()
    outcome = evaluate_instagram_editorial_gate(pkg, art)
    assert outcome.decision is InstagramGateDecision.READY_FOR_EDITOR
    assert outcome.permits_publication is True


def test_art_validation_failure_blocks_before_any_claim_check() -> None:
    pkg, _ = _clean_package()
    from services.instagram_art_validator import InstagramArtValidationResult

    failed_art = InstagramArtValidationResult(passed=False, blocking_issues=["missing_brand_mark: x"])
    outcome = evaluate_instagram_editorial_gate(pkg, failed_art)
    assert outcome.decision is InstagramGateDecision.BLOCK
    assert outcome.permits_publication is False
    assert any("art_validation_failed" in code for code in outcome.reason_codes)


def test_restricted_claim_in_text_blocks() -> None:
    opp = ContentOpportunity(
        id="opp-2", source_type=OpportunitySourceType.NEWS, story_id="s2", product_mention_allowed=True,
        restricted_claims=["unreleased chip"],
    )
    single = InstagramSingleCreative(
        creative_angle="a", visual_concept="v", on_image_copy="Our unreleased chip is here",
        caption_direction="Brief about chip", final_caption="Our unreleased chip is here.", source_subject="Our", cta=None,
    )
    pkg = build_instagram_content_package(
        opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(single=single), source_image_ref="test-source",
    )
    result = render_instagram_feed_image(pkg, source_image=_SOURCE_IMAGE)
    art = validate_instagram_art(pkg, [result])
    outcome = evaluate_instagram_editorial_gate(pkg, art)
    assert outcome.decision is InstagramGateDecision.BLOCK
    assert any("restricted_claim_violation" in code for code in outcome.reason_codes)


def test_product_mention_not_allowed_blocks() -> None:
    opp = ContentOpportunity(
        id="opp-3", source_type=OpportunitySourceType.NEWS, story_id="s3", product_mention_allowed=False,
        restricted_claims=["Ninja Widget Pro"],
    )
    single = InstagramSingleCreative(
        creative_angle="a", visual_concept="v", on_image_copy="Meet the Ninja Widget Pro",
        caption_direction="Brief about product", final_caption="Meet the Ninja Widget Pro.", source_subject="Ninja Widget Pro", cta=None,
    )
    pkg = build_instagram_content_package(
        opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(single=single), source_image_ref="test-source",
    )
    result = render_instagram_feed_image(pkg, source_image=_SOURCE_IMAGE)
    art = validate_instagram_art(pkg, [result])
    outcome = evaluate_instagram_editorial_gate(pkg, art)
    assert outcome.decision is InstagramGateDecision.BLOCK


def test_pre_launch_state_holds_never_blocks_for_content_reasons() -> None:
    pkg, art = _clean_package()
    outcome = evaluate_instagram_editorial_gate(pkg, art, launch_state="pre_launch")
    assert outcome.decision is InstagramGateDecision.HOLD
    assert outcome.permits_publication is False
    assert any("launch_state" in code for code in outcome.reason_codes)


def test_transition_state_also_holds() -> None:
    pkg, art = _clean_package()
    outcome = evaluate_instagram_editorial_gate(pkg, art, launch_state="transition")
    assert outcome.decision is InstagramGateDecision.HOLD


def test_live_state_with_clean_content_is_ready_for_editor() -> None:
    pkg, art = _clean_package()
    outcome = evaluate_instagram_editorial_gate(pkg, art, launch_state="live")
    assert outcome.decision is InstagramGateDecision.READY_FOR_EDITOR


def test_only_ready_for_editor_permits_publication() -> None:
    pkg, art = _clean_package()
    ready = evaluate_instagram_editorial_gate(pkg, art)
    hold = evaluate_instagram_editorial_gate(pkg, art, launch_state="pre_launch")
    assert ready.permits_publication is True
    assert hold.permits_publication is False


def test_caption_marked_draft_holds_even_with_valid_media() -> None:
    pkg, art = _clean_package()
    draft = replace(pkg, caption_is_draft=True)
    gate = evaluate_instagram_editorial_gate(draft, art)
    assert gate.decision is InstagramGateDecision.HOLD
    assert "final_caption_missing_or_draft" in gate.reason_codes


def test_named_news_subject_must_survive_in_final_copy() -> None:
    pkg, art = _clean_package()
    vague = replace(pkg, caption="A generic update happened.")
    gate = evaluate_instagram_editorial_gate(vague, art)
    assert gate.decision is InstagramGateDecision.HOLD
    assert "source_subject_absent_from_caption" in gate.reason_codes


def _ready_reel_package():
    opp = ContentOpportunity(id="reel-opp", source_type=OpportunitySourceType.NEWS, story_id="story-reel")
    reel = InstagramReelCreative(
        objective="reach", hook="Company X changed the story", target_duration_seconds=20,
        scene_sequence=["Opening", "Closing"], pacing="brisk", caption_direction="internal brief",
        final_caption="Company X announced a real update.", source_subject="Company X",
        scenes=[
            InstagramReelSceneCreative(start_seconds=0, end_seconds=10, spoken_line="Company X announced a real update.", on_screen_text="Company X", visual_direction="Show the real announcement."),
            InstagramReelSceneCreative(start_seconds=10, end_seconds=20, spoken_line="Here is what Company X changed.", on_screen_text="What changed", visual_direction="Show the product detail and end on the source."),
        ],
        loop_ending_concept="Close on the changed feature and source.",
    )
    package = build_instagram_content_package(
        opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.REEL),
        shadow_plan=_SP, creative_outcome=CreativeGenerationOutcome(reel=reel),
        reel_script_readiness="production_script",
    )
    cover = render_instagram_reel_cover(package)
    return package, cover, validate_instagram_art(package, [cover])


def test_finished_reel_script_passes_without_a_video_file() -> None:
    pkg, cover, art = _ready_reel_package()
    assert pkg.content_format is ContentFormat.REEL
    assert pkg.external_video_asset_ref is None
    assert evaluate_instagram_editorial_gate(pkg, art).decision is InstagramGateDecision.READY_FOR_EDITOR
    presentation = present_reel(pkg, cover, version=1)
    assert presentation.kind == "reel_script"
    assert "REEL-КОНЦЕПТ" not in presentation.control_text
    assert "0–10" in presentation.control_text
    assert "Company X announced" in presentation.control_text
    assert pkg.content_format is ContentFormat.REEL


def test_null_hook_and_concept_readiness_hold_reel() -> None:
    pkg, _, art = _ready_reel_package()
    no_hook = replace(pkg, media_plan={**pkg.media_plan, "hook": None})
    assert "reel_hook_missing" in evaluate_instagram_editorial_gate(no_hook, art).reason_codes
    concept = replace(pkg, reel_script_readiness="concept_script")
    assert "reel_not_production_script" in evaluate_instagram_editorial_gate(concept, art).reason_codes


def test_reel_requires_timings_and_spoken_lines() -> None:
    pkg, _, art = _ready_reel_package()
    bad_scenes = [dict(scene) for scene in pkg.media_plan["scenes"]]
    bad_scenes[1]["start_seconds"] = 12
    bad_scenes[1]["spoken_line"] = ""
    incomplete = replace(pkg, media_plan={**pkg.media_plan, "scenes": bad_scenes})
    reasons = evaluate_instagram_editorial_gate(incomplete, art).reason_codes
    assert "reel_scene_timing_invalid" in reasons
