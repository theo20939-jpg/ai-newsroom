"""OpenAIAdapter tests (docs/phase7_architecture_contract.md §2, §20.1 step 2 - "the same shape
of assertions" as tests/contract/test_provider_adapter_contract.py, applied here against a
mocked OpenAI transport instead of FakeProviderAdapter, per that file's own docstring).

No real network call anywhere in this file - every test either constructs an OpenAIAdapter with
an injected mock `AsyncOpenAI`-shaped client (an AsyncMock whose `.responses.create` is
configured per test), or exercises pure translation helpers directly. Fake responses are built
from the REAL, installed `openai` SDK's own Pydantic response types (`Response.model_construct`,
`ResponseUsage`, etc.) - an "official SDK-compatible fake," not an invented shape - so a
translation bug that only manifests against the real type structure would still be caught here.
"""
import asyncio
from typing import Any
from unittest.mock import AsyncMock

import httpx
import openai
import pytest
from openai import AsyncOpenAI
from openai.types.responses.response import IncompleteDetails, Response
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText
from openai.types.responses.response_usage import InputTokensDetails, OutputTokensDetails, ResponseUsage

from integrations.llm_gateway.errors import (
    ProviderModerationBlockedError,
    ProviderPermanentIncompatibleError,
    ProviderRegionalUnavailableError,
    ProviderTransientError,
)
from integrations.llm_gateway.protocol import (
    ClassifyRequest,
    ContentPart,
    EmbedRequest,
    GenerateRequest,
    GenerateResponse,
    Message,
    ModerateRequest,
    RerankRequest,
    ToolDefinition,
    UnsupportedGatewayCapabilityError,
)
from integrations.llm_gateway.providers.base import ProviderCredential
from integrations.llm_gateway.providers.openai_adapter import OpenAIAdapter, build_openai_provider_factory
from integrations.llm_gateway.routing.criteria import RoutingCriteria
from integrations.llm_gateway.models.registry import ModelDescriptor


def _usage(input_tokens: int = 10, output_tokens: int = 5) -> ResponseUsage:
    return ResponseUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        input_tokens_details=InputTokensDetails(cached_tokens=0, cache_write_tokens=0),
        output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
    )


def _text_response(
    text: str = "hello from openai",
    *,
    model: str = "gpt-5.6-terra",
    status: str = "completed",
    incomplete_details: IncompleteDetails | None = None,
    usage: ResponseUsage | None = None,
) -> Response:
    message = ResponseOutputMessage(
        id="msg_1",
        type="message",
        role="assistant",
        status="completed",
        content=[ResponseOutputText(type="output_text", text=text, annotations=[])],
    )
    return Response.model_construct(
        id="resp_1",
        created_at=0.0,
        error=None,
        incomplete_details=incomplete_details,
        instructions=None,
        metadata=None,
        model=model,
        object="response",
        output=[message],
        parallel_tool_calls=True,
        temperature=None,
        tool_choice="auto",
        tools=[],
        top_p=None,
        status=status,
        text=None,
        usage=usage or _usage(),
    )


def _tool_call_response(
    *, name: str = "search", arguments: str = '{"query": "hi"}', model: str = "gpt-5.6-terra"
) -> Response:
    call = ResponseFunctionToolCall(type="function_call", call_id="call_1", name=name, arguments=arguments)
    return Response.model_construct(
        id="resp_2",
        created_at=0.0,
        error=None,
        incomplete_details=None,
        instructions=None,
        metadata=None,
        model=model,
        object="response",
        output=[call],
        parallel_tool_calls=True,
        temperature=None,
        tool_choice="auto",
        tools=[],
        top_p=None,
        status="completed",
        text=None,
        usage=_usage(),
    )


def _mock_client(response: Response | BaseException) -> AsyncOpenAI:
    client = AsyncMock(spec=AsyncOpenAI)
    if isinstance(response, BaseException):
        client.responses.create = AsyncMock(side_effect=response)
    else:
        client.responses.create = AsyncMock(return_value=response)
    return client


def _credential(api_key: str = "sk-test-fake-key-0123456789") -> ProviderCredential:
    return ProviderCredential(api_key=api_key)  # type: ignore[arg-type]


def _request(**metadata: Any) -> GenerateRequest:
    return GenerateRequest(
        messages=[Message(role="user", content=[ContentPart(type="text", text="hello")])],
        metadata=metadata,
    )


def _bad_request_error(code: str, message: str = "bad request") -> openai.BadRequestError:
    req = httpx.Request("POST", "https://api.openai.com/v1/responses")
    resp = httpx.Response(400, request=req, json={"error": {"message": message, "code": code}})
    return openai.BadRequestError(message, response=resp, body={"message": message, "code": code})


def _status_error(cls: type, status_code: int, message: str = "error") -> Exception:
    req = httpx.Request("POST", "https://api.openai.com/v1/responses")
    resp = httpx.Response(status_code, request=req, json={"error": {"message": message}})
    return cls(message, response=resp, body={"message": message})


# ---------------------------------------------------------------------------
# Successful generation, request translation, response translation, usage/model mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_text_generation() -> None:
    client = _mock_client(_text_response("hi there"))
    adapter = OpenAIAdapter(_credential(), client=client)

    response = await adapter.generate(_request(resolved_model_id="gpt-5.6-terra"))

    assert isinstance(response, GenerateResponse)
    assert response.text == "hi there"
    assert response.finish_reason == "stop"
    assert response.model_used == "gpt-5.6-terra"


@pytest.mark.asyncio
async def test_request_translation_builds_correct_payload() -> None:
    client = _mock_client(_text_response())
    adapter = OpenAIAdapter(_credential(), client=client)
    request = GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text="be terse")]),
            Message(role="user", content=[ContentPart(type="text", text="hello")]),
        ],
        max_tokens=256,
        temperature=0.5,
        tools=[ToolDefinition(name="search", description="search the web", parameters_schema={"type": "object"})],
        tool_choice="auto",
        metadata={"resolved_model_id": "gpt-5.6-sol"},
    )

    await adapter.generate(request)

    kwargs = client.responses.create.call_args.kwargs
    assert kwargs["model"] == "gpt-5.6-sol"
    assert kwargs["max_output_tokens"] == 256
    assert kwargs["temperature"] == 0.5
    assert kwargs["input"] == [
        {"role": "system", "content": [{"type": "input_text", "text": "be terse"}]},
        {"role": "user", "content": [{"type": "input_text", "text": "hello"}]},
    ]
    assert kwargs["tools"] == [
        {
            "type": "function",
            "name": "search",
            "description": "search the web",
            "parameters": {"type": "object"},
            "strict": False,
        }
    ]
    assert kwargs["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_response_translation_maps_tool_calls_and_finish_reason() -> None:
    client = _mock_client(_tool_call_response(name="search", arguments='{"query": "cats"}'))
    adapter = OpenAIAdapter(_credential(), client=client)

    response = await adapter.generate(_request(resolved_model_id="gpt-5.6-terra"))

    assert response.finish_reason == "tool_calls"
    assert response.tool_calls is not None
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "search"
    assert response.tool_calls[0].arguments == {"query": "cats"}


@pytest.mark.asyncio
async def test_response_translation_maps_length_and_content_filter() -> None:
    client_length = _mock_client(
        _text_response("truncated", incomplete_details=IncompleteDetails(reason="max_output_tokens"), status="incomplete")
    )
    adapter_length = OpenAIAdapter(_credential(), client=client_length)
    response_length = await adapter_length.generate(_request(resolved_model_id="gpt-5.6-luna"))
    assert response_length.finish_reason == "length"

    client_filtered = _mock_client(
        _text_response("", incomplete_details=IncompleteDetails(reason="content_filter"), status="incomplete")
    )
    adapter_filtered = OpenAIAdapter(_credential(), client=client_filtered)
    response_filtered = await adapter_filtered.generate(_request(resolved_model_id="gpt-5.6-luna"))
    assert response_filtered.finish_reason == "content_filter"


@pytest.mark.asyncio
async def test_usage_mapping() -> None:
    client = _mock_client(_text_response(usage=_usage(input_tokens=123, output_tokens=45)))
    adapter = OpenAIAdapter(_credential(), client=client)

    response = await adapter.generate(_request(resolved_model_id="gpt-5.6-terra"))

    assert response.usage.input_tokens == 123
    assert response.usage.output_tokens == 45


@pytest.mark.asyncio
async def test_model_mapping_prefers_resolved_model_id_over_preferred_model() -> None:
    client = _mock_client(_text_response(model="gpt-5.6-sol"))
    adapter = OpenAIAdapter(_credential(), client=client)
    request = GenerateRequest(
        messages=[Message(role="user", content=[ContentPart(type="text", text="hi")])],
        preferred_model="gpt-5.6-luna",
        metadata={"resolved_model_id": "gpt-5.6-sol"},
    )

    response = await adapter.generate(request)

    assert client.responses.create.call_args.kwargs["model"] == "gpt-5.6-sol"
    assert response.model_used == "gpt-5.6-sol"  # from the response itself, not re-derived


@pytest.mark.asyncio
async def test_model_mapping_falls_back_to_preferred_model_without_resolved_metadata() -> None:
    client = _mock_client(_text_response(model="gpt-5.6-luna"))
    adapter = OpenAIAdapter(_credential(), client=client)
    request = GenerateRequest(
        messages=[Message(role="user", content=[ContentPart(type="text", text="hi")])],
        preferred_model="gpt-5.6-luna",
    )

    await adapter.generate(request)

    assert client.responses.create.call_args.kwargs["model"] == "gpt-5.6-luna"


@pytest.mark.asyncio
async def test_model_mapping_raises_when_no_model_can_be_determined() -> None:
    client = _mock_client(_text_response())
    adapter = OpenAIAdapter(_credential(), client=client)
    request = GenerateRequest(messages=[Message(role="user", content=[ContentPart(type="text", text="hi")])])

    with pytest.raises(ProviderPermanentIncompatibleError):
        await adapter.generate(request)
    client.responses.create.assert_not_called()


# ---------------------------------------------------------------------------
# Metadata mapping: resolved_model_id/resolved_provider_id is the channel FallbackPolicy uses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metadata_resolved_model_id_drives_dispatch_target() -> None:
    client = _mock_client(_text_response(model="gpt-5.6-luna"))
    adapter = OpenAIAdapter(_credential(), client=client)

    await adapter.generate(_request(resolved_model_id="gpt-5.6-luna", resolved_provider_id="openai"))

    assert client.responses.create.call_args.kwargs["model"] == "gpt-5.6-luna"


# ---------------------------------------------------------------------------
# Persistent client reuse
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persistent_client_reused_across_calls() -> None:
    client = _mock_client(_text_response())
    adapter = OpenAIAdapter(_credential(), client=client)

    await adapter.generate(_request(resolved_model_id="gpt-5.6-terra"))
    await adapter.generate(_request(resolved_model_id="gpt-5.6-terra"))

    assert adapter._client is client  # the same instance held across both calls, never rebuilt
    assert client.responses.create.await_count == 2


def test_constructor_builds_exactly_one_client_when_none_injected(monkeypatch: pytest.MonkeyPatch) -> None:
    build_calls: list[dict[str, Any]] = []

    class _RecordingAsyncOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            build_calls.append(kwargs)

    monkeypatch.setattr("integrations.llm_gateway.providers.openai_adapter.AsyncOpenAI", _RecordingAsyncOpenAI)

    OpenAIAdapter(_credential(api_key="sk-construct-test-key"))

    assert len(build_calls) == 1
    assert build_calls[0]["api_key"] == "sk-construct-test-key"


# ---------------------------------------------------------------------------
# Unsupported (deferred) methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_stream_raises_unsupported() -> None:
    adapter = OpenAIAdapter(_credential(), client=_mock_client(_text_response()))
    with pytest.raises(UnsupportedGatewayCapabilityError):
        async for _ in adapter.generate_stream(_request()):
            pass


@pytest.mark.asyncio
async def test_embed_raises_unsupported() -> None:
    adapter = OpenAIAdapter(_credential(), client=_mock_client(_text_response()))
    with pytest.raises(UnsupportedGatewayCapabilityError):
        await adapter.embed(EmbedRequest(inputs=["hi"]))


@pytest.mark.asyncio
async def test_classify_raises_unsupported() -> None:
    adapter = OpenAIAdapter(_credential(), client=_mock_client(_text_response()))
    with pytest.raises(UnsupportedGatewayCapabilityError):
        await adapter.classify(ClassifyRequest(input="hi", labels=["a", "b"]))


@pytest.mark.asyncio
async def test_moderate_raises_unsupported() -> None:
    adapter = OpenAIAdapter(_credential(), client=_mock_client(_text_response()))
    with pytest.raises(UnsupportedGatewayCapabilityError):
        await adapter.moderate(ModerateRequest(input="hi"))


@pytest.mark.asyncio
async def test_rerank_raises_unsupported() -> None:
    adapter = OpenAIAdapter(_credential(), client=_mock_client(_text_response()))
    with pytest.raises(UnsupportedGatewayCapabilityError):
        await adapter.rerank(RerankRequest(query="hi", documents=["a", "b"]))


# ---------------------------------------------------------------------------
# Exception translation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_error_translates_to_provider_transient_error() -> None:
    client = _mock_client(_status_error(openai.RateLimitError, 429))
    adapter = OpenAIAdapter(_credential(), client=client)
    with pytest.raises(ProviderTransientError):
        await adapter.generate(_request(resolved_model_id="gpt-5.6-terra"))


@pytest.mark.asyncio
async def test_internal_server_error_translates_to_provider_transient_error() -> None:
    client = _mock_client(_status_error(openai.InternalServerError, 500))
    adapter = OpenAIAdapter(_credential(), client=client)
    with pytest.raises(ProviderTransientError):
        await adapter.generate(_request(resolved_model_id="gpt-5.6-terra"))


@pytest.mark.asyncio
async def test_authentication_error_translates_to_provider_transient_error() -> None:
    """§5.2's own wording: "auth (this attempt only)" is classified TRANSIENT, not permanent."""
    client = _mock_client(_status_error(openai.AuthenticationError, 401))
    adapter = OpenAIAdapter(_credential(), client=client)
    with pytest.raises(ProviderTransientError):
        await adapter.generate(_request(resolved_model_id="gpt-5.6-terra"))


@pytest.mark.asyncio
async def test_connection_error_translates_to_provider_transient_error() -> None:
    req = httpx.Request("POST", "https://api.openai.com/v1/responses")
    client = _mock_client(openai.APIConnectionError(request=req))
    adapter = OpenAIAdapter(_credential(), client=client)
    with pytest.raises(ProviderTransientError):
        await adapter.generate(_request(resolved_model_id="gpt-5.6-terra"))


@pytest.mark.asyncio
async def test_timeout_error_translates_to_provider_transient_error() -> None:
    req = httpx.Request("POST", "https://api.openai.com/v1/responses")
    client = _mock_client(openai.APITimeoutError(request=req))
    adapter = OpenAIAdapter(_credential(), client=client)
    with pytest.raises(ProviderTransientError):
        await adapter.generate(_request(resolved_model_id="gpt-5.6-terra"))


@pytest.mark.asyncio
async def test_permission_denied_error_translates_to_provider_regional_unavailable_error() -> None:
    """Phase 15 runtime reliability fix: split out from ProviderPermanentIncompatibleError - a
    403 is regional/account-scoped, not a genuinely permanent model/schema misconfiguration (see
    ProviderRegionalUnavailableError's own docstring and docs/phase15_runtime_reliability_
    report.md)."""
    client = _mock_client(_status_error(openai.PermissionDeniedError, 403))
    adapter = OpenAIAdapter(_credential(), client=client)
    with pytest.raises(ProviderRegionalUnavailableError):
        await adapter.generate(_request(resolved_model_id="gpt-5.6-terra"))


@pytest.mark.asyncio
async def test_not_found_error_translates_to_provider_permanent_incompatible_error() -> None:
    client = _mock_client(_status_error(openai.NotFoundError, 404))
    adapter = OpenAIAdapter(_credential(), client=client)
    with pytest.raises(ProviderPermanentIncompatibleError):
        await adapter.generate(_request(resolved_model_id="gpt-5.6-terra"))


@pytest.mark.asyncio
async def test_bad_request_error_translates_to_provider_permanent_incompatible_error() -> None:
    client = _mock_client(_bad_request_error("invalid_request", "malformed request"))
    adapter = OpenAIAdapter(_credential(), client=client)
    with pytest.raises(ProviderPermanentIncompatibleError):
        await adapter.generate(_request(resolved_model_id="gpt-5.6-terra"))


@pytest.mark.asyncio
async def test_moderation_error_code_translates_to_provider_moderation_blocked_error() -> None:
    client = _mock_client(_bad_request_error("invalid_prompt", "blocked by safety system"))
    adapter = OpenAIAdapter(_credential(), client=client)
    with pytest.raises(ProviderModerationBlockedError):
        await adapter.generate(_request(resolved_model_id="gpt-5.6-terra"))


@pytest.mark.asyncio
async def test_no_raw_openai_exception_crosses_the_boundary() -> None:
    client = _mock_client(_status_error(openai.RateLimitError, 429))
    adapter = OpenAIAdapter(_credential(), client=client)
    with pytest.raises(Exception) as excinfo:
        await adapter.generate(_request(resolved_model_id="gpt-5.6-terra"))
    assert not isinstance(excinfo.value, openai.OpenAIError)


# ---------------------------------------------------------------------------
# Credential redaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_credential_redaction_strips_api_key_from_translated_exception() -> None:
    secret = "sk-super-secret-value-should-never-leak-000111"
    req = httpx.Request("POST", "https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {secret}"})
    resp = httpx.Response(
        500, request=req, json={"error": {"message": f"upstream saw Authorization: Bearer {secret}"}}
    )
    exc = openai.InternalServerError(
        f"upstream saw Authorization: Bearer {secret}", response=resp, body={"message": "..."}
    )
    client = _mock_client(exc)
    adapter = OpenAIAdapter(_credential(api_key=secret), client=client)

    with pytest.raises(ProviderTransientError) as excinfo:
        await adapter.generate(_request(resolved_model_id="gpt-5.6-terra"))

    assert secret not in str(excinfo.value)
    assert "REDACTED" in str(excinfo.value)


@pytest.mark.asyncio
async def test_credential_redaction_strips_generic_bearer_pattern_even_without_exact_key_match() -> None:
    """Defense-in-depth: redact a Bearer-header-shaped substring even if it isn't literally
    this adapter's own configured key (e.g. an upstream proxy echoing a different token)."""
    req = httpx.Request("POST", "https://api.openai.com/v1/responses")
    resp = httpx.Response(500, request=req, json={"error": {"message": "saw Authorization: Bearer sk-someothertoken123456"}})
    exc = openai.InternalServerError(
        "saw Authorization: Bearer sk-someothertoken123456", response=resp, body={"message": "..."}
    )
    client = _mock_client(exc)
    adapter = OpenAIAdapter(_credential(api_key="sk-this-adapters-own-key-abcdef"), client=client)

    with pytest.raises(ProviderTransientError) as excinfo:
        await adapter.generate(_request(resolved_model_id="gpt-5.6-terra"))

    assert "sk-someothertoken123456" not in str(excinfo.value)
    assert "Bearer [REDACTED]" in str(excinfo.value) or "[REDACTED]" in str(excinfo.value)


# ---------------------------------------------------------------------------
# asyncio.CancelledError propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancelled_error_propagates_unchanged() -> None:
    client = _mock_client(asyncio.CancelledError())
    adapter = OpenAIAdapter(_credential(), client=client)

    with pytest.raises(asyncio.CancelledError):
        await adapter.generate(_request(resolved_model_id="gpt-5.6-terra"))


# ---------------------------------------------------------------------------
# No OpenAI-specific leakage into shared schemas; Protocol/contract compatibility
# ---------------------------------------------------------------------------


def test_no_openai_specific_fields_on_shared_schemas() -> None:
    """§2 rule 1 / P11: provider-neutral schemas must carry no provider-specific field.
    A regression here (someone adding e.g. `openai_response_id` to GenerateResponse) would
    fail this exact assertion."""
    assert set(GenerateRequest.model_fields.keys()) == {
        "messages",
        "preferred_model",
        "preferred_provider",
        "max_tokens",
        "temperature",
        "tools",
        "tool_choice",
        "response_mode",
        "response_schema",
        "modalities",
        "metadata",
    }
    assert set(GenerateResponse.model_fields.keys()) == {
        "text",
        "structured_output",
        "tool_calls",
        "artifacts",
        "finish_reason",
        "model_used",
        "usage",
    }
    assert set(RoutingCriteria.model_fields.keys()) == {
        "gateway_method",
        "capability_name",
        "priority",
        "requires_tools",
        "requires_vision",
        "requires_streaming",
        "requires_structured_output",
        "input_image_count",
        "input_pdf_page_count",
        "preferred_model",
        "preferred_provider",
        "excluded_providers",
        "objective",
        "cost_ceiling",
        "fallback",
    }
    assert set(ModelDescriptor.model_fields.keys()) == {
        "model_id",
        "provider_id",
        "display_name",
        "context_window_tokens",
        "max_output_tokens",
        "supports_tools",
        "supports_streaming",
        "supports_vision",
        "supports_structured_output",
        "supports_embeddings",
        "embedding_dimension",
        "max_images_per_request",
        "max_file_size_mb",
        "max_pdf_pages",
        "reasoning_tier",
        "quality_tier",
        "pricing_tiers",
        "pricing_currency",
        "availability",
        "deprecation_note",
        "replacement_model_id",
    }


@pytest.mark.asyncio
async def test_adapter_satisfies_llm_gateway_protocol_shape() -> None:
    """Runtime structural check mirroring tests/contract/test_provider_adapter_contract.py's
    "same shape of assertions" against a real, mocked-transport adapter instead of the fake."""
    adapter = OpenAIAdapter(_credential(), client=_mock_client(_text_response()))

    assert asyncio.iscoroutinefunction(adapter.generate)
    assert asyncio.iscoroutinefunction(adapter.embed)
    assert asyncio.iscoroutinefunction(adapter.classify)
    assert asyncio.iscoroutinefunction(adapter.moderate)
    assert asyncio.iscoroutinefunction(adapter.rerank)
    assert not asyncio.iscoroutinefunction(adapter.generate_stream)  # an async generator function

    response = await adapter.generate(_request(resolved_model_id="gpt-5.6-terra"))
    assert isinstance(response, GenerateResponse)  # real Pydantic validation, not a stub shape


def test_build_openai_provider_factory_produces_a_working_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "integrations.llm_gateway.providers.openai_adapter.AsyncOpenAI",
        lambda **kwargs: _mock_client(_text_response()),
    )
    factory = build_openai_provider_factory()

    assert factory.descriptor.provider_id == "openai"
    adapter = factory.build_adapter(_credential())
    assert isinstance(adapter, OpenAIAdapter)
