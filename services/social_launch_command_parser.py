"""SOCIAL-INTELLIGENCE-PRELAUNCH-1 §12/§13/§14: SocialLaunchCommandParser. Turns one free-text
/launch message into a structured, human-reviewable proposal - NEVER writes canonical
SocialLaunchContext state itself (same "propose, never self-confirm" discipline services/
telegram_surface_command_parser.py already established).

Architecture note (identical precedent): a one-shot `capabilities/gateway_call.py::call_generate()`
call with a synthetic `RuntimeContext` - /launch has no EditorialTask/Story to bind to either."""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from capabilities.gateway_call import call_generate
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, LLMGateway, Message
from integrations.prompts.protocol import PromptRepository
from schemas.capability import RuntimeContext

PARSER_PROMPT_NAME = "social_launch_parser"
PARSER_PROMPT_VERSION = "1"


class SocialLaunchParseError(Exception):
    """Wraps a Gateway failure - callers should show a plain "could not parse" message, never a
    raw stack trace (mirrors services/telegram_surface_command_parser.py::
    TelegramSurfaceParseError)."""


@dataclass(frozen=True)
class SocialLaunchExtraction:
    target_identity: str
    current_identity: str | None = None
    launch_state: str | None = None
    planned_launch_at: str | None = None
    launch_date_status: str | None = None
    baseline_policy: str | None = None
    historical_content_policy: str | None = None
    summary: str = ""
    clarification_needed: list[str] = field(default_factory=list)


async def parse_launch_command(
    gateway: LLMGateway, prompt_repository: PromptRepository, *, raw_text: str, platform: str,
    previous_structure: dict | None,
) -> SocialLaunchExtraction:
    prompt = prompt_repository.resolve(PARSER_PROMPT_NAME, PARSER_PROMPT_VERSION)
    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    previous_text = f"\n\nCURRENT SAVED CONTEXT (may be empty): {previous_structure or 'none yet'}"
    user_text = f"PLATFORM: {platform}{previous_text}\n\nMESSAGE TO PARSE:\n{raw_text}"
    request = GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=system_text)]),
            Message(role="user", content=[ContentPart(type="text", text=user_text)]),
        ],
        response_mode="json_schema", response_schema=prompt.output_schema,
    )
    runtime = RuntimeContext(
        task_id=uuid4(), event_id=uuid4(), capability_name=PARSER_PROMPT_NAME, priority=TaskPriority.S,
        attempt=1, iteration_count=0,
    )

    try:
        outcome = await call_generate(gateway, request, runtime=runtime, sequence=0)
    except Exception as exc:
        raise SocialLaunchParseError(str(exc)) from exc
    if outcome.error is not None:
        raise SocialLaunchParseError(str(outcome.error))
    assert outcome.response is not None
    output = outcome.response.structured_output or {}

    return SocialLaunchExtraction(
        target_identity=output.get("target_identity") or "NINJA PULSE",
        current_identity=output.get("current_identity"), launch_state=output.get("launch_state"),
        planned_launch_at=output.get("planned_launch_at"), launch_date_status=output.get("launch_date_status"),
        baseline_policy=output.get("baseline_policy"), historical_content_policy=output.get("historical_content_policy"),
        summary=output.get("summary", ""), clarification_needed=list(output.get("clarification_needed") or []),
    )


def extraction_to_structure(extraction: SocialLaunchExtraction) -> dict:
    """Only includes fields the extraction actually set - confirm_proposal() carries the previous
    version's own value forward for anything omitted here, never silently resetting it to a
    schema-mandated placeholder (spec §16's own "changes... invalidate", not "omissions erase")."""
    structure: dict[str, str] = {"target_identity": extraction.target_identity, "summary": extraction.summary}
    if extraction.current_identity is not None:
        structure["current_identity"] = extraction.current_identity
    if extraction.launch_state is not None:
        structure["launch_state"] = extraction.launch_state
    if extraction.planned_launch_at is not None:
        structure["planned_launch_at"] = extraction.planned_launch_at
    if extraction.launch_date_status is not None:
        structure["launch_date_status"] = extraction.launch_date_status
    if extraction.baseline_policy is not None:
        structure["baseline_policy"] = extraction.baseline_policy
    if extraction.historical_content_policy is not None:
        structure["historical_content_policy"] = extraction.historical_content_policy
    return structure
