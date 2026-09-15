"""INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1 §7/§10/§15: the unified media-truthfulness/rights
pipeline actually wired into Instagram. No real network call anywhere in this file."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from PIL import Image

from schemas.media_intent import DesiredVisualType, MediaIntent, MediaSubjectType
from schemas.media_subject_match import (
    DiscoveryTier,
    MediaProvenance,
    MediaUsageClassification,
    ResolvedMediaCandidate,
    SubjectMatchClassification,
    SubjectMatchValidation,
)
from services.editorial_pipeline.evidence import build_evidence_pack
from services.editorial_pipeline.platforms.instagram import evaluate_instagram_package
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import CreativeGenerationOutcome
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_media_safety import resolve_instagram_media
from services.instagram_platform_renderer import render_instagram_feed_image
from services.instagram_shadow_pipeline import ShadowPlanResult
from schemas.instagram_creative import InstagramSingleCreative

_OPPORTUNITY = ContentOpportunity(
    id="opp-1", source_type=OpportunitySourceType.NEWS, story_id="story-1", campaign_id="camp-1",
    product_mention_allowed=True, allowed_claims=["fast charging"], restricted_claims=[],
)
_SHADOW_PLAN = ShadowPlanResult(
    campaign_name="Product Launch", campaign_phase="LAUNCH", opportunity_description="NEWS opportunity",
    primary_objective="reach", audience_description="tech enthusiasts", recommended_format="single",
    hook_family="curiosity", creative_concept_summary="a strong concept", alternative_format=None,
    alternative_objective=None, product_mention_allowed=True, evidence=["evidence bullet 1"], confidence=0.65,
)

_FOLDABLE_INTENT = MediaIntent(
    subject_type=MediaSubjectType.PRODUCT, primary_entity="foldable iPhone", product_name="iPhone",
    model_name="foldable iPhone", must_show=["foldable design"], must_not_imply=["standard non-folding design"],
    desired_visual_type=DesiredVisualType.PRODUCT_PHOTO,
)


def _candidate(
    candidate_id: str, *, caption_or_alt: str | None = None,
    usage: MediaUsageClassification = MediaUsageClassification.APPROVED_SOURCE_MEDIA,
) -> ResolvedMediaCandidate:
    return ResolvedMediaCandidate(
        candidate_id=candidate_id,
        provenance=MediaProvenance(
            origin_url=f"https://example.com/{candidate_id}", asset_url=f"https://example.com/{candidate_id}.jpg",
            discovered_at=datetime.now(timezone.utc), discovery_tier=DiscoveryTier.TIER1_CURRENT_SOURCE,
            caption_or_alt=caption_or_alt,
        ),
        usage_classification=usage,
    )


def _build_package(caption: str, media_selection=None):
    single = InstagramSingleCreative(
        creative_angle="angle", visual_concept="concept", on_image_copy="FOLDABLE IPHONE",
        caption_direction="Internal direction", final_caption=caption, source_subject="foldable iPhone", cta="Learn more",
    )
    return build_instagram_content_package(
        opportunity=_OPPORTUNITY, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE, why="reach"),
        shadow_plan=_SHADOW_PLAN, creative_outcome=CreativeGenerationOutcome(single=single),
        media_selection=media_selection,
    )


# ---------------------------------------------------------------------------
# §7 - resolve_instagram_media() reuses the SAME authority Telegram uses.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mismatch_candidate_never_becomes_selected() -> None:
    wrong = _candidate("wrong-iphone", caption_or_alt="standard non-folding design iPhone 16 Pro")
    correct = _candidate("real-foldable", caption_or_alt="foldable iPhone foldable design shown folded and unfolded")
    selection = await resolve_instagram_media(_FOLDABLE_INTENT, tier1_candidates=[wrong, correct])
    assert selection.selected is not None
    assert selection.selected.candidate_id == "real-foldable"
    assert selection.selected.candidate_id != "wrong-iphone"


@pytest.mark.asyncio
async def test_not_usable_candidate_never_becomes_selected() -> None:
    not_usable = _candidate("stock-photo", usage=MediaUsageClassification.NOT_USABLE, caption_or_alt="foldable iPhone foldable design")
    selection = await resolve_instagram_media(_FOLDABLE_INTENT, tier1_candidates=[not_usable])
    assert selection.selected is None


@pytest.mark.asyncio
async def test_editorial_review_required_candidate_never_becomes_selected() -> None:
    review_required = _candidate(
        "needs-review", usage=MediaUsageClassification.EDITORIAL_REVIEW_REQUIRED,
        caption_or_alt="foldable iPhone foldable design shown folded and unfolded",
    )
    selection = await resolve_instagram_media(_FOLDABLE_INTENT, tier1_candidates=[review_required])
    assert selection.selected is None


@pytest.mark.asyncio
async def test_exact_subject_candidate_flows_through_to_the_package() -> None:
    correct = _candidate("real-foldable-2", caption_or_alt="foldable iPhone foldable design shown folded and unfolded")
    selection = await resolve_instagram_media(_FOLDABLE_INTENT, tier1_candidates=[correct])
    assert selection.selected is not None

    package = _build_package("A real foldable iPhone announcement.", media_selection=selection)
    assert package.media_candidate_id == "real-foldable-2"
    assert package.media_subject_match == SubjectMatchClassification.EXACT_SUBJECT.value
    assert package.source_image_ref == "real-foldable-2"


@pytest.mark.asyncio
async def test_no_media_selection_supplied_is_fully_backward_compatible() -> None:
    package = _build_package("A real foldable iPhone announcement.")
    assert package.media_candidate_id is None
    assert package.media_subject_match is None
    assert package.media_usage_classification is None


# ---------------------------------------------------------------------------
# §10/§15 - defense-in-depth: even a MISMATCH/NOT_USABLE that somehow reached `selected` must be
# BLOCKed by the shared quality gate, never quietly published. (`is_selectable()` already prevents
# this from happening in the first place - this proves the SECOND, independent layer too, mirroring
# exactly how Telegram is proven at both layers.)
# ---------------------------------------------------------------------------


def _fake_selection(candidate):
    from schemas.media_subject_match import MediaSelectionResult

    return MediaSelectionResult(
        intent_primary_entity="x", selected=candidate, selected_score=10.0,
        exact_subject_media_not_found=False, fallback_used=False, candidates_considered=1,
    )


def test_mismatch_selected_candidate_blocks_at_the_gate_defense_in_depth() -> None:
    mismatch_candidate = ResolvedMediaCandidate(
        candidate_id="somehow-mismatch",
        provenance=MediaProvenance(
            origin_url="https://example.com/a", asset_url="https://example.com/a.jpg",
            discovered_at=datetime.now(timezone.utc), discovery_tier=DiscoveryTier.TIER1_CURRENT_SOURCE,
        ),
        usage_classification=MediaUsageClassification.APPROVED_SOURCE_MEDIA,
        subject_match=SubjectMatchValidation(
            depicted_subject_description="wrong subject", subject_match=SubjectMatchClassification.MISMATCH,
            must_not_imply_violated=True, reason="test-forced mismatch",
        ),
    )
    package = _build_package("A real foldable iPhone announcement.", media_selection=_fake_selection(mismatch_candidate))
    render_result = render_instagram_feed_image(package)
    evidence = build_evidence_pack(news_event_id=uuid4(), story_id=None, source_url=None, research_facts=[])

    gate_result, recovery = evaluate_instagram_package(
        package=package, render_results=[render_result], evidence=evidence, content_draft_id=uuid4(),
        media_selection=_fake_selection(mismatch_candidate),
    )
    assert gate_result.verdict.value == "BLOCK"
    assert recovery is not None


def test_not_usable_selected_candidate_blocks_at_the_gate_defense_in_depth() -> None:
    not_usable_candidate = ResolvedMediaCandidate(
        candidate_id="somehow-not-usable",
        provenance=MediaProvenance(
            origin_url="https://example.com/a", asset_url="https://example.com/a.jpg",
            discovered_at=datetime.now(timezone.utc), discovery_tier=DiscoveryTier.TIER1_CURRENT_SOURCE,
        ),
        usage_classification=MediaUsageClassification.NOT_USABLE,
    )
    package = _build_package("A real foldable iPhone announcement.", media_selection=_fake_selection(not_usable_candidate))
    render_result = render_instagram_feed_image(package)
    evidence = build_evidence_pack(news_event_id=uuid4(), story_id=None, source_url=None, research_facts=[])

    gate_result, recovery = evaluate_instagram_package(
        package=package, render_results=[render_result], evidence=evidence, content_draft_id=uuid4(),
        media_selection=_fake_selection(not_usable_candidate),
    )
    assert gate_result.verdict.value == "BLOCK"
    assert recovery is not None


def test_clean_exact_subject_package_still_reaches_ready() -> None:
    """The wiring must not regress the happy path - a genuinely clean, exact-subject package still
    passes, exactly as it did before this phase (test_editorial_pipeline_instagram_adapter.py's own
    established baseline)."""
    exact_candidate = ResolvedMediaCandidate(
        candidate_id="clean-exact",
        provenance=MediaProvenance(
            origin_url="https://example.com/a", asset_url="https://example.com/a.jpg",
            discovered_at=datetime.now(timezone.utc), discovery_tier=DiscoveryTier.TIER1_CURRENT_SOURCE,
        ),
        usage_classification=MediaUsageClassification.APPROVED_SOURCE_MEDIA,
        subject_match=SubjectMatchValidation(
            depicted_subject_description="the real foldable iPhone", subject_match=SubjectMatchClassification.EXACT_SUBJECT,
            must_not_imply_violated=False, reason="test-confirmed exact",
        ),
    )
    package = _build_package("A real foldable iPhone announcement.", media_selection=_fake_selection(exact_candidate))
    render_result = render_instagram_feed_image(package, source_image=Image.new("RGB", (512, 512), "navy"))
    evidence = build_evidence_pack(news_event_id=uuid4(), story_id=None, source_url=None, research_facts=[])

    gate_result, recovery = evaluate_instagram_package(
        package=package, render_results=[render_result], evidence=evidence, content_draft_id=uuid4(),
        media_selection=_fake_selection(exact_candidate),
    )
    assert gate_result.verdict.value == "READY"
    assert recovery is None


# ---------------------------------------------------------------------------
# §7/§10 - same-asset identity.
# ---------------------------------------------------------------------------


def test_same_asset_identity_diverges_blocks() -> None:
    """A render that CLAIMS to have used a real photo (`source_image_treatment != "none"`) for a
    DIFFERENT candidate than the package's own `media_candidate_id` must BLOCK - proven directly
    against `_verify_same_asset_identity()` via a hand-built render result, since the real,
    unmodified renderer never produces a genuine divergence on its own today (disclosed limitation -
    see docs/instagram_production_readiness_closure_1_report.md §F)."""
    from dataclasses import replace

    from services.editorial_pipeline.platforms.instagram import _verify_same_asset_identity

    exact_candidate = ResolvedMediaCandidate(
        candidate_id="candidate-A",
        provenance=MediaProvenance(
            origin_url="https://example.com/a", asset_url="https://example.com/a.jpg",
            discovered_at=datetime.now(timezone.utc), discovery_tier=DiscoveryTier.TIER1_CURRENT_SOURCE,
        ),
        usage_classification=MediaUsageClassification.APPROVED_SOURCE_MEDIA,
    )
    package = _build_package("Announcement.", media_selection=_fake_selection(exact_candidate))
    assert package.media_candidate_id == "candidate-A"

    render_result = render_instagram_feed_image(package)
    diverged_evidence = replace(render_result.evidence, source_image_treatment="cover_cropped", source_media_candidate_id="candidate-B")
    diverged_render = replace(render_result, evidence=diverged_evidence)

    assert _verify_same_asset_identity(package, [diverged_render]) is False
    assert _verify_same_asset_identity(package, [render_result]) is True  # untouched render (treatment="none") trivially passes
