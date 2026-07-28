"""IntelligenceCapability - Phase 9 M5: editorial-significance judgment from Research's
already-extracted facts (docs/phase9_research_intelligence_architecture_contract.md §9).

An ordinary Phase 8 `Capability`, identical construction shape to `ResearchCapability`/
`QualityCapability`: `__init__(gateway, prompt_repository)` only, one `call_generate()`
invocation, no retry (§10 remains optional - not implemented here, same reasoning as M4).

Binding rule (§9.1): `IntelligenceCapability` MUST NOT hold a direct reference to
`ResearchCapability`, import it, or call it - this file contains no such import anywhere.
Research's output is consumed exclusively through the existing, already-frozen Phase 6
mechanism: `context.business.workflow_state.step_results["research"]`. If that key is missing
or empty (Research did not run, or this is a malformed synthetic test), `execute()` still
runs - it does not raise merely for this reason; the built prompt states the absence
explicitly rather than fabricating facts.

This module intentionally duplicates `research_capability.py`/`scoring_capability.py`/
`quality_capability.py`'s floor-validation helper rather than factoring out a shared one, per
the same rationale those modules already record (§19.2 Q1).
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

CAPABILITY_NAME = "intelligence"
PROMPT_VERSION = "2"

INTELLIGENCE_CAPABILITY_DEFINITION = CapabilityDefinition(
    name=CAPABILITY_NAME,
    version=1,
    config=CapabilityConfig(timeout_seconds=30),
    required_context=["news_event"],
    expected_output_keys=["significance", "angle", "audience_relevance", "recommendation"],
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
    """Contract §9.1's floor - see scoring_capability._floor_validate's identical docstring
    for the full rationale. Duplicated intentionally (module docstring)."""
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
        expected_python_type = _SCHEMA_TYPE_TO_PYTHON_TYPE.get(declared_type)
        if expected_python_type is None:
            continue
        value = structured_output[key]
        if declared_type == "integer" and isinstance(value, bool):
            return f"structured_output['{key}'] must be an integer, got bool."
        if not isinstance(value, expected_python_type):
            return f"structured_output['{key}'] must be of type '{declared_type}', got {type(value).__name__}."

    return None


def _format_research_facts(research_output: dict[str, Any]) -> str:
    if not research_output:
        return "(Research did not run, or produced no output - proceed on title/category alone.)"
    facts = research_output.get("facts", [])
    confidence = research_output.get("confidence")
    gaps = research_output.get("gaps", [])
    return f"Facts: {facts}\nConfidence: {confidence}\nGaps: {gaps}"


def _build_request(context: CapabilityContext, prompt: RenderedPrompt) -> GenerateRequest:
    """§9's Input row: `CapabilityContext` for the same `NewsEvent` (title/category only, for
    identifying context - never `content`, since Intelligence MUST NOT re-extract facts),
    plus `context.business.workflow_state.step_results["research"]` (§9.1's exact,
    already-frozen field path - never a direct import or call of `ResearchCapability`)."""
    news_event = context.business.news_event
    research_output = context.business.workflow_state.step_results.get("research", {})
    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    context_text = (
        f"Title: {news_event.title}\n"
        f"Category: {news_event.category}\n"
        f"Target output language: {context.business.language}\n\n"
        f"Research output:\n{_format_research_facts(research_output)}"
    )
    task_text = (
        "Assess the editorial significance, angle, audience relevance, and recommendation for "
        "the event above, based only on the given title/category and Research's facts."
    )

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


class IntelligenceCapability:
    """Implements the `Capability` Protocol (`capabilities.registry.Capability`). Holds only
    `LLMGateway` and `PromptRepository` (§4.2 of the frozen Phase 8 contract) - no
    `BudgetGuard`, no `CostTracker`. No per-call mutable state (§3.2). Never imports or calls
    `ResearchCapability` (§9.1)."""

    def __init__(self, gateway: LLMGateway, prompt_repository: PromptRepository) -> None:
        self._gateway = gateway
        self._prompt_repository = prompt_repository

    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        started_at = datetime.now(timezone.utc)

        prompt = self._prompt_repository.resolve(CAPABILITY_NAME, PROMPT_VERSION)
        request = _build_request(context, prompt)

        # §6.4/§6.5/§6.7 via the centralized M1 mechanism (§6.8) - never reimplemented here.
        outcome = await call_generate(self._gateway, request, runtime=context.runtime, sequence=0)

        if outcome.error is not None:
            # Preserve the failed CapabilityCall (durable, structured) before the classified
            # CapabilityError crosses this execute() call's boundary (§11.1) - mirrors
            # ResearchCapability/ScoringCapability/QualityCapability's identical pattern.
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
        assert response is not None  # GatewayCallOutcome guarantees exactly one of response/error is set

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
