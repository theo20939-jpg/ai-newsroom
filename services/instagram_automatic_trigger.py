"""INSTAGRAM-AUTOMATIC-EDITORIAL-TRIGGER-1: the real, automatic newsroom-to-Instagram-Telegram
pipeline - submits an ALREADY-COMPLETE, ALREADY-EVIDENCE-GROUNDED real story into the EXISTING
Instagram opportunity/package/QA/delivery chain, reusing every stage verbatim (§5's own explicit
"do NOT copy/paste the manual script into the worker" - this module IS the extracted, reusable
service boundary the manual canary scripts should have been all along).

Eligibility (§2/§3 - no new score invented): a story is submitted for Instagram evaluation ONLY
if `services.editorial_treatment.classify_editorial_treatment()` - the SAME real, already-reviewed
significance/evidence classifier `worker/content_cycle.py` already computes for every NEWS story
today (Phase 23.1H/23.1P) - returns `MAJOR`. This is not a new threshold: it is the existing
"deserves more than baseline editorial treatment" tier, reused as-is. `STANDARD`/`BRIEF`/`SKIP`
stories are never submitted - the majority of real NEWS stories are expected to fall here, exactly
matching the phase brief's own "do NOT interpret 10 NEWS drafts as 10 Instagram packages" warning.

Format is always SINGLE this phase (§15 "preserve current visual behavior") - `evaluate_format_
shadow()` is called with `has_video_asset=False, has_multi_step_narrative=False`, which its own
real, existing, deterministic logic always resolves to SINGLE. No new format-selection heuristic
is introduced.

Idempotency (§7) is the EXISTING `instagram_editorial_deliveries` table's own partial-unique
`package_identity` index - `compute_package_identity(source_key=event_id, content_format="single")`
is checked BEFORE any generation work begins (so a re-submitted, already-delivered story never
even triggers a wasted LLM call), and the delivery itself is still protected by the same DB-level
guarantee under a race.

The real Creative Director call reuses `gate_gateway`/`gate_prompt_repository` - the SAME real
`LLMGateway`/`PromptRepository` instances `worker/content_main.py` already constructs once at
startup and threads into `run_content_cycle()` for every other real capability call. No second
gateway is constructed anywhere in this module."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from services.editorial_treatment import MAJOR, EditorialTreatmentDecision
from services.instagram_art_validator import validate_instagram_art
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import (
    CreativeDirectorInput,
    CreativeDirectorUnavailableError,
    CreativeFactSafetyError,
    UngroundedEvidenceError,
)
from services.instagram_editorial_delivery_state import InstagramEditorialDeliveryService, compute_package_identity
from services.instagram_editorial_gate import evaluate_instagram_editorial_gate
from services.instagram_editorial_package_snapshot import build_package_snapshot
from services.instagram_editorial_regeneration import build_default_regenerator
from services.instagram_format_director import ContentFormat, evaluate_format_shadow
from services.instagram_objective_selection import recommend_objective
from services.instagram_objectives import ContentObjective
from services.instagram_platform_renderer import render_instagram_feed_image
from services.instagram_shadow_pipeline import ShadowPlanResult
from services.instagram_telegram_delivery import deliver_instagram_package
from services.instagram_telegram_package_presenter import present_single

logger = logging.getLogger(__name__)

_ELIGIBLE_TREATMENTS = (MAJOR,)
"""§3: the ONLY selection criterion - the existing MAJOR tier, never a new invented cutoff."""


@dataclass(frozen=True)
class InstagramTriggerCandidateOutcome:
    event_id: str
    accepted: bool
    reason: str
    gate_decision: str | None = None
    delivery_sent: bool = False
    delivery_reason: str | None = None
    delivery_id: str | None = None


@dataclass(frozen=True)
class InstagramTriggerCycleReport:
    """§17 observability - every counter the phase brief names, nothing more (no secrets/prompt
    contents)."""

    stories_evaluated: int = 0
    opportunities_accepted: int = 0
    opportunities_rejected: int = 0
    packages_ready: int = 0
    packages_hold: int = 0
    packages_block: int = 0
    packages_delivered: int = 0
    duplicate_submissions_suppressed: int = 0
    duplicate_deliveries_suppressed: int = 0
    candidates: list[InstagramTriggerCandidateOutcome] = field(default_factory=list)

    def as_log_extra(self) -> dict[str, int]:
        return {
            "stories_evaluated": self.stories_evaluated, "opportunities_accepted": self.opportunities_accepted,
            "opportunities_rejected": self.opportunities_rejected, "packages_ready": self.packages_ready,
            "packages_hold": self.packages_hold, "packages_block": self.packages_block,
            "packages_delivered": self.packages_delivered,
            "duplicate_submissions_suppressed": self.duplicate_submissions_suppressed,
            "duplicate_deliveries_suppressed": self.duplicate_deliveries_suppressed,
        }


async def evaluate_and_submit_instagram_candidate(
    session: Any, bot: Any, *, event_id: str, event_title: str, treatment: EditorialTreatmentDecision,
    research_facts: list[str], gateway: Any, prompt_repository: Any, source_url: str | None = None,
) -> InstagramTriggerCandidateOutcome:
    """The one entry point per story. Never raises - a Creative Director failure (rate limit,
    ungrounded evidence, provider error) degrades to a rejected/failed outcome for THIS story only,
    never crashing the caller's cycle (§8 crash safety - a per-story failure must not take down the
    whole scan)."""
    if treatment.treatment not in _ELIGIBLE_TREATMENTS:
        return InstagramTriggerCandidateOutcome(event_id=event_id, accepted=False, reason=f"treatment={treatment.treatment}")

    identity = compute_package_identity(source_key=event_id, content_format="single")
    delivery_service = InstagramEditorialDeliveryService()
    existing = await delivery_service.find_current(session, package_identity=identity)
    if existing is not None:
        return InstagramTriggerCandidateOutcome(
            event_id=event_id, accepted=True, reason="already_submitted", delivery_id=str(existing.id),
        )

    opp = ContentOpportunity(id=event_id, source_type=OpportunitySourceType.NEWS, story_id=event_id, product_mention_allowed=False)
    format_decision = evaluate_format_shadow(objective=ContentObjective.REACH, has_video_asset=False, has_multi_step_narrative=False)
    assert format_decision.recommended_format is ContentFormat.SINGLE  # §15 - always true today, asserted rather than assumed silently

    director_input = CreativeDirectorInput(
        objective=ContentObjective.REACH.value, format=format_decision.recommended_format.value,
        opportunity_summary=event_title, allowed_evidence=list(research_facts),
    )

    try:
        regenerator = build_default_regenerator(gateway, prompt_repository)
        creative_outcome = await regenerator(director_input, format_decision.recommended_format)
    except (CreativeDirectorUnavailableError, UngroundedEvidenceError, CreativeFactSafetyError) as exc:
        logger.warning("instagram_automatic_trigger_creative_director_failed", extra={"event_id": event_id, "error": type(exc).__name__})
        return InstagramTriggerCandidateOutcome(event_id=event_id, accepted=True, reason=f"creative_director_failed:{type(exc).__name__}")
    except Exception:
        logger.exception("instagram_automatic_trigger_unexpected_creative_director_error", extra={"event_id": event_id})
        return InstagramTriggerCandidateOutcome(event_id=event_id, accepted=True, reason="creative_director_failed:unexpected_error")

    single = creative_outcome.single
    shadow_plan = ShadowPlanResult(
        campaign_name=None, campaign_phase=None, opportunity_description=event_title, primary_objective=ContentObjective.REACH.value,
        audience_description="", recommended_format=format_decision.recommended_format.value, hook_family=None,
        creative_concept_summary=single.creative_angle if single is not None else None, alternative_format=None,
        alternative_objective=None, product_mention_allowed=False, evidence=list(research_facts), confidence=0.5,
    )
    pkg = build_instagram_content_package(
        opportunity=opp, format_decision=format_decision, shadow_plan=shadow_plan,
        creative_outcome=creative_outcome, account_key="default",
    )
    render = render_instagram_feed_image(pkg)
    art = validate_instagram_art(pkg, [render])
    gate = evaluate_instagram_editorial_gate(pkg, art)
    presentation = present_single(pkg, render, version=1)
    snapshot = build_package_snapshot(
        package=pkg, opportunity=opp, format_decision=format_decision, shadow_plan=shadow_plan,
        director_input=director_input, previous_creative=single, source_url=source_url,
    )

    delivery_outcome = await deliver_instagram_package(
        bot, session, presentation=presentation, gate_decision=gate.decision, package_identity=identity,
        source_story_id=event_id, content_format="single", package_snapshot=snapshot, source_url=source_url,
        hold_or_block_reason=gate.short_reason or None,
    )
    return InstagramTriggerCandidateOutcome(
        event_id=event_id, accepted=True, reason="submitted", gate_decision=gate.decision.value,
        delivery_sent=delivery_outcome.sent, delivery_reason=delivery_outcome.reason, delivery_id=delivery_outcome.delivery_id,
    )


# ---------------------------------------------------------------------------
# INSTAGRAM-CONTENT-STRATEGY-V2 Phase 2: the general entrypoint - PRODUCT (this phase) and, in
# later phases, NEWS_DIGEST/TREND all flow through HERE via `generate_growth_strategy()`'s already-
# ranked output, instead of each lane hand-rolling its own Creative Director call the way the NEWS
# path above still does. `evaluate_and_submit_instagram_candidate()` above is left completely
# untouched (byte-identical behavior, zero risk to the live NEWS lane or its 14+3 existing tests) -
# this is a NEW, general SIBLING, not a replacement, matching the run brief's own "generalize the
# existing trigger... do NOT build another trigger" instruction (this module remains the one and
# only Instagram automatic-trigger service; a second entrypoint inside it is not a second trigger).
# ---------------------------------------------------------------------------


async def evaluate_and_submit_instagram_opportunity(
    session: Any, bot: Any, *, opportunity: ContentOpportunity, opportunity_summary: str,
    gateway: Any, prompt_repository: Any, source_url: str | None = None,
) -> InstagramTriggerCandidateOutcome:
    """Takes an ALREADY-BUILT, ALREADY-RANKED `ContentOpportunity` (any `source_type` - selection/
    ranking is `generate_growth_strategy()`'s job, called by whichever lane constructs the
    opportunity, never this function's) and runs it through the SAME real format/creative/render/
    QA/delivery chain the NEWS path uses - `opportunity.evidence`/`.product_mention_allowed`/
    `.allowed_claims`/`.restricted_claims` (already real, resolved fields on `ContentOpportunity`)
    are read directly, never a parallel `research_facts`-style parameter - one canonical evidence
    source per opportunity, regardless of lane. Never raises (mirrors
    `evaluate_and_submit_instagram_candidate()`'s own crash-safety contract exactly)."""
    identity = compute_package_identity(source_key=opportunity.id, content_format="single")
    delivery_service = InstagramEditorialDeliveryService()
    existing = await delivery_service.find_current(session, package_identity=identity)
    if existing is not None:
        return InstagramTriggerCandidateOutcome(
            event_id=opportunity.id, accepted=True, reason="already_submitted", delivery_id=str(existing.id),
        )

    # SINGLE only, this phase too (§15's "preserve current visual behavior" carries over to every
    # lane until the photo-led/CAROUSEL/REEL visual work, disclosed as separate, future work) -
    # asserted, not silently assumed, exactly like the NEWS path above.
    format_decision = evaluate_format_shadow(objective=ContentObjective.REACH, has_video_asset=False, has_multi_step_narrative=False)
    assert format_decision.recommended_format is ContentFormat.SINGLE

    recommendation = recommend_objective(opportunity=opportunity)
    director_input = CreativeDirectorInput(
        objective=recommendation.primary_objective.value, format=format_decision.recommended_format.value,
        opportunity_summary=opportunity_summary, allowed_evidence=list(opportunity.evidence),
        approved_claims=list(opportunity.allowed_claims), restricted_claims=list(opportunity.restricted_claims),
        product_mention_allowed=opportunity.product_mention_allowed,
    )

    try:
        regenerator = build_default_regenerator(gateway, prompt_repository)
        creative_outcome = await regenerator(director_input, format_decision.recommended_format)
    except (CreativeDirectorUnavailableError, UngroundedEvidenceError, CreativeFactSafetyError) as exc:
        logger.warning(
            "instagram_automatic_trigger_creative_director_failed",
            extra={"opportunity_id": opportunity.id, "source_type": opportunity.source_type.value, "error": type(exc).__name__},
        )
        return InstagramTriggerCandidateOutcome(event_id=opportunity.id, accepted=True, reason=f"creative_director_failed:{type(exc).__name__}")
    except Exception:
        logger.exception(
            "instagram_automatic_trigger_unexpected_creative_director_error",
            extra={"opportunity_id": opportunity.id, "source_type": opportunity.source_type.value},
        )
        return InstagramTriggerCandidateOutcome(event_id=opportunity.id, accepted=True, reason="creative_director_failed:unexpected_error")

    single = creative_outcome.single
    shadow_plan = ShadowPlanResult(
        campaign_name=None, campaign_phase=opportunity.campaign_phase, opportunity_description=opportunity_summary,
        primary_objective=recommendation.primary_objective.value, audience_description="",
        recommended_format=format_decision.recommended_format.value, hook_family=None,
        creative_concept_summary=single.creative_angle if single is not None else None, alternative_format=None,
        alternative_objective=None, product_mention_allowed=opportunity.product_mention_allowed,
        evidence=list(opportunity.evidence), confidence=opportunity.confidence,
    )
    pkg = build_instagram_content_package(
        opportunity=opportunity, format_decision=format_decision, shadow_plan=shadow_plan,
        creative_outcome=creative_outcome, account_key="default",
    )
    render = render_instagram_feed_image(pkg)
    art = validate_instagram_art(pkg, [render])
    gate = evaluate_instagram_editorial_gate(pkg, art)
    presentation = present_single(pkg, render, version=1)
    snapshot = build_package_snapshot(
        package=pkg, opportunity=opportunity, format_decision=format_decision, shadow_plan=shadow_plan,
        director_input=director_input, previous_creative=single, source_url=source_url,
    )

    delivery_outcome = await deliver_instagram_package(
        bot, session, presentation=presentation, gate_decision=gate.decision, package_identity=identity,
        source_story_id=opportunity.id, content_format="single", package_snapshot=snapshot, source_url=source_url,
        hold_or_block_reason=gate.short_reason or None,
    )
    return InstagramTriggerCandidateOutcome(
        event_id=opportunity.id, accepted=True, reason="submitted", gate_decision=gate.decision.value,
        delivery_sent=delivery_outcome.sent, delivery_reason=delivery_outcome.reason, delivery_id=delivery_outcome.delivery_id,
    )
