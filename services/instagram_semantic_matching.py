"""INSTAGRAM-GROWTH-3, item 1: semantic relatedness evaluation via the existing Newsroom AI
Gateway - the "documented future enhancement" services/instagram_trend_matching.py's own docstring
already named by file path. No ad-hoc provider: this calls `capabilities/gateway_call.py::
call_generate()` directly with a synthetic `RuntimeContext`, the exact sanctioned pattern
services/business_context_command_parser.py already established for a one-shot Gateway call with
no EditorialTask/Story to bind to (Instagram trend/opportunity matching has none either - forcing
one into existence would be the same "disproportionate, ill-fitting architecture graft" that
module's own docstring already rejects).

CRITICAL fail-soft contract (item 1): `evaluate_semantic_relatedness()` NEVER raises on a Gateway
failure - it returns `SemanticMatchResult(available=False, ...)`. Every caller (services/
instagram_semantic_trend_matching.py) MUST fall back to deterministic lexical/entity matching alone
when `available=False`, exactly as if the semantic layer had never been called."""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from capabilities.gateway_call import call_generate
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, LLMGateway, Message
from integrations.prompts.protocol import PromptRepository
from schemas.capability import CapabilityCall, RuntimeContext

SEMANTIC_MATCH_PROMPT_NAME = "instagram_semantic_match"
SEMANTIC_MATCH_PROMPT_VERSION = "1"

# item 1: bounded cost - short, capped subject/context strings, no open-ended conversation, no
# tool use, a single non-streaming call.
_MAX_SUBJECT_CHARS = 300
_MAX_CONTEXT_CHARS = 600


@dataclass(frozen=True)
class SemanticMatchResult:
    available: bool
    is_related: bool | None = None
    relatedness: float | None = None
    rationale: str | None = None
    shared_concepts: list[str] = field(default_factory=list)
    unavailable_reason: str | None = None
    call: CapabilityCall | None = None


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def evaluate_semantic_relatedness(
    gateway: LLMGateway, prompt_repository: PromptRepository, *, subject_a: str, subject_b: str,
    context_a: str = "", context_b: str = "",
) -> SemanticMatchResult:
    try:
        prompt = prompt_repository.resolve(SEMANTIC_MATCH_PROMPT_NAME, SEMANTIC_MATCH_PROMPT_VERSION)
    except Exception as exc:  # prompt file missing/invalid - fail soft, never crash the caller
        return SemanticMatchResult(available=False, unavailable_reason=f"prompt unavailable: {exc}")

    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    user_text = (
        f"SUBJECT A: {_truncate(subject_a, _MAX_SUBJECT_CHARS)}\n"
        f"SUBJECT A CONTEXT: {_truncate(context_a, _MAX_CONTEXT_CHARS)}\n\n"
        f"SUBJECT B: {_truncate(subject_b, _MAX_SUBJECT_CHARS)}\n"
        f"SUBJECT B CONTEXT: {_truncate(context_b, _MAX_CONTEXT_CHARS)}"
    )
    request = GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=system_text)]),
            Message(role="user", content=[ContentPart(type="text", text=user_text)]),
        ],
        response_mode="json_schema", response_schema=prompt.output_schema,
    )
    runtime = RuntimeContext(
        task_id=uuid4(), event_id=uuid4(), capability_name=SEMANTIC_MATCH_PROMPT_NAME,
        priority=TaskPriority.S, attempt=1, iteration_count=0,
    )

    try:
        outcome = await call_generate(gateway, request, runtime=runtime, sequence=0)
    except Exception as exc:
        # item 1's own fail-soft contract: ANY Gateway failure (not only the 4 exception types
        # capabilities/gateway_call.py::call_generate() itself classifies) must degrade to
        # "unavailable", never propagate and crash a deterministic caller.
        return SemanticMatchResult(available=False, unavailable_reason=f"gateway call failed: {exc}")
    if outcome.error is not None:
        return SemanticMatchResult(available=False, unavailable_reason=str(outcome.error), call=outcome.call)

    response = outcome.response
    assert response is not None
    output = response.structured_output
    if output is None or not isinstance(output.get("is_related"), bool) or not isinstance(output.get("relatedness"), (int, float)):
        return SemanticMatchResult(available=False, unavailable_reason="malformed structured output", call=outcome.call)

    return SemanticMatchResult(
        available=True, is_related=output["is_related"], relatedness=float(output["relatedness"]),
        rationale=output.get("rationale"), shared_concepts=list(output.get("shared_concepts") or []),
        call=outcome.call,
    )
