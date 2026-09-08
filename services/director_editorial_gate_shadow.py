"""DIRECTOR-CONTROL-PLANE-1A §2-8: the real PRE-GENERATION Editorial Gate orchestration -
supersedes DIRECTOR-CONTROL-PLANE-1's own identically-named module, which ran too late (at the
presentation-decision point, after copywriting had already happened). This version is called from
worker/content_cycle.py's real per-event loop BEFORE run_content_generation_for_event() - see that
call site's own comment for the exact call graph.

Exact call graph (spec §2's own required return value):

    _select_eligible_events()
    -> [router mode only] _classify_event_for_router_treatment() -> SKIP check
    -> [router mode only] check_duplicate_story_delivery() -> duplicate_blocked check
    -> check_update_would_fail_closed() -> update_fail_closed check
    -> run_pre_generation_gate()                                    <-- THIS MODULE
       -> services.director_editorial_gate_context.build_gate_input_for_event()  (real signals)
       -> services.director_editorial_gate.evaluate_editorial_gate()             (Stage 1, always)
       -> services.director_editorial_gate_llm.is_escalation_worthy()            (Stage 2 trigger, cheap)
       -> [ONLY if escalation_worthy AND a real gateway was threaded in AND
           check_gate_llm_budget() allows]
             services.director_editorial_gate.run_editorial_gate_fail_soft(
                 llm_escalate=director_editorial_gate_llm.llm_escalate_gate, is_ambiguous=True)
          -> real Gateway-backed Stage 2 Director judgment, or - on ANY gateway failure
             (timeout / provider error / rate limit / invalid schema / empty output) - a
             fail-soft fall back to the Stage 1 deterministic outcome (never DROP-everything).
       -> persist_gate_decision() (always, regardless of flag - spec §7's own "OFF -> still persist")
          - director_version="v1-llm" whenever a Stage 2 call was ATTEMPTED (success OR
            fail-soft), so check_gate_llm_budget()'s own daily count bounds paid calls, not
            just successful ones.
    -> [ONLY if telegram_editorial_gate_enabled AND decision in (DROP, HOLD)] continue (skip generation)
    -> run_content_generation_for_event()

Stage 2 is BOUNDED (spec §3): a call happens only when is_escalation_worthy() is True, a real
gateway/prompt_repository pair was threaded through from worker/content_main.py, AND
services/director_editorial_gate_budget.py::check_gate_llm_budget() reports budget available
(settings.director_editorial_gate_max_llm_reviews_per_day, default 100). Budget exhausted -> the
Stage 1 deterministic outcome is used unchanged. A caller that threads no gateway (tests that do
not opt in, any environment where the AI layer is unavailable) gets Stage-1-only behavior,
byte-identical to before this wiring."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.director_editorial_decision import EditorialGateDecision, EditorialGateReasonCode
from services.director_editorial_gate import GateOutcome, evaluate_editorial_gate, run_editorial_gate_fail_soft
from services.director_editorial_gate_budget import STAGE_2_DIRECTOR_VERSION_MARKER, check_gate_llm_budget
from services.director_editorial_gate_context import build_gate_input_for_event
from services.director_editorial_gate_llm import is_escalation_worthy, llm_escalate_gate
from services.director_editorial_gate_persistence import persist_gate_decision

if TYPE_CHECKING:
    from integrations.llm_gateway.protocol import LLMGateway
    from integrations.prompts.protocol import PromptRepository

logger = logging.getLogger(__name__)

_QUEUE_REACHING_DECISIONS = frozenset({
    EditorialGateDecision.SEND_TO_EDITOR, EditorialGateDecision.PRIORITY, EditorialGateDecision.BREAKING,
})
_SUPPRESSIBLE_DECISIONS = frozenset({EditorialGateDecision.DROP, EditorialGateDecision.HOLD})

# `GateEvaluation.stage2_status` values - log/metric visibility only, never a control signal.
STAGE2_NOT_ELIGIBLE = "not_eligible"          # is_escalation_worthy() was False
STAGE2_NO_GATEWAY = "no_gateway"              # eligible, but no gateway/prompt_repository threaded in
STAGE2_BUDGET_EXHAUSTED = "budget_exhausted"  # eligible + gateway present, daily LLM budget spent
STAGE2_USED = "used"                          # a real Stage 2 judgment was applied
STAGE2_FAILED_FELL_BACK = "failed_fell_back"  # Stage 2 attempted, provider failed, Stage 1 outcome kept


@dataclass(frozen=True)
class GateEvaluation:
    """What worker/content_cycle.py's own loop needs back: the real outcome, plus the two boolean
    facts it uses to update ContentCycleResult's shadow counters and decide whether to `continue`.
    `stage2_status` is one of the module-level `STAGE2_*` strings."""

    outcome: GateOutcome
    escalation_worthy: bool
    suppress_generation: bool  # True only when the flag is ON and decision is DROP/HOLD
    stage2_status: str = STAGE2_NOT_ELIGIBLE


async def run_pre_generation_gate(
    session: AsyncSession, event_id: UUID, *, platform: str = "telegram", now: datetime,
    gateway: "LLMGateway | None" = None, prompt_repository: "PromptRepository | None" = None,
) -> GateEvaluation | None:
    """Returns None only if `build_gate_input_for_event()` itself returns None (the event row is
    already gone - defensive, should not happen for an event the caller just selected). Always
    computes and persists a real decision, REGARDLESS of `telegram_editorial_gate_enabled` (spec
    §7's own "OFF -> still calculate and persist real gate decisions" requirement) - only
    `suppress_generation` is flag-gated.

    `gateway`/`prompt_repository`: when BOTH are supplied (worker/content_main.py's real call
    site), an escalation-worthy candidate whose daily Stage 2 budget is not yet exhausted gets a
    real Gateway-backed Director judgment, fail-soft to the Stage 1 outcome on any provider
    failure. When either is None, Stage 1 is the decision - identical to pre-wiring behavior."""
    gate_input = await build_gate_input_for_event(session, event_id, platform=platform, now=now)
    if gate_input is None:
        return None

    baseline = evaluate_editorial_gate(gate_input)
    escalation_worthy = is_escalation_worthy(gate_input, baseline)

    outcome = baseline
    director_version = "v1"
    stage2_status = STAGE2_NOT_ELIGIBLE

    if escalation_worthy:
        if gateway is None or prompt_repository is None:
            stage2_status = STAGE2_NO_GATEWAY
        else:
            budget = await check_gate_llm_budget(session, now=now)
            if not budget.allowed:
                stage2_status = STAGE2_BUDGET_EXHAUSTED
                logger.info(
                    "director_editorial_gate_stage2_budget_exhausted reviews_today=%d max=%d",
                    budget.reviews_today, budget.max_reviews_per_day,
                )
            else:
                async def _escalate(gi: object) -> GateOutcome:
                    return await llm_escalate_gate(gateway, prompt_repository, gi)  # type: ignore[arg-type]

                outcome = await run_editorial_gate_fail_soft(gate_input, llm_escalate=_escalate, is_ambiguous=True)
                # An ATTEMPT was made - it counts against the daily bound whether the provider
                # answered or we fell soft back to Stage 1 (spec §3: the bound is on paid calls).
                director_version = STAGE_2_DIRECTOR_VERSION_MARKER
                if outcome.fallback_mode is not None:
                    stage2_status = STAGE2_FAILED_FELL_BACK
                    outcome = _annotate_fallback(outcome)
                else:
                    stage2_status = STAGE2_USED

    await persist_gate_decision(
        session, gate_input=gate_input, outcome=outcome, director="channel_director",
        director_version=director_version,
    )

    suppress = settings.telegram_editorial_gate_enabled and outcome.decision in _SUPPRESSIBLE_DECISIONS
    logger.info(
        "director_editorial_gate decision=%s priority=%d reasons=%s escalation_worthy=%s "
        "stage2=%s enforcement=%s suppress_generation=%s",
        outcome.decision.value, outcome.priority, [c.value for c in outcome.reason_codes],
        escalation_worthy, stage2_status, settings.telegram_editorial_gate_enabled, suppress,
    )
    return GateEvaluation(
        outcome=outcome, escalation_worthy=escalation_worthy, suppress_generation=suppress,
        stage2_status=stage2_status,
    )


def _annotate_fallback(outcome: GateOutcome) -> GateOutcome:
    """Stamp the fail-soft provenance onto the persisted reason codes so a shadow-metrics reader
    can tell a Stage-1-by-fallback decision from a Stage-1-by-design one - `GateOutcome` is
    frozen, so this returns a new one rather than mutating."""
    if EditorialGateReasonCode.LLM_UNAVAILABLE_FALLBACK in outcome.reason_codes:
        return outcome
    return GateOutcome(
        decision=outcome.decision, priority=outcome.priority,
        reason_codes=[*outcome.reason_codes, EditorialGateReasonCode.LLM_UNAVAILABLE_FALLBACK],
        short_reason=outcome.short_reason, fallback_mode=outcome.fallback_mode,
    )


def reaches_editor_queue(decision: EditorialGateDecision) -> bool:
    return decision in _QUEUE_REACHING_DECISIONS
