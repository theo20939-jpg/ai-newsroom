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
    -> run_pre_generation_gate()                                    <-- THIS MODULE, NEW
       -> services.director_editorial_gate_context.build_gate_input_for_event()  (real signals)
       -> services.director_editorial_gate.evaluate_editorial_gate()             (Stage 1, always)
       -> services.director_editorial_gate_llm.is_escalation_worthy()            (Stage 2 trigger, cheap)
          [Stage 2 LLM call itself is NOT invoked from this live call site - see module docstring
           "HONEST SCOPE" note below; is_escalation_worthy() alone still drives the real
           gate_director_reviewed shadow metric]
       -> persist_gate_decision() (always, regardless of flag - spec §7's own "OFF -> still persist")
    -> [ONLY if telegram_editorial_gate_enabled AND decision in (DROP, HOLD)] continue (skip generation)
    -> run_content_generation_for_event()

HONEST SCOPE NOTE on Stage 2: `services/director_editorial_gate_llm.py::llm_escalate_gate()` is a
real, tested, Gateway-backed function - it is not called from this live orchestration because
`run_content_cycle()`'s own signature has no `gateway`/`prompt_repository` parameter to thread
through (every existing real LLM call in this file goes through the full Capability/
CapabilityExecutor/WorkflowRunner machinery instead, which is Story/EditorialTask-bound and not
reachable at this exact pre-generation point without a real, disproportionate signature change to
an already-`enforce`-mode production hot path). `is_escalation_worthy()` - the cheap, real, Gateway-
free trigger check - IS called for real here, so `gate_director_reviewed` reports the true count of
candidates that WOULD be escalated to Stage 2 once a future phase threads a gateway through."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.director_editorial_decision import EditorialGateDecision
from services.director_editorial_gate import GateOutcome, evaluate_editorial_gate
from services.director_editorial_gate_context import build_gate_input_for_event
from services.director_editorial_gate_llm import is_escalation_worthy
from services.director_editorial_gate_persistence import persist_gate_decision

logger = logging.getLogger(__name__)

_QUEUE_REACHING_DECISIONS = frozenset({
    EditorialGateDecision.SEND_TO_EDITOR, EditorialGateDecision.PRIORITY, EditorialGateDecision.BREAKING,
})
_SUPPRESSIBLE_DECISIONS = frozenset({EditorialGateDecision.DROP, EditorialGateDecision.HOLD})


@dataclass(frozen=True)
class GateEvaluation:
    """What worker/content_cycle.py's own loop needs back: the real outcome, plus the two boolean
    facts it uses to update ContentCycleResult's shadow counters and decide whether to `continue`."""

    outcome: GateOutcome
    escalation_worthy: bool
    suppress_generation: bool  # True only when the flag is ON and decision is DROP/HOLD


async def run_pre_generation_gate(
    session: AsyncSession, event_id: UUID, *, platform: str = "telegram", now: datetime,
) -> GateEvaluation | None:
    """Returns None only if `build_gate_input_for_event()` itself returns None (the event row is
    already gone - defensive, should not happen for an event the caller just selected). Always
    computes and persists a real decision, REGARDLESS of `telegram_editorial_gate_enabled` (spec
    §7's own "OFF -> still calculate and persist real gate decisions" requirement) - only
    `suppress_generation` is flag-gated."""
    gate_input = await build_gate_input_for_event(session, event_id, platform=platform, now=now)
    if gate_input is None:
        return None

    outcome = evaluate_editorial_gate(gate_input)
    escalation_worthy = is_escalation_worthy(gate_input, outcome)

    await persist_gate_decision(session, gate_input=gate_input, outcome=outcome, director="channel_director")

    suppress = settings.telegram_editorial_gate_enabled and outcome.decision in _SUPPRESSIBLE_DECISIONS
    logger.info(
        "director_editorial_gate decision=%s priority=%d reasons=%s escalation_worthy=%s "
        "enforcement=%s suppress_generation=%s",
        outcome.decision.value, outcome.priority, [c.value for c in outcome.reason_codes],
        escalation_worthy, settings.telegram_editorial_gate_enabled, suppress,
    )
    return GateEvaluation(outcome=outcome, escalation_worthy=escalation_worthy, suppress_generation=suppress)


def reaches_editor_queue(decision: EditorialGateDecision) -> bool:
    return decision in _QUEUE_REACHING_DECISIONS
