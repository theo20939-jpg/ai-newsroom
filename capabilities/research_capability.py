"""ResearchCapability - Phase 9 M4: structured fact extraction from one `NewsEvent`'s
existing text, nothing more (docs/phase9_research_intelligence_architecture_contract.md §8).

An ordinary Phase 8 `Capability`, following `capabilities/quality_capability.py`'s shape
exactly: `__init__(gateway, prompt_repository)` only, one `call_generate()` invocation, no
retry (§10 remains optional - not implemented here, matching `QualityCapability`'s own
precedent).

Binding scope clarification (Contract §8): no external research tool exists anywhere in this
architecture. `ResearchCapability` operates solely from the `CapabilityContext` it receives -
`context.business.news_event` only. It never reads `context.business.workflow_state.
step_results`, since Research always runs first in this phase and has nothing upstream to
read. "Research" in this phase means structured fact extraction, precisely - never external
fact-checking, browsing, or verification, which this Capability cannot structurally perform.

TELEGRAPH Checkpoint 3 addendum: reused, unmodified as a class/registration, for article-level
Deep Research too - `capabilities.registry.build_registry()` registers exactly one
`ResearchCapability` instance under the name "research"; `workflows/definitions/
telegraph_research.py`'s own "deep_research" step reuses that same registered name (never a
second Research subsystem). The branch is driven entirely by
`context.business.telegraph_research_bundle_text`: `None` (every NEWS_ANALYSIS/
CONTENT_GENERATION/MEME_GENERATION call, unconditionally) resolves `PROMPT_VERSION` ("2") and
builds the request exactly as before, byte-for-byte; a non-None bundle (only ever set by
`capabilities/executor.py` for a TELEGRAPH_RESEARCH workflow's "deep_research" step) resolves
`PROMPT_VERSION_TELEGRAPH_DEEP_RESEARCH` ("3", prompts/research/v3.yaml - a new, immutable
version; v1/v2 are untouched) and builds the request from the bundle text instead of
`news_event.content`. `news_event` itself is still present in that branch (the Story's anchor
event, required by `EditorialTask.event_id`/`CapabilityExecutor`'s own NewsEvent-centric
contract) but its `content` is deliberately NOT read for the deep-research request - the bundle
is the complete, already-aggregated input.

This module intentionally duplicates `scoring_capability.py`/`quality_capability.py`'s
floor-validation helper rather than factoring out a shared one, per the same rationale those
two modules already record (§19.2 Q1: validation-strategy sharing is deliberately left
unresolved until real evidence exists across several Capabilities).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from capabilities.errors import RetryableCapabilityError, ValidationCapabilityError
from capabilities.gateway_call import call_generate
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, LLMGateway, Message
from integrations.prompts.protocol import PromptRepository, RenderedPrompt
from schemas.capability import CapabilityContext, CapabilityResult
from schemas.capability_definition import CapabilityConfig, CapabilityDefinition

logger = logging.getLogger(__name__)

CAPABILITY_NAME = "research"
PROMPT_VERSION = "2"
# TELEGRAPH Checkpoint 3 - see module docstring's addendum. Selected only when
# context.business.telegraph_research_bundle_text is present.
PROMPT_VERSION_TELEGRAPH_DEEP_RESEARCH = "3"

RESEARCH_CAPABILITY_DEFINITION = CapabilityDefinition(
    name=CAPABILITY_NAME,
    version=1,
    config=CapabilityConfig(timeout_seconds=30),
    required_context=["news_event"],
    expected_output_keys=["facts", "confidence", "gaps"],
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


def _build_request(context: CapabilityContext, prompt: RenderedPrompt) -> GenerateRequest:
    """§8's Input row: title, category, content, language - from `context.business.news_event`
    (plus `context.business.language`) only. Never `workflow_state` - Research is always the
    first step to run in this phase, so there is nothing upstream to read yet."""
    news_event = context.business.news_event
    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    # Phase 19 M1/M2 (services/evidence_package.py): article_evidence_text is only ever non-None
    # when article_acquisition_mode == "enforce" and a usable acquisition exists - byte-identical
    # to the original news_event.content read in every other case (off/shadow, or no evidence).
    content_text = context.business.article_evidence_text or news_event.content or "(none)"
    context_text = (
        f"Title: {news_event.title}\n"
        f"Category: {news_event.category}\n"
        f"Content: {content_text}\n"
        f"Target output language: {context.business.language}"
    )
    task_text = "Extract the structured factual content actually present in the text above."

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


def _build_deep_research_request(context: CapabilityContext, prompt: RenderedPrompt) -> GenerateRequest:
    """TELEGRAPH Checkpoint 3. Built from `context.business.telegraph_research_bundle_text`
    only - never `news_event.content` (see module docstring's addendum)."""
    bundle_text = context.business.telegraph_research_bundle_text
    assert bundle_text is not None  # only called when the caller already checked this
    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    context_text = (
        f"EVIDENCE BUNDLE:\n{bundle_text}\n\nTarget output language: {context.business.language}"
    )
    task_text = (
        "Conduct deep research on the story above, strictly from the evidence bundle given - "
        "produce structured evidence for a future article writer, not article prose."
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


class ResearchCapability:
    """Implements the `Capability` Protocol (`capabilities.registry.Capability`). Holds only
    `LLMGateway` and `PromptRepository` (§4.2 of the frozen Phase 8 contract) - no
    `BudgetGuard`, no `CostTracker`. No per-call mutable state (§3.2)."""

    def __init__(self, gateway: LLMGateway, prompt_repository: PromptRepository) -> None:
        self._gateway = gateway
        self._prompt_repository = prompt_repository

    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        started_at = datetime.now(timezone.utc)

        is_deep_research = context.business.telegraph_research_bundle_text is not None
        if is_deep_research:
            prompt = self._prompt_repository.resolve(CAPABILITY_NAME, PROMPT_VERSION_TELEGRAPH_DEEP_RESEARCH)
            request = _build_deep_research_request(context, prompt)
        else:
            prompt = self._prompt_repository.resolve(CAPABILITY_NAME, PROMPT_VERSION)
            request = _build_request(context, prompt)

        # §6.4/§6.5/§6.7 via the centralized M1 mechanism (§6.8) - never reimplemented here.
        outcome = await call_generate(self._gateway, request, runtime=context.runtime, sequence=0)

        if outcome.error is not None:
            # Preserve the failed CapabilityCall (durable, structured) before the classified
            # CapabilityError crosses this execute() call's boundary (§11.1) - mirrors
            # ScoringCapability/QualityCapability's identical pattern.
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
            # Production forensics: 333/333 failed NEWS_ANALYSIS Research tasks (314 arXiv) all
            # failed this exact floor validation with finish_reason="length" - the gateway
            # response was truncated at the output-token ceiling before the model could finish
            # its structured JSON, a transient capacity failure, not a permanent one. §9.1's
            # floor validation itself is unchanged and still runs unconditionally (never
            # relaxed, never fabricated) - only the error TYPE raised on an already-detected
            # violation changes, and only for this one finish_reason. A violation whose
            # finish_reason is anything else (content_filter included) keeps its existing
            # ValidationCapabilityError (permanent) classification exactly as before; a fully
            # valid structured_output is unaffected regardless of finish_reason, since this
            # branch is only reached after floor validation has already failed.
            # Cost-accounting forensic fix: `outcome.call` reflects a gateway call that actually
            # completed (real provider spend, real usage/model data) - it must travel with the
            # raised error so CapabilityExecutor can still cost it (via the exact same
            # `_record_cost()` seam the success path already uses) even though this Capability
            # itself is about to raise rather than return a CapabilityResult.
            if response.finish_reason == "length":
                raise RetryableCapabilityError(
                    f"research: gateway response truncated at the output-token ceiling before "
                    f"completing structured output (finish_reason='length') - {violation}",
                    calls=[outcome.call],
                )
            raise ValidationCapabilityError(violation, calls=[outcome.call])

        finished_at = datetime.now(timezone.utc)
        return CapabilityResult(
            status="SUCCESS",
            structured_output=response.structured_output,
            calls=[outcome.call],
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=(finished_at - started_at).total_seconds(),
        )
