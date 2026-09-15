"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 5: the ONE bounded, schema-constrained LLM call that turns
a raw trend observation's text into a small, structured fingerprint - `{topic, entities, format,
hook_pattern, mechanic, visual_pattern}`. Reuses the EXISTING `LLMGateway`/`PromptRepository` via
`capabilities/gateway_call.py::call_generate()` with a synthetic `RuntimeContext` - the SAME
sanctioned one-shot-call pattern `services/business_context_command_parser.py` and
`services/instagram_semantic_matching.py` already established for a call with no EditorialTask/
Story to bind to. One call per NEW observation - never a second reasoning pipeline, never an
open-ended conversation.

Fail-soft (mirrors `services/instagram_semantic_matching.py`'s own contract exactly): a Gateway
failure NEVER raises - it returns `TrendFingerprintResult(available=False, ...)`, and the raw
observation is still recorded (`services/trend_signal_matching.py` degrades to raw-text comparison
when a fingerprint is absent, never blocking ingestion on an LLM outage)."""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from capabilities.gateway_call import call_generate
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, LLMGateway, Message
from integrations.prompts.protocol import PromptRepository
from schemas.capability import CapabilityCall, RuntimeContext

TREND_FINGERPRINT_PROMPT_NAME = "trend_fingerprint"
TREND_FINGERPRINT_PROMPT_VERSION = "1"

_MAX_TEXT_CHARS = 800


@dataclass(frozen=True)
class TrendFingerprint:
    topic: str
    entities: list[str] = field(default_factory=list)
    format: str = ""
    hook_pattern: str = ""
    mechanic: str = ""
    visual_pattern: str = ""

    def as_dict(self) -> dict:
        return {
            "topic": self.topic, "entities": list(self.entities), "format": self.format,
            "hook_pattern": self.hook_pattern, "mechanic": self.mechanic, "visual_pattern": self.visual_pattern,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TrendFingerprint":
        return cls(
            topic=data.get("topic", ""), entities=list(data.get("entities") or []),
            format=data.get("format", ""), hook_pattern=data.get("hook_pattern", ""),
            mechanic=data.get("mechanic", ""), visual_pattern=data.get("visual_pattern", ""),
        )


@dataclass(frozen=True)
class TrendFingerprintResult:
    available: bool
    fingerprint: TrendFingerprint | None = None
    unavailable_reason: str | None = None
    call: CapabilityCall | None = None


def _truncate(text: str, limit: int = _MAX_TEXT_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def compute_trend_fingerprint(
    gateway: LLMGateway, prompt_repository: PromptRepository, *, raw_topic_text: str, source: str,
) -> TrendFingerprintResult:
    try:
        prompt = prompt_repository.resolve(TREND_FINGERPRINT_PROMPT_NAME, TREND_FINGERPRINT_PROMPT_VERSION)
    except Exception as exc:  # prompt file missing/invalid - fail soft, never crash the caller
        return TrendFingerprintResult(available=False, unavailable_reason=f"prompt unavailable: {exc}")

    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    user_text = f"SOURCE: {source}\n\nRAW TEXT:\n{_truncate(raw_topic_text)}"
    request = GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=system_text)]),
            Message(role="user", content=[ContentPart(type="text", text=user_text)]),
        ],
        response_mode="json_schema", response_schema=prompt.output_schema,
    )
    runtime = RuntimeContext(
        task_id=uuid4(), event_id=uuid4(), capability_name=TREND_FINGERPRINT_PROMPT_NAME,
        priority=TaskPriority.S, attempt=1, iteration_count=0,
    )

    try:
        outcome = await call_generate(gateway, request, runtime=runtime, sequence=0)
    except Exception as exc:
        return TrendFingerprintResult(available=False, unavailable_reason=f"gateway call failed: {exc}")
    if outcome.error is not None:
        return TrendFingerprintResult(available=False, unavailable_reason=str(outcome.error), call=outcome.call)

    response = outcome.response
    if response is None or response.structured_output is None:
        return TrendFingerprintResult(available=False, unavailable_reason="no structured output returned", call=outcome.call)

    fingerprint = TrendFingerprint.from_dict(response.structured_output)
    return TrendFingerprintResult(available=True, fingerprint=fingerprint, call=outcome.call)
