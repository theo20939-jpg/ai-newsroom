"""QualityCapability - Phase 8 M7's second `Capability`, proving contract §14's zero-change
extension guarantee for real: a second, genuinely different `Capability` (different prompt,
different output shape - `{"passed": bool, "issues": list}` vs. `ScoringCapability`'s
`{"score": int, "rationale": str}`), built using only the M6 testing convention, with zero
modification to `ScoringCapability`, `workflows/`, `LLMGateway`, or `PromptRepository`'s own
contract.

Identical shape to M3/M4 (single Gateway call, no retry) - M5's correction-retry extension is
deliberately not pulled in here, to keep this milestone's proof focused on the extension model
itself, not a re-demonstration of M5.

This module intentionally duplicates `scoring_capability.py`'s floor-validation helper rather
than factoring out a shared one - per §19.2 Q1, validation-strategy sharing is deliberately
left unresolved until real evidence exists across several Capabilities; this milestone is
that evidence, not the milestone that acts on it.

Phase 10 M2 amendment (docs/phase10_production_content_pipeline_architecture_contract.md §5.1):
`_build_request()` additionally reads `step_results["copywriting"]` and formats it into
`context_text`, mirroring `IntelligenceCapability._build_request()`'s own
`step_results["research"]` formatting exactly, including its "did not run" degradation when the
key is absent/empty. `PROMPT_VERSION` moves to `"2"`, resolving `prompts/quality/v2.yaml`;
`prompts/quality/v1.yaml` is left in place, unmodified, per Phase 6 §8's prompt-immutability
rule. Nothing else in this file changes: `__init__`, `execute()`'s control flow,
`QUALITY_CAPABILITY_DEFINITION.expected_output_keys`, and `_floor_validate()` are byte-for-byte
unchanged from M7.
"""
from __future__ import annotations

import logging
import json
from datetime import datetime, timezone
from typing import Any

from capabilities.errors import ValidationCapabilityError
from capabilities.gateway_call import call_generate
from core.config import settings
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, LLMGateway, Message
from integrations.prompts.protocol import PromptRepository, RenderedPrompt
from schemas.capability import CapabilityContext, CapabilityResult
from schemas.capability_definition import CapabilityConfig, CapabilityDefinition
from services.kage_content_lineage_audit import kage_content_generation_input_metadata

logger = logging.getLogger(__name__)

CAPABILITY_NAME = "quality"
PROMPT_VERSION = "3"
PROMPT_VERSION_KAGE = "9.2"

QUALITY_CAPABILITY_DEFINITION = CapabilityDefinition(
    name=CAPABILITY_NAME,
    version=1,
    config=CapabilityConfig(timeout_seconds=30),
    required_context=["news_event"],
    expected_output_keys=["passed", "issues"],
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


def _format_copywriting_draft(copywriting_output: dict[str, Any]) -> str:
    if not copywriting_output:
        return "(Copywriting did not run, or produced no output - assess the raw event alone.)"
    title = copywriting_output.get("title")
    # v10+ keeps the immutable newer schema (`main_body` + nullable `ending`) while older
    # production versions still emit `body`. Quality must review the complete draft from either
    # lineage rather than silently seeing `Body: None` for every KAGE experiment.
    body = copywriting_output.get("body")
    if body is None:
        body = copywriting_output.get("main_body")
    ending = copywriting_output.get("ending")
    if isinstance(ending, str) and ending.strip():
        body = f"{body or ''}\n\n{ending}".strip()
    # Phase 18.10 M4: hashtags dropped from the Quality review context - no longer generated or
    # persisted downstream, so there is nothing useful for Quality to review here anymore.
    return f"Title: {title}\nBody: {body}"


def _build_request(context: CapabilityContext, prompt: RenderedPrompt) -> GenerateRequest:
    """§7.2/§7.3: CONTEXT/TASK come from CapabilityContext only, never from PromptRepository;
    CapabilityContext itself is never passed to PromptRepository. Phase 10 §5.1: additionally
    reads `step_results["copywriting"]` (never a direct import/call of
    `CopywritingCapability`), mirroring `IntelligenceCapability._build_request()`'s own
    `step_results["research"]` formatting exactly."""
    news_event = context.business.news_event
    copywriting_output = context.business.workflow_state.step_results.get("copywriting", {})
    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    context_text = (
        f"Title: {news_event.title}\n"
        f"Category: {news_event.category}\n"
        f"Summary: {news_event.summary or '(none)'}\n"
        f"Target output language: {context.business.language}\n\n"
        f"Copywriting draft:\n{_format_copywriting_draft(copywriting_output)}"
    )
    if prompt.version == PROMPT_VERSION_KAGE:
        research_output = context.business.workflow_state.step_results.get("research", {})
        facts = research_output.get("facts", []) if isinstance(research_output, dict) else []
        source_excerpt = context.business.article_evidence_text or news_event.content or ""
        context_text += (
            f"\n\nResearch facts (only these plus the source text establish claims):\n{facts}"
            f"\n\nSource excerpt:\n{source_excerpt[:6000]}"
        )
        from services.kage_evidence_first import editorial_take_contract, minimum_story_contract

        intelligence_output = context.business.workflow_state.step_results.get("intelligence") or {}
        contract = minimum_story_contract(
            research_output, intelligence_output, source_headline=news_event.title,
        )
        context_text += (
            "\n\nMINIMUM STORY CONTRACT (judge core meaning, not article completeness):\n"
            + json.dumps(contract, ensure_ascii=False)
        )
        take = editorial_take_contract(
            research_output, intelligence_output, source_headline=news_event.title,
        )
        context_text += (
            "\n\nEDITORIAL TAKE CONTRACT (diagnose voice separately from publication safety):\n"
            + json.dumps(take, ensure_ascii=False)
        )
    task_text = (
        "Assess whether the generated draft above (if present) meets basic editorial quality "
        "standards, in light of the underlying event."
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


class QualityCapability:
    """Implements the `Capability` Protocol (`capabilities.registry.Capability`). Holds only
    `LLMGateway` and `PromptRepository` (§4.2) - no `BudgetGuard`, no `CostTracker`
    (§4.3/§4.4). No per-call mutable state (§3.2)."""

    def __init__(self, gateway: LLMGateway, prompt_repository: PromptRepository) -> None:
        self._gateway = gateway
        self._prompt_repository = prompt_repository

    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        started_at = datetime.now(timezone.utc)

        prompt_version = PROMPT_VERSION_KAGE if settings.copywriting_prompt_version == "11.10" else PROMPT_VERSION
        prompt = self._prompt_repository.resolve(CAPABILITY_NAME, prompt_version)
        request = _build_request(context, prompt)

        # §6.4/§6.5/§6.7 via the centralized M1 mechanism (§6.8) - never reimplemented here.
        outcome = await call_generate(self._gateway, request, runtime=context.runtime, sequence=0)

        if outcome.error is not None:
            # Preserve the failed CapabilityCall (durable, structured) before the classified
            # CapabilityError crosses this execute() call's boundary (§11.1) - mirrors
            # ScoringCapability's identical pattern (Task #1's recorded requirement).
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

        structured_output = response.structured_output
        if prompt.version == PROMPT_VERSION_KAGE:
            from services.kage_reaction_safety import reaction_safety_issues

            steps = context.business.workflow_state.step_results
            draft = steps.get("copywriting") or {}
            research = steps.get("research") or {}
            intelligence = steps.get("intelligence") or {}
            if draft and research and intelligence:
                local_issues = reaction_safety_issues(
                    draft, research, intelligence, source_headline=context.business.news_event.title,
                )
                if local_issues:
                    structured_output = dict(structured_output)
                    structured_output["passed"] = False
                    structured_output["issues"] = list(dict.fromkeys([
                        *structured_output["issues"], *local_issues,
                    ]))

        finished_at = datetime.now(timezone.utc)
        return CapabilityResult(
            status="SUCCESS",
            structured_output=structured_output,
            calls=[outcome.call],
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=(finished_at - started_at).total_seconds(),
            metadata=kage_content_generation_input_metadata(
                context, request, prompt_name=CAPABILITY_NAME, prompt_version=prompt.version,
            ),
        )
