"""EditorialPlanningCapability - Phase 19 M3: structured editorial planning metadata, produced
BEFORE Copywriting writes anything (docs/phase19_m0_audit.md).

An ordinary Capability, following capabilities/research_capability.py's shape exactly
(`__init__(gateway, prompt_repository)` only, one `call_generate()` invocation, no retry).

Registered in capabilities/registry.py like every other Capability (real, resolvable, cost-
tracked via capability_mapping.py's "editorial_planning" -> AICapability.INTELLIGENCE entry) -
but, in this phase, deliberately NOT referenced by CONTENT_GENERATION's own WorkflowDefinition,
mirroring the exact precedent capabilities/registry.py's own comment already documents for
"meme_concept"/"meme_copywriting" (Phase 18 M2/M4): registered and independently callable, before
any live workflow step references it. The only caller of this Capability's real, LLM-backed
`execute()` in this phase is the manually-invoked, never-auto-run comparison script
(scripts/phase19_m3_editorial_plan_comparison.py) - the live CONTENT_GENERATION path's own
"shadow" behavior uses services/editorial_planning_deterministic.py's zero-cost, zero-LLM-call
scaffold instead (see capabilities/executor.py::_attach_editorial_plan()), per the explicit
constraint that shadow mode must never make a live LLM call or alter Copywriting's own output.

This module intentionally duplicates the floor-validation helper other Capabilities already
duplicate (§19.2 Q1 precedent) - the `isinstance(declared_type, str)` guard mirrors
capabilities/copywriting_capability.py's own fix for nullable (`[type, "null"]`) schema fields.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from capabilities.errors import ValidationCapabilityError
from capabilities.gateway_call import call_generate
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, LLMGateway, Message
from integrations.prompts.protocol import PromptRepository, RenderedPrompt
from schemas.capability import CapabilityContext, CapabilityResult
from schemas.capability_definition import CapabilityConfig, CapabilityDefinition

logger = logging.getLogger(__name__)

CAPABILITY_NAME = "editorial_planning"
PROMPT_VERSION = "1"

EDITORIAL_PLANNING_CAPABILITY_DEFINITION = CapabilityDefinition(
    name=CAPABILITY_NAME,
    version=1,
    config=CapabilityConfig(timeout_seconds=30),
    required_context=["news_event"],
    expected_output_keys=[
        "central_fact", "what_changed", "what_is_new", "why_it_matters", "essential_facts",
        "secondary_facts_omittable", "necessary_background", "already_published_summary",
        "must_not_repeat", "story_classification", "headline_emphasis", "opening_emphasis",
        "what_remains_unknown", "verified_quote_text", "media_role_needed", "editorial_risks",
    ],
)

_SCHEMA_TYPE_TO_PYTHON_TYPE: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _floor_validate(structured_output: dict[str, Any] | None, output_schema: dict[str, Any]) -> str | None:
    """Contract §9.1's floor - see scoring_capability._floor_validate's identical docstring for
    the full rationale. Duplicated intentionally (module docstring). `isinstance(declared_type,
    str)` guard mirrors capabilities/copywriting_capability.py's own fix: a nullable field's
    `type` is a list (`["string", "null"]`), not a hashable dict-lookup key."""
    if structured_output is None:
        return "structured_output is missing; the §9.1 floor requires an object."

    required = output_schema.get("required", [])
    missing = [key for key in required if key not in structured_output]
    if missing:
        return f"structured_output is missing required key(s): {missing}"

    properties: dict[str, Any] = output_schema.get("properties", {})
    for key, declared in properties.items():
        if key not in structured_output:
            continue
        declared_type = declared.get("type")
        if not isinstance(declared_type, str):
            continue  # nullable ([type, "null"]) - not checked at this floor
        expected_python_type = _SCHEMA_TYPE_TO_PYTHON_TYPE.get(declared_type)
        if expected_python_type is None:
            continue
        value = structured_output[key]
        if declared_type == "integer" and isinstance(value, bool):
            return f"structured_output['{key}'] must be an integer, got bool."
        if not isinstance(value, expected_python_type):
            return f"structured_output['{key}'] must be of type '{declared_type}', got {type(value).__name__}."

    return None


def _build_request(context: CapabilityContext, prompt: RenderedPrompt) -> GenerateRequest:
    """Reads context.business.news_event plus (when present) the already-completed research/
    intelligence step_results and the Phase 19 M1/M2 article evidence field - the same
    already-wired evidence-attachment mechanism research_capability.py's own _build_request()
    uses, never a second, divergent evidence-reading path."""
    news_event = context.business.news_event
    research_output = context.business.workflow_state.step_results.get("research", {})
    intelligence_output = context.business.workflow_state.step_results.get("intelligence", {})
    evidence_text = context.business.article_evidence_text or news_event.content or "(none)"

    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    context_text = (
        f"Title: {news_event.title}\n"
        f"Category: {news_event.category}\n"
        f"Evidence text: {evidence_text}\n"
        f"Research facts: {research_output.get('facts', [])}\n"
        f"Intelligence judgment: {intelligence_output}\n"
        f"Target output language: {context.business.language}"
    )
    task_text = "Produce the structured editorial plan, grounded only in the evidence above."

    return GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=system_text)]),
            Message(
                role="user",
                content=[ContentPart(type="text", text=f"CONTEXT:\n{context_text}\n\nTASK:\n{task_text}")],
            ),
        ],
        preferred_model=context.execution.preferred_model,
        preferred_provider=context.execution.preferred_provider,
        max_tokens=context.execution.max_tokens,
        reasoning_effort=context.execution.reasoning_effort,
        temperature=context.execution.temperature,
        response_mode="json_schema",
        response_schema=prompt.output_schema,
    )


class EditorialPlanningCapability:
    """Implements the Capability Protocol. Holds only LLMGateway/PromptRepository - no
    BudgetGuard, no CostTracker, no mutable per-call state."""

    def __init__(self, gateway: LLMGateway, prompt_repository: PromptRepository) -> None:
        self._gateway = gateway
        self._prompt_repository = prompt_repository

    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        started_at = datetime.now(timezone.utc)

        prompt = self._prompt_repository.resolve(CAPABILITY_NAME, PROMPT_VERSION)
        request = _build_request(context, prompt)

        outcome = await call_generate(self._gateway, request, runtime=context.runtime, sequence=0)

        if outcome.error is not None:
            logger.info(
                "capability_call_failed",
                extra={
                    "capability_name": CAPABILITY_NAME,
                    "call_id": str(outcome.call.call_id),
                    "sequence": outcome.call.sequence,
                    "gateway_method": outcome.call.gateway_method,
                    "status": outcome.call.status,
                    "error": outcome.call.error,
                },
            )
            raise outcome.error

        response = outcome.response
        assert response is not None

        violation = _floor_validate(response.structured_output, prompt.output_schema)
        if violation is not None:
            raise ValidationCapabilityError(violation)

        finished_at = datetime.now(timezone.utc)
        return CapabilityResult(
            status="SUCCESS",
            structured_output=response.structured_output,
            calls=[outcome.call],
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=(finished_at - started_at).total_seconds(),
        )
