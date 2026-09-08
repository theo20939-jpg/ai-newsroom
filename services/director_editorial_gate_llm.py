"""DIRECTOR-CONTROL-PLANE-1A §4-5: Stage 2 - real Director LLM judgment for the minority of
candidates Stage 1 (services/director_editorial_gate.py's own deterministic core) flags as
ambiguous/high-value. Reuses the SAME Gateway architecture every other one-shot advisory call in
this codebase already established (services/business_context_command_parser.py's own synthetic-
RuntimeContext precedent, services/telegram_art_director_vision.py's own identical pattern for a
vision call) - never a new, second LLM-calling framework (spec §4's own explicit instruction).

Not wired to fire automatically from any live worker path in this phase - `is_escalation_worthy()`
and `llm_escalate_gate()` are real, tested, callable functions a future phase's own budget-gated
orchestration wires in, exactly like services/visual_design_loop.py's own injected `render_fn`/
`art_director_fn` precedent (the real decision logic is complete; only the live network call is
deferred, and only because no paid-call authorization exists for this exact phase)."""
from __future__ import annotations

from uuid import uuid4

from database.models.editorial_task import TaskPriority
from database.models.director_editorial_decision import EditorialGateDecision, EditorialGateReasonCode
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, LLMGateway, Message
from integrations.prompts.protocol import PromptRepository
from schemas.capability import RuntimeContext
from services.director_editorial_gate import EditorialGateInput, GateOutcome

GATE_PROMPT_NAME = "director_editorial_gate"
GATE_PROMPT_VERSION = "1"

# Spec §4's own required escalation triggers - ambiguous/high-value/campaign-relevant/breaking/
# feed-gap candidates only, never every story.
_AMBIGUOUS_NOVELTY_BAND = (0.35, 0.65)


def is_escalation_worthy(gate_input: EditorialGateInput, baseline: GateOutcome) -> bool:
    """Spec §4's own explicit trigger list. Deterministic, cheap (no Gateway call itself) - the
    real cost-bounding filter Stage 2 sits behind."""
    if gate_input.active_campaign_relevant:
        return True
    if gate_input.is_potential_breaking:
        return True
    if EditorialGateReasonCode.FEED_GAP_FILL in baseline.reason_codes:
        return True
    if _AMBIGUOUS_NOVELTY_BAND[0] <= gate_input.novelty_score <= _AMBIGUOUS_NOVELTY_BAND[1]:
        return True
    return False


def _build_task_text(gate_input: EditorialGateInput) -> str:
    directive_lines = "\n".join(f"- {d.instruction}" for d in gate_input.active_directives) or "(none active)"
    return (
        f"story_facts_summary: {gate_input.story_facts_summary}\n"
        f"category: {gate_input.category}\n"
        f"topic_keywords: {gate_input.topic_keywords}\n"
        f"source_confidence: {gate_input.source_confidence}\n"
        f"novelty_score: {gate_input.novelty_score}\n"
        f"is_duplicate_of_recent: {gate_input.is_duplicate_of_recent}\n"
        f"active_campaign_relevant: {gate_input.active_campaign_relevant}\n"
        f"recent_posting_cadence_per_hour: {gate_input.recent_posting_cadence_per_hour}\n"
        f"feed_topic_distribution: {gate_input.feed_topic_distribution}\n"
        f"active Founder Directives:\n{directive_lines}"
    )


async def llm_escalate_gate(
    gateway: LLMGateway, prompt_repository: PromptRepository, gate_input: EditorialGateInput,
) -> GateOutcome:
    """The real Stage 2 call. Never raises past this point in a way the caller can't fail-soft
    on - services/director_editorial_gate.py::run_editorial_gate_fail_soft() already wraps
    whatever `llm_escalate` callable it is given in its own try/except, falling back to the Stage
    1 deterministic outcome on any failure (spec §6's own fail-soft requirement)."""
    prompt = prompt_repository.resolve(GATE_PROMPT_NAME, GATE_PROMPT_VERSION)
    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    request = GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=system_text)]),
            Message(role="user", content=[ContentPart(type="text", text=_build_task_text(gate_input))]),
        ],
        response_mode="json_schema", response_schema=prompt.output_schema,
    )
    runtime = RuntimeContext(
        task_id=uuid4(), event_id=uuid4(), capability_name="director_editorial_gate",
        priority=TaskPriority.S, attempt=1, iteration_count=0,
    )

    from capabilities.gateway_call import call_generate  # local import: avoids a capabilities<->services import cycle at module load time

    outcome = await call_generate(gateway, request, runtime=runtime, sequence=1)
    if outcome.error is not None:
        raise RuntimeError(str(outcome.error))
    assert outcome.response is not None
    output = outcome.response.structured_output or {}

    decision = EditorialGateDecision(output.get("decision", "hold"))
    reason_codes = [EditorialGateReasonCode(code) for code in output.get("reason_codes", [])]
    priority_by_decision = {
        EditorialGateDecision.DROP: 0, EditorialGateDecision.HOLD: 20,
        EditorialGateDecision.SEND_TO_EDITOR: 50, EditorialGateDecision.PRIORITY: 75,
        EditorialGateDecision.BREAKING: 100,
    }
    return GateOutcome(
        decision=decision, priority=priority_by_decision[decision], reason_codes=reason_codes,
        short_reason=str(output.get("short_reason", "")),
    )
