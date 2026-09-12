"""INSTAGRAM-EXECUTION-FOUNDATION-1 section 27: editorial gate routing (READY_FOR_EDITOR / HOLD /
BLOCK)."""
from __future__ import annotations

from services.instagram_art_validator import validate_instagram_art
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import CreativeGenerationOutcome
from services.instagram_editorial_gate import InstagramGateDecision, evaluate_instagram_editorial_gate
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_platform_renderer import render_instagram_feed_image
from services.instagram_shadow_pipeline import ShadowPlanResult
from schemas.instagram_creative import InstagramSingleCreative

_SP = ShadowPlanResult(
    campaign_name=None, campaign_phase=None, opportunity_description="NEWS opp", primary_objective="reach",
    audience_description="", recommended_format="single", hook_family=None, creative_concept_summary="concept",
    alternative_format=None, alternative_objective=None, product_mention_allowed=True, evidence=[], confidence=0.5,
)


def _clean_package(**opp_overrides) -> tuple:
    opp = ContentOpportunity(id="opp-1", source_type=OpportunitySourceType.NEWS, story_id="s1", product_mention_allowed=True, **opp_overrides)
    single = InstagramSingleCreative(creative_angle="a", visual_concept="v", on_image_copy="A clean headline", caption_direction="A safe caption", cta="Learn more")
    pkg = build_instagram_content_package(
        opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(single=single),
    )
    result = render_instagram_feed_image(pkg)
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
        caption_direction="Details about the unreleased chip", cta=None,
    )
    pkg = build_instagram_content_package(
        opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(single=single),
    )
    result = render_instagram_feed_image(pkg)
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
        caption_direction="A look at the Ninja Widget Pro", cta=None,
    )
    pkg = build_instagram_content_package(
        opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(single=single),
    )
    result = render_instagram_feed_image(pkg)
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
