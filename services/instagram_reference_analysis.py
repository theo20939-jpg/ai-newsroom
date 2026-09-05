"""INSTAGRAM-GROWTH-3, item 12: AI-assisted Reference Deconstruction. Same one-shot
`call_generate()` pattern as services/instagram_semantic_matching.py/
services/instagram_creative_director.py - no ad-hoc provider. The result is re-validated through
the ACCEPTED `services/instagram_reference_deconstruction.py::ReferenceDeconstruction` dataclass
(must_not_copy required non-empty) before being handed back - a model that omits it is rejected,
never silently defaulted."""
from __future__ import annotations

from uuid import uuid4

from capabilities.gateway_call import call_generate
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, LLMGateway, Message
from integrations.prompts.protocol import PromptRepository
from schemas.capability import RuntimeContext
from services.instagram_reference_deconstruction import ReferenceDeconstruction

REFERENCE_ANALYSIS_PROMPT_NAME = "instagram_reference_analysis"
REFERENCE_ANALYSIS_PROMPT_VERSION = "1"


class ReferenceAnalysisUnavailableError(Exception):
    """Raised on any Gateway failure - no deterministic fallback exists for creative mechanic
    analysis, so failure is explicit, never fabricated placeholder content."""


async def analyze_reference_with_ai(
    gateway: LLMGateway, prompt_repository: PromptRepository, *, reference_description: str,
) -> ReferenceDeconstruction:
    try:
        prompt = prompt_repository.resolve(REFERENCE_ANALYSIS_PROMPT_NAME, REFERENCE_ANALYSIS_PROMPT_VERSION)
    except Exception as exc:
        raise ReferenceAnalysisUnavailableError(f"prompt unavailable: {exc}") from exc

    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    request = GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=system_text)]),
            Message(role="user", content=[ContentPart(type="text", text=f"REFERENCE DESCRIPTION:\n{reference_description}")]),
        ],
        response_mode="json_schema", response_schema=prompt.output_schema,
    )
    runtime = RuntimeContext(
        task_id=uuid4(), event_id=uuid4(), capability_name=REFERENCE_ANALYSIS_PROMPT_NAME,
        priority=TaskPriority.S, attempt=1, iteration_count=0,
    )

    try:
        outcome = await call_generate(gateway, request, runtime=runtime, sequence=0)
    except Exception as exc:
        raise ReferenceAnalysisUnavailableError(f"gateway call failed: {exc}") from exc
    if outcome.error is not None:
        raise ReferenceAnalysisUnavailableError(str(outcome.error))

    response = outcome.response
    assert response is not None
    output = response.structured_output
    if output is None:
        raise ReferenceAnalysisUnavailableError("no structured output returned")

    try:
        return ReferenceDeconstruction(
            reference_description=reference_description,
            hook_mechanics=output.get("hook_mechanics", ""), pacing=output.get("pacing", ""),
            scene_structure=output.get("scene_structure", ""), narrative_progression=output.get("narrative_progression", ""),
            typography_behavior=output.get("typography_behavior", ""), visual_rhythm=output.get("visual_rhythm", ""),
            editing_rhythm=output.get("editing_rhythm", ""), cta_mechanics=output.get("cta_mechanics", ""),
            interaction_pattern=output.get("interaction_pattern", ""),
            what_appears_effective=list(output.get("what_appears_effective") or []),
            must_not_copy=list(output.get("must_not_copy") or []),
            originality_constraints=list(output.get("originality_constraints") or []),
        )
    except ValueError as exc:
        # Reuses the accepted dataclass's own "must_not_copy cannot be empty" validation - a
        # model that omits it is rejected, never silently defaulted to a made-up constraint.
        raise ReferenceAnalysisUnavailableError(f"AI output failed originality validation: {exc}") from exc
