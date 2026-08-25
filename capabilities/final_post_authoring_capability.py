"""FinalPostAuthoringCapability - Phase I.1: Approved EVENT_RECAP -> Final Post Authoring Core.

A genuinely NEW Capability class - deliberately never `CopywritingCapability` or
`EventRecapCapability` reused/branched. `capabilities/executor.py` has several existing hooks
keyed strictly off `step.capability == "copywriting"` (adaptive-length shadow plan, beginner-
friendly shadow plan, Image Intelligence attach) - all real, all NEWS/CONTENT_GENERATION-only
behavior that must never fire for a Final Post authored from an already-approved recap. Registering
this step under its own name ("final_post_authoring", mapped to `AICapability.COPYWRITING` in
capabilities/capability_mapping.py - the semantically closest existing value, reused rather than
adding a new enum member/migration, mirroring `article_generation -> COPYWRITING`'s own precedent)
makes that separation structural, not just a docstring promise. Mirrors
capabilities/article_generation_capability.py's own shape/discipline exactly - a self-contained
Capability that builds and issues its own single Gateway request, no domain-service indirection
needed (unlike EventRecapCapability's own delegation to services/event_recap.py, which exists
because that module's readiness/evidence-hygiene logic is substantially larger and shared with
Story Integrity/R1 - no such shared logic exists here).

Binding scope: this Capability NEVER re-queries the source EVENT_RECAP task, the EventRecapReview,
or the Story. It reads `context.business.final_post_authoring_bundle` (the deterministic authoring
source bundle services/final_post_processor.py::build_final_post_source_bundle() already
assembled, threaded in by capabilities/executor.py's own FINAL_POST_AUTHORING branch) - never any
other prior step_results, never `context.business.news_event.content`. The approved recap text
inside that bundle is the sole source of truth (module docstring of prompts/final_post_authoring/
v1.yaml); any `verified_facts` present are a guardrail only, never additional editorial license.

Output is deliberately narrow: exactly `{"title": str, "body": str}` - no recap fields, no media
fields, no source/CTA/publication-destination text (Phase I.1's own explicit scope boundary -
presentation and sourcing are owned entirely outside this Capability, by a later phase)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from capabilities.errors import CapabilityConfigurationError, RetryableCapabilityError, ValidationCapabilityError
from capabilities.gateway_call import call_generate
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, LLMGateway, Message
from integrations.prompts.protocol import PromptRepository, RenderedPrompt
from schemas.capability import CapabilityContext, CapabilityResult
from schemas.capability_definition import CapabilityConfig, CapabilityDefinition

logger = logging.getLogger(__name__)

CAPABILITY_NAME = "final_post_authoring"
PROMPT_VERSION = "1"

FINAL_POST_AUTHORING_CAPABILITY_DEFINITION = CapabilityDefinition(
    name=CAPABILITY_NAME,
    version=1,
    config=CapabilityConfig(timeout_seconds=120),
    required_context=["final_post_authoring_bundle"],
    expected_output_keys=["title", "body"],
)


def _floor_validate(structured_output: dict[str, Any] | None) -> str | None:
    """Byte-for-byte the same §9.1 floor `capabilities/article_generation_capability.py::
    _floor_validate()` implements, narrowed to this capability's own `{title, body}` schema -
    duplicated per this codebase's own established per-Capability convention (see that module's
    own docstring for why)."""
    if structured_output is None:
        return "structured_output is missing; the §9.1 floor requires an object."
    for key in ("title", "body"):
        value = structured_output.get(key)
        if not isinstance(value, str):
            return f"structured_output['{key}'] must be a string, got {type(value).__name__}."
    return None


def _render_bundle_text(bundle: dict[str, Any]) -> str:
    """Deterministic plain-text rendering of the authoring source bundle's editorial content only
    - deliberately excludes `source_event_recap_task_id`/`source_event_recap_review_id`/`story_id`/
    `anchor_event_id`/`selected_media_plan` (module docstring's own "media metadata never crosses
    into the LLM prompt" scope, plus these are audit/provenance fields, not writing material) and
    `source_refs` (raw reference identities/URLs - not editorial content, and including them risks
    tempting the model to cite/embed them as text, which is not this Capability's job)."""
    approved = bundle.get("approved_recap") or {}
    lines = [
        f"Approved recap title: {approved.get('recap_title', '')}",
        "",
        f"Approved recap summary: {approved.get('recap_summary', '')}",
    ]
    key_takeaways = approved.get("key_takeaways") or []
    if key_takeaways:
        lines.append("")
        lines.append("Approved key developments:")
        lines.extend(f"- {takeaway}" for takeaway in key_takeaways)
    uncertainty_notes = approved.get("uncertainty_notes") or []
    if uncertainty_notes:
        lines.append("")
        lines.append(
            "Approved uncertainty notes (preserve this uncertainty naturally in the final post - "
            "never state these as settled facts):"
        )
        lines.extend(f"- {note}" for note in uncertainty_notes)
    verified_facts = bundle.get("verified_facts") or []
    if verified_facts:
        lines.append("")
        lines.append(
            "Additional verified supporting facts (guardrail only - do not reinterpret or expand "
            "beyond what the approved recap above already conveys):"
        )
        lines.extend(f"- {fact.get('fact_type')}: {fact.get('value')}" for fact in verified_facts)
    return "\n".join(lines)


def _build_request(context: CapabilityContext, prompt: RenderedPrompt) -> GenerateRequest:
    bundle = context.business.final_post_authoring_bundle
    assert bundle is not None  # required_context - capabilities/executor.py always sets this
    bundle_text = _render_bundle_text(bundle)

    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    context_text = f"APPROVED SOURCE:\n{bundle_text}\n\nTarget output language: {context.business.language}"
    task_text = (
        "Write the final, publish-ready public news post - a title and a body - strictly from the "
        "approved source above. Never add facts outside it."
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


class FinalPostAuthoringCapability:
    """Implements the `Capability` Protocol. Holds only `LLMGateway` and `PromptRepository` -
    no `BudgetGuard`, no `CostTracker`, no `AsyncSession` (mirrors every other Capability's own
    §4.2 constraint, and the "no ORM object crosses into a Capability" rule)."""

    def __init__(self, gateway: LLMGateway, prompt_repository: PromptRepository) -> None:
        self._gateway = gateway
        self._prompt_repository = prompt_repository

    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        started_at = datetime.now(timezone.utc)

        if context.business.final_post_authoring_bundle is None:
            logger.info(
                "final_post_authoring_capability_missing_bundle",
                extra={
                    "capability_name": CAPABILITY_NAME,
                    "news_event_id": str(context.business.news_event.id),
                    "reason": "context.business.final_post_authoring_bundle is None - either "
                              "capabilities/executor.py's own FINAL_POST_AUTHORING branch did not "
                              "run for this step, or no source bundle was available.",
                },
            )
            raise CapabilityConfigurationError(
                "final_post_authoring: context.business.final_post_authoring_bundle is missing - "
                "no authoring source bundle was threaded into this CapabilityContext (see this "
                "module's own docstring for the capabilities/executor.py hook that is supposed to "
                "populate it).",
            )

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

        violation = _floor_validate(response.structured_output)
        if violation is not None:
            if response.finish_reason == "length":
                raise RetryableCapabilityError(
                    f"final_post_authoring: gateway response truncated at the output-token ceiling "
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
