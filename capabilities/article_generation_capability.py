"""ArticleGenerationCapability - TELEGRAPH Checkpoint 5: long-form article drafting from an
already-completed Deep Research bundle, for exactly one Story's "generate_article" step of a
TELEGRAPH_ARTICLE workflow.

A genuinely NEW Capability class - deliberately never `CopywritingCapability` reused/branched
(unlike Checkpoint 3's own reuse of `ResearchCapability`). `capabilities/executor.py` has several
existing hooks keyed strictly off `step.capability == "copywriting"` (adaptive-length shadow
plan, beginner-friendly shadow plan, Image Intelligence attach) - all real, all NEWS/CONTENT_
GENERATION-only behavior that must never fire for a TELEGRAPH article. Registering this step
under its own name ("article_generation", mapped to `AICapability.COPYWRITING` in capabilities/
capability_mapping.py - the semantically closest existing value, reused rather than adding a new
enum member/migration, mirroring `editorial_planning -> INTELLIGENCE`/`media_vision_review ->
QUALITY`'s own precedent) makes that separation structural, not just a docstring promise.

Ordinary `Capability` Protocol implementation otherwise - one `call_generate()` invocation, no
retry of its own (WorkflowStepDefinition.max_attempts governs retries, exactly like every other
Capability), the same §9.1 floor-validation discipline `ResearchCapability`/`ScoringCapability`/
`QualityCapability` already established (duplicated per this codebase's own convention, not
factored into a shared helper - see research_capability.py's own docstring for why).

Binding scope: this Capability NEVER re-runs Research. It reads
`context.business.telegraph_deep_research_output` (the prior TELEGRAPH_RESEARCH task's own
already-completed "deep_research" step result, threaded in by capabilities/executor.py) and
`context.business.telegraph_visual_bundle_summary` (informational only - Visual Research image
selections, never embedded/described as article content) - never `context.business.news_event.
content`, never any other prior step_results.

Editorial channel split (prompts/article_generation/v2.yaml): `context.business.
telegraph_editorial_channel` ("ninja_ai"/"ninja_pulse", classified once at shortlist-creation
time by services/editorial_channel_classifier.py) is threaded into the request text - still ONE
capability, ONE prompt name, ONE output schema (byte-identical between channels) - only the
model's TONE changes, per v2's own system text. `PROMPT_VERSION = "2"` is now the active version
for every TELEGRAPH article generation call; v1 (prompts/article_generation/v1.yaml) is left in
place, unmodified, per this codebase's own prompt-immutability rule - it is simply no longer
resolved by this class.
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

CAPABILITY_NAME = "article_generation"
PROMPT_VERSION = "2"

ARTICLE_GENERATION_CAPABILITY_DEFINITION = CapabilityDefinition(
    name=CAPABILITY_NAME,
    version=1,
    config=CapabilityConfig(timeout_seconds=90),
    required_context=["telegraph_deep_research_output"],
    expected_output_keys=[
        "headline", "lead", "context", "timeline", "confirmed_facts", "analysis", "implications",
        "background", "risks", "conclusion", "sources",
    ],
)

_SCHEMA_TYPE_TO_PYTHON_TYPE: dict[str, type | tuple[type, ...]] = {
    "string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict,
}


def _floor_validate(structured_output: dict[str, Any] | None, output_schema: dict[str, Any]) -> str | None:
    """Byte-for-byte the same §9.1 floor `capabilities/research_capability.py::_floor_validate()`
    implements - duplicated per this codebase's own established per-Capability convention."""
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


def _render_research_bundle(research_output: dict[str, Any]) -> str:
    """Deterministic plain-text rendering of the prior TELEGRAPH_RESEARCH task's own structured
    output (prompts/research/v3.yaml's schema) - never re-summarized/re-interpreted, just laid
    out for the model to read. Missing keys degrade to an empty list/string, never an exception -
    a malformed upstream result is still something this function can render honestly."""

    def _lines(key: str, label: str) -> list[str]:
        values = research_output.get(key) or []
        if not isinstance(values, list):
            return []
        return [f"{label}:"] + [f"- {v}" for v in values] + [""]

    parts: list[str] = [f"Thesis: {research_output.get('thesis', '(none)')}", ""]
    parts += _lines("confirmed_facts", "Confirmed facts")
    parts += _lines("timeline", "Timeline")
    parts += _lines("source_evidence", "Source evidence")
    parts += _lines("primary_sources", "Primary sources")
    parts += _lines("context_background", "Background")
    parts += _lines("implications", "Implications")
    parts += _lines("competing_views", "Competing views")
    parts += _lines("gaps", "Known gaps")
    parts += _lines("risky_claims", "Claims needing cautious attribution")
    return "\n".join(parts)


def _build_request(context: CapabilityContext, prompt: RenderedPrompt) -> GenerateRequest:
    research_output = context.business.telegraph_deep_research_output
    assert research_output is not None  # required_context - capabilities/executor.py always sets this
    bundle_text = _render_research_bundle(research_output)
    visual_summary = context.business.telegraph_visual_bundle_summary or "(no visual research available)"
    # Deliberately no fallback default here - a missing channel is a genuine upstream
    # configuration gap (every TELEGRAPH_ARTICLE task's proposal always has one, set at shortlist-
    # creation time), never silently guessed. capabilities/executor.py's own TELEGRAPH_ARTICLE
    # branch is the sole place this is populated.
    editorial_channel = context.business.telegraph_editorial_channel or "(unspecified)"

    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    context_text = (
        f"Editorial channel: {editorial_channel}\n\n"
        f"RESEARCH BUNDLE:\n{bundle_text}\n\n"
        f"VISUAL RESEARCH (informational only - do not describe or embed these images in the "
        f"article text):\n{visual_summary}\n\n"
        f"Target output language: {context.business.language}"
    )
    task_text = "Write the complete long-form article, strictly from the research bundle above."

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


class ArticleGenerationCapability:
    """Implements the `Capability` Protocol. Holds only `LLMGateway` and `PromptRepository` -
    no `BudgetGuard`, no `CostTracker` (mirrors every other Capability's own §4.2 constraint)."""

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
                    "capability_name": CAPABILITY_NAME, "call_id": str(outcome.call.call_id),
                    "sequence": outcome.call.sequence, "gateway_method": outcome.call.gateway_method,
                    "status": outcome.call.status, "error": outcome.call.error,
                },
            )
            raise outcome.error

        response = outcome.response
        assert response is not None

        violation = _floor_validate(response.structured_output, prompt.output_schema)
        if violation is not None:
            if response.finish_reason == "length":
                raise RetryableCapabilityError(
                    f"article_generation: gateway response truncated at the output-token ceiling "
                    f"before completing structured output (finish_reason='length') - {violation}",
                    calls=[outcome.call],
                )
            raise ValidationCapabilityError(violation, calls=[outcome.call])

        finished_at = datetime.now(timezone.utc)
        return CapabilityResult(
            status="SUCCESS", structured_output=response.structured_output, calls=[outcome.call],
            started_at=started_at, finished_at=finished_at,
            duration_seconds=(finished_at - started_at).total_seconds(),
        )
