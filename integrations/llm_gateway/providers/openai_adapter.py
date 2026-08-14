"""OpenAIAdapter: the first real ProviderAdapter (docs/phase7_architecture_contract.md §2, §20.1).

M18 scope, per instruction: `generate()` only. `generate_stream()`/`embed()`/`classify()`/
`moderate()`/`rerank()` all raise `UnsupportedGatewayCapabilityError` until their own,
separately approved milestones - matching `tests/fakes/fake_provider_adapter.py`'s established
pattern for the same five deferred methods.

Official-source verification (2026-07-17, before any code in this file was written):
  - SDK: the official `openai` PyPI package (https://pypi.org/project/openai/), current
    release line 2.4x as of this writing. Only `from openai import AsyncOpenAI` and the typed
    exception hierarchy from `openai/_exceptions.py` are used.
  - API surface: OpenAI's Responses API (`client.responses.create(...)`), per
    developers.openai.com/api/docs/guides/migrate-to-responses - "Responses is recommended for
    all new projects" (Chat Completions remains supported but is not the recommended surface
    for new integrations as of this writing). Request/response field names below
    (`input`, `instructions`, `tools`/`FunctionToolParam`, `text.format` for structured
    outputs, `response.output_text`, `response.usage.{input,output,total}_tokens`,
    `response.status`, `response.incomplete_details.reason`,
    `response.output[].type == "function_call"`) were verified against the live
    `openai/types/responses/*.py` source in github.com/openai/openai-python (main branch),
    not from training-data memory or an unofficial source.
  - Model catalogue: `integrations/llm_gateway/models/catalog.py`'s GPT-5.6 Sol/Terra/Luna
    entries (model_id, context_window_tokens, max_output_tokens, standard-tier pricing) were
    independently re-verified against developers.openai.com/api/docs/models/gpt-5.6-{sol,
    terra,luna} during this same verification pass and found to match exactly - no catalogue
    change was needed or made.
  - Exception hierarchy: `openai.APIConnectionError`/`APITimeoutError`/`RateLimitError`/
    `AuthenticationError`/`InternalServerError`/`ConflictError`/`BadRequestError`/
    `PermissionDeniedError`/`NotFoundError`/`UnprocessableEntityError`, all subclasses of
    `openai.OpenAIError`, verified against the live `openai/_exceptions.py` source.

Provider isolation (P11, §1): this is the ONLY file that imports the `openai` package,
directly or transitively, anywhere in this codebase outside its own tests/smoke script.

Architectural gap found and fixed during this milestone (not an OpenAI-specific concern -
documented at length in `integrations/llm_gateway/fallback/policy.py`'s module docstring):
`FallbackPolicy` previously called `adapter.generate(request)` with the plain, unmodified
request - never telling the adapter which candidate `(provider_id, model_id)` routing/fallback
had actually resolved. This was invisible with `FakeProviderAdapter` (each fake test instance
is hard-wired to exactly one model), but a real, multi-model provider adapter like this one has
no other way to know whether to call `gpt-5.6-sol`, `-terra`, or `-luna` for a given attempt.
Fixed by having `FallbackPolicy` inject `resolved_model_id`/`resolved_provider_id` into
`request.metadata` immediately before each dispatch attempt - the same "extend via metadata,
never the frozen schema" pattern already used throughout M17 (request_id, capability_name,
priority, excluded_providers, cache_policy) and confirmed cache-key-neutral (§13.2's
`normalized_request_hash` already excludes `metadata` entirely). `_resolve_model_id()` below
reads `request.metadata["resolved_model_id"]`, falling back to `request.preferred_model` only
for direct/manual adapter invocation outside the full pipeline (e.g. the smoke-test script).
"""
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from typing import Any, Literal

import openai
from openai import AsyncOpenAI

from integrations.llm_gateway.errors import (
    GatewayError,
    ProviderModerationBlockedError,
    ProviderPermanentIncompatibleError,
    ProviderRegionalUnavailableError,
    ProviderTransientError,
)
from integrations.llm_gateway.protocol import (
    ClassifyRequest,
    ClassifyResponse,
    ContentPart,
    EmbedRequest,
    EmbedResponse,
    GenerateChunk,
    GenerateRequest,
    GenerateResponse,
    Message,
    ModerateRequest,
    ModerateResponse,
    RerankRequest,
    RerankResponse,
    ToolCall,
    ToolDefinition,
    UnsupportedGatewayCapabilityError,
)
from integrations.llm_gateway.providers.base import (
    ProviderCredential,
    ProviderDescriptor,
    ProviderFactory,
    build_openai_credential,
)
from schemas.capability import CapabilityUsage

logger = logging.getLogger(__name__)

OPENAI_PROVIDER_ID = "openai"  # duplicated literal, not imported from models/catalog.py -
# ProviderAdapter -> ModelRegistry is a forbidden edge (§1's table); provider_id is an opaque
# string by design (§27 rule 6), so re-stating the same literal here is expected, not a DRY sin.

_MODERATION_ERROR_CODES = frozenset(
    {"invalid_prompt", "bio_policy", "image_content_policy_violation", "content_policy_violation"}
)

_BEARER_PATTERN = re.compile(r"Bearer\s+\S+", re.IGNORECASE)
_SK_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{8,}")


def _redact(text: str, api_key: str | None) -> str:
    """§2 rule 7 / §17.2: strip/redact anything matching a known credential pattern from a
    logged representation - never rely on the SDK's default __str__/__repr__. Redacts the
    adapter's own actual key value (literal-value match, the most reliable signal available)
    plus generic Bearer-header and sk-prefixed-key patterns as defense in depth."""
    redacted = text
    if api_key:
        redacted = redacted.replace(api_key, "[REDACTED]")
    redacted = _BEARER_PATTERN.sub("Bearer [REDACTED]", redacted)
    redacted = _SK_KEY_PATTERN.sub("[REDACTED]", redacted)
    return redacted


def _translate_exception(exc: Exception, api_key: str | None) -> GatewayError:
    """§5.2/§20's typed-exception-hierarchy translation: every openai.OpenAIError subtype maps
    to exactly one of this contract's three provider-failure exceptions. Only `.message`/
    `.code`/`.status_code`/the exception's own type name are ever read - never `.request`/
    `.response` (httpx objects that may carry the Authorization header), and the assembled
    message is always passed through `_redact()` before being attached to the raised
    exception (requirement: "No raw OpenAI exception may cross the ProviderAdapter boundary")."""
    kind = type(exc).__name__

    if isinstance(exc, openai.BadRequestError):
        code = getattr(exc, "code", None)
        message = _redact(f"openai: bad request (code={code}): {exc.message}", api_key)  # type: ignore[attr-defined]
        if code in _MODERATION_ERROR_CODES:
            return ProviderModerationBlockedError(message)
        return ProviderPermanentIncompatibleError(message)

    if isinstance(exc, openai.PermissionDeniedError):
        # Phase 15 runtime reliability fix: split out from NotFoundError/UnprocessableEntityError
        # below - a 403 is regional/account-scoped (docs/llm_runtime_availability_recovery_
        # report.md's own directly-observed `unsupported_country_region_territory` case, proven
        # stale by a same-day re-probe), never a genuinely permanent model/schema misconfiguration.
        message = _redact(
            f"openai: {kind} (status={exc.status_code}): {exc.message}", api_key  # type: ignore[attr-defined]
        )
        return ProviderRegionalUnavailableError(message)

    if isinstance(exc, (openai.NotFoundError, openai.UnprocessableEntityError)):
        message = _redact(
            f"openai: {kind} (status={exc.status_code}): {exc.message}", api_key  # type: ignore[attr-defined]
        )
        return ProviderPermanentIncompatibleError(message)

    if isinstance(
        exc,
        (
            openai.RateLimitError,
            openai.AuthenticationError,  # §5.2: "auth (this attempt only)" is TRANSIENT
            openai.InternalServerError,
            openai.ConflictError,
        ),
    ):
        message = _redact(
            f"openai: {kind} (status={exc.status_code}): {exc.message}", api_key  # type: ignore[attr-defined]
        )
        return ProviderTransientError(message)

    if isinstance(exc, openai.APIConnectionError):  # covers APITimeoutError (its subclass)
        message = _redact(f"openai: {kind}: {exc.message}", api_key)  # type: ignore[attr-defined]
        return ProviderTransientError(message)

    if isinstance(exc, openai.APIStatusError):
        message = _redact(
            f"openai: unmapped status error {kind} (status={exc.status_code}): {exc.message}", api_key  # type: ignore[attr-defined]
        )
        return ProviderTransientError(message)

    if isinstance(exc, openai.OpenAIError):
        message = _redact(f"openai: {kind}: {exc}", api_key)
        return ProviderTransientError(message)

    # Not an OpenAIError at all (an unexpected, non-SDK exception) - still must never leak a
    # raw, unredacted representation past this boundary.
    return ProviderTransientError(_redact(f"openai: unexpected error ({kind}): {exc}", api_key))


def _translate_content_part(part: ContentPart) -> dict[str, Any]:
    if part.type == "text":
        return {"type": "input_text", "text": part.text or ""}
    if part.mime_type is not None and part.mime_type.startswith("image/"):
        return {"type": "input_image", "image_url": part.artifact_ref}
    raise ProviderPermanentIncompatibleError(
        f"openai adapter: unsupported content part for translation (type={part.type!r}, "
        f"mime_type={part.mime_type!r}) - only text and image artifact_ref parts are "
        "translated in this delivery"
    )


def _translate_message(message: Message) -> dict[str, Any]:
    if message.role == "tool":
        # Responses API input items have no "tool" role (valid roles: user/assistant/system/
        # developer) - a tool result is a distinct `function_call_output` item type, linked by
        # call_id. Translating that requires the tool-use loop's call_id bookkeeping, which
        # lives in Capability.execute() (§9.3) - no concrete Capability exists yet in this
        # codebase (per docs/phase7_implementation_log.md's M16/M17 entries), so there is
        # nothing to translate against yet. Raising a clear, typed error here is preferable to
        # silently mistranslating a tool-result message into a plain user message.
        raise ProviderPermanentIncompatibleError(
            "openai adapter: role='tool' message translation is not implemented in this "
            "delivery - the tool-calling loop (§9) is a deferred capability with no concrete "
            "Capability driving it yet"
        )
    return {
        "role": message.role,
        "content": [_translate_content_part(part) for part in message.content],
    }


def _translate_tool(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters_schema,
        "strict": False,
    }


def _build_payload(request: GenerateRequest, model_id: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model_id,
        "input": [_translate_message(message) for message in request.messages],
    }
    if request.max_tokens is not None:
        payload["max_output_tokens"] = request.max_tokens
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.reasoning_effort is not None:
        payload["reasoning"] = {"effort": request.reasoning_effort}
    if request.tools:
        payload["tools"] = [_translate_tool(tool) for tool in request.tools]
    if request.tool_choice is not None:
        payload["tool_choice"] = request.tool_choice
    if request.response_mode == "json_schema" and request.response_schema is not None:
        payload["text"] = {
            "format": {
                "type": "json_schema",
                "name": "structured_output",
                "schema": request.response_schema,
                "strict": True,
            }
        }
    return payload


def _extract_tool_calls(output: list[Any]) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for item in output:
        if getattr(item, "type", None) == "function_call":
            calls.append(ToolCall(name=item.name, arguments=json.loads(item.arguments)))
    return calls


def _finish_reason(
    response: Any, tool_calls: list[ToolCall]
) -> Literal["stop", "tool_calls", "length", "content_filter"]:
    incomplete = getattr(response, "incomplete_details", None)
    if incomplete is not None and incomplete.reason == "max_output_tokens":
        return "length"
    if incomplete is not None and incomplete.reason == "content_filter":
        return "content_filter"
    if tool_calls:
        return "tool_calls"
    return "stop"


def _extract_structured_output(response: Any) -> dict[str, Any] | None:
    """§9.1 structured-output extraction. `response.output_text` (a single string concatenated
    across the whole response) is unreliable for Responses API structured JSON output - it can
    be empty even though a structured content part is present. Tries, in order:

    1. A content part's own `.parsed` attribute (present in some structured-output response
       shapes; not a field on the SDK's own `ResponseOutputText` type, so always read
       defensively via getattr - never assumed to exist).
    2. That same content part's `.text` field, parsed as JSON.
    3. `response.output_text`, parsed as JSON - last-resort fallback, kept for backward
       compatibility with responses that only ever populated this field.

    Returns a dict only. A value that parses successfully but is not a JSON object (a bare
    list/string/number), or a `.parsed` value that is not itself a dict, is treated exactly like
    "no structured output" - the §9.1 floor requires an object, never a partial/malformed
    substitute."""
    for item in getattr(response, "output", None) or []:
        for part in getattr(item, "content", None) or []:
            parsed = getattr(part, "parsed", None)
            if isinstance(parsed, dict):
                return parsed

            text = getattr(part, "text", None)
            if text:
                try:
                    candidate = json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    candidate = None
                if isinstance(candidate, dict):
                    return candidate

    text = getattr(response, "output_text", None)
    if text:
        try:
            candidate = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            candidate = None
        if isinstance(candidate, dict):
            return candidate

    return None


def _translate_response(response: Any, response_mode: str) -> GenerateResponse:
    tool_calls = _extract_tool_calls(response.output)
    finish_reason = _finish_reason(response, tool_calls)
    text = response.output_text or None

    structured_output: dict[str, Any] | None = None
    if response_mode == "json_schema":
        structured_output = _extract_structured_output(response)

    usage = response.usage
    return GenerateResponse(
        text=text,
        structured_output=structured_output,
        tool_calls=tool_calls or None,
        artifacts=None,
        finish_reason=finish_reason,
        model_used=response.model,
        usage=CapabilityUsage(
            input_tokens=usage.input_tokens if usage is not None else None,
            output_tokens=usage.output_tokens if usage is not None else None,
            # API cost optimization: defensive getattr chains - never invented, only extracted
            # when the real response actually reports them (some SDK/response shapes omit the
            # nested *_details objects entirely, e.g. a non-reasoning-tier response).
            cached_input_tokens=_get_nested(usage, "input_tokens_details", "cached_tokens"),
            reasoning_tokens=_get_nested(usage, "output_tokens_details", "reasoning_tokens"),
        ),
    )


def _get_nested(obj: Any, *attrs: str) -> int | None:
    for attr in attrs:
        if obj is None:
            return None
        obj = getattr(obj, attr, None)
    return obj if isinstance(obj, int) else None


class OpenAIAdapter:
    """LLMGateway implementation scoped to the OpenAI SDK (§2 P12 - not a distinct Protocol).

    Holds one persistent AsyncOpenAI client per instance (§2 rule 6), constructed once here,
    reused across every generate() call - never a new client per request.
    """

    def __init__(self, credential: ProviderCredential, *, client: AsyncOpenAI | None = None) -> None:
        self._api_key = credential.api_key.get_secret_value() if credential.api_key is not None else None
        self._client = client if client is not None else AsyncOpenAI(api_key=self._api_key, base_url=credential.base_url)

    def _resolve_model_id(self, request: GenerateRequest) -> str:
        resolved = request.metadata.get("resolved_model_id")
        if resolved:
            return str(resolved)
        if request.preferred_model:
            return request.preferred_model
        raise ProviderPermanentIncompatibleError(
            "openai adapter: cannot determine which model to call - GenerateRequest carries "
            "neither metadata['resolved_model_id'] (normally set by FallbackPolicy before "
            "dispatch, see this module's docstring) nor a preferred_model hint"
        )

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        model_id = self._resolve_model_id(request)
        payload = _build_payload(request, model_id)
        started = time.monotonic()
        try:
            response = await self._client.responses.create(**payload)
        except openai.OpenAIError as exc:
            # asyncio.CancelledError is a BaseException, never an OpenAIError - it is not
            # caught here and propagates unchanged (requirement 8), exactly as with the
            # equivalent try/except in fallback/policy.py's _attempt_candidate.
            raise _translate_exception(exc, self._api_key) from None
        elapsed_ms = (time.monotonic() - started) * 1000
        logger.info(
            "latency",
            extra={
                "boundary": "provider_http",
                "provider_id": OPENAI_PROVIDER_ID,
                "model_id": model_id,
                "attempt_latency_ms": elapsed_ms,
            },
        )
        return _translate_response(response, request.response_mode)

    async def generate_stream(self, request: GenerateRequest) -> AsyncIterator[GenerateChunk]:
        raise UnsupportedGatewayCapabilityError(
            "openai: generate_stream() is deferred past this delivery (M18 scope: generate() only)"
        )
        yield  # pragma: no cover - unreachable; keeps this an async generator for typing

    async def embed(self, request: EmbedRequest) -> EmbedResponse:
        raise UnsupportedGatewayCapabilityError(
            "openai: embed() is deferred past this delivery (M18 scope: generate() only)"
        )

    async def classify(self, request: ClassifyRequest) -> ClassifyResponse:
        raise UnsupportedGatewayCapabilityError(
            "openai: classify() is deferred past this delivery (M18 scope: generate() only)"
        )

    async def moderate(self, request: ModerateRequest) -> ModerateResponse:
        raise UnsupportedGatewayCapabilityError(
            "openai: moderate() is deferred past this delivery (M18 scope: generate() only)"
        )

    async def rerank(self, request: RerankRequest) -> RerankResponse:
        raise UnsupportedGatewayCapabilityError(
            "openai: rerank() is deferred past this delivery (M18 scope: generate() only)"
        )


def build_openai_provider_factory() -> ProviderFactory:
    """Ready for M19's `assemble_ai_integration_layer()` to pass to `build_provider_registry()`
    - not itself wired into any real boot sequence yet (that's M19's job, §19 rule 3)."""
    return ProviderFactory(
        descriptor=ProviderDescriptor(provider_id=OPENAI_PROVIDER_ID, display_name="OpenAI"),
        build_credential=build_openai_credential,
        build_adapter=lambda credential: OpenAIAdapter(credential),
    )
