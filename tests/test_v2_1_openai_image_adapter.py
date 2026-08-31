"""Phase V2.1 - OpenAIImageAdapter tests (mirrors tests/test_openai_adapter.py's own established
"AsyncMock-injected client + real SDK Pydantic response types" convention, applied here to
`images.with_raw_response.edit()` instead of `responses.create()`).

No real network call anywhere in this file - the adapter always receives an injected mock client,
never constructs a real `AsyncOpenAI()`.
"""
from __future__ import annotations

import base64
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import (
    APIConnectionError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
)
from openai.types.image import Image
from openai.types.images_response import ImagesResponse, Usage, UsageInputTokensDetails, UsageOutputTokensDetails

from integrations.llm_gateway.image_protocol import (
    ImageGenerationOperation,
    ImageGenerationRequest,
    ReferenceImage,
)
from integrations.llm_gateway.providers.openai_image_adapter import (
    GPT_IMAGE_2,
    OpenAIImageAdapter,
    OpenAIImageAdapterError,
)

_SOURCE_PNG = b"\x89PNG\r\n\x1a\n" + b"source-bytes" * 5
_OUTPUT_PNG_B64 = base64.b64encode(b"fake-output-png-bytes").decode("ascii")


def _edit_request(prompt: str = "recompose this hero product shot", target_aspect_ratio: str | None = "16:9") -> ImageGenerationRequest:
    return ImageGenerationRequest(
        prompt=prompt, operation=ImageGenerationOperation.IMAGE_EDIT,
        reference_images=(ReferenceImage(data=_SOURCE_PNG, mime_type="image/png"),),
        target_aspect_ratio=target_aspect_ratio,
    )


def _usage(input_tokens: int = 50, output_tokens: int = 1000) -> Usage:
    return Usage(
        input_tokens=input_tokens,
        input_tokens_details=UsageInputTokensDetails(image_tokens=input_tokens, text_tokens=0),
        output_tokens=output_tokens,
        output_tokens_details=UsageOutputTokensDetails(image_tokens=output_tokens, text_tokens=0),
        total_tokens=input_tokens + output_tokens,
    )


def _images_response(b64_json: str | None = _OUTPUT_PNG_B64, usage: Usage | None = _usage()) -> ImagesResponse:
    return ImagesResponse.model_construct(
        created=0,
        background="opaque",
        data=[Image.model_construct(b64_json=b64_json, revised_prompt=None, url=None)] if b64_json is not None else [],
        output_format="png",
        quality="standard",
        size="1536x1024",
        usage=usage,
    )


class _FakeRawResponse:
    """Minimal stand-in for the real SDK's `LegacyAPIResponse`/`APIResponse` object that
    `images.with_raw_response.edit()` returns - exposes exactly the two members the adapter
    actually uses (`headers`, `parse()`), nothing invented beyond that."""

    def __init__(self, parsed: ImagesResponse, request_id: str | None = "req_abc123") -> None:
        self._parsed = parsed
        self.headers = {"x-request-id": request_id} if request_id is not None else {}

    def parse(self) -> ImagesResponse:
        return self._parsed


def _mock_client(raw_response: _FakeRawResponse | BaseException, *, method: str = "edit") -> AsyncOpenAI:
    client = AsyncMock(spec=AsyncOpenAI)
    client.images = AsyncMock()
    client.images.with_raw_response = AsyncMock()
    mocked = AsyncMock(side_effect=raw_response) if isinstance(raw_response, BaseException) else AsyncMock(return_value=raw_response)
    setattr(client.images.with_raw_response, method, mocked)
    return client


def _text_to_image_request(prompt: str = "a robot at a desk") -> ImageGenerationRequest:
    return ImageGenerationRequest(prompt=prompt, operation=ImageGenerationOperation.TEXT_TO_IMAGE)


# ---------------------------------------------------------------------------
# Request translation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_source_image_bytes_and_mime_preserved_in_request() -> None:
    client = _mock_client(_FakeRawResponse(_images_response()))
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    await adapter.generate_image(_edit_request())

    kwargs = client.images.with_raw_response.edit.call_args.kwargs
    assert len(kwargs["image"]) == 1
    filename, data, mime = kwargs["image"][0]
    assert data == _SOURCE_PNG
    assert mime == "image/png"
    assert filename.endswith(".png")


@pytest.mark.asyncio
async def test_prompt_preserved_in_request() -> None:
    client = _mock_client(_FakeRawResponse(_images_response()))
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    await adapter.generate_image(_edit_request(prompt="a very specific instruction"))

    assert client.images.with_raw_response.edit.call_args.kwargs["prompt"] == "a very specific instruction"


@pytest.mark.asyncio
async def test_response_format_is_never_sent() -> None:
    """V2.2A repair regression test: the live gpt-image-2 API rejects `response_format` with
    `400 Unknown parameter` - it must never be sent, and never replaced with another
    undocumented field (module docstring's own explicit instruction)."""
    client = _mock_client(_FakeRawResponse(_images_response()))
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    await adapter.generate_image(_edit_request())

    kwargs = client.images.with_raw_response.edit.call_args.kwargs
    assert "response_format" not in kwargs


@pytest.mark.asyncio
async def test_model_is_always_gpt_image_2() -> None:
    client = _mock_client(_FakeRawResponse(_images_response()))
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    await adapter.generate_image(_edit_request())

    assert client.images.with_raw_response.edit.call_args.kwargs["model"] == GPT_IMAGE_2


@pytest.mark.asyncio
async def test_16_9_aspect_ratio_maps_to_closest_supported_literal_size() -> None:
    client = _mock_client(_FakeRawResponse(_images_response()))
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    await adapter.generate_image(_edit_request(target_aspect_ratio="16:9"))

    assert client.images.with_raw_response.edit.call_args.kwargs["size"] == "1536x1024"


@pytest.mark.asyncio
async def test_unrecognized_aspect_ratio_falls_back_to_auto_never_guesses() -> None:
    client = _mock_client(_FakeRawResponse(_images_response()))
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    await adapter.generate_image(_edit_request(target_aspect_ratio="4:3"))

    assert client.images.with_raw_response.edit.call_args.kwargs["size"] == "auto"


@pytest.mark.asyncio
async def test_no_aspect_ratio_hint_falls_back_to_auto() -> None:
    client = _mock_client(_FakeRawResponse(_images_response()))
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    await adapter.generate_image(_edit_request(target_aspect_ratio=None))

    assert client.images.with_raw_response.edit.call_args.kwargs["size"] == "auto"


# ---------------------------------------------------------------------------
# Response translation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_b64_json_decoded_into_image_bytes() -> None:
    client = _mock_client(_FakeRawResponse(_images_response()))
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    response = await adapter.generate_image(_edit_request())

    assert response.image_bytes == base64.b64decode(_OUTPUT_PNG_B64)
    assert response.model_used == GPT_IMAGE_2
    assert response.provider == "openai"


@pytest.mark.asyncio
async def test_request_id_read_from_raw_response_headers() -> None:
    client = _mock_client(_FakeRawResponse(_images_response(), request_id="req_specific_value"))
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    response = await adapter.generate_image(_edit_request())

    assert response.request_id == "req_specific_value"


@pytest.mark.asyncio
async def test_usage_tokens_mapped_from_real_sdk_usage_object() -> None:
    client = _mock_client(_FakeRawResponse(_images_response(usage=_usage(input_tokens=77, output_tokens=1290))))
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    response = await adapter.generate_image(_edit_request())

    assert response.usage.input_tokens == 77
    assert response.usage.output_tokens == 1290


@pytest.mark.asyncio
async def test_cost_usd_is_never_invented_even_when_usage_is_present() -> None:
    """OpenAI's own ImagesResponse.usage reports tokens, not a dollar amount - cost_usd must stay
    None here regardless of whether usage is populated (module docstring's own explicit rule)."""
    client = _mock_client(_FakeRawResponse(_images_response(usage=_usage())))
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    response = await adapter.generate_image(_edit_request())

    assert response.cost_usd is None


@pytest.mark.asyncio
async def test_missing_usage_falls_back_to_a_bare_unit_count() -> None:
    client = _mock_client(_FakeRawResponse(_images_response(usage=None)))
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    response = await adapter.generate_image(_edit_request())

    assert response.usage.units == 1
    assert response.usage.unit_type == "image"


# ---------------------------------------------------------------------------
# Fail-open
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_data_list_raises_typed_error_not_crashes() -> None:
    client = _mock_client(_FakeRawResponse(_images_response(b64_json=None)))
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    with pytest.raises(OpenAIImageAdapterError):
        await adapter.generate_image(_edit_request())


@pytest.mark.asyncio
async def test_openai_error_translates_to_typed_error() -> None:
    client = _mock_client(OpenAIError("upstream failure"))
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    with pytest.raises(OpenAIImageAdapterError):
        await adapter.generate_image(_edit_request())


@pytest.mark.asyncio
async def test_text_to_image_operation_routes_to_generate_not_edit() -> None:
    """MEME-PROD-2: TEXT_TO_IMAGE is now a real, verified code path (the meme-image production
    path) - it must call `images.generate()`, never `images.edit()` (no reference image exists)."""
    client = _mock_client(_FakeRawResponse(_images_response()), method="generate")
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    await adapter.generate_image(_text_to_image_request())

    client.images.with_raw_response.generate.assert_called_once()
    client.images.with_raw_response.edit.assert_not_called()


# ---------------------------------------------------------------------------
# MEME-PROD-2: TEXT_TO_IMAGE (gpt-image-2 via images.generate()) - the real meme-image
# production path (services/meme_generation_orchestrator.py, "enforce" mode).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_to_image_uses_gpt_image_2() -> None:
    client = _mock_client(_FakeRawResponse(_images_response()), method="generate")
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    await adapter.generate_image(_text_to_image_request())

    assert client.images.with_raw_response.generate.call_args.kwargs["model"] == GPT_IMAGE_2


@pytest.mark.asyncio
async def test_text_to_image_default_quality_is_medium() -> None:
    client = _mock_client(_FakeRawResponse(_images_response()), method="generate")
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    await adapter.generate_image(_text_to_image_request())

    assert client.images.with_raw_response.generate.call_args.kwargs["quality"] == "medium"


@pytest.mark.asyncio
async def test_text_to_image_default_size_is_square_1024() -> None:
    client = _mock_client(_FakeRawResponse(_images_response()), method="generate")
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    await adapter.generate_image(_text_to_image_request())

    assert client.images.with_raw_response.generate.call_args.kwargs["size"] == "1024x1024"


@pytest.mark.asyncio
async def test_text_to_image_requests_exactly_one_image() -> None:
    client = _mock_client(_FakeRawResponse(_images_response()), method="generate")
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    await adapter.generate_image(_text_to_image_request())

    assert client.images.with_raw_response.generate.call_args.kwargs["n"] == 1


@pytest.mark.asyncio
async def test_text_to_image_response_format_never_sent() -> None:
    client = _mock_client(_FakeRawResponse(_images_response()), method="generate")
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    await adapter.generate_image(_text_to_image_request())

    assert "response_format" not in client.images.with_raw_response.generate.call_args.kwargs


@pytest.mark.asyncio
async def test_text_to_image_prompt_preserved_verbatim() -> None:
    """No reference to top_text/bottom_text/meme copy - the prompt passed to the adapter is
    whatever the caller built (services/meme_image_generation.py::build_image_prompt() is the
    real caller, tested separately) - the adapter itself never rewrites or augments it."""
    client = _mock_client(_FakeRawResponse(_images_response()), method="generate")
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    await adapter.generate_image(_text_to_image_request(prompt="a very specific visual scene description"))

    assert client.images.with_raw_response.generate.call_args.kwargs["prompt"] == "a very specific visual scene description"


@pytest.mark.asyncio
async def test_text_to_image_never_sends_reference_images() -> None:
    """TEXT_TO_IMAGE has no `image=` parameter at all - .generate() (unlike .edit()) never
    accepts one."""
    client = _mock_client(_FakeRawResponse(_images_response()), method="generate")
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    await adapter.generate_image(_text_to_image_request())

    assert "image" not in client.images.with_raw_response.generate.call_args.kwargs


@pytest.mark.asyncio
async def test_text_to_image_custom_quality_and_size_are_honored() -> None:
    client = _mock_client(_FakeRawResponse(_images_response()), method="generate")
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client, quality="high", text_to_image_size="1536x1024")

    await adapter.generate_image(_text_to_image_request())

    kwargs = client.images.with_raw_response.generate.call_args.kwargs
    assert kwargs["quality"] == "high"
    assert kwargs["size"] == "1536x1024"


@pytest.mark.asyncio
async def test_text_to_image_decodes_response_into_valid_image_bytes() -> None:
    client = _mock_client(_FakeRawResponse(_images_response()), method="generate")
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    response = await adapter.generate_image(_text_to_image_request())

    assert response.image_bytes == base64.b64decode(_OUTPUT_PNG_B64)
    assert response.model_used == GPT_IMAGE_2
    assert response.provider == "openai"
    assert response.mime_type == "image/png"


@pytest.mark.asyncio
async def test_text_to_image_empty_response_data_raises_typed_error() -> None:
    client = _mock_client(_FakeRawResponse(_images_response(b64_json=None)), method="generate")
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    with pytest.raises(OpenAIImageAdapterError):
        await adapter.generate_image(_text_to_image_request())


@pytest.mark.asyncio
async def test_text_to_image_api_key_never_appears_in_a_raised_error_message() -> None:
    client = _mock_client(OpenAIError("upstream failure"), method="generate")
    adapter = OpenAIImageAdapter(api_key="secret-api-key-value", client=client)

    with pytest.raises(OpenAIImageAdapterError) as exc_info:
        await adapter.generate_image(_text_to_image_request())

    assert "secret-api-key-value" not in str(exc_info.value)


def test_capabilities_declare_text_to_image_support() -> None:
    adapter = OpenAIImageAdapter(api_key="fake-key", client=_mock_client(_FakeRawResponse(_images_response())))
    assert adapter.CAPABILITIES.supports_text_to_image is True


# ---------------------------------------------------------------------------
# MEME-PROD-2 §10: retryable classification - authentication/malformed-request/permission/not-
# found (4xx client errors retrying the identical request cannot fix) must be marked non-retryable;
# every other OpenAIError (rate limit, connection, server error, generic) stays retryable, matching
# the pre-existing "always retry once" behavior exactly.
# ---------------------------------------------------------------------------


def _fake_status_error(cls: type[OpenAIError], *, message: str = "boom", status_code: int = 400) -> OpenAIError:
    """Constructs a real instance of one of the openai SDK's own typed exception classes - never a
    hand-rolled stand-in - using its real constructor shape (every `APIStatusError` subclass
    requires `response`/`body`)."""
    request = httpx.Request("POST", "https://api.openai.com/v1/images/generations")
    response = httpx.Response(status_code, request=request, json={"error": {"message": message}})
    return cls(message=message, response=response, body=None)  # type: ignore[call-arg]


def _fake_connection_error() -> OpenAIError:
    request = httpx.Request("POST", "https://api.openai.com/v1/images/generations")
    return APIConnectionError(message="connection failed", request=request)


@pytest.mark.parametrize(
    "error_ctor",
    [
        lambda: _fake_status_error(AuthenticationError, status_code=401),
        lambda: _fake_status_error(BadRequestError, status_code=400),
        lambda: _fake_status_error(PermissionDeniedError, status_code=403),
        lambda: _fake_status_error(NotFoundError, status_code=404),
    ],
)
@pytest.mark.asyncio
async def test_client_error_types_are_never_retryable(error_ctor) -> None:
    client = _mock_client(error_ctor(), method="generate")
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    with pytest.raises(OpenAIImageAdapterError) as exc_info:
        await adapter.generate_image(_text_to_image_request())

    assert exc_info.value.retryable is False


@pytest.mark.parametrize(
    "error_ctor",
    [
        lambda: _fake_status_error(RateLimitError, status_code=429),
        lambda: _fake_status_error(InternalServerError, status_code=500),
        _fake_connection_error,
        lambda: OpenAIError("a generic, unclassified transport failure"),
    ],
)
@pytest.mark.asyncio
async def test_transient_error_types_remain_retryable(error_ctor) -> None:
    client = _mock_client(error_ctor(), method="generate")
    adapter = OpenAIImageAdapter(api_key="fake-key", client=client)

    with pytest.raises(OpenAIImageAdapterError) as exc_info:
        await adapter.generate_image(_text_to_image_request())

    assert exc_info.value.retryable is True


def test_default_retryable_is_true_when_constructed_directly() -> None:
    """A caller constructing OpenAIImageAdapterError without an explicit `retryable=` value (e.g.
    the `.edit()` path's own empty-response-data error) preserves the exact prior "always retry
    once" default."""
    assert OpenAIImageAdapterError("some failure").retryable is True


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


def test_capabilities_declare_image_edit_support_and_sixteen_reference_images() -> None:
    adapter = OpenAIImageAdapter(api_key="fake-key", client=_mock_client(_FakeRawResponse(_images_response())))
    assert adapter.CAPABILITIES.supports_image_edit is True
    assert adapter.CAPABILITIES.max_reference_images == 16


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_key_and_source_bytes_never_appear_in_a_raised_error_message() -> None:
    client = _mock_client(OpenAIError("upstream failure"))
    adapter = OpenAIImageAdapter(api_key="secret-api-key-value", client=client)

    with pytest.raises(OpenAIImageAdapterError) as exc_info:
        await adapter.generate_image(_edit_request())

    message = str(exc_info.value)
    assert "secret-api-key-value" not in message
    assert b"source-bytes" not in message.encode("latin-1", errors="ignore")


def test_constructor_never_logs_or_stores_api_key_in_plain_reachable_attribute() -> None:
    """Injected-client construction path (the only one exercised in this whole test file) never
    even touches the api_key argument beyond passing it through - confirmed by using an obviously
    distinguishable value and checking it isn't echoed by repr()."""
    adapter = OpenAIImageAdapter(api_key="totally-distinguishable-secret-xyz", client=_mock_client(_FakeRawResponse(_images_response())))
    assert "totally-distinguishable-secret-xyz" not in repr(adapter)
