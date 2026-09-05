"""SOCIAL-INTELLIGENCE-OPS-1, spec §3/§4: TelegramSurfaceCommandParser. Turns one free-text /surface
message into a structured, human-reviewable proposal - NEVER writes canonical state itself (spec
§4's own "never write TelegramSurface immediately from parser output" instruction).

Architecture note (identical precedent to services/business_context_command_parser.py): a one-shot
`capabilities/gateway_call.py::call_generate()` call with a synthetic `RuntimeContext` - /surface
has no EditorialTask/Story to bind to either."""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from capabilities.gateway_call import call_generate
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, LLMGateway, Message
from integrations.prompts.protocol import PromptRepository
from schemas.capability import RuntimeContext

PARSER_PROMPT_NAME = "telegram_surface_parser"
PARSER_PROMPT_VERSION = "1"


class TelegramSurfaceParseError(Exception):
    """Wraps a Gateway failure - callers should show a plain "could not parse" message, never a
    raw stack trace (mirrors services/business_context_command_parser.py::BusinessContextParseError)."""


@dataclass(frozen=True)
class TelegramSurfaceExtraction:
    role: str
    name: str
    refers_to_current_chat: bool
    active: bool = True
    analytics_enabled: bool = False
    username: str | None = None
    clarification_needed: list[str] = field(default_factory=list)


async def parse_surface_command(
    gateway: LLMGateway, prompt_repository: PromptRepository, *, raw_text: str, current_chat_name_hint: str,
) -> TelegramSurfaceExtraction:
    prompt = prompt_repository.resolve(PARSER_PROMPT_NAME, PARSER_PROMPT_VERSION)
    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    user_text = f"CURRENT CHAT NAME: {current_chat_name_hint}\n\nMESSAGE TO PARSE:\n{raw_text}"
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
        raise TelegramSurfaceParseError(str(exc)) from exc
    if outcome.error is not None:
        raise TelegramSurfaceParseError(str(outcome.error))
    assert outcome.response is not None
    output = outcome.response.structured_output or {}

    return TelegramSurfaceExtraction(
        role=output.get("role", "other"), name=output.get("name", ""),
        refers_to_current_chat=bool(output.get("refers_to_current_chat", False)),
        active=bool(output.get("active", True)), analytics_enabled=bool(output.get("analytics_enabled", False)),
        username=output.get("username"), clarification_needed=list(output.get("clarification_needed") or []),
    )


def resolve_chat_id(extraction: TelegramSurfaceExtraction, *, current_chat_id: int) -> int | None:
    """Spec §7's own "do not invent unresolved channel IDs" instruction, enforced deterministically
    (never trusted to the model alone): the ONLY chat_id this function will ever return is the real
    chat_id the command was actually sent from, and only when the extraction explicitly said the
    message refers to that same chat. Every other case returns None - the caller must treat that as
    needing clarification, never a guess."""
    if extraction.refers_to_current_chat:
        return current_chat_id
    return None
