"""MediaVisionReviewCapability - Phase 19 M13: reviews one final-candidate image using the
existing LLM Gateway vision plumbing (RoutingCriteria.requires_vision, GenerateRequest.
modalities=["image"], ContentPart(type="artifact_ref") -> openai_adapter.py's
`_translate_content_part()` "input_image" translation - all already real, already-wired code;
this is the first Capability to actually construct an image-bearing request. No change to the
gateway/routing/provider-adapter layer at all.

An ordinary Capability, following capabilities/editorial_planning_capability.py's exact shape
(`__init__(gateway, prompt_repository)` only, one `call_generate()` invocation, no retry).
Registered in capabilities/registry.py like every other Capability, but never referenced by any
live WorkflowDefinition step - the same "meme_concept"/"editorial_planning" precedent.

CRITICAL: `context.business.media_review_image_data_uri`/`media_review_story_summary` are always
None in every live production path (schemas/capability.py's own docstring for both fields -
capabilities/executor.py::_build_context() never populates either). `execute()` raises
ValidationCapabilityError immediately if the image is missing, rather than silently no-op'ing -
this makes "nothing calls this without an image" a loud, structural guarantee, not a convention
someone could quietly violate. The only caller that ever supplies an image is
scripts/phase19_m13_vision_review_manual.py, a manually-invoked, never-auto-run harness script -
there is no scheduled/automatic live-worker path to this capability's real, LLM-backed execute().
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

CAPABILITY_NAME = "media_vision_review"
PROMPT_VERSION = "1"

MEDIA_VISION_REVIEW_CAPABILITY_DEFINITION = CapabilityDefinition(
    name=CAPABILITY_NAME,
    version=1,
    config=CapabilityConfig(timeout_seconds=30),
    required_context=["news_event"],
    expected_output_keys=[
        "relevant_to_story", "source_logo_present", "watermark_present",
        "website_or_social_ui_present", "advertisement_or_banner_present", "readable_quality",
        "recommended_role",
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
    """Contract §9.1's floor - see editorial_planning_capability._floor_validate's identical
    docstring for the full rationale. Duplicated intentionally (module docstring)."""
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
        if not isinstance(declared_type, str):
            continue
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
    """Raises ValidationCapabilityError immediately if no image was supplied - see module
    docstring for why this is a loud, structural check rather than a silent degrade."""
    image_data_uri = context.business.media_review_image_data_uri
    if not image_data_uri:
        raise ValidationCapabilityError(
            "media_vision_review_capability.execute() called with no "
            "context.business.media_review_image_data_uri - this capability must never be "
            "invoked without a real image to review."
        )
    story_summary = context.business.media_review_story_summary or context.business.news_event.title

    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    task_text = f"Story summary:\n{story_summary}\n\nReview the attached image against this story."

    return GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=system_text)]),
            Message(
                role="user",
                content=[
                    ContentPart(type="text", text=task_text),
                    ContentPart(type="artifact_ref", artifact_ref=image_data_uri, mime_type="image/jpeg"),
                ],
            ),
        ],
        preferred_model=context.execution.preferred_model,
        preferred_provider=context.execution.preferred_provider,
        max_tokens=context.execution.max_tokens,
        reasoning_effort=context.execution.reasoning_effort,
        temperature=context.execution.temperature,
        response_mode="json_schema",
        response_schema=prompt.output_schema,
        modalities=["text", "image"],
    )


class MediaVisionReviewCapability:
    """Implements the Capability Protocol. Holds only LLMGateway/PromptRepository - no
    BudgetGuard, no CostTracker, no mutable per-call state."""

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
