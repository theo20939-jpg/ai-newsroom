"""MemeConceptCapability - Phase 18 M2: invents one original meme concept (premise/setup/
punchline/humor mechanism/visual scene/text overlay intent), grounded in Research's already-
extracted facts (docs/phase18_m2_meme_concept_report.md).

An ordinary Phase 8 `Capability`, identical construction shape to every existing one
(`CopywritingCapability`/`ResearchCapability`/`IntelligenceCapability`/`QualityCapability`):
`__init__(gateway, prompt_repository)` only, one `call_generate()` invocation, no retry.

Binding rule (mirrors Contract §5's own CopywritingCapability rule): `MemeConceptCapability` MUST
NOT hold a direct reference to `ResearchCapability`/`IntelligenceCapability`, import either, or
call either - their output is consumed exclusively through `context.business.workflow_state.
step_results["research"]`. If that key is missing or empty, `execute()` still runs and states the
absence explicitly rather than fabricating facts (mirrors `CopywritingCapability`'s identical
degradation).

This module intentionally duplicates the floor-validation/step-result-formatting helpers other
capability modules already duplicate independently, per this codebase's own established rationale
(§19.2 Q1 of the Phase 9 contract, restated in every sibling capability's own docstring).
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

CAPABILITY_NAME = "meme_concept"
# MEME PRODUCTION PIPELINE: bumped to "2" (prompts/meme_concept/v2.yaml) - broader creative-tone
# rules, free-text meme_format (format diversity), and consumption of the new optional
# `context.business.meme_recent_diversity_context` field (see _build_request() below). v1 stays
# frozen/unmodified per this codebase's own prompt-immutability rule.
PROMPT_VERSION = "2"

MEME_CONCEPT_CAPABILITY_DEFINITION = CapabilityDefinition(
    name=CAPABILITY_NAME,
    version=1,
    config=CapabilityConfig(timeout_seconds=30),
    required_context=["news_event"],
    expected_output_keys=[
        "premise", "setup", "punchline", "humor_mechanism", "visual_scene",
        "characters_objects", "text_overlay_intent", "source_fact_links",
        "forbidden_interpretations", "meme_format",
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
    the full rationale. Duplicated intentionally (module docstring)."""
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


def _format_research_context(research_output: dict[str, Any]) -> str:
    if not research_output:
        return "(Research did not run, or produced no output - proceed on title/category alone.)"
    facts = research_output.get("facts", [])
    confidence = research_output.get("confidence")
    gaps = research_output.get("gaps", [])
    return f"Facts: {facts}\nConfidence: {confidence}\nGaps: {gaps}"


def _build_request(context: CapabilityContext, prompt: RenderedPrompt) -> GenerateRequest:
    """Only title/category from `context.business.news_event` (never `content`, mirroring every
    sibling capability's own "MUST NOT re-extract" discipline) plus `step_results["research"]` -
    never a direct import or call of ResearchCapability."""
    news_event = context.business.news_event
    research_output = context.business.workflow_state.step_results.get("research", {})
    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    context_text = (
        f"Title: {news_event.title}\n"
        f"Category: {news_event.category}\n\n"
        f"Research output:\n{_format_research_context(research_output)}"
    )
    # MEME PRODUCTION PIPELINE: additive, optional - populated by capabilities/executor.py from
    # services/meme_diversity.py's bounded recent-history lookback. Absent (None) for the first
    # meme of a fresh deployment, or whenever that lookback finds zero prior candidates - the
    # request is otherwise byte-identical to the no-diversity-context shape.
    if context.business.meme_recent_diversity_context:
        context_text += f"\n\nRECENTLY USED FORMATS/MECHANISMS:\n{context.business.meme_recent_diversity_context}"
    task_text = (
        "Invent one original meme concept for the event above, based only on the given "
        "title/category and Research's own output."
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


class MemeConceptCapability:
    """Implements the `Capability` Protocol (`capabilities.registry.Capability`). Holds only
    `LLMGateway` and `PromptRepository` (§4.2 of the frozen Phase 8 contract) - no `BudgetGuard`,
    no `CostTracker`. No per-call mutable state (§3.2). Never imports or calls
    `ResearchCapability`/`IntelligenceCapability`."""

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
