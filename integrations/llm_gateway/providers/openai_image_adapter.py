"""OpenAIImageAdapter (Phase V2.1 initial build; Phase V2.2A contract repair,
docs/phase_v2_2a_protocol_repair_and_smoke_report.md): implements `ImageGenerationGateway` for
OpenAI's `gpt-image-2` image-editing model.

Official-source verification, V2.2A pass (2026-08-27, WebSearch + the ACTUAL raw HTTP error
observed during the first live V2.2 bake-off attempt):

  - **Root cause of the V2.2 attempt #1 failure**: the V2.1 adapter sent `response_format=
    "b64_json"`. The live API rejected every one of the 3 request/case pairs with
    `400 Bad Request: Unknown parameter: 'response_format'`. Confirmed via WebSearch (2026-08-27,
    OpenAI community/docs corroboration): **`response_format` is not supported for the GPT image
    models at all** (gpt-image-1/1.5/2, chatgpt-image-latest) - they always return base64-encoded
    JSON unconditionally; the parameter only ever applied to the older `dall-e-2`/`dall-e-3`
    models, which could alternatively return a `url`. The installed SDK's own
    `inspect.signature(AsyncImages.edit)` still lists `response_format` as an accepted keyword
    (the client-side type stub is shared/generic across all image models and does not reflect
    this per-model server-side restriction) - this is exactly why the V2.1 pass's "read it
    straight from the installed SDK signature" verification, though a real and reasonable method,
    was insufficient here: a parameter can be SDK-valid but still API-rejected for a specific
    model. **Fix: `response_format` is no longer sent at all** - never substituted with another
    undocumented field, per this phase's own explicit instruction.
  - Model ID `gpt-image-2`, the `images.edit` endpoint/method, `size`'s closed Literal set, and
    the `ImagesResponse.data[].b64_json` / `ImagesResponse.usage.{input_tokens,output_tokens,
    total_tokens}` response shape: unchanged from the V2.1 pass (still read directly from
    `inspect.signature`/the installed `openai==2.45.0` package) - not re-verified in V2.2A, since
    only the `response_format` parameter was the broken part of the request, not the model ID,
    endpoint, or response shape.
  - Pricing (informational only, NOT used for request behavior): see the V2.1 pass / bake-off
    harness's own ESTIMATE-labeled cost figures.

Provider isolation (mirrors `openai_adapter.py`'s own P11 rule stated for the TEXT LLMGateway
adapter): this is the ONLY file that calls `client.images.*` for image generation/editing -
`openai_adapter.py` itself only ever calls `client.responses.create(...)` for text, never
`images.*`. Both files may import the `openai` package; neither imports the other.

Never logs raw image bytes, base64 payloads, or the API key."""
from __future__ import annotations

import base64
from typing import Literal

from openai import AsyncOpenAI, OpenAIError

from integrations.llm_gateway.image_protocol import (
    ImageAdapterCapabilities,
    ImageGenerationOperation,
    ImageGenerationRequest,
    ImageGenerationResponse,
)
from schemas.capability import CapabilityUsage

GPT_IMAGE_2 = "gpt-image-2"

# The exact closed Literal set `AsyncImages.edit(size=...)` accepts, per direct inspection of the
# installed `openai` package (module docstring) - no exact 16:9/1280x720 option exists.
_SUPPORTED_SIZES: tuple[str, ...] = ("256x256", "512x512", "1024x1024", "1536x1024", "1024x1536", "auto")
_CLOSEST_LANDSCAPE_SIZE: Literal["1536x1024"] = "1536x1024"  # nearest to 16:9 among the closed set


class OpenAIImageAdapterError(RuntimeError):
    """Raised for any OpenAI image-edit API failure - a plain, typed exception the existing
    bounded-retry `except Exception` convention (`services/meme_image_generation.py`) already
    handles correctly."""


def _closest_supported_size(target_aspect_ratio: str | None) -> str:
    """Deterministic, provider-neutral -> provider-specific size mapping. Only "16:9" is mapped
    to a non-default size in this phase (the only ratio this bake-off actually requests, per
    Stage 9) - everything else falls back to the model's own "auto" rather than guessing."""
    if target_aspect_ratio == "16:9":
        return _CLOSEST_LANDSCAPE_SIZE
    return "auto"


class OpenAIImageAdapter:
    """Implements `ImageGenerationGateway` for `gpt-image-2` via `AsyncOpenAI().images.edit()`."""

    def __init__(self, *, api_key: str, client: AsyncOpenAI | None = None) -> None:
        self._client = client or AsyncOpenAI(api_key=api_key)

    @property
    def CAPABILITIES(self) -> ImageAdapterCapabilities:  # noqa: N802 - matches the established class-attribute convention
        return ImageAdapterCapabilities(
            supports_text_to_image=True, supports_image_edit=True,
            max_reference_images=16, supports_aspect_ratio_control=True,
        )

    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        if request.operation != ImageGenerationOperation.IMAGE_EDIT:
            raise OpenAIImageAdapterError(
                "OpenAIImageAdapter (Phase V2.1) is built and verified for ImageGenerationOperation."
                "IMAGE_EDIT only in this phase - TEXT_TO_IMAGE via gpt-image-2 is a separate, "
                "not-yet-verified code path, deliberately not enabled here rather than guessed."
            )

        images = [(ref.data, ref.mime_type) for ref in request.reference_images]
        size = _closest_supported_size(request.target_aspect_ratio)

        try:
            raw = await self._client.images.with_raw_response.edit(
                model=GPT_IMAGE_2,
                image=[(f"reference_{i}.{mime.split('/')[-1]}", data, mime) for i, (data, mime) in enumerate(images)],
                prompt=request.prompt,
                size=size,  # type: ignore[arg-type]
                # response_format deliberately NOT sent (V2.2A repair) - unsupported for GPT image
                # models, which always return b64_json unconditionally; see module docstring.
            )
        except OpenAIError as exc:
            raise OpenAIImageAdapterError(f"OpenAI images.edit request failed: {type(exc).__name__}: {exc}") from exc

        request_id = raw.headers.get("x-request-id")
        parsed = raw.parse()

        if not parsed.data or not parsed.data[0].b64_json:
            raise OpenAIImageAdapterError("OpenAI images.edit response contained no b64_json image data")

        image_bytes = base64.b64decode(parsed.data[0].b64_json)

        usage = CapabilityUsage(units=1, unit_type="image")
        cost_usd: str | None = None
        if parsed.usage is not None:
            usage = CapabilityUsage(
                input_tokens=parsed.usage.input_tokens, output_tokens=parsed.usage.output_tokens,
                units=1, unit_type="image",
            )
            # Never invented: OpenAI's ImagesResponse.usage reports TOKENS, not a dollar amount -
            # cost_usd stays None here; a future caller converts tokens -> cost using its own
            # explicitly-sourced, non-stale pricing table (never a constant baked into this file).

        return ImageGenerationResponse(
            image_bytes=image_bytes, mime_type="image/png", model_used=GPT_IMAGE_2, provider="openai",
            usage=usage, request_id=request_id, cost_usd=cost_usd,
        )
