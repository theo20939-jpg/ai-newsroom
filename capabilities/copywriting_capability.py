"""CopywritingCapability - Phase 10 M1: drafts a short, social-ready post from Research's
already-extracted facts and Intelligence's already-formed editorial judgment
(docs/phase10_production_content_pipeline_architecture_contract.md §5).

An ordinary Phase 8 `Capability`, identical construction shape to `ResearchCapability`/
`IntelligenceCapability`/`QualityCapability`: `__init__(gateway, prompt_repository)` only, one
`call_generate()` invocation, no retry (matching every existing Capability's own precedent).

Binding rule (Contract §5): `CopywritingCapability` MUST NOT hold a direct reference to
`ResearchCapability` or `IntelligenceCapability`, import either, or call either - this file
contains no such import anywhere. Their output is consumed exclusively through the existing,
already-frozen Phase 6 mechanism: `context.business.workflow_state.step_results["research"]` /
`["intelligence"]`. If either key is missing or empty (that step did not run, or this is a
malformed synthetic test), `execute()` still runs - it does not raise merely for this reason;
the built prompt states the absence explicitly rather than fabricating facts, mirroring
`IntelligenceCapability`'s own "Research did not run" degradation exactly.

This module intentionally duplicates `research_capability.py`/`intelligence_capability.py`/
`quality_capability.py`'s floor-validation helper rather than factoring out a shared one, per
the same rationale those modules already record (§19.2 Q1 of the Phase 9 contract).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from capabilities.errors import ValidationCapabilityError
from capabilities.gateway_call import call_generate
from core.config import settings
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, LLMGateway, Message
from integrations.prompts.protocol import PromptRepository, RenderedPrompt
from schemas.capability import CapabilityContext, CapabilityResult
from schemas.capability_definition import CapabilityConfig, CapabilityDefinition

logger = logging.getLogger(__name__)

CAPABILITY_NAME = "copywriting"
# v4 (Phase 18.10 M5/M6, docs/phase18_10_editorial_intelligence_report.md): drops hashtags from
# the schema at the source, adds a structured what_happened/why_it_matters/what_remains_unknown
# shape and an optional, narrowly-verified quote field.
# v5 (Phase 19 M4, docs/phase19_m0_audit.md): genuinely editorial long-form structure (opening/
# context/why_it_matters/what_changed/what_happens_next/conclusion), selectable via
# core/config.py's copywriting_prompt_version setting - defaults "4" (v5 is opt-in, not yet the
# default). prompts/copywriting/v{1,2,3,4}.yaml are left in place, unmodified, per Phase 6 §8's
# prompt-immutability rule - PROMPT_VERSION below is the fallback/default only; execute() reads
# settings.copywriting_prompt_version at call time, never a fixed constant, so the active version
# can change without a code deploy.
PROMPT_VERSION = "4"

# Phase 18.10 M5 "Amendment B" (mirrors capabilities/capability_mapping.py's own "Amendment A"
# precedent for a narrow, disclosed, deliberate exception): Copywriting is otherwise forbidden
# from reading news_event.content directly (Contract §5's "MUST NOT re-extract" discipline,
# unchanged) - this one field is the sole, explicit exception, scoped to quote-sourcing only (see
# the v4 prompt's own rules), never to extracting additional facts beyond what Research/
# Intelligence already established. Bounded to keep prompt size/cost predictable - long enough to
# contain a realistic quote, never the full article.
#
# Phase 23.1P: raised 3000->6000 with direct evidence, not a guess - now that this excerpt can be
# the already-acquired full article (see _format_quote_source_excerpt()'s own docstring), a real
# genuinely useful quote (the Research Gold story's Jenny Berrio quote, Phase 23.1O) measured at
# character offset 3364 in its own cleaned article text - already past the old 3000-char cap, cut
# off by it even after this phase's own retrieval fix. 6000 leaves real margin past that measured
# offset while staying a small, bounded, cost-predictable excerpt (~1500 tokens).
_QUOTE_SOURCE_EXCERPT_CHARS = 6000

COPYWRITING_CAPABILITY_DEFINITION = CapabilityDefinition(
    name=CAPABILITY_NAME,
    version=1,
    config=CapabilityConfig(timeout_seconds=30),
    required_context=["news_event"],
    expected_output_keys=[
        "title", "body", "what_happened", "why_it_matters", "what_remains_unknown", "quote",
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
    """Contract §9.1's floor - see scoring_capability._floor_validate's identical docstring
    for the full rationale. Duplicated intentionally (module docstring). A declared union type
    (e.g. `["string", "null"]`, used here for the genuinely-optional what_remains_unknown/quote
    fields) is not present as a key in `_SCHEMA_TYPE_TO_PYTHON_TYPE` and is therefore skipped for
    the type check, same as any other unrecognized declared type - presence of the required key
    is still enforced (mirrors capabilities/meme_copywriting_capability.py's own identical fix
    for its own nullable fields)."""
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


def _format_research_context(research_output: dict[str, Any]) -> str:
    if not research_output:
        return "(Research did not run, or produced no output - proceed on title/category alone.)"
    facts = research_output.get("facts", [])
    confidence = research_output.get("confidence")
    gaps = research_output.get("gaps", [])
    return f"Facts: {facts}\nConfidence: {confidence}\nGaps: {gaps}"


def _format_intelligence_context(intelligence_output: dict[str, Any]) -> str:
    if not intelligence_output:
        return "(Intelligence did not run, or produced no output - proceed on title/category alone.)"
    significance = intelligence_output.get("significance")
    angle = intelligence_output.get("angle")
    audience_relevance = intelligence_output.get("audience_relevance")
    recommendation = intelligence_output.get("recommendation")
    return (
        f"Significance: {significance}\nAngle: {angle}\n"
        f"Audience relevance: {audience_relevance}\nRecommendation: {recommendation}"
    )


def _format_quote_source_excerpt(news_event: Any, quote_source_text: str | None = None) -> str:
    """Phase 18.10 M5 "Amendment B" (see PROMPT_VERSION's own comment above): the sole, narrow,
    disclosed exception to Copywriting's "never reads news_event.content" rule - bounded, and
    labeled for quote-sourcing only, never for extracting additional facts.

    Phase 23.1P (docs/phase23_1p_story_memory_quotes_gate_report.md): prefers `quote_source_text`
    (the already-acquired, already-cleaned full article text - `CapabilityContext.business.
    quote_source_text`, populated by capabilities/executor.py only when article_acquisition_mode
    != "off" and a FULL_TEXT/PARTIAL_TEXT acquisition exists) over the plain `news_event.content`
    RSS teaser this function used exclusively before - the proven root cause of real, useful
    quotes never reaching Copywriting at all (confirmed: a 130-char news_event.content with zero
    quotes vs. an 11,289-char acquired article containing several, for the real Research Gold
    story, Phase 23.1O). Falls back to today's `news_event.content` behavior, byte-identical,
    whenever no richer text was acquired - never a regression for that case."""
    content = quote_source_text or getattr(news_event, "content", None)
    if not content:
        return "(No source excerpt available - no quote can be sourced; leave quote null.)"
    excerpt = content[:_QUOTE_SOURCE_EXCERPT_CHARS]
    return excerpt


def _build_request(context: CapabilityContext, prompt: RenderedPrompt) -> GenerateRequest:
    """Contract §5's Input row: title/category only from `context.business.news_event` (never
    `content`, mirroring `IntelligenceCapability`'s own "MUST NOT re-extract" discipline - Phase
    18.10 M5's own "Amendment B" is the sole, narrow exception, scoped to quote-sourcing only, see
    `_format_quote_source_excerpt()`), plus `context.business.workflow_state.step_results
    ["research"]`/`["intelligence"]` (§5's exact, already-frozen field paths - never a direct
    import or call of either upstream Capability)."""
    news_event = context.business.news_event
    research_output = context.business.workflow_state.step_results.get("research", {})
    intelligence_output = context.business.workflow_state.step_results.get("intelligence", {})
    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    context_text = (
        f"Title: {news_event.title}\n"
        f"Category: {news_event.category}\n"
        f"Target output language: {context.business.language}\n\n"
        f"Research output:\n{_format_research_context(research_output)}\n\n"
        f"Intelligence output:\n{_format_intelligence_context(intelligence_output)}\n\n"
        f"Source excerpt (for quote-sourcing only - never for additional facts):\n"
        f"{_format_quote_source_excerpt(news_event, context.business.quote_source_text)}"
    )
    # Phase 19 overnight A/B/C validation seam: gated on prompt.version itself (RenderedPrompt's
    # own field, not a settings re-read) rather than merely "the caller happened not to supply
    # them" - v4 and the existing, frozen v5 structurally never append these blocks even if a
    # caller mistakenly populated the BusinessContext fields for them; v6/v7/v8/v8.1/v8.2
    # (prompts/copywriting/v6.yaml, v7.yaml, v8.yaml, v8.1.yaml, v8.2.yaml - each one's smaller
    # schema still accepts the same optional context blocks) ever do, and only when present.
    # NEWS Output Stability Fix (Case F, docs/news_output_stability_forensic_report.md §7/§13
    # item 2): v8.6 (prompts/copywriting/v8.6.yaml) is a pure prompt-rule-text successor to v8.5 -
    # confirmed by direct diff, identical schema, only the UNCERTAINTY rule's wording changed -
    # was missing from this tuple entirely, which would have silently dropped the EDITORIAL PLAN/
    # PRIOR COVERAGE context blocks the moment v8.6 actually went live, a real regression this
    # activation would otherwise have introduced. v8.3/v8.4 were already listed even though not
    # individually mentioned by name in this comment - v8.6+ follow the same "every v8-family
    # version accepts these blocks" pattern.
    if prompt.version in ("6", "7", "8", "8.1", "8.2", "8.3", "8.4", "8.5", "8.6", "8.7", "8.8"):
        if context.business.editorial_plan_context is not None:
            context_text += f"\n\nEDITORIAL PLAN:\n{context.business.editorial_plan_context}"
        if context.business.prior_coverage_context is not None:
            context_text += f"\n\nPRIOR COVERAGE / STORY CONTEXT:\n{context.business.prior_coverage_context}"
    task_text = (
        "Write the post for the event above, following the system prompt's required structure "
        "exactly, based only on the given title/category, Research's/Intelligence's output, and "
        "(for quote-sourcing only) the source excerpt."
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


class CopywritingCapability:
    """Implements the `Capability` Protocol (`capabilities.registry.Capability`). Holds only
    `LLMGateway` and `PromptRepository` (§4.2 of the frozen Phase 8 contract) - no
    `BudgetGuard`, no `CostTracker`. No per-call mutable state (§3.2). Never imports or calls
    `ResearchCapability`/`IntelligenceCapability` (Contract §5)."""

    def __init__(self, gateway: LLMGateway, prompt_repository: PromptRepository) -> None:
        self._gateway = gateway
        self._prompt_repository = prompt_repository

    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        started_at = datetime.now(timezone.utc)

        # Phase 19 M4: read at call time, not a fixed constant - settings.copywriting_prompt_
        # version defaults to "4" (byte-identical to pre-Phase-19 behavior); v5 is opt-in.
        prompt_version = settings.copywriting_prompt_version
        prompt = self._prompt_repository.resolve(CAPABILITY_NAME, prompt_version)
        request = _build_request(context, prompt)

        # §6.4/§6.5/§6.7 via the centralized M1 mechanism (§6.8) - never reimplemented here.
        outcome = await call_generate(self._gateway, request, runtime=context.runtime, sequence=0)

        if outcome.error is not None:
            # Preserve the failed CapabilityCall (durable, structured) before the classified
            # CapabilityError crosses this execute() call's boundary (§11.1) - mirrors
            # ResearchCapability/IntelligenceCapability/QualityCapability's identical pattern.
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
