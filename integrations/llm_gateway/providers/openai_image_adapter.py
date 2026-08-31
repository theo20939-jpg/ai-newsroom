"""OpenAIImageAdapter (Phase V2.1 initial build; Phase V2.2A contract repair,
docs/phase_v2_2a_protocol_repair_and_smoke_report.md; MEME-PROD-2 TEXT_TO_IMAGE extension):
implements `ImageGenerationGateway` for OpenAI's `gpt-image-2` model, both operations.

MEME-PROD-2: TEXT_TO_IMAGE via `images.generate()` is now a real, verified code path (real
production meme image generation, `services/meme_generation_orchestrator.py`) - previously
deliberately rejected here (see the V2.1 pass's own disclosure, kept below for its still-accurate
IMAGE_EDIT-specific findings) as "not-yet-verified." Reuses the exact same `_client`/error-
translation/response-parsing discipline as the pre-existing IMAGE_EDIT path - one class, one
provider-isolation boundary, never a second file calling `client.images.*`. `quality`/the
TEXT_TO_IMAGE `size` are adapter-level constructor configuration, never added to the shared,
provider-neutral `ImageGenerationRequest` schema (that module's own docstring already establishes
this exact rule for `input_fidelity`/`quality`-style provider-specific knobs).

Retry classification (MEME-PROD-2 §10): `OpenAIImageAdapterError.retryable` distinguishes a
genuinely transient provider/transport/server condition (rate limit, connection failure, 5xx,
timeout - worth a second bounded attempt) from a condition retrying the IDENTICAL request cannot
fix (authentication, malformed request, content-policy refusal - all client-side 4xx errors) -
`services/meme_image_generation.py`'s own bounded-retry loop reads this attribute via `getattr(...,
True)` so any OTHER gateway's exception (lacking the attribute) keeps its exact prior "always
retryable" behavior, unchanged.

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

from openai import (
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    OpenAIError,
    PermissionDeniedError,
)

from integrations.llm_gateway.image_protocol import (
    ImageAdapterCapabilities,
    ImageGenerationOperation,
    ImageGenerationRequest,
    ImageGenerationResponse,
)
from schemas.capability import CapabilityUsage

GPT_IMAGE_2 = "gpt-image-2"

# The exact closed Literal set `AsyncImages.generate(size=...)` accepts for gpt-image-2, per direct
# inspection of the installed `openai` package (`openai==2.45.0`) - a superset of `.edit()`'s own
# set (also includes the two square sizes below "1024x1024"), but this adapter only ever requests
# the one meme-appropriate square size.
_TEXT_TO_IMAGE_DEFAULT_SIZE: Literal["1024x1024"] = "1024x1024"
ImageQuality = Literal["low", "medium", "high", "auto"]
_DEFAULT_QUALITY: ImageQuality = "medium"

# §10: exactly the OpenAI SDK exception classes whose underlying HTTP status can never be fixed by
# retrying the SAME request unchanged - authentication/authorization/not-found/malformed-request
# (all 4xx). Every other OpenAIError (RateLimitError 429, InternalServerError 5xx,
# APIConnectionError, APITimeoutError, and any future/unclassified subclass) stays retryable.
_NON_RETRYABLE_ERROR_TYPES: tuple[type[OpenAIError], ...] = (
    AuthenticationError, BadRequestError, PermissionDeniedError, NotFoundError,
)

# The exact closed Literal set `AsyncImages.edit(size=...)` accepts, per direct inspection of the
# installed `openai` package (module docstring) - no exact 16:9/1280x720 option exists.
_SUPPORTED_SIZES: tuple[str, ...] = ("256x256", "512x512", "1024x1024", "1536x1024", "1024x1536", "auto")
_CLOSEST_LANDSCAPE_SIZE: Literal["1536x1024"] = "1536x1024"  # nearest to 16:9 among the closed set


class OpenAIImageAdapterError(RuntimeError):
    """Raised for any OpenAI image-generation/edit API failure - a plain, typed exception the
    existing bounded-retry `except Exception` convention (`services/meme_image_generation.py`)
    already handles correctly. `retryable` (MEME-PROD-2 §10, default `True` - preserves the exact
    prior "always retry once" behavior for anything not explicitly classified) tells the retry
    loop whether a second attempt could plausibly help; read via `getattr(exc, "retryable", True)`
    so a caller never needs to import this class or the `openai` package to make the decision."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


def _wrap_openai_error(exc: OpenAIError, *, operation: str) -> OpenAIImageAdapterError:
    retryable = not isinstance(exc, _NON_RETRYABLE_ERROR_TYPES)
    return OpenAIImageAdapterError(
        f"OpenAI {operation} request failed: {type(exc).__name__}: {exc}", retryable=retryable,
    )


def _closest_supported_size(target_aspect_ratio: str | None) -> str:
    """Deterministic, provider-neutral -> provider-specific size mapping. Only "16:9" is mapped
    to a non-default size in this phase (the only ratio this bake-off actually requests, per
    Stage 9) - everything else falls back to the model's own "auto" rather than guessing."""
    if target_aspect_ratio == "16:9":
        return _CLOSEST_LANDSCAPE_SIZE
    return "auto"


def _parse_images_response(raw, *, operation: str) -> ImageGenerationResponse:
    """Shared response parsing for both `.edit()` and `.generate()` - identical `ImagesResponse`
    shape (`data[].b64_json`, `usage.{input_tokens,output_tokens}`) for both, per direct
    inspection of the installed `openai` package (module docstring)."""
    request_id = raw.headers.get("x-request-id")
    parsed = raw.parse()

    if not parsed.data or not parsed.data[0].b64_json:
        raise OpenAIImageAdapterError(f"OpenAI {operation} response contained no b64_json image data")

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


class OpenAIImageAdapter:
    """Implements `ImageGenerationGateway` for `gpt-image-2` - `images.edit()` for IMAGE_EDIT,
    `images.generate()` for TEXT_TO_IMAGE (MEME-PROD-2 - the real meme-image production path).

    `quality`/`text_to_image_size` are THIS adapter's own configuration (never the shared,
    provider-neutral `ImageGenerationRequest` schema - see module docstring). Defaults match
    MEME-PROD-2's own required production profile: medium quality, one square 1024-class image -
    a caller only needs to override either for a genuinely different use case."""

    def __init__(
        self, *, api_key: str, client: AsyncOpenAI | None = None,
        quality: ImageQuality = _DEFAULT_QUALITY,
        text_to_image_size: str = _TEXT_TO_IMAGE_DEFAULT_SIZE,
    ) -> None:
        self._client = client or AsyncOpenAI(api_key=api_key)
        self._quality = quality
        self._text_to_image_size = text_to_image_size

    @property
    def CAPABILITIES(self) -> ImageAdapterCapabilities:  # noqa: N802 - matches the established class-attribute convention
        return ImageAdapterCapabilities(
            supports_text_to_image=True, supports_image_edit=True,
            max_reference_images=16, supports_aspect_ratio_control=True,
        )

    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        if request.operation == ImageGenerationOperation.TEXT_TO_IMAGE:
            return await self._generate_text_to_image(request)
        if request.operation != ImageGenerationOperation.IMAGE_EDIT:
            raise OpenAIImageAdapterError(f"unsupported ImageGenerationOperation: {request.operation!r}")
        return await self._generate_image_edit(request)

    async def _generate_text_to_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        """MEME-PROD-2: the real meme-image production path - a single square image, no reference
        images, `n=1` (never more than one paid generation per call - §5's own explicit "generate
        only ONE source image per meme request")."""
        try:
            raw = await self._client.images.with_raw_response.generate(
                model=GPT_IMAGE_2,
                prompt=request.prompt,
                size=self._text_to_image_size,  # type: ignore[arg-type]
                quality=self._quality,  # type: ignore[arg-type]
                n=1,
                output_format="png",
                # response_format deliberately NOT sent (V2.2A repair, still applies to .generate()
                # too) - unsupported for GPT image models, which always return b64_json
                # unconditionally; see module docstring.
            )
        except OpenAIError as exc:
            raise _wrap_openai_error(exc, operation="images.generate") from exc
        return _parse_images_response(raw, operation="images.generate")

    async def _generate_image_edit(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
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
            raise _wrap_openai_error(exc, operation="images.edit") from exc
        return _parse_images_response(raw, operation="images.edit")
