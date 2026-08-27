"""Phase V2.2A - Gemini adapter response-parsing repair tests (docs/phase_v2_2a_protocol_repair_
and_smoke_report.md). Covers the exact real response shapes discovered by the first live V2.2
bake-off attempt (a `steps`-based async-job-shaped Interactions API response, not the
`output_image` convenience field the V2.1 adapter incorrectly assumed as primary).

No real network call anywhere in this file - every test uses `httpx.MockTransport` (the repo's
own Barrier-3 convention, tests/conftest.py) injected via the adapter's own `client=` constructor
parameter."""
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
from integrations.llm_gateway.providers import gemini_image_adapter as gemini_image_adapter_module
from integrations.llm_gateway.providers.gemini_image_adapter import (
    GEMINI_3_1_FLASH_IMAGE,
    GeminiImageAdapter,
    GeminiImageAdapterError,
)

_SOURCE_PNG = b"\x89PNG\r\n\x1a\n" + b"source-bytes" * 5
_OUTPUT_PNG_B64 = base64.b64encode(b"fake-output-png-bytes").decode("ascii")


def _edit_request() -> ImageGenerationRequest:
    return ImageGenerationRequest(
        prompt="recompose this hero product shot", operation=ImageGenerationOperation.IMAGE_EDIT,
        reference_images=(ReferenceImage(data=_SOURCE_PNG, mime_type="image/png"),),
        target_aspect_ratio="16:9",
    )


def _model_output_step(content: list[dict]) -> dict:
    return {"type": "model_output", "content": content}


def _image_content_block(data_b64: str = _OUTPUT_PNG_B64, mime_type: str = "image/png") -> dict:
    return {"type": "image", "data": data_b64, "mime_type": mime_type}


class _SequencedTransport:
    """Returns one canned response per call, in order - used to simulate a POST followed by one
    or more polling GETs. Each entry is (status_code, json_body)."""

    def __init__(self, responses: list[tuple[int, dict]]) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status_code, body = self._responses.pop(0)
        return httpx.Response(status_code, json=body, request=request)


def _client_for(transport: _SequencedTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(transport.handler))


def _adapter(transport: _SequencedTransport) -> GeminiImageAdapter:
    return GeminiImageAdapter(model_id=GEMINI_3_1_FLASH_IMAGE, api_key="fake-key", client=_client_for(transport))


# --- 1. completed + output_image convenience property (defensive first-checked path) -----------


@pytest.mark.asyncio
async def test_completed_with_output_image_convenience_field() -> None:
    transport = _SequencedTransport([
        (200, {"id": "int-1", "status": "completed", "output_image": {"data": _OUTPUT_PNG_B64, "mime_type": "image/png"}}),
    ])
    response = await _adapter(transport).generate_image(_edit_request())
    assert response.image_bytes == base64.b64decode(_OUTPUT_PNG_B64)


# --- 2. completed + no output_image + image inside steps -> model_output -> content -------------


@pytest.mark.asyncio
async def test_completed_with_image_inside_steps_model_output_content() -> None:
    transport = _SequencedTransport([
        (200, {
            "id": "int-2", "status": "completed",
            "steps": [
                {"type": "user_input", "content": [{"type": "text", "text": "hi"}]},
                _model_output_step([_image_content_block()]),
            ],
        }),
    ])
    response = await _adapter(transport).generate_image(_edit_request())
    assert response.image_bytes == base64.b64decode(_OUTPUT_PNG_B64)


# --- 3. initial in_progress -> interactions.get() -> completed -> image in steps ----------------


@pytest.mark.asyncio
async def test_in_progress_polls_and_resolves_to_completed_image_in_steps() -> None:
    transport = _SequencedTransport([
        (200, {"id": "int-3", "status": "in_progress"}),
        (200, {"id": "int-3", "status": "in_progress"}),
        (200, {"id": "int-3", "status": "completed", "steps": [_model_output_step([_image_content_block()])]}),
    ])
    response = await _adapter(transport).generate_image(_edit_request())
    assert response.image_bytes == base64.b64decode(_OUTPUT_PNG_B64)
    # The two poll GETs must target the interaction-id URL, not the base POST endpoint.
    assert transport.requests[1].url.path.endswith("/int-3")
    assert transport.requests[2].url.path.endswith("/int-3")


@pytest.mark.asyncio
async def test_polling_uses_bounded_short_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    """Confirms the poll loop actually sleeps between GETs using the module's own bounded
    interval constant, rather than busy-looping."""
    monkeypatch.setattr(gemini_image_adapter_module, "_POLL_INTERVAL_SECONDS", 0.01)
    transport = _SequencedTransport([
        (200, {"id": "int-3b", "status": "in_progress"}),
        (200, {"id": "int-3b", "status": "completed", "steps": [_model_output_step([_image_content_block()])]}),
    ])
    response = await _adapter(transport).generate_image(_edit_request())
    assert response.image_bytes == base64.b64decode(_OUTPUT_PNG_B64)


# --- 4. in_progress -> failed -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_in_progress_polls_and_resolves_to_failed_raises_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gemini_image_adapter_module, "_POLL_INTERVAL_SECONDS", 0.01)
    transport = _SequencedTransport([
        (200, {"id": "int-4", "status": "in_progress"}),
        (200, {"id": "int-4", "status": "failed"}),
    ])
    with pytest.raises(GeminiImageAdapterError, match="failed"):
        await _adapter(transport).generate_image(_edit_request())


# --- 5. completed with text only / no image -----------------------------------------------------


@pytest.mark.asyncio
async def test_completed_text_only_no_image_raises_typed_error_not_crashes() -> None:
    transport = _SequencedTransport([
        (200, {
            "id": "int-5", "status": "completed",
            "steps": [_model_output_step([{"type": "text", "text": "Here is a description instead of an image."}])],
        }),
    ])
    with pytest.raises(GeminiImageAdapterError, match="no usable image"):
        await _adapter(transport).generate_image(_edit_request())


# --- 6. malformed image data ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_base64_in_steps_image_block_raises_typed_error() -> None:
    transport = _SequencedTransport([
        (200, {
            "id": "int-6", "status": "completed",
            "steps": [_model_output_step([_image_content_block(data_b64="not-valid-base64!!!")])],
        }),
    ])
    with pytest.raises(GeminiImageAdapterError):
        await _adapter(transport).generate_image(_edit_request())


# --- 7. polling timeout --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_polling_timeout_raises_typed_error_never_polls_forever(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gemini_image_adapter_module, "_POLL_INTERVAL_SECONDS", 0.02)
    monkeypatch.setattr(gemini_image_adapter_module, "_MAX_POLL_WAIT_SECONDS", 0.05)
    # Always in_progress, indefinitely - the adapter must give up after the bounded timeout, not
    # exhaust this list (which would raise IndexError if polling were unbounded).
    responses = [(200, {"id": "int-7", "status": "in_progress"}) for _ in range(1000)]
    transport = _SequencedTransport(responses)
    with pytest.raises(GeminiImageAdapterError, match="timed out"):
        await _adapter(transport).generate_image(_edit_request())


# --- 8. interaction usage metadata preserved ------------------------------------------------------


@pytest.mark.asyncio
async def test_usage_metadata_mapped_from_total_input_output_tokens() -> None:
    transport = _SequencedTransport([
        (200, {
            "id": "int-8", "status": "completed",
            "steps": [_model_output_step([_image_content_block()])],
            "usage": {"total_input_tokens": 42, "total_output_tokens": 1290, "total_tokens": 1332},
        }),
    ])
    response = await _adapter(transport).generate_image(_edit_request())
    assert response.usage.input_tokens == 42
    assert response.usage.output_tokens == 1290


@pytest.mark.asyncio
async def test_missing_usage_field_falls_back_to_bare_unit_count() -> None:
    transport = _SequencedTransport([
        (200, {"id": "int-8b", "status": "completed", "steps": [_model_output_step([_image_content_block()])]}),
    ])
    response = await _adapter(transport).generate_image(_edit_request())
    assert response.usage.units == 1
    assert response.usage.unit_type == "image"


# --- 9. request/model ID preserved where available ------------------------------------------------


@pytest.mark.asyncio
async def test_request_id_and_model_used_both_preserved() -> None:
    transport = _SequencedTransport([
        (200, {"id": "int-9-specific", "status": "completed", "steps": [_model_output_step([_image_content_block()])]}),
    ])
    response = await _adapter(transport).generate_image(_edit_request())
    assert response.request_id == "int-9-specific"
    assert response.model_used == GEMINI_3_1_FLASH_IMAGE


# --- Request-shape regressions (response_format always sent; Api-Revision header) -----------------


@pytest.mark.asyncio
async def test_response_format_always_sent_even_without_target_aspect_ratio() -> None:
    """V2.2A fix: response_format must always be sent (not only when target_aspect_ratio is set) -
    omitting it risks a text-only completion (scenario 5 above)."""
    transport = _SequencedTransport([
        (200, {"id": "int-10", "status": "completed", "steps": [_model_output_step([_image_content_block()])]}),
    ])
    request = ImageGenerationRequest(
        prompt="edit", operation=ImageGenerationOperation.IMAGE_EDIT,
        reference_images=(ReferenceImage(data=_SOURCE_PNG, mime_type="image/png"),),
    )
    await _adapter(transport).generate_image(request)
    body = json.loads(transport.requests[0].content)
    assert body["response_format"]["type"] == "image"
    assert "aspect_ratio" not in body["response_format"]


@pytest.mark.asyncio
async def test_api_revision_header_sent_on_every_request() -> None:
    transport = _SequencedTransport([
        (200, {"id": "int-11", "status": "in_progress"}),
        (200, {"id": "int-11", "status": "completed", "steps": [_model_output_step([_image_content_block()])]}),
    ])
    await _adapter(transport).generate_image(_edit_request())
    for req in transport.requests:
        assert req.headers["Api-Revision"] == "2026-05-20"
