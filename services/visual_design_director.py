"""VISUAL-DESIGN-AUTONOMY-1, spec §9/§30-31: VisualDesignDirector - builds the compact
VisualDirectorContext and makes the ONE creative-direction LLM call per attempt.

Architecture note (mirrors services/instagram_creative_director.py's own, and ultimately
services/business_context_command_parser.py's original precedent, exactly): a one-shot
`capabilities/gateway_call.py::call_generate()` call with a synthetic `RuntimeContext` - the
Visual Design Director has no EditorialTask/Story-bound workflow of its own to attach to, so
forcing the full Capability+CapabilityExecutor+WorkflowRunner machinery into existence would be a
disproportionate architecture graft. A Gateway failure has no sensible deterministic fallback (spec
§9: there is no simpler algorithm that "designs a creative direction") - it raises a typed error,
never fabricates placeholder creative content.

CRITICAL fact/brand safety (spec §66/§67/§74): every returned prompt is checked against
services/visual_brand_core.py AFTER generation, never trusted to prompt discipline alone - a
violation raises VisualDesignFactSafetyError, the caller must not use that prompt."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, LLMGateway, Message
from integrations.prompts.protocol import PromptRepository
from schemas.capability import RuntimeContext
from services.visual_brand_core import BRAND_CORE_RULES, check_creative_prompt_against_brand_core
from services.visual_creative_direction import (
    MediaStrategy,
    PreviousAttemptFeedback,
    VisualCreativeDirection,
    VisualDirectorContext,
)

PROMPT_NAME = "telegram_visual_design_director"
_PROMPT_VERSION = "1"


class VisualDesignDirectorUnavailableError(Exception):
    """Raised when the Gateway call itself fails - no deterministic fallback exists for creative
    direction; callers must handle this explicitly, never fabricate a direction in its place."""


class VisualDesignFactSafetyError(Exception):
    """Raised when a generated prompt violates VisualBrandCore - the direction is REJECTED,
    never silently sanitized or used anyway."""


@dataclass(frozen=True)
class StoryFactsInput:
    """A deliberately small, decoupled summary of the real Story this design is for - callers
    build this from whatever Story/NewsEvent row they actually have; this module never imports
    database.models.story itself, keeping the creative-direction call testable without a DB."""

    story_id: str
    title: str
    category: str | None = None
    entities: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    summary: str = ""


def _story_facts_summary(story: StoryFactsInput) -> str:
    parts = [f"title: {story.title}"]
    if story.category:
        parts.append(f"category: {story.category}")
    if story.entities:
        parts.append(f"entities: {', '.join(story.entities[:8])}")
    if story.keywords:
        parts.append(f"keywords: {', '.join(story.keywords[:8])}")
    if story.summary:
        parts.append(f"summary: {story.summary[:500]}")
    return "\n".join(parts)


def build_visual_director_context(
    *, story: StoryFactsInput, platform: str, presentation_type: str | None,
    designer_brief_text: str, designer_brief_scope: str, designer_brief_version: int,
    feed_context_summary: list[str], recent_failure_summary: list[str],
    available_media_summary: str, renderer_constraints_summary: str,
    attempts_used: int, max_attempts: int, budget_state_summary: str,
    restricted_claims: list[str] | None = None, previous_attempt: PreviousAttemptFeedback | None = None,
    launch_context_summary: str = "", now: datetime | None = None,
) -> VisualDirectorContext:
    return VisualDirectorContext(
        as_of=now or datetime.now(timezone.utc), story_id=story.story_id, platform=platform,
        presentation_type=presentation_type, story_facts_summary=_story_facts_summary(story),
        brand_core_rules=list(BRAND_CORE_RULES), designer_brief_text=designer_brief_text,
        designer_brief_scope=designer_brief_scope, designer_brief_version=designer_brief_version,
        feed_context_summary=feed_context_summary, recent_failure_summary=recent_failure_summary,
        available_media_summary=available_media_summary, renderer_constraints_summary=renderer_constraints_summary,
        attempts_used=attempts_used, max_attempts=max_attempts, budget_state_summary=budget_state_summary,
        restricted_claims=restricted_claims or [], previous_attempt=previous_attempt,
        launch_context_summary=launch_context_summary,
    )


def _build_user_text(context: VisualDirectorContext) -> str:
    lines = [
        f"STORY: {context.story_facts_summary}",
        f"PLATFORM: {context.platform}",
        f"PRESENTATION_TYPE: {context.presentation_type or '(none)'}",
        f"DESIGNER BRIEF (scope={context.designer_brief_scope}, v{context.designer_brief_version}):\n{context.designer_brief_text}",
        "RECENT FEED CONTEXT (advisory only, not a rule):\n" + "\n".join(f"- {line}" for line in context.feed_context_summary),
        "RECENT ART DIRECTOR FAILURES (advisory only):\n" + "\n".join(f"- {line}" for line in context.recent_failure_summary),
        f"AVAILABLE MEDIA: {context.available_media_summary}",
        f"RENDERER CONSTRAINTS: {context.renderer_constraints_summary}",
        f"ATTEMPTS: {context.attempts_used}/{context.max_attempts} used",
        f"BUDGET STATE: {context.budget_state_summary}",
        f"RESTRICTED CLAIMS (never depict): {context.restricted_claims}",
        f"LAUNCH CONTEXT (advisory only, not a rule): {context.launch_context_summary or '(established account - no launch context)'}",
    ]
    if context.previous_attempt is not None:
        prev = context.previous_attempt
        lines.append(
            "PREVIOUS ATTEMPT (this is a REWORK retry - you may refine OR completely redesign):\n"
            f"attempt_number: {prev.attempt_number}\n"
            f"previous_direction: {prev.previous_creative_direction_summary}\n"
            f"previous_prompt: {prev.previous_prompt_text}\n"
            f"art_director_decision: {prev.art_decision}\n"
            f"issue_codes: {prev.issue_codes}\n"
            f"art_director_instructions: {prev.instructions}\n"
            f"root_cause: {prev.root_cause}\n"
            f"attempts_remaining: {prev.attempts_remaining}"
        )
    return "\n\n".join(lines)


def _parse_media_strategy(raw: str) -> MediaStrategy:
    try:
        return MediaStrategy(raw)
    except ValueError:
        return MediaStrategy.USE_SOURCE_MEDIA


async def generate_creative_direction(
    gateway: LLMGateway, prompt_repository: PromptRepository, *, context: VisualDirectorContext,
) -> VisualCreativeDirection:
    from capabilities.gateway_call import call_generate  # local import: avoids a capabilities<->services import cycle at module load time

    try:
        prompt = prompt_repository.resolve(PROMPT_NAME, _PROMPT_VERSION)
    except Exception as exc:
        raise VisualDesignDirectorUnavailableError(f"prompt unavailable: {exc}") from exc

    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    system_text += "\n\nIMMUTABLE BRAND CORE (never violate):\n" + "\n".join(f"- {rule}" for rule in context.brand_core_rules)

    request = GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=system_text)]),
            Message(role="user", content=[ContentPart(type="text", text=_build_user_text(context))]),
        ],
        response_mode="json_schema", response_schema=prompt.output_schema,
    )
    runtime = RuntimeContext(
        task_id=uuid4(), event_id=uuid4(), capability_name=PROMPT_NAME, priority=TaskPriority.S,
        attempt=1, iteration_count=0,
    )

    try:
        outcome = await call_generate(gateway, request, runtime=runtime, sequence=0)
    except Exception as exc:
        raise VisualDesignDirectorUnavailableError(f"gateway call failed: {exc}") from exc
    if outcome.error is not None:
        raise VisualDesignDirectorUnavailableError(str(outcome.error))

    response = outcome.response
    if response is None or response.structured_output is None:
        raise VisualDesignDirectorUnavailableError("no structured output returned")
    output = response.structured_output

    direction = VisualCreativeDirection(
        story_id=context.story_id, platform=context.platform, presentation_type=context.presentation_type,
        creative_intent=output.get("creative_intent", ""), visual_angle=output.get("visual_angle", ""),
        composition=output.get("composition", ""), subject_priority=output.get("subject_priority", ""),
        palette_direction=output.get("palette_direction", ""), lighting_direction=output.get("lighting_direction", ""),
        background_direction=output.get("background_direction", ""), visual_density=output.get("visual_density", ""),
        negative_space_strategy=output.get("negative_space_strategy", ""), overlay_strategy=output.get("overlay_strategy", ""),
        style_direction=output.get("style_direction", ""), media_strategy=_parse_media_strategy(output.get("media_strategy", "")),
        preferred_overlay_zone=output.get("preferred_overlay_zone") or None,
        preferred_overlay_variant=output.get("preferred_overlay_variant") or None,
        preferred_overlay_contrast=output.get("preferred_overlay_contrast") or None,
        risks=list(output.get("risks", [])), reasoning=list(output.get("reasoning", [])),
        prompt_text=output.get("prompt_text", ""),
    )

    if direction.prompt_text:
        brand_check = check_creative_prompt_against_brand_core(direction.prompt_text, restricted_claims=context.restricted_claims)
        if not brand_check.compliant:
            raise VisualDesignFactSafetyError(
                "generated prompt violates Brand Core: " + "; ".join(v.detail for v in brand_check.violations)
            )

    return direction
