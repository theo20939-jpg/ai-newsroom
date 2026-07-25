"""EngagementCapability - Phase 13: predicted editorial/audience engagement potential from
Research's and Intelligence's already-extracted findings (docs/
phase13_automatic_news_analysis_architecture_contract.md §6/§7).

PREDICTED potential, never observed engagement - this Capability's prompt still does not read
any real Telegram metric. engagement_potential_score remains a pure LLM-produced estimate.

Phase 15 M3 update: real Telegram engagement metrics (views, forwards, replies, and an
aggregate reaction total) ARE now persisted onto NewsEvent (database/models/news_event.py,
docs/phase15_m3_engagement_signal_preservation_report.md) - the "none is persisted anywhere"
statement from Phase 13 no longer holds. M3 deliberately did NOT wire these fields into this
Capability's prompt context (test_engagement_capability.py::
test_engagement_capability_does_not_yet_read_real_engagement_metrics enforces this structurally)
- doing so would change engagement_potential_score's output distribution, which is explicitly
out of M3's data-preservation-only scope. Consuming the persisted metrics here is deferred to a
future milestone (M4 Editorial Scoring V2).

Ordinary Phase 8 Capability, identical construction shape to IntelligenceCapability:
__init__(gateway, prompt_repository) only, one call_generate() invocation, no retry.
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

CAPABILITY_NAME = "engagement"
PROMPT_VERSION = "1"

ENGAGEMENT_CAPABILITY_DEFINITION = CapabilityDefinition(
    name=CAPABILITY_NAME,
    version=1,
    config=CapabilityConfig(timeout_seconds=30),
    required_context=["news_event"],
    expected_output_keys=["engagement_potential_score", "audience_fit", "reasoning"],
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
    """Contract §9.1's floor (duplicated intentionally, matching every sibling capability's own
    established non-shared-helper convention - see intelligence_capability.py's identical docstring)."""
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


def _format_prior_step(label: str, output: dict[str, Any]) -> str:
    if not output:
        return f"({label} did not run, or produced no output - proceed without it.)"
    return str(output)


def _build_request(context: CapabilityContext, prompt: RenderedPrompt) -> GenerateRequest:
    news_event = context.business.news_event
    research_output = context.business.workflow_state.step_results.get("research", {})
    intelligence_output = context.business.workflow_state.step_results.get("intelligence", {})
    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    context_text = (
        f"Title: {news_event.title}\n"
        f"Category: {news_event.category}\n"
        f"Target output language: {context.business.language}\n\n"
        f"Research output:\n{_format_prior_step('Research', research_output)}\n\n"
        f"Intelligence output:\n{_format_prior_step('Intelligence', intelligence_output)}"
    )
    task_text = (
        "Estimate the predicted editorial/audience engagement potential for the event above, "
        "based only on the given title/category and Research's/Intelligence's prior findings. "
        "This is a prediction, not a measurement - no real engagement data is available."
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
        temperature=context.execution.temperature,
        response_mode="json_schema",
        response_schema=prompt.output_schema,
    )


class EngagementCapability:
    """Implements the Capability Protocol. Holds only LLMGateway/PromptRepository - no
    BudgetGuard, no CostTracker (Amendment C, unchanged). Never claims access to real,
    observed engagement metrics - none reach this class (Contract §6)."""

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
