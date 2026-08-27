"""Phase V2.1 - GeminiImageAdapter tests. NO real network call anywhere in this file - the
`httpx.AsyncClient` is always a test double injected via the adapter's own `client=` constructor
parameter, never a real client."""
from __future__ import annotations

import base64
import json

import httpx
import pytest

from integrations.llm_gateway.image_protocol import (
    ImageGenerationOperation,
    ImageGenerationRequest,
    ReferenceImage,
)
from integrations.llm_gateway.providers.gemini_image_adapter import (
    GEMINI_3_1_FLASH_IMAGE,
    GEMINI_3_PRO_IMAGE,
    GeminiImageAdapter,
    GeminiImageAdapterError,
    _INTERACTIONS_ENDPOINT,
)

_SOURCE_PNG = b"\x89PNG\r\n\x1a\n" + b"source-bytes" * 5
_OUTPUT_PNG_B64 = base64.b64encode(b"fake-output-png-bytes").decode("ascii")


def _edit_request(prompt: str = "recompose this hero product shot") -> ImageGenerationRequest:
    return ImageGenerationRequest(
        prompt=prompt, operation=ImageGenerationOperation.IMAGE_EDIT,
        reference_images=(ReferenceImage(data=_SOURCE_PNG, mime_type="image/png"),),
        target_aspect_ratio="16:9",
    )


class _CapturingTransport:
    """Records the outgoing request and returns a canned response via httpx.MockTransport - the
    repo's own established Phase 18.9-R Barrier 3 convention (tests/conftest.py) recognizes ONLY
    `isinstance(client._transport, httpx.MockTransport)` as safe; a custom AsyncBaseTransport
    subclass is correctly blocked as real network egress."""

    def __init__(self, response_json: dict, status_code: int = 200) -> None:
        self.captured_request: httpx.Request | None = None
        self._response_json = response_json
        self._status_code = status_code

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.captured_request = request
        return httpx.Response(self._status_code, json=self._response_json, request=request)


def _client_for(transport: _CapturingTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(transport.handler))


@pytest.mark.asyncio
async def test_shared_adapter_works_for_both_model_ids() -> None:
    for model_id in (GEMINI_3_1_FLASH_IMAGE, GEMINI_3_PRO_IMAGE):
        transport = _CapturingTransport({"id": "int-123", "output_image": {"data": _OUTPUT_PNG_B64, "mime_type": "image/png"}})
        adapter = GeminiImageAdapter(model_id=model_id, api_key="fake-key", client=_client_for(transport))
        response = await adapter.generate_image(_edit_request())
        assert response.model_used == model_id
        assert response.provider == "gemini"


def test_rejects_unsupported_model_id() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        GeminiImageAdapter(model_id="gemini-1.5-flash", api_key="fake-key")


@pytest.mark.asyncio
async def test_source_image_bytes_and_mime_preserved_in_request() -> None:
    transport = _CapturingTransport({"id": "int-1", "output_image": {"data": _OUTPUT_PNG_B64, "mime_type": "image/png"}})
    adapter = GeminiImageAdapter(model_id=GEMINI_3_1_FLASH_IMAGE, api_key="fake-key", client=_client_for(transport))

    await adapter.generate_image(_edit_request())

    assert transport.captured_request is not None
    body = json.loads(transport.captured_request.content)
    image_blocks = [b for b in body["input"] if b["type"] == "image"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["mime_type"] == "image/png"
    assert base64.b64decode(image_blocks[0]["data"]) == _SOURCE_PNG


@pytest.mark.asyncio
async def test_prompt_preserved_in_request() -> None:
    transport = _CapturingTransport({"id": "int-1", "output_image": {"data": _OUTPUT_PNG_B64, "mime_type": "image/png"}})
    adapter = GeminiImageAdapter(model_id=GEMINI_3_1_FLASH_IMAGE, api_key="fake-key", client=_client_for(transport))

    await adapter.generate_image(_edit_request(prompt="a very specific instruction"))

    assert transport.captured_request is not None
    body = json.loads(transport.captured_request.content)
    text_blocks = [b for b in body["input"] if b["type"] == "text"]
    assert text_blocks[0]["text"] == "a very specific instruction"


@pytest.mark.asyncio
async def test_api_key_sent_as_header_never_query_param() -> None:
    transport = _CapturingTransport({"id": "int-1", "output_image": {"data": _OUTPUT_PNG_B64, "mime_type": "image/png"}})
    adapter = GeminiImageAdapter(model_id=GEMINI_3_1_FLASH_IMAGE, api_key="super-secret-key", client=_client_for(transport))

    await adapter.generate_image(_edit_request())

    assert transport.captured_request is not None
    assert transport.captured_request.headers["x-goog-api-key"] == "super-secret-key"
    assert "super-secret-key" not in str(transport.captured_request.url)


@pytest.mark.asyncio
async def test_endpoint_url_matches_verified_interactions_api() -> None:
    transport = _CapturingTransport({"id": "int-1", "output_image": {"data": _OUTPUT_PNG_B64, "mime_type": "image/png"}})
    adapter = GeminiImageAdapter(model_id=GEMINI_3_1_FLASH_IMAGE, api_key="fake-key", client=_client_for(transport))

    await adapter.generate_image(_edit_request())

    assert transport.captured_request is not None
    assert str(transport.captured_request.url) == _INTERACTIONS_ENDPOINT


@pytest.mark.asyncio
async def test_response_mapped_correctly_snake_case_shape() -> None:
    transport = _CapturingTransport({"id": "int-abc", "output_image": {"data": _OUTPUT_PNG_B64, "mime_type": "image/png"}})
    adapter = GeminiImageAdapter(model_id=GEMINI_3_1_FLASH_IMAGE, api_key="fake-key", client=_client_for(transport))

    response = await adapter.generate_image(_edit_request())

    assert response.image_bytes == base64.b64decode(_OUTPUT_PNG_B64)
    assert response.request_id == "int-abc"
    assert response.cost_usd is None  # never invented


@pytest.mark.asyncio
async def test_response_mapped_correctly_camel_case_fallback_shape() -> None:
    """Defensive fallback for the residual response-casing uncertainty disclosed in the
    adapter's own module docstring."""
    transport = _CapturingTransport({"id": "int-xyz", "outputImage": {"data": _OUTPUT_PNG_B64, "mimeType": "image/png"}})
    adapter = GeminiImageAdapter(model_id=GEMINI_3_1_FLASH_IMAGE, api_key="fake-key", client=_client_for(transport))

    response = await adapter.generate_image(_edit_request())

    assert response.image_bytes == base64.b64decode(_OUTPUT_PNG_B64)


# --- Fail-open ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_response_missing_output_image_does_not_crash_uncaught() -> None:
    transport = _CapturingTransport({"id": "int-1", "unexpected": "shape"})
    adapter = GeminiImageAdapter(model_id=GEMINI_3_1_FLASH_IMAGE, api_key="fake-key", client=_client_for(transport))

    with pytest.raises(GeminiImageAdapterError):
        await adapter.generate_image(_edit_request())


@pytest.mark.asyncio
async def test_malformed_base64_in_response_raises_typed_error() -> None:
    transport = _CapturingTransport({"id": "int-1", "output_image": {"data": "not-valid-base64!!!", "mime_type": "image/png"}})
    adapter = GeminiImageAdapter(model_id=GEMINI_3_1_FLASH_IMAGE, api_key="fake-key", client=_client_for(transport))

    with pytest.raises(GeminiImageAdapterError):
        await adapter.generate_image(_edit_request())


@pytest.mark.asyncio
async def test_http_error_status_raises_typed_error_not_crashes() -> None:
    transport = _CapturingTransport({"error": "bad request"}, status_code=400)
    adapter = GeminiImageAdapter(model_id=GEMINI_3_1_FLASH_IMAGE, api_key="fake-key", client=_client_for(transport))

    with pytest.raises(GeminiImageAdapterError):
        await adapter.generate_image(_edit_request())


@pytest.mark.asyncio
async def test_transport_error_raises_typed_error() -> None:
    def _raising_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connection timed out", request=request)

    adapter = GeminiImageAdapter(
        model_id=GEMINI_3_1_FLASH_IMAGE, api_key="fake-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(_raising_handler)),
    )

    with pytest.raises(GeminiImageAdapterError):
        await adapter.generate_image(_edit_request())


# --- Capabilities ---------------------------------------------------------------------------


def test_capabilities_declare_image_edit_support() -> None:
    adapter = GeminiImageAdapter(model_id=GEMINI_3_1_FLASH_IMAGE, api_key="fake-key")
    assert adapter.CAPABILITIES.supports_image_edit is True
    assert adapter.CAPABILITIES.supports_text_to_image is True


# --- Security ---------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_source_bytes_never_appear_in_a_raised_error_message() -> None:
    transport = _CapturingTransport({"unexpected": "shape"})
    adapter = GeminiImageAdapter(model_id=GEMINI_3_1_FLASH_IMAGE, api_key="secret-api-key-value", client=_client_for(transport))

    with pytest.raises(GeminiImageAdapterError) as exc_info:
        await adapter.generate_image(_edit_request())

    message = str(exc_info.value)
    assert "secret-api-key-value" not in message
    assert b"source-bytes" not in message.encode("latin-1", errors="ignore")
