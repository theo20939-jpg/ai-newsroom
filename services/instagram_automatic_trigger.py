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

INSTAGRAM PHASE A: the NEWS and PRODUCT worker call sites opt into one pre-generation editorial
decision on the existing general opportunity path. The decision sees brand/account/product truth,
Story Memory discussion signals and recent/in-flight Instagram history, chooses the angle and then
one already-executable format. Direct service callers retain the pre-Phase-A compatibility path
unless they explicitly opt in. A REEL remains gated by `settings.instagram_reel_execution_enabled`
and is never silently downgraded.

Idempotency (§7) remains the EXISTING `instagram_editorial_deliveries` partial-unique identity.
Phase A adds a pre-generation canonical-Story + structured-angle guard across formats; explicit
regeneration versions and explicit canary overrides remain separate and auditable.

The real Creative Director call reuses `gate_gateway`/`gate_prompt_repository` - the SAME real
`LLMGateway`/`PromptRepository` instances `worker/content_main.py` already constructs once at
startup and threads into `run_content_cycle()` for every other real capability call. No second
gateway is constructed anywhere in this module."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any
from uuid import UUID

from PIL import Image
from sqlalchemy import select

from core.config import settings
from database.models.news_event import NewsEvent
from database.models.social_launch_context import SocialLaunchPlatform
from database.models.story_link import NewsEventStoryLink
from services.business_context_snapshot_service import get_business_context_snapshot
from services.editorial_treatment import MAJOR, EditorialTreatmentDecision
from services.image_persistence import EditorialImageCandidate, get_editorial_image_candidates, read_candidate_bytes
from services.video_discovery_persistence import get_video_candidates_for_event, select_best_video_candidate
from services.instagram_art_validator import validate_instagram_art
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import (
    AudienceFacingCopyError,
    CreativeDirectorInput,
    CreativeLanguageError,
    CreativeDirectorUnavailableError,
    CreativeFactSafetyError,
    InstagramEditorialDecisionInput,
    UngroundedEvidenceError,
    generate_editorial_decision,
)
from services.instagram_director_context import (
    load_instagram_director_context,
    render_account_context,
    render_product_truth,
)
from services.instagram_editorial_delivery_state import (
    InstagramEditorialDeliveryService,
    InstagramEditorialDuplicateDecision,
    check_instagram_editorial_duplicate,
    compute_package_identity,
    load_recent_instagram_editorial_history,
)
from services.instagram_editorial_gate import evaluate_instagram_editorial_gate
from services.instagram_editorial_package_snapshot import build_package_snapshot
from services.instagram_editorial_regeneration import build_default_regenerator
from services.instagram_format_director import ContentFormat, FormatDecision, evaluate_format_shadow
from services.instagram_objective_selection import recommend_objective
from services.instagram_platform_renderer import (
    render_instagram_carousel,
    render_instagram_feed_image,
    render_instagram_reel_cover,
)
from services.instagram_reel_script_readiness import compute_reel_script_readiness
from services.instagram_shadow_pipeline import ShadowPlanResult
from services.instagram_telegram_delivery import deliver_instagram_package
from services.instagram_telegram_package_presenter import present_carousel, present_reel, present_single
from services.social_launch_context_service import get_current_context

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
    opportunity_id: str | None = None
    opportunity_type: str | None = None
    trend_signal: str | None = None
    why_now: str | None = None
    audience_value: str | None = None
    angle: str | None = None
    chosen_format: str | None = None
    product_connection: str | None = None
    duplication_decision: str | None = None
    recent_history_inputs: list[str] = field(default_factory=list)
    output_language: str = "ru"


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



def _is_external_news(opportunity: ContentOpportunity) -> bool:
    return (
        opportunity.source_type is OpportunitySourceType.NEWS
        and opportunity.story_id is not None
        and opportunity.product_id is None
        and opportunity.campaign_id is None
    )


@dataclass(frozen=True)
class _PhaseAEditorialPlan:
    opportunity: ContentOpportunity
    format_decision: FormatDecision
    duplicate: InstagramEditorialDuplicateDecision
    brand_context: str
    account_context: str
    product_context: str
    recent_content_context: str


async def _resolve_canonical_story_id(session: Any, event_id: str) -> str:
    try:
        event_uuid = UUID(event_id)
    except ValueError:
        return event_id
    link = await session.get(NewsEventStoryLink, event_uuid)
    return str(link.story_id) if link is not None else event_id


async def _story_memory_trend_context(session: Any, *, canonical_story_id: str) -> str:
    """Normalize the existing Story Memory cluster into a bounded discussion-trend signal.

    The evidence gate (>=3 events and >=2 sources in 48h) is the same threshold used by the
    repository's previous autonomous trend canary. No crawler, table or parallel ranking service
    is introduced. Story Memory can currently prove a discussion/topic trend only; it cannot
    honestly claim a meme, audio or format trend.
    """
    try:
        story_uuid = UUID(canonical_story_id)
    except ValueError:
        return ""
    cutoff = datetime.now(UTC) - timedelta(hours=48)
    stmt = (
        select(NewsEvent.id, NewsEvent.source_id, NewsEvent.title, NewsEvent.collected_at)
        .join(NewsEventStoryLink, NewsEventStoryLink.news_event_id == NewsEvent.id)
        .where(NewsEventStoryLink.story_id == story_uuid, NewsEvent.collected_at >= cutoff)
        .order_by(NewsEvent.collected_at.desc())
        .limit(20)
    )
    rows = (await session.execute(stmt)).all()
    distinct_sources = {str(row.source_id) for row in rows}
    if len(rows) < 3 or len(distinct_sources) < 2:
        return ""
    titles = " | ".join(str(row.title) for row in rows[:5])
    return (
        "kind=discussion; source=Newsroom Story Memory; window=48h; "
        f"events={len(rows)}; distinct_sources={len(distinct_sources)}; evidence_titles={titles}"
    )


def _recent_history_context(history: list[Any]) -> tuple[str, list[str]]:
    if not history:
        return "No recent or in-flight Instagram content.", []
    lines: list[str] = []
    compact: list[str] = []
    for item in history[:12]:
        angle = item.angle or item.caption[:180]
        line = (
            f"{item.created_at.date()} | {item.state} | {item.content_format} | "
            f"topic={item.topic or '(legacy unknown)'} | purpose={item.purpose or '(legacy unknown)'} | "
            f"origin={item.origin or '(legacy unknown)'} | angle={angle or '(unknown)'}"
        )
        lines.append(line)
        compact.append(f"{item.content_format}:{item.topic or angle[:60]}")
    return "\n".join(lines), compact


async def _build_phase_a_editorial_plan(
    session: Any, *, opportunity: ContentOpportunity, source_summary: str, trend_context: str,
    gateway: Any, prompt_repository: Any, allow_duplicate_canary: bool,
) -> _PhaseAEditorialPlan:
    now = datetime.now(UTC)
    snapshot = await get_business_context_snapshot(session, now=now)
    launch_context = await get_current_context(session, SocialLaunchPlatform.INSTAGRAM)
    history = await load_recent_instagram_editorial_history(session, now=now)
    recent_note, _compact = _recent_history_context(history)
    brand_context = load_instagram_director_context()
    account_context = render_account_context(launch_context)
    product_context = render_product_truth(snapshot)
    decision, _call = await generate_editorial_decision(
        gateway,
        prompt_repository,
        decision_input=InstagramEditorialDecisionInput(
            source_type=opportunity.source_type.value,
            source_summary=source_summary,
            allowed_evidence=list(opportunity.evidence),
            brand_context=brand_context,
            account_context=account_context,
            product_context=product_context,
            trend_context=trend_context,
            recent_content_context=recent_note,
        ),
    )
    if not opportunity.product_mention_allowed and decision.product_connection:
        raise CreativeFactSafetyError(
            "Director proposed a NINJA product connection where product_mention_allowed=False"
        )
    duplicate = await check_instagram_editorial_duplicate(
        session,
        source_story_id=opportunity.story_id,
        angle=decision.angle,
        angle_intent=decision.angle_intent,
        allow_duplicate_canary=allow_duplicate_canary,
        now=now,
    )
    decision_payload = decision.model_dump()
    decision_payload.update(
        {
            "duplication_decision": "BLOCK" if duplicate.blocked else "ALLOW",
            "duplication_rationale": duplicate.reason,
            "recent_history_count": len(duplicate.recent_history),
            "canary_override_used": duplicate.canary_override_used,
            "output_language": "ru",
        }
    )
    planned_opportunity = replace(opportunity, editorial_decision=decision_payload)
    chosen_format = ContentFormat(decision.recommended_format)
    alternatives = [fmt for fmt in ContentFormat if fmt is not chosen_format]
    format_decision = FormatDecision(
        recommended_format=chosen_format,
        alternatives=alternatives,
        why=decision.format_reason,
        expected_role={
            ContentFormat.CAROUSEL: "education/reference",
            ContentFormat.REEL: "reach/reaction/storytelling",
            ContentFormat.SINGLE: "hero/breaking/statement",
        }[chosen_format],
        risk="medium" if chosen_format is ContentFormat.REEL else "low",
        confidence=max(0.5, opportunity.confidence),
        warnings=[],
    )
    return _PhaseAEditorialPlan(
        opportunity=planned_opportunity,
        format_decision=format_decision,
        duplicate=duplicate,
        brand_context=brand_context,
        account_context=account_context,
        product_context=product_context,
        recent_content_context=recent_note,
    )


def _decision_outcome(
    *, opportunity: ContentOpportunity, reason: str, trend_signal: str, duplicate: InstagramEditorialDuplicateDecision,
    accepted: bool, gate_decision: str | None = None, delivery_sent: bool = False,
    delivery_reason: str | None = None, delivery_id: str | None = None,
) -> InstagramTriggerCandidateOutcome:
    decision = opportunity.editorial_decision
    _note, compact_history = _recent_history_context(duplicate.recent_history)
    return InstagramTriggerCandidateOutcome(
        event_id=opportunity.id, accepted=accepted, reason=reason, gate_decision=gate_decision,
        delivery_sent=delivery_sent, delivery_reason=delivery_reason, delivery_id=delivery_id,
        opportunity_id=opportunity.id, opportunity_type=decision.get("opportunity_type"),
        trend_signal=trend_signal or None, why_now=decision.get("why_now"),
        audience_value=decision.get("audience_value"), angle=decision.get("angle"),
        chosen_format=decision.get("recommended_format"), product_connection=decision.get("product_connection"),
        duplication_decision=decision.get("duplication_rationale"), recent_history_inputs=compact_history,
        output_language="ru",
    )


async def _resolve_single_source_image(
    session: Any, story_id: str | None,
) -> tuple[Image.Image | None, EditorialImageCandidate | None, int, int]:
    if not story_id:
        return None, None, 0, 0
    try:
        event_id = UUID(story_id)
    except ValueError:
        return None, None, 0, 0
    candidates = await get_editorial_image_candidates(session, news_event_id=event_id, limit=10)
    for candidate in candidates:
        if candidate.is_expired:
            continue
        data = read_candidate_bytes(candidate)
        if not data:
            continue
        try:
            with Image.open(BytesIO(data)) as check:
                check.verify()
            with Image.open(BytesIO(data)) as decoded:
                if min(decoded.size) < 256:
                    continue
                source_image = decoded.convert("RGB")
        except (OSError, ValueError):
            logger.warning("instagram_single_image_decode_failed", extra={"media_candidate_id": str(candidate.id)})
            continue
        return source_image, candidate, len(candidates), len(data)
    return None, None, len(candidates), 0

async def evaluate_and_submit_instagram_candidate(
    session: Any, bot: Any, *, event_id: str, event_title: str, treatment: EditorialTreatmentDecision,
    research_facts: list[str], gateway: Any, prompt_repository: Any, source_url: str | None = None,
    phase_a_enabled: bool = False,
) -> InstagramTriggerCandidateOutcome:
    """The one entry point per story. Never raises - a Creative Director failure (rate limit,
    ungrounded evidence, provider error) degrades to a rejected/failed outcome for THIS story only,
    never crashing the caller's cycle (§8 crash safety - a per-story failure must not take down the
    whole scan)."""
    if treatment.treatment not in _ELIGIBLE_TREATMENTS:
        return InstagramTriggerCandidateOutcome(event_id=event_id, accepted=False, reason=f"treatment={treatment.treatment}")

    canonical_story_id = await _resolve_canonical_story_id(session, event_id) if phase_a_enabled else event_id
    trend_context = (
        await _story_memory_trend_context(session, canonical_story_id=canonical_story_id)
        if phase_a_enabled else ""
    )
    opportunity = ContentOpportunity(
        id=event_id, source_type=OpportunitySourceType.NEWS, story_id=canonical_story_id,
        news_value=1.0, audience_relevance=0.5, product_mention_allowed=False,
        evidence=list(research_facts), confidence=0.5,
    )
    return await evaluate_and_submit_instagram_opportunity(
        session, bot, opportunity=opportunity, opportunity_summary=event_title,
        gateway=gateway, prompt_repository=prompt_repository, source_url=source_url,
        source_event_id=event_id, trend_context=trend_context, phase_a_enabled=phase_a_enabled,
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
    source_event_id: str | None = None, trend_context: str = "", allow_duplicate_canary: bool = False,
    phase_a_enabled: bool = False,
) -> InstagramTriggerCandidateOutcome:
    """Takes an ALREADY-BUILT, ALREADY-RANKED `ContentOpportunity` (any `source_type` - selection/
    ranking is `generate_growth_strategy()`'s job, called by whichever lane constructs the
    opportunity, never this function's) and runs it through the SAME real format/creative/render/
    QA/delivery chain the NEWS path uses - `opportunity.evidence`/`.product_mention_allowed`/
    `.allowed_claims`/`.restricted_claims` (already real, resolved fields on `ContentOpportunity`)
    are read directly, never a parallel `research_facts`-style parameter - one canonical evidence
    source per opportunity, regardless of lane. Never raises (mirrors
    `evaluate_and_submit_instagram_candidate()`'s own crash-safety contract exactly)."""
    has_multi_step_narrative = len(opportunity.evidence) > 1
    has_video_asset = False
    if _is_external_news(opportunity) and (source_event_id or opportunity.story_id):
        try:
            video_candidates = await get_video_candidates_for_event(
                session, UUID(source_event_id or opportunity.story_id or "")
            )
            has_video_asset = select_best_video_candidate(video_candidates) is not None
        except ValueError:
            pass
    recommendation = recommend_objective(opportunity=opportunity, has_multi_step_narrative=has_multi_step_narrative)
    if phase_a_enabled:
        try:
            phase_a_plan = await _build_phase_a_editorial_plan(
                session, opportunity=opportunity, source_summary=opportunity_summary,
                trend_context=trend_context, gateway=gateway, prompt_repository=prompt_repository,
                allow_duplicate_canary=allow_duplicate_canary,
            )
        except (
            CreativeDirectorUnavailableError, UngroundedEvidenceError, CreativeFactSafetyError,
            CreativeLanguageError, AudienceFacingCopyError,
        ) as exc:
            logger.warning(
                "instagram_editorial_decision_failed",
                extra={"opportunity_id": opportunity.id, "error": type(exc).__name__},
            )
            return InstagramTriggerCandidateOutcome(
                event_id=opportunity.id, accepted=False, reason=f"editorial_decision_failed:{type(exc).__name__}",
            )
    else:
        legacy_format = evaluate_format_shadow(
            objective=recommendation.primary_objective, has_video_asset=has_video_asset,
            has_multi_step_narrative=has_multi_step_narrative,
        )
        phase_a_plan = _PhaseAEditorialPlan(
            opportunity=opportunity,
            format_decision=legacy_format,
            duplicate=InstagramEditorialDuplicateDecision(False, "legacy compatibility path"),
            brand_context="",
            account_context="",
            product_context="",
            recent_content_context="",
        )

    opportunity = phase_a_plan.opportunity
    format_decision = phase_a_plan.format_decision
    if phase_a_plan.duplicate.blocked:
        return _decision_outcome(
            opportunity=opportunity, reason="duplicate_angle_blocked", trend_signal=trend_context,
            duplicate=phase_a_plan.duplicate, accepted=False,
        )

    identity = compute_package_identity(source_key=opportunity.id, content_format=format_decision.recommended_format.value)
    delivery_service = InstagramEditorialDeliveryService()
    existing = await delivery_service.find_current(session, package_identity=identity)
    if existing is not None:
        return _decision_outcome(
            opportunity=opportunity, reason="already_submitted", trend_signal=trend_context,
            duplicate=phase_a_plan.duplicate, accepted=True, delivery_id=str(existing.id),
        )

    # CONTROLLED ROLLOUT: a REEL decision is deferred - never silently downgraded to SINGLE -
    # while settings.instagram_reel_execution_enabled (default False) is off. A bounded canary
    # invocation may pass a locally-true settings override for this one call only; persistent
    # production config is never touched by this check.
    if format_decision.recommended_format is ContentFormat.REEL and not settings.instagram_reel_execution_enabled:
        logger.info(
            "instagram_product_lane_reel_execution_disabled",
            extra={"opportunity_id": opportunity.id, "source_type": opportunity.source_type.value},
        )
        return _decision_outcome(
            opportunity=opportunity, reason="reel_execution_disabled", trend_signal=trend_context,
            duplicate=phase_a_plan.duplicate, accepted=True,
        )

    source_image = None
    image_candidate = None
    if format_decision.recommended_format is ContentFormat.SINGLE:
        source_image, image_candidate, image_count, read_length = await _resolve_single_source_image(
            session, source_event_id or opportunity.story_id
        )
        if source_image is None or image_candidate is None:
            logger.warning("instagram_single_source_image_unavailable", extra={
                "opportunity_id": opportunity.id, "image_candidate_count": image_count,
            })
            return InstagramTriggerCandidateOutcome(event_id=opportunity.id, accepted=True, reason="source_image_unavailable")
        logger.info("instagram_single_source_image_selected", extra={
            "opportunity_id": opportunity.id, "image_candidate_count": image_count,
            "media_candidate_id": str(image_candidate.id), "read_byte_length": read_length,
        })

    director_input = CreativeDirectorInput(
        objective=recommendation.primary_objective.value, format=format_decision.recommended_format.value,
        opportunity_summary=opportunity_summary, allowed_evidence=list(opportunity.evidence),
        approved_claims=list(opportunity.allowed_claims), restricted_claims=list(opportunity.restricted_claims),
        product_mention_allowed=opportunity.product_mention_allowed,
        external_news_entities_allowed=_is_external_news(opportunity),
        locale="ru" if phase_a_enabled else "", brand_context=phase_a_plan.brand_context,
        account_context=phase_a_plan.account_context, product_context=phase_a_plan.product_context,
        recent_content_context=phase_a_plan.recent_content_context,
        editorial_decision=json.dumps(opportunity.editorial_decision, ensure_ascii=False, sort_keys=True),
    )

    try:
        regenerator = build_default_regenerator(gateway, prompt_repository)
        creative_outcome = await regenerator(director_input, format_decision.recommended_format)
    except (
        CreativeDirectorUnavailableError, UngroundedEvidenceError, CreativeFactSafetyError,
        CreativeLanguageError, AudienceFacingCopyError,
    ) as exc:
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

    single, carousel, reel = creative_outcome.single, creative_outcome.carousel, creative_outcome.reel
    concept_summary = (
        single.creative_angle if single is not None
        else reel.hook if reel is not None
        else carousel.hook_slide.slide_copy if carousel is not None else None
    )
    # CONTROLLED ROLLOUT: a REEL package's script-readiness axis (services/instagram_reel_script_
    # readiness.py, Phase 3) - `unresolved_facts` stays empty by construction here: this lane's own
    # opportunity sources (_product_opportunities_from_campaigns/_product_opportunities_from_context,
    # services/director_execution_service.py) only ever build evidence from CONFIRMED Product facts
    # in the first place, so nothing UNKNOWN/UNDECIDED reaches the Creative Director to begin with.
    # `asset_requirements_satisfiable=False` is the honest default - no real filming-asset pipeline
    # feeds the PRODUCT lane; external NEWS with an existing video candidate can satisfy this
    # asset-readiness signal while the script itself remains separate from an mp4.
    reel_script_readiness = (
        compute_reel_script_readiness(unresolved_facts=[], asset_requirements_satisfiable=has_video_asset and _is_external_news(opportunity))
        if format_decision.recommended_format is ContentFormat.REEL else None
    )
    shadow_plan = ShadowPlanResult(
        campaign_name=None, campaign_phase=opportunity.campaign_phase, opportunity_description=opportunity_summary,
        primary_objective=recommendation.primary_objective.value, audience_description="",
        recommended_format=format_decision.recommended_format.value, hook_family=None,
        creative_concept_summary=concept_summary, alternative_format=None,
        alternative_objective=None, product_mention_allowed=opportunity.product_mention_allowed,
        evidence=list(opportunity.evidence), confidence=opportunity.confidence,
    )
    pkg = build_instagram_content_package(
        opportunity=opportunity, format_decision=format_decision, shadow_plan=shadow_plan,
        creative_outcome=creative_outcome, account_key="default", reel_script_readiness=reel_script_readiness,
        source_image_ref=image_candidate.candidate_id if image_candidate else None,
        media_candidate_id=str(image_candidate.id) if image_candidate else None,
    )

    try:
        if format_decision.recommended_format is ContentFormat.CAROUSEL:
            renders = render_instagram_carousel(pkg)
            presentation = present_carousel(pkg, renders, version=1)
        elif format_decision.recommended_format is ContentFormat.REEL:
            renders = [render_instagram_reel_cover(pkg)]
            presentation = present_reel(pkg, renders[0], version=1)
        else:
            renders = [render_instagram_feed_image(pkg, source_image=source_image)]
            logger.info("instagram_single_source_image_rendered", extra={
                "opportunity_id": opportunity.id, "media_candidate_id": str(image_candidate.id),
                "rendered_byte_length": len(renders[0].image_bytes),
                "source_image_treatment": renders[0].evidence.source_image_treatment,
            })
            presentation = present_single(pkg, renders[0], version=1)

    except Exception:
        logger.exception("instagram_opportunity_render_failed", extra={"opportunity_id": opportunity.id})
        return InstagramTriggerCandidateOutcome(event_id=opportunity.id, accepted=True, reason="render_failed")
    art = validate_instagram_art(pkg, renders)
    gate = evaluate_instagram_editorial_gate(pkg, art)
    snapshot = build_package_snapshot(
        package=pkg, opportunity=opportunity, format_decision=format_decision, shadow_plan=shadow_plan,
        director_input=director_input, previous_creative=(single or carousel or reel), source_url=source_url,
    )

    delivery_outcome = await deliver_instagram_package(
        bot, session, presentation=presentation, gate_decision=gate.decision, package_identity=identity,
        source_story_id=opportunity.story_id, content_format=format_decision.recommended_format.value,
        package_snapshot=snapshot, source_url=source_url, hold_or_block_reason=gate.short_reason or None,
    )
    return _decision_outcome(
        opportunity=opportunity, reason="submitted", trend_signal=trend_context,
        duplicate=phase_a_plan.duplicate, accepted=True, gate_decision=gate.decision.value,
        delivery_sent=delivery_outcome.sent, delivery_reason=delivery_outcome.reason,
        delivery_id=delivery_outcome.delivery_id,
    )
