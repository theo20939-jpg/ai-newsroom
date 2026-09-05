"""MemeConceptCapability - Phase 18 M2, evolved by MEME-PROD-4 into a "Meme Director": invents one
original meme concept (premise/setup/punchline/humor mechanism/visual scene/visual punchline/panel
structure/visual style/text overlay intent), grounded in Research's already-extracted facts
(docs/phase18_m2_meme_concept_report.md).

An ordinary Phase 8 `Capability`, identical construction shape to every existing one
(`CopywritingCapability`/`ResearchCapability`/`IntelligenceCapability`/`QualityCapability`):
`__init__(gateway, prompt_repository)` only.

Binding rule (mirrors Contract §5's own CopywritingCapability rule): `MemeConceptCapability` MUST
NOT hold a direct reference to `ResearchCapability`/`IntelligenceCapability`, import either, or
call either - their output is consumed exclusively through `context.business.workflow_state.
step_results["research"]`. If that key is missing or empty, `execute()` still runs and states the
absence explicitly rather than fabricating facts (mirrors `CopywritingCapability`'s identical
degradation).

This module intentionally duplicates the floor-validation/step-result-formatting helpers other
capability modules already duplicate independently, per this codebase's own established rationale
(§19.2 Q1 of the Phase 9 contract, restated in every sibling capability's own docstring).

MEME-PROD-4: real production canary evidence showed technically clean but "editorial illustration,
not a meme" output - `services/meme_shape_gate.py::assess_meme_shape_risk()` is a cheap,
deterministic pre-filter (never the semantic judge itself - see that module's own docstring) that
decides whether to spend exactly ONE bounded correction retry, mirroring `capabilities/
scoring_capability.py`'s own §10 schema-correction-retry shape exactly: call once (sequence=0) →
if the shape gate flags risk, append a correction message quoting the brief's own bad/good
examples and re-call (sequence=1) → accept the second result UNCONDITIONALLY regardless of the
gate's second-pass verdict, never a third attempt. Schema-floor validation is unchanged and still
hard on both attempts (raises `ValidationCapabilityError`, no retry added for that axis - out of
this phase's scope). Incremental cost: at most one extra text-only concept-generation call, only
when the shape gate actually flags risk; the image-generation call downstream is never duplicated."""
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
from services.meme_shape_gate import assess_meme_shape_risk

logger = logging.getLogger(__name__)

CAPABILITY_NAME = "meme_concept"
# MEME-PROD-4: bumped to "4" (prompts/meme_concept/v4.yaml) - the Meme Director prompt: a new
# required `visual_punchline` field (the specific visual joke, distinct from `visual_scene`),
# `panel_count`/`panel_beats` (real multi-panel format support), `visual_style`, and explicit
# meme-vs-illustration framing with bad/good examples. v1/v2/v3 stay frozen/unmodified per this
# codebase's own prompt-immutability rule (previous bump comment, still accurate for v3 itself:
# visual_scene must depict the comedic exaggeration/incongruity, plus a UI-density note).
PROMPT_VERSION = "4"

MEME_CONCEPT_CAPABILITY_DEFINITION = CapabilityDefinition(
    name=CAPABILITY_NAME,
    version=1,
    config=CapabilityConfig(timeout_seconds=30),
    required_context=["news_event"],
    expected_output_keys=[
        "premise", "setup", "punchline", "humor_mechanism", "visual_scene", "visual_punchline",
        "characters_objects", "panel_count", "panel_beats", "visual_style", "text_overlay_intent",
        "source_fact_links", "forbidden_interpretations", "meme_format",
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


def _build_shape_correction_request(
    original_request: GenerateRequest, response: GenerateResponse, risk_reason: str,
) -> GenerateRequest:
    """MEME-PROD-4: mirrors capabilities/scoring_capability.py::_build_correction_request() shape
    exactly - append a new, separate correction Message (never replacing the message list) and pin
    `preferred_model` to the same resolved model (no re-routing). Quotes the prompt's own bad/good
    examples so the model has concrete guidance for what "distinct visual joke" actually means,
    rather than a bare "try again" instruction."""
    correction_message = Message(
        role="user",
        content=[
            ContentPart(
                type="text",
                text=(
                    f"Your previous concept's visual_punchline failed a quality check: {risk_reason}. "
                    "visual_punchline must be a specific visual joke, reaction, contrast, or "
                    "absurdity that is genuinely DIFFERENT from visual_scene's plain description "
                    "and from the news premise - never a restatement of either. For example, if "
                    "the news is a chip price increase, a weak visual_punchline just re-describes "
                    "the price increase visually (e.g. chips passing through an expensive toll "
                    "booth) - a strong one shows a human cost or reaction instead (e.g. a gamer "
                    "handing over a wallet, then a watch, then reaching for a kidney-transplant "
                    "folder just to buy one processor). Rewrite the concept - especially "
                    "visual_punchline, and visual_scene/panel_beats if needed to support it - so "
                    "the visual joke is clear and distinct, and respond again matching the schema "
                    "exactly."
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


class MemeConceptCapability:
    """Implements the `Capability` Protocol (`capabilities.registry.Capability`). Holds only
    `LLMGateway` and `PromptRepository` (§4.2 of the frozen Phase 8 contract) - no `BudgetGuard`,
    no `CostTracker`. No per-call mutable state (§3.2). Never imports or calls
    `ResearchCapability`/`IntelligenceCapability`."""

    def __init__(self, gateway: LLMGateway, prompt_repository: PromptRepository) -> None:
        self._gateway = gateway
        self._prompt_repository = prompt_repository

    def _log_failed_call(self, outcome: GatewayCallOutcome) -> None:
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

        outcome = await call_generate(self._gateway, request, runtime=context.runtime, sequence=0)

        if outcome.error is not None:
            self._log_failed_call(outcome)
            raise outcome.error

        response = outcome.response
        assert response is not None  # GatewayCallOutcome guarantees exactly one of response/error is set

        violation = _floor_validate(response.structured_output, prompt.output_schema)
        if violation is not None:
            raise ValidationCapabilityError(violation)

        structured_output = response.structured_output
        assert structured_output is not None  # floor_validate already confirmed this

        # MEME-PROD-4: cheap deterministic pre-filter, not the semantic judge itself - see
        # services/meme_shape_gate.py's own docstring. Missing string fields default to "" rather
        # than raising here - a genuinely missing required field was already caught by
        # _floor_validate() above; this check is purely an additional quality signal on top of an
        # already-schema-valid response.
        shape_risk = assess_meme_shape_risk(
            visual_scene=str(structured_output.get("visual_scene", "")),
            visual_punchline=str(structured_output.get("visual_punchline", "")),
            premise=str(structured_output.get("premise", "")),
        )

        if shape_risk.risk_reason is None:
            finished_at = datetime.now(timezone.utc)
            return CapabilityResult(
                status="SUCCESS",
                structured_output=structured_output,
                calls=[outcome.call],
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=(finished_at - started_at).total_seconds(),
            )

        # MEME-PROD-4: exactly one bounded correction retry, mirroring scoring_capability.py's
        # own §10 shape - a provider failure on the retry still raises (never silently swallowed);
        # a schema-floor failure on the retry still raises (structural validity stays hard); but a
        # SECOND shape-risk verdict is accepted unconditionally - shape is a soft quality signal,
        # never grounds for a third attempt or a hard failure.
        correction_request = _build_shape_correction_request(request, response, shape_risk.risk_reason)
        retry_outcome = await call_generate(self._gateway, correction_request, runtime=context.runtime, sequence=1)

        if retry_outcome.error is not None:
            self._log_failed_call(retry_outcome)
            raise retry_outcome.error

        retry_response = retry_outcome.response
        assert retry_response is not None

        retry_violation = _floor_validate(retry_response.structured_output, prompt.output_schema)
        if retry_violation is not None:
            raise ValidationCapabilityError(
                f"structured_output failed schema validation on the MEME-PROD-4 shape-correction "
                f"retry: {retry_violation}"
            )

        finished_at = datetime.now(timezone.utc)
        return CapabilityResult(
            status="SUCCESS",
            structured_output=retry_response.structured_output,
            calls=[outcome.call, retry_outcome.call],
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=(finished_at - started_at).total_seconds(),
            metadata={
                "retry_reason": "meme_shape_risk",
                "retried_call_id": str(outcome.call.call_id),
                "shape_risk_reason": shape_risk.risk_reason,
            },
        )
