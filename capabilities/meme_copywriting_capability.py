"""MemeCopywritingCapability - Phase 18 M4: writes the final meme text (top/bottom overlay,
short punchline, Telegram caption, optional editor explanation, alt text) from an already-
generated `MemeConcept` (docs/phase18_m4_meme_copywriting_report.md).

An ordinary Phase 8 `Capability`, identical construction shape to every existing one.
`__init__(gateway, prompt_repository)` only, one `call_generate()` invocation, no retry.

Binding rule (mirrors every sibling capability's own non-coupling rule): `MemeCopywritingCapability`
MUST NOT hold a direct reference to `MemeConceptCapability`, import it, or call it - the concept
is consumed exclusively through `context.business.workflow_state.step_results["meme_concept"]`.

Reuses Phase 17 editorial intelligence as *input*, never recomputes it (brief's own "если Phase 17
уже дала useful editorial intelligence - используй её как input, а не дублируй заново"): when
`step_results["intelligence"]` already carries an `editorial_brief`/`beginner_friendly_plan` (both
are the same "intelligence"/"copywriting"-step shadow hooks `capabilities/executor.py` already
attaches for ANY workflow whose step is literally named "intelligence"/"copywriting" - unrelated
to whether that workflow is CONTENT_GENERATION or MEME_GENERATION), this capability folds a short
summary of it into the prompt context; when absent (the common case today, since those hooks
default to `"off"`), it degrades gracefully exactly like every sibling capability's own
"did not run" handling.
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

CAPABILITY_NAME = "meme_copywriting"
PROMPT_VERSION = "1"

MEME_COPYWRITING_CAPABILITY_DEFINITION = CapabilityDefinition(
    name=CAPABILITY_NAME,
    version=1,
    config=CapabilityConfig(timeout_seconds=30),
    required_context=["news_event"],
    expected_output_keys=[
        "top_text", "bottom_text", "punchline_short", "telegram_caption",
        "editor_explanation", "alt_text",
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
    the full rationale. Duplicated intentionally (every sibling capability's own established
    convention). A declared union type (e.g. `["string", "null"]`, used here for the two
    genuinely-optional fields) is not present as a key in `_SCHEMA_TYPE_TO_PYTHON_TYPE` and is
    therefore skipped for the type check, same as any other unrecognized declared type - presence
    of the required key is still enforced; full type correctness is enforced by Pydantic when
    this same payload is later validated into `schemas.meme_copy.MemeCopy`."""
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
        expected_python_type = _SCHEMA_TYPE_TO_PYTHON_TYPE.get(declared_type) if isinstance(declared_type, str) else None
        if expected_python_type is None:
            continue
        value = structured_output[key]
        if declared_type == "integer" and isinstance(value, bool):
            return f"structured_output['{key}'] must be an integer, got bool."
        if not isinstance(value, expected_python_type):
            return f"structured_output['{key}'] must be of type '{declared_type}', got {type(value).__name__}."

    return None


def _format_concept_context(concept_output: dict[str, Any]) -> str:
    if not concept_output:
        return "(meme_concept did not run, or produced no output - cannot write copy without a concept.)"
    return (
        f"Premise: {concept_output.get('premise')}\n"
        f"Setup: {concept_output.get('setup')}\n"
        f"Punchline: {concept_output.get('punchline')}\n"
        f"Visual scene: {concept_output.get('visual_scene')}\n"
        f"Text overlay intent: {concept_output.get('text_overlay_intent')}\n"
        f"Meme format: {concept_output.get('meme_format')}"
    )


def _format_editorial_intelligence_context(intelligence_output: dict[str, Any]) -> str:
    """Optional, additive - see module docstring. Never required, never re-derives either
    artifact, only summarizes whichever of the two is already present."""
    brief = intelligence_output.get("editorial_brief") if isinstance(intelligence_output, dict) else None
    lines: list[str] = []
    if isinstance(brief, dict):
        why_it_matters = brief.get("why_it_matters")
        if why_it_matters:
            lines.append(f"Editorial brief - why it matters: {why_it_matters}")
    if not lines:
        return "(No additional editorial intelligence available.)"
    return "\n".join(lines)


def _build_request(context: CapabilityContext, prompt: RenderedPrompt) -> GenerateRequest:
    concept_output = context.business.workflow_state.step_results.get("meme_concept", {})
    intelligence_output = context.business.workflow_state.step_results.get("intelligence", {})
    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    context_text = (
        f"Concept:\n{_format_concept_context(concept_output)}\n\n"
        f"Editorial intelligence (optional):\n{_format_editorial_intelligence_context(intelligence_output)}"
    )
    task_text = "Write the final meme text for the concept above, following every rule exactly."

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


class MemeCopywritingCapability:
    """Implements the `Capability` Protocol. Holds only `LLMGateway` and `PromptRepository` - no
    `BudgetGuard`, no `CostTracker`. Never imports or calls `MemeConceptCapability`."""

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
