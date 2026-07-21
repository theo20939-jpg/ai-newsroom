"""ScoringCapability - Phase 8 M3's Golden Path: the smallest possible real `Capability`
slice, proving `CapabilityContext` -> `GenerateRequest` -> `GenerateResponse` ->
`CapabilityResult` end to end, on top of the real M1 mechanism (`capabilities.gateway_call`)
and the real M2 `PromptRepository` (`FilePromptRepository`).

Assigns a newsworthiness score to one `NewsEventSnapshot`. Which specific product capability
this milestone builds is a product-scoping choice, not an architectural one (see
docs/phase8_capability_planning.md's M3 section); "scoring" was chosen from the existing
`capabilities/capability_mapping.py` roster as the smallest well-defined task with no tool
dependency.

Text-only. The same `Message`/`ContentPart`/`CapabilityResult` shape already accommodates the
multimodal abstractions contract §6.9 confirms are sufficient - a future multimodal
`Capability` follows this exact template, not a different one.

Registered in `build_registry()` since M4. Phase 8 M5 adds the §10 structured-output
correction retry: on a first schema-validation mismatch, retry exactly once by appending a
correction `Message` and pinning `preferred_model` to the first attempt's resolved model
(§10.2's "no re-routing" obligation - `preferred_model` remains an advisory-only hint per
§6.2, so this is the only channel available to express it). A second consecutive mismatch
raises `ValidationCapabilityError` (§10.4) - no third attempt is ever made.

`CapabilityCall` schema note (contract §10.3 verification finding): the frozen `CapabilityCall`
model (schemas/capability.py, Phase 6, extra="forbid") has no `metadata` field, so
`retry_reason`/`retried_call_id` are recorded in `CapabilityResult.metadata` instead (which
does have one) - confirmed as the correct reading, not a Phase 6/7 schema change, since M5's
own scope forbids touching any Phase 6/7 file.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from capabilities.errors import ValidationCapabilityError
from capabilities.gateway_call import GatewayCallOutcome, call_generate
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, GenerateResponse, LLMGateway, Message
from integrations.prompts.protocol import PromptRepository, RenderedPrompt
from schemas.capability import CapabilityContext, CapabilityResult
from schemas.capability_definition import CapabilityConfig, CapabilityDefinition

logger = logging.getLogger(__name__)

CAPABILITY_NAME = "scoring"
PROMPT_VERSION = "2"

SCORING_CAPABILITY_DEFINITION = CapabilityDefinition(
    name=CAPABILITY_NAME,
    version=1,
    config=CapabilityConfig(timeout_seconds=30),
    required_context=["news_event"],
    expected_output_keys=["score", "rationale"],
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
    """Contract §9.1's floor: at minimum, the JSON Schema *shape* declared by the resolved
    prompt's output_schema. Deliberately not a general JSON Schema engine (no $ref/anyOf/
    format/pattern support, no new dependency) - §19.2 Q3 explicitly leaves validation
    strategy beyond this floor to each Capability author, to be revisited once patterns
    emerge across several real Capabilities (not yet - only one exists).

    Returns None if `structured_output` satisfies the floor, otherwise a human-readable
    violation description - never raises directly, so the same check can drive both the
    first attempt (a mismatch triggers §10's retry) and the retry (a mismatch raises
    ValidationCapabilityError, §10.4)."""
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


def _build_correction_request(
    original_request: GenerateRequest, response: GenerateResponse, violation: str
) -> GenerateRequest:
    """§10.2/§10.3: append a new, separate correction Message to the existing message list
    (never replacing it) and pin `preferred_model` to the same resolved model - the only
    channel available to express "no re-routing" (§6.2: preferred_model is advisory-only).
    Never touches `RenderedPrompt` content (system/rules/output_schema) - only this
    already-built GenerateRequest's own messages/preferred_model."""
    correction_message = Message(
        role="user",
        content=[
            ContentPart(
                type="text",
                text=(
                    f"Your previous response violated the required output schema: {violation}. "
                    "Correct it and respond again, matching the schema exactly."
                ),
            )
        ],
    )
    return original_request.model_copy(
        update={
            "messages": [*original_request.messages, correction_message],
            "preferred_model": response.model_used,
        }
    )


def _build_request(context: CapabilityContext, prompt: RenderedPrompt) -> GenerateRequest:
    """§7.2/§7.3: CONTEXT/TASK come from CapabilityContext only, never from PromptRepository;
    CapabilityContext itself is never passed to PromptRepository."""
    news_event = context.business.news_event
    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    context_text = (
        f"Title: {news_event.title}\n"
        f"Category: {news_event.category}\n"
        f"Summary: {news_event.summary or '(none)'}\n"
        f"Language: {context.business.language}"
    )
    task_text = "Assign a newsworthiness score and a short rationale for the event above."

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


class ScoringCapability:
    """Implements the `Capability` Protocol (`capabilities.registry.Capability`). Holds only
    `LLMGateway` and `PromptRepository` (§4.2) - no `BudgetGuard`, no `CostTracker`
    (§4.3/§4.4). No per-call mutable state (§3.2): every fact one `execute()` call needs comes
    from its own `CapabilityContext` argument or these two constant, injected dependencies."""

    def __init__(self, gateway: LLMGateway, prompt_repository: PromptRepository) -> None:
        self._gateway = gateway
        self._prompt_repository = prompt_repository

    def _log_failed_call(self, outcome: GatewayCallOutcome) -> None:
        # Preserve the failed CapabilityCall (durable, structured) before the classified
        # CapabilityError crosses this execute() call's boundary (§11.1) - there is no
        # CapabilityResult to attach it to on this path, since raising IS the failure
        # signal (§11.1), not a returned status="FAILED" result.
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

    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        started_at = datetime.now(timezone.utc)

        prompt = self._prompt_repository.resolve(CAPABILITY_NAME, PROMPT_VERSION)
        request = _build_request(context, prompt)

        # §6.4/§6.5/§6.7 via the centralized M1 mechanism (§6.8) - never reimplemented here.
        outcome = await call_generate(self._gateway, request, runtime=context.runtime, sequence=0)

        if outcome.error is not None:
            self._log_failed_call(outcome)
            raise outcome.error

        response = outcome.response
        assert response is not None  # GatewayCallOutcome guarantees exactly one of response/error is set

        violation = _floor_validate(response.structured_output, prompt.output_schema)
        if violation is None:
            finished_at = datetime.now(timezone.utc)
            return CapabilityResult(
                status="SUCCESS",
                structured_output=response.structured_output,
                calls=[outcome.call],
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=(finished_at - started_at).total_seconds(),
            )

        # §10.2: first mismatch - retry exactly once, appending a correction Message,
        # never mutating the original RenderedPrompt, never re-routing to a different model.
        correction_request = _build_correction_request(request, response, violation)
        retry_outcome = await call_generate(self._gateway, correction_request, runtime=context.runtime, sequence=1)

        if retry_outcome.error is not None:
            self._log_failed_call(retry_outcome)
            raise retry_outcome.error

        retry_response = retry_outcome.response
        assert retry_response is not None

        retry_violation = _floor_validate(retry_response.structured_output, prompt.output_schema)
        if retry_violation is not None:
            # §10.4: a second consecutive mismatch raises ValidationCapabilityError - no
            # third attempt is ever made.
            raise ValidationCapabilityError(
                f"structured_output failed validation on both the original attempt and the "
                f"§10.2 correction retry: {retry_violation}"
            )

        finished_at = datetime.now(timezone.utc)
        return CapabilityResult(
            status="SUCCESS",
            structured_output=retry_response.structured_output,
            calls=[outcome.call, retry_outcome.call],
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=(finished_at - started_at).total_seconds(),
            # §10.3's shape, recorded on CapabilityResult.metadata rather than
            # CapabilityCall.metadata - see this module's docstring for why.
            metadata={
                "retry_reason": "schema_validation_failure",
                "retried_call_id": str(outcome.call.call_id),
            },
        )
