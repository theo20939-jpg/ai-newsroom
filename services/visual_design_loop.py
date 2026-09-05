"""VISUAL-DESIGN-AUTONOMY-1, spec §22/§48/§49: the per-post design loop - Story -> Visual Design
Director -> creative prompt -> generation/render (INJECTED, see below) -> Art Director -> PASS or
REWORK, feeding real Art Director feedback back to the Visual Design Director on every retry.

CRITICAL (spec §62/§26): this phase implements REAL orchestration logic (budget checks, attempt
counting, root-cause routing, hard termination, VisualDesignAttempt persistence) but never wires a
real image-generation or rendering call itself - `render_fn` is an INJECTED async callable the
caller supplies (a real one in a future production-wiring phase, a fake one in every test here).
This is not a contract-only placeholder (spec §83): every decision this loop makes - whether to
continue, what root cause to route on, when to stop - is real, tested logic; only the actual
network/pixel work is deferred to the caller, exactly like services/telegram_art_director_vision.py
already defers to an injected `gateway`.

CRITICAL (spec §46): this loop persists VisualDesignAttempt rows (its own per-attempt memory) and,
only when explicitly enabled, ONE summary DirectorRun at the end - mirroring
services/director_execution_service.py's own "execution, never console-read, may persist" role.
Nothing in bot/services/worker calls this loop automatically this phase (spec §62's own "no
production wiring" instruction)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.director_run import DirectorRunStatus, DirectorType
from database.models.visual_design_attempt import VisualDesignAttempt, VisualDesignAttemptStatus, VisualFailureRootCause
from database.models.visual_designer_brief import VisualDesignerBriefVersion
from integrations.llm_gateway.protocol import LLMGateway
from integrations.prompts.protocol import PromptRepository
from services.director_run_service import compute_input_fingerprint, create_director_run
from services.telegram_art_director import ArtDirectorDecision, ArtDirectorResult
from services.visual_budget_service import BudgetCheckResult, BudgetDecision, check_budget
from services.visual_creative_direction import PreviousAttemptFeedback, VisualCreativeDirection
from services.visual_design_director import (
    StoryFactsInput,
    VisualDesignDirectorUnavailableError,
    VisualDesignFactSafetyError,
    build_visual_director_context,
    generate_creative_direction,
)
from services.visual_designer_brief_service import GLOBAL_SCOPE, get_active_or_frozen_brief
from services.visual_feed_context import compute_visual_feed_context
from services.visual_root_cause import classify_root_cause

logger = logging.getLogger(__name__)

RenderFn = Callable[[VisualCreativeDirection], Awaitable["RenderOutcome"]]
ArtDirectorFn = Callable[["RenderOutcome"], Awaitable[ArtDirectorResult]]

_TERMINAL_STATUSES = frozenset({
    VisualDesignAttemptStatus.PASSED, VisualDesignAttemptStatus.FAILED,
    VisualDesignAttemptStatus.BUDGET_EXHAUSTED, VisualDesignAttemptStatus.HUMAN_REVIEW,
})


@dataclass(frozen=True)
class RenderOutcome:
    """What an injected `render_fn` returns - real bytes/cost/reference in production, a fake,
    fully-controlled value in every test."""

    rendered_bytes: bytes
    render_reference: str | None
    generation_model: str | None
    generation_cost: float | None


@dataclass(frozen=True)
class VisualDesignLoopResult:
    story_id: str
    platform: str
    final_status: VisualDesignAttemptStatus
    attempts: list[VisualDesignAttempt]
    director_run_id: UUID | None = None


def _art_decision_to_attempt_status(decision: ArtDirectorDecision) -> VisualDesignAttemptStatus:
    if decision == ArtDirectorDecision.PASS:
        return VisualDesignAttemptStatus.PASSED
    if decision == ArtDirectorDecision.PASS_WITH_NOTES:
        return VisualDesignAttemptStatus.PASSED
    return VisualDesignAttemptStatus.REWORK


async def run_visual_design_loop(
    session: AsyncSession, gateway: LLMGateway, prompt_repository: PromptRepository, *,
    story: StoryFactsInput, platform: str, presentation_type: str | None, scope: str = GLOBAL_SCOPE,
    render_fn: RenderFn, art_director_fn: ArtDirectorFn,
    available_media_summary: str = "unknown", renderer_constraints_summary: str = "unknown",
    restricted_claims: list[str] | None = None, now: datetime | None = None,
) -> VisualDesignLoopResult:
    now = now or datetime.now(timezone.utc)
    story_uuid = _safe_uuid(story.story_id)

    brief = await get_active_or_frozen_brief(session, scope)
    brief_text = brief.brief_text if brief is not None else "(no persistent Designer Brief configured yet for this scope)"
    brief_version_number = brief.version if brief is not None else 0

    feed_context = await compute_visual_feed_context(session, now=now)

    attempts: list[VisualDesignAttempt] = []
    previous_feedback: PreviousAttemptFeedback | None = None

    while True:
        budget = await check_budget(session, story_id=story_uuid, platform=platform, presentation_type=presentation_type, now=now)
        if not budget.allowed:
            status = _budget_decision_to_status(budget.decision)
            attempt = await _persist_attempt(
                session, story_uuid=story_uuid, platform=platform, presentation_type=presentation_type,
                brief=brief, attempt_number=budget.attempts_used + 1, status=status,
            )
            attempts.append(attempt)
            break

        context = build_visual_director_context(
            story=story, platform=platform, presentation_type=presentation_type,
            designer_brief_text=brief_text, designer_brief_scope=scope, designer_brief_version=brief_version_number,
            feed_context_summary=feed_context.summary_lines(), recent_failure_summary=_failure_summary(previous_feedback),
            available_media_summary=available_media_summary, renderer_constraints_summary=renderer_constraints_summary,
            attempts_used=budget.attempts_used, max_attempts=budget.max_attempts,
            budget_state_summary=_budget_summary(budget), restricted_claims=restricted_claims,
            previous_attempt=previous_feedback, now=now,
        )

        attempt_number = budget.attempts_used + 1
        try:
            direction = await generate_creative_direction(gateway, prompt_repository, context=context)
        except (VisualDesignDirectorUnavailableError, VisualDesignFactSafetyError) as exc:
            logger.warning("visual_design_director_unavailable", extra={"story_id": story.story_id, "reason": str(exc)})
            attempt = await _persist_attempt(
                session, story_uuid=story_uuid, platform=platform, presentation_type=presentation_type,
                brief=brief, attempt_number=attempt_number, status=VisualDesignAttemptStatus.FAILED,
            )
            attempts.append(attempt)
            break

        render_outcome = await render_fn(direction)
        art_result = await art_director_fn(render_outcome)
        root_cause = classify_root_cause(list(art_result.issue_codes)) if art_result.issue_codes else None
        total_cost = _sum_known_costs(render_outcome.generation_cost)

        status = _art_decision_to_attempt_status(art_result.decision)
        if art_result.decision == ArtDirectorDecision.BLOCK:
            status = VisualDesignAttemptStatus.HUMAN_REVIEW

        attempt = await _persist_attempt(
            session, story_uuid=story_uuid, platform=platform, presentation_type=presentation_type, brief=brief,
            attempt_number=attempt_number, status=status, creative_direction=_direction_payload(direction),
            prompt_text=direction.prompt_text, source_media_decision=direction.media_strategy.value,
            generation_model=render_outcome.generation_model, generation_cost=render_outcome.generation_cost,
            total_cost=total_cost, render_reference=render_outcome.render_reference,
            art_decision=art_result.decision.value, issue_codes=[c.value for c in art_result.issue_codes],
            root_cause=root_cause,
        )
        attempts.append(attempt)

        if status in _TERMINAL_STATUSES:
            break

        # REWORK and budget still allows another try - feed real feedback back for the next
        # iteration (spec §49: never biased toward a minimal edit, the director may redesign).
        previous_feedback = PreviousAttemptFeedback(
            attempt_number=attempt_number, previous_creative_direction_summary=direction.creative_intent,
            previous_prompt_text=direction.prompt_text, art_decision=art_result.decision.value,
            issue_codes=[c.value for c in art_result.issue_codes], instructions=art_result.instructions,
            root_cause=(root_cause.value if root_cause is not None else "unknown"),
            attempts_remaining=max(budget.max_attempts - attempt_number, 0),
        )

    final_status = attempts[-1].status
    director_run_id = await _maybe_persist_director_run(
        session, story=story, platform=platform, attempts=attempts, final_status=final_status, now=now,
    )
    return VisualDesignLoopResult(story_id=story.story_id, platform=platform, final_status=final_status, attempts=attempts, director_run_id=director_run_id)


def _safe_uuid(story_id: str) -> UUID:
    try:
        return UUID(story_id)
    except ValueError:
        # Non-UUID story ids (e.g. a synthetic test id) still need a stable, real UUID column
        # value - deterministic from the string, never random, so repeated calls for the same
        # story_id keep counting against the same budget row set.
        import uuid as _uuid
        return _uuid.uuid5(_uuid.NAMESPACE_URL, f"visual-design-story:{story_id}")


def _budget_decision_to_status(decision: BudgetDecision) -> VisualDesignAttemptStatus:
    if decision == BudgetDecision.ATTEMPT_LIMIT_REACHED:
        return VisualDesignAttemptStatus.HUMAN_REVIEW
    return VisualDesignAttemptStatus.BUDGET_EXHAUSTED


def _budget_summary(budget: BudgetCheckResult) -> str:
    parts = [f"{budget.attempts_used}/{budget.max_attempts} attempts used"]
    if budget.post_cost_known:
        parts.append(f"${budget.post_cost_so_far:.2f} spent on this post")
    else:
        parts.append("post cost unknown")
    if budget.daily_cost_known:
        parts.append(f"${budget.daily_cost_so_far:.2f} spent today")
    else:
        parts.append("daily cost unknown")
    return "; ".join(parts)


def _failure_summary(previous_feedback: PreviousAttemptFeedback | None) -> list[str]:
    if previous_feedback is None:
        return []
    return [f"attempt {previous_feedback.attempt_number}: {previous_feedback.art_decision} - {previous_feedback.instructions}"]


def _direction_payload(direction: VisualCreativeDirection) -> dict:
    return {
        "creative_intent": direction.creative_intent, "visual_angle": direction.visual_angle,
        "composition": direction.composition, "palette_direction": direction.palette_direction,
        "media_strategy": direction.media_strategy.value, "preferred_overlay_zone": direction.preferred_overlay_zone,
        "risks": direction.risks, "reasoning": direction.reasoning,
    }


def _sum_known_costs(*costs: float | None) -> float | None:
    """None (never a fabricated 0.0) the moment ANY supplied cost is unknown - mirrors
    services/visual_budget_service.py's own "unknown cost is never silently zero" rule."""
    if any(c is None for c in costs):
        return None
    return sum(costs)  # type: ignore[arg-type]  # every element is a float once the None-check above passes


async def _persist_attempt(
    session: AsyncSession, *, story_uuid: UUID, platform: str, presentation_type: str | None,
    brief: VisualDesignerBriefVersion | None, attempt_number: int, status: VisualDesignAttemptStatus,
    creative_direction: dict | None = None, prompt_text: str | None = None, source_media_decision: str | None = None,
    generation_model: str | None = None, generation_cost: float | None = None, total_cost: float | None = None,
    render_reference: str | None = None, art_decision: str | None = None, issue_codes: list[str] | None = None,
    root_cause: VisualFailureRootCause | None = None,
) -> VisualDesignAttempt:
    attempt = VisualDesignAttempt(
        story_id=story_uuid, platform=platform, presentation_type=presentation_type,
        brief_version_id=brief.id if brief is not None else None, attempt_number=attempt_number,
        creative_direction=creative_direction, prompt_text=prompt_text, source_media_decision=source_media_decision,
        generation_model=generation_model, generation_cost=generation_cost, total_cost=total_cost,
        render_reference=render_reference, art_decision=art_decision, issue_codes=issue_codes,
        root_cause=root_cause, status=status,
    )
    session.add(attempt)
    await session.commit()
    await session.refresh(attempt)
    logger.info(
        "visual_design_attempt_completed",
        extra={"attempt_id": str(attempt.id), "story_id": str(story_uuid), "status": status.value, "attempt_number": attempt_number},
    )
    if status == VisualDesignAttemptStatus.REWORK:
        logger.info("visual_design_rework_requested", extra={"attempt_id": str(attempt.id), "attempt_number": attempt_number})
    if status == VisualDesignAttemptStatus.BUDGET_EXHAUSTED:
        logger.info("visual_design_budget_exhausted", extra={"story_id": str(story_uuid), "attempt_number": attempt_number})
    return attempt


_FINAL_STATUS_TO_RUN_STATUS: dict[VisualDesignAttemptStatus, DirectorRunStatus] = {
    VisualDesignAttemptStatus.PASSED: DirectorRunStatus.OK,
    VisualDesignAttemptStatus.FAILED: DirectorRunStatus.BLOCKED,
    VisualDesignAttemptStatus.BUDGET_EXHAUSTED: DirectorRunStatus.BLOCKED,
    VisualDesignAttemptStatus.HUMAN_REVIEW: DirectorRunStatus.BLOCKED,
}


async def _maybe_persist_director_run(
    session: AsyncSession, *, story: StoryFactsInput, platform: str, attempts: list[VisualDesignAttempt],
    final_status: VisualDesignAttemptStatus, now: datetime,
) -> UUID | None:
    """Spec §46: one summary DirectorRun for `/directors`/`/design` continuity, persisted only
    when explicitly enabled - never from a console read (this function is only ever reachable via
    run_visual_design_loop(), an execution, exactly like services/director_execution_service.py's
    own run_* functions)."""
    if not settings.director_run_persistence_enabled:
        return None
    last = attempts[-1]
    run = await create_director_run(
        session, director_type=DirectorType.TELEGRAM_VISUAL_DESIGN, platform=platform, generated_at=now,
        input_fingerprint=compute_input_fingerprint(story.story_id, platform, len(attempts)),
        result_payload={
            "attempt_count": len(attempts), "final_status": final_status.value,
            "issue_codes": last.issue_codes or [], "root_cause": last.root_cause.value if last.root_cause else None,
        },
        status=_FINAL_STATUS_TO_RUN_STATUS.get(final_status, DirectorRunStatus.WAITING_FOR_DATA),
        subject_type="story", subject_id=_safe_uuid(story.story_id), decision=f"{len(attempts)} attempt(s), {final_status.value}",
    )
    return run.id
