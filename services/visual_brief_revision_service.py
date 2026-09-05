"""VISUAL-DESIGN-AUTONOMY-1A, spec §1/§6/§17-19: VisualBriefRevisionService - the ONE orchestration
path from repeated-pattern evidence to a persisted CANDIDATE brief:

    evidence gate (reuse) -> revision generator -> Brand Core validation -> persist CANDIDATE

Never calls the Gateway when the scope is FROZEN, the evidence gate says not-yet-eligible, or the
daily visual budget is unknown/exhausted (spec §17-19) - checked BEFORE ever building a context or
calling generate_candidate_brief_proposal(). This function is the only intended caller of
services/visual_brief_revision_generator.py; a console read (bot/handlers/visual_design.py) must
never call it directly (mirrors services/director_execution_service.py's own "execution, never
console-read" boundary already established for the rest of this visual system)."""
from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.visual_designer_brief import VisualDesignerBriefVersion
from integrations.llm_gateway.protocol import LLMGateway
from integrations.prompts.protocol import PromptRepository
from services.visual_brand_core import check_brief_text_against_brand_core
from services.visual_brief_adaptation_service import may_create_candidate, recent_attempts_for_scope
from services.visual_brief_revision_generator import (
    BriefRevisionBrandCoreViolationError,
    BriefRevisionUnavailableError,
    CandidateBriefProposal,
    build_brief_revision_context,
    generate_candidate_brief_proposal,
)
from services.visual_budget_service import daily_cost_summary
from services.visual_designer_brief_service import create_candidate_brief, get_active_or_frozen_brief, get_frozen_brief
from services.visual_feed_context import compute_visual_feed_context

logger = logging.getLogger(__name__)


class BriefRevisionStatus(str, enum.Enum):
    CANDIDATE_CREATED = "candidate_created"
    NOT_ELIGIBLE = "not_eligible"
    BRIEF_FROZEN = "brief_frozen"
    BUDGET_UNKNOWN = "budget_unknown"
    BUDGET_EXHAUSTED = "budget_exhausted"
    BRIEF_REVISION_UNAVAILABLE = "brief_revision_unavailable"
    REJECTED_BY_BRAND_CORE = "rejected_by_brand_core"
    NO_BRIEF_YET = "no_brief_yet"


@dataclass(frozen=True)
class BriefRevisionResult:
    status: BriefRevisionStatus
    reason: str
    candidate: VisualDesignerBriefVersion | None = None
    proposal: CandidateBriefProposal | None = None


def _issue_code_distribution(attempts) -> dict[str, int]:  # noqa: ANN001 - list[VisualDesignAttempt], avoids a heavy import purely for the annotation
    counts: dict[str, int] = {}
    for attempt in attempts:
        for code in attempt.issue_codes or []:
            counts[code] = counts.get(code, 0) + 1
    return counts


def _successful_history_summary(attempts) -> list[str]:  # noqa: ANN001
    from database.models.visual_design_attempt import VisualDesignAttemptStatus

    passed = [a for a in attempts if a.status == VisualDesignAttemptStatus.PASSED]
    if not passed:
        return ["insufficient evidence: no recent PASSED attempts to summarize"]
    clean = sum(1 for a in passed if not a.issue_codes)
    media_strategies = {a.source_media_decision for a in passed if a.source_media_decision}
    lines = [f"{clean}/{len(passed)} recent PASSED attempts had zero notes"]
    if media_strategies:
        lines.append(f"media strategies that recently passed: {sorted(media_strategies)}")
    return lines


def _recent_art_director_feedback(attempts) -> list[str]:  # noqa: ANN001
    from database.models.visual_design_attempt import VisualDesignAttemptStatus

    rework = [a for a in attempts if a.status == VisualDesignAttemptStatus.REWORK][:5]
    if not rework:
        return ["no recent REWORK attempts"]
    return [f"attempt {a.attempt_number}: {a.art_decision} - issues={a.issue_codes}" for a in rework]


async def _budget_gate(session: AsyncSession, *, now: datetime) -> tuple[bool, str]:
    cost_known, cost_so_far = await daily_cost_summary(session, now=now)
    if not cost_known:
        return False, "daily visual cost unknown - fail-safe, revision not attempted"
    if cost_so_far >= settings.visual_max_cost_per_day:
        return False, f"daily visual budget exhausted (${cost_so_far:.2f}/${settings.visual_max_cost_per_day:.2f})"
    return True, f"${cost_so_far:.2f}/${settings.visual_max_cost_per_day:.2f} spent today"


async def request_brief_revision(
    session: AsyncSession, gateway: LLMGateway, prompt_repository: PromptRepository, *, scope: str,
    now: datetime | None = None,
) -> BriefRevisionResult:
    now = now or datetime.now(timezone.utc)

    if await get_frozen_brief(session, scope) is not None:
        return BriefRevisionResult(status=BriefRevisionStatus.BRIEF_FROZEN, reason="scope is FROZEN - per-post prompts may still vary, but the persistent brief cannot auto-change")

    active = await get_active_or_frozen_brief(session, scope)
    if active is None:
        return BriefRevisionResult(status=BriefRevisionStatus.NO_BRIEF_YET, reason="no Designer Brief exists yet for this scope")

    allowed, reason = await may_create_candidate(session, scope, now=now)
    if not allowed:
        return BriefRevisionResult(status=BriefRevisionStatus.NOT_ELIGIBLE, reason=reason)

    budget_ok, budget_reason = await _budget_gate(session, now=now)
    if not budget_ok:
        status = BriefRevisionStatus.BUDGET_UNKNOWN if "unknown" in budget_reason else BriefRevisionStatus.BUDGET_EXHAUSTED
        return BriefRevisionResult(status=status, reason=budget_reason)

    attempts = await recent_attempts_for_scope(session, scope)
    feed_context = await compute_visual_feed_context(session, now=now)

    context = build_brief_revision_context(
        scope=scope, active_brief_text=active.brief_text, active_brief_version=active.version,
        adaptation_reason=reason, issue_code_distribution=_issue_code_distribution(attempts),
        successful_history_summary=_successful_history_summary(attempts),
        feed_context_summary=feed_context.summary_lines(),
        recent_art_director_feedback=_recent_art_director_feedback(attempts),
        budget_state_summary=budget_reason, now=now,
    )

    logger.info("visual_brief_revision_requested", extra={"scope": scope, "reason": reason})

    try:
        proposal = await generate_candidate_brief_proposal(gateway, prompt_repository, context=context, parent_brief_version_id=str(active.id))
    except BriefRevisionBrandCoreViolationError as exc:
        logger.info("visual_brief_revision_rejected_by_brand_core", extra={"scope": scope, "reason": str(exc)})
        return BriefRevisionResult(status=BriefRevisionStatus.REJECTED_BY_BRAND_CORE, reason=str(exc))
    except BriefRevisionUnavailableError as exc:
        logger.warning("visual_brief_revision_failed", extra={"scope": scope, "reason": str(exc)})
        return BriefRevisionResult(status=BriefRevisionStatus.BRIEF_REVISION_UNAVAILABLE, reason=str(exc))

    # Defense in depth: re-validate here too, even though generate_candidate_brief_proposal()
    # already validated internally - a candidate is never persisted on the strength of the
    # generator's own internal check alone.
    brand_check = check_brief_text_against_brand_core(proposal.candidate_brief_text)
    if not brand_check.compliant:
        reason_text = "; ".join(v.detail for v in brand_check.violations)
        logger.info("visual_brief_revision_rejected_by_brand_core", extra={"scope": scope, "reason": reason_text})
        return BriefRevisionResult(status=BriefRevisionStatus.REJECTED_BY_BRAND_CORE, reason=reason_text, proposal=proposal)

    candidate = await create_candidate_brief(
        session, scope=scope, brief_text=proposal.candidate_brief_text, reason=proposal.change_summary,
        evidence={
            "target_failure_patterns": proposal.target_failure_patterns, "expected_effects": proposal.expected_effects,
            "known_risks": proposal.known_risks, "reasoning": proposal.reasoning, "evidence_refs": proposal.evidence_refs,
            "confidence": proposal.confidence, "model_provider": proposal.model_provider, "model_name": proposal.model_name,
            "cost_usd": proposal.cost_usd, "adaptation_reason": reason,
        },
    )
    logger.info(
        "visual_brief_revision_generated",
        extra={"scope": scope, "candidate_id": str(candidate.id), "confidence": proposal.confidence},
    )
    return BriefRevisionResult(status=BriefRevisionStatus.CANDIDATE_CREATED, reason=proposal.change_summary, candidate=candidate, proposal=proposal)


class AdaptationStatusLabel(str, enum.Enum):
    """Spec §20: a small, honest vocabulary for /design to show - never a raw evidence dump."""

    STABLE = "stable"
    POSSIBLE_SIGNAL = "possible_signal"
    REPEATED_PATTERN_DETECTED = "repeated_pattern_detected"
    CANDIDATE_READY = "candidate_ready"
    CANDIDATE_REJECTED = "candidate_rejected"
    FROZEN = "frozen"
    INSUFFICIENT_DATA = "insufficient_data"


async def describe_adaptation_status(session: AsyncSession, scope: str, *, now: datetime | None = None) -> AdaptationStatusLabel:
    """Pure read, zero Gateway calls - used by /design's own detail view (bot/handlers/
    visual_design.py never calls request_brief_revision() itself)."""
    from database.models.visual_designer_brief import VisualDesignerBriefStatus
    from services.visual_brief_adaptation_service import EvidenceStage, detect_repeated_pattern
    from services.visual_designer_brief_service import list_history

    now = now or datetime.now(timezone.utc)
    if await get_frozen_brief(session, scope) is not None:
        return AdaptationStatusLabel.FROZEN

    history = await list_history(session, scope)
    if any(v.status == VisualDesignerBriefStatus.CANDIDATE for v in history):
        return AdaptationStatusLabel.CANDIDATE_READY
    most_recent_rejected = next((v for v in history if v.status == VisualDesignerBriefStatus.REJECTED), None)
    if most_recent_rejected is not None and history and history[0].id == most_recent_rejected.id:
        return AdaptationStatusLabel.CANDIDATE_REJECTED

    evidence = await detect_repeated_pattern(session, scope)
    if evidence is None:
        return AdaptationStatusLabel.INSUFFICIENT_DATA
    if evidence.stage == EvidenceStage.REPEATED_PATTERN:
        return AdaptationStatusLabel.REPEATED_PATTERN_DETECTED
    if evidence.stage == EvidenceStage.POSSIBLE_SIGNAL:
        return AdaptationStatusLabel.POSSIBLE_SIGNAL
    return AdaptationStatusLabel.STABLE
