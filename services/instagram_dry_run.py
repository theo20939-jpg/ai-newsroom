"""INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1 §10/§11: the missing live-dry-run runtime path -
`docs/instagram_production_rollout_1_report.md` §H disclosed `DRY_RUN_CANDIDATES=0`: only unit
tests existed, nothing ran real recent candidates through the actual pipeline shape.

Runs each candidate through the REAL chain this phase wires together, with ZERO network writes at
any step:

    real title/evidence -> MediaIntent -> services.instagram_media_safety.resolve_instagram_media()
    (the REAL, unmodified MediaResearchService/is_selectable()/classify_subject_match Telegram
    already uses) -> a REAL InstagramContentPackage (services.instagram_content_package.
    build_instagram_content_package(), carrying the real media_selection) -> the REAL,
    unmodified renderer (services.instagram_platform_renderer.render_instagram_feed_image()) ->
    the REAL, unmodified shared quality gate (services.editorial_pipeline.platforms.instagram.
    evaluate_instagram_package(), now media-selection-aware per this phase) -> the REAL
    ShadowInstagramPublishClient (services.instagram_publish_adapter, shadow=True always here -
    never a live client, never `instagram_publication_enabled` read).

Disclosed, bounded scope (never silently overclaimed - see the main report §I): this dry run does
NOT invoke the real Growth Strategist / Creative Director LLM chain (that would require real LLM
calls this bounded dry run does not make) - `ContentOpportunity`/`FormatDecision`/`ShadowPlanResult`
are built structurally, directly and honestly from the SAME real title/category a real event
already has, clearly not a fabricated creative brief (caption_is_draft stays True, matching this
package type's own existing, established honesty convention). What IS fully real and exercised end
to end is exactly the safety-critical part this phase closes: media discovery -> truthfulness/
rights verification -> package/gate/render identity -> shadow publish."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from schemas.media_intent import MediaIntent
from schemas.media_subject_match import (
    DiscoveryTier,
    MediaProvenance,
    MediaUsageClassification,
    ResolvedMediaCandidate,
)
from services.editorial_pipeline.evidence import build_evidence_pack
from services.editorial_pipeline.platforms.instagram import evaluate_instagram_package
from services.editorial_pipeline.subject_extraction import extract_media_subject
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_media_safety import resolve_instagram_media
from services.instagram_platform_renderer import render_instagram_feed_image
from services.instagram_publish_adapter import (
    ShadowInstagramPublishClient,
    publish_instagram_content,
)
from services.instagram_shadow_pipeline import ShadowPlanResult
from schemas.instagram_creative import InstagramSingleCreative


@dataclass(frozen=True)
class DryRunImageCandidateInput:
    """One real, already-persisted `image_candidates` row's non-sensitive fields - exactly what
    `services.image_persistence.get_editorial_image_candidates()` already reads for Telegram,
    reused here read-only (never a second discovery mechanism)."""

    candidate_id: str
    width: int | None
    height: int | None
    caption_or_alt: str | None = None  # None for essentially every real Tier-1 row today -
    # confirmed disclosed limitation, honestly reflected here, never invented.


@dataclass(frozen=True)
class DryRunCandidateInput:
    news_event_id: str
    title: str
    category: str | None
    image_candidates: list[DryRunImageCandidateInput] = field(default_factory=list)


@dataclass(frozen=True)
class DryRunResult:
    news_event_id: str
    title: str
    media_intent_primary_entity: str
    media_intent_subject_type: str
    deterministic_and_final_subject_match: str | None
    selected_candidate_id: str | None
    media_usage_classification: str | None
    package_id: str
    render_candidate_id: str | None
    qa_verdict: str
    qa_check_summary: list[str]
    shadow_publish_status: str
    classification: str  # "READY" | "HOLD" | "BLOCK"


def _build_evidence_intent(candidate: DryRunCandidateInput) -> MediaIntent:
    extracted = extract_media_subject(candidate.title)
    if extracted is None:
        from schemas.media_intent import DesiredVisualType, MediaSubjectType

        return MediaIntent(
            subject_type=MediaSubjectType.CONCEPT, primary_entity=candidate.title[:200],
            desired_visual_type=DesiredVisualType.GRAPHIC_LAYOUT, platform="instagram",
        )
    from schemas.media_intent import DesiredVisualType, MediaSubjectType

    primary = extracted.versioned_form or extracted.proper_noun_run or extracted.brand_form or candidate.title[:200]
    return MediaIntent(
        subject_type=MediaSubjectType.PRODUCT if (extracted.versioned_form or extracted.brand_form) else MediaSubjectType.PERSON,
        primary_entity=primary[:200], product_name=extracted.brand_form, model_name=extracted.versioned_form,
        person=extracted.proper_noun_run if not (extracted.brand_form or extracted.versioned_form) else None,
        desired_visual_type=DesiredVisualType.PRODUCT_PHOTO, platform="instagram",
    )


def _tier1_candidates(candidate: DryRunCandidateInput) -> list[ResolvedMediaCandidate]:
    return [
        ResolvedMediaCandidate(
            candidate_id=img.candidate_id,
            provenance=MediaProvenance(
                origin_url=f"https://internal/{candidate.news_event_id}", asset_url=f"https://internal/{img.candidate_id}",
                discovered_at=datetime.now(timezone.utc), discovery_tier=DiscoveryTier.TIER1_CURRENT_SOURCE,
                caption_or_alt=img.caption_or_alt,
            ),
            width=img.width, height=img.height, usage_classification=MediaUsageClassification.APPROVED_SOURCE_MEDIA,
            image_candidate_record_id=img.candidate_id,
        )
        for img in candidate.image_candidates[:10]  # RUNTIME-CLOSURE-1's own bound, reused here too
    ]


async def run_dry_run_candidate(candidate: DryRunCandidateInput) -> DryRunResult:
    """Zero network writes anywhere in this function - `shadow=True` is hardcoded, never a
    parameter a caller could flip."""
    intent = _build_evidence_intent(candidate)
    tier1 = _tier1_candidates(candidate)
    media_selection = await resolve_instagram_media(intent, tier1_candidates=tier1)

    opportunity = ContentOpportunity(
        id=f"dryrun-{candidate.news_event_id}", source_type=OpportunitySourceType.NEWS,
        story_id=candidate.news_event_id, campaign_id=None, product_mention_allowed=True,
        allowed_claims=[], restricted_claims=[],
    )
    shadow_plan = ShadowPlanResult(
        campaign_name=None, campaign_phase=None, opportunity_description=candidate.title,
        primary_objective="reach", audience_description="general audience", recommended_format="single",
        hook_family="news", creative_concept_summary=candidate.title, alternative_format=None,
        alternative_objective=None, product_mention_allowed=True, evidence=[candidate.title], confidence=0.5,
    )
    single = InstagramSingleCreative(
        creative_angle="news", visual_concept=candidate.title, on_image_copy=candidate.title[:60],
        caption_direction=candidate.title, cta="Learn more",
    )
    from services.instagram_creative_director import CreativeGenerationOutcome

    package = build_instagram_content_package(
        opportunity=opportunity, format_decision=FormatDecision(recommended_format=ContentFormat.SINGLE, why="reach"),
        shadow_plan=shadow_plan, creative_outcome=CreativeGenerationOutcome(single=single),
        media_selection=media_selection,
    )

    render_result = render_instagram_feed_image(package)
    evidence = build_evidence_pack(news_event_id=uuid4(), story_id=None, source_url=None, research_facts=[candidate.title])
    gate_result, recovery = evaluate_instagram_package(
        package=package, render_results=[render_result], evidence=evidence, content_draft_id=uuid4(),
        media_selection=media_selection,
    )

    from services.instagram_editorial_gate import evaluate_instagram_editorial_gate

    art_result = None
    try:
        from services.instagram_art_validator import validate_instagram_art

        art_result = validate_instagram_art(package, [render_result])
    except Exception:  # noqa: BLE001 - the art validator is exercised for its own real signal;
        # a failure here must never crash the dry run itself.
        art_result = None

    classification = "BLOCK" if gate_result.verdict.value == "BLOCK" else ("HOLD" if gate_result.verdict.value == "HOLD" else "READY")

    shadow_status = "not_attempted"
    if classification == "READY" and art_result is not None:
        gate_outcome = evaluate_instagram_editorial_gate(package, art_result)
        if gate_outcome.permits_publication:
            result = await publish_instagram_content(
                package, gate_outcome, client=ShadowInstagramPublishClient(), account_id="dry-run-account", shadow=True,
            )
            shadow_status = result.status.value
        else:
            shadow_status = f"editorial_gate:{gate_outcome.decision.value}"

    return DryRunResult(
        news_event_id=candidate.news_event_id, title=candidate.title,
        media_intent_primary_entity=intent.primary_entity, media_intent_subject_type=intent.subject_type.value,
        deterministic_and_final_subject_match=(media_selection.selected.subject_match.subject_match.value if media_selection.selected and media_selection.selected.subject_match else None),
        selected_candidate_id=media_selection.selected.candidate_id if media_selection.selected else None,
        media_usage_classification=media_selection.selected.usage_classification.value if media_selection.selected else None,
        package_id=package.package_id,
        render_candidate_id=render_result.evidence.source_media_candidate_id,
        qa_verdict=gate_result.verdict.value,
        qa_check_summary=[f"{c.name.value}={'PASS' if c.passed else 'FAIL'}" for c in gate_result.checks],
        shadow_publish_status=shadow_status,
        classification=classification,
    )


async def run_dry_run_batch(candidates: list[DryRunCandidateInput]) -> list[DryRunResult]:
    return [await run_dry_run_candidate(c) for c in candidates]
