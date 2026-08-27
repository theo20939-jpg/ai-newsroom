"""GeminiImageAdapter (Phase V2.1 initial build; Phase V2.2A contract repair,
docs/phase_v2_2a_protocol_repair_and_smoke_report.md): implements `ImageGenerationGateway` for
Google's Gemini image-editing models via the raw Interactions API (no `google-genai` SDK is
installed in this environment - confirmed absent again in V2.2A, still deliberately not added).

Official-source verification, V2.2A pass (2026-08-27, WebSearch/WebFetch + the ACTUAL raw HTTP
response bodies observed during the first live V2.2 bake-off attempt - both used as source of
truth, per this phase's own instruction, over the V2.1 pass's incomplete doc reading):

  - **Root cause of the V2.2 attempt #1 failure**: the V2.1 adapter assumed a synchronous
    `output_image`/`outputImage` convenience JSON field. The real, live raw response bodies had
    NEITHER - their top-level keys were `created, id, model, object, service_tier, status, steps,
    updated, usage`. Confirmed via WebFetch of ai.google.dev/api/interactions-api (2026-08-27) that
    `interaction.output_image` is a **Python SDK-only computed property** ("returns the last
    generated image block" - i.e. it scans `steps` for you); it is NOT a raw JSON response field.
    A raw-HTTP adapter (this file, no SDK) must therefore always extract from `steps` itself.
  - **Response shape** (ai.google.dev/api/interactions-api, full schema reference, fetched
    2026-08-27): `status` is one of `in_progress | requires_action | completed | failed |
    cancelled | incomplete | budget_exceeded | queued`. `steps` is an array of step objects; a
    `model_output` step has a `content` array of typed blocks. An image content block has
    exactly: `{"type": "image", "data": "<base64>", "mime_type": "image/png|image/jpeg|...",
    "resolution": "low|medium|high|ultra_high", "uri": <optional>}` - this file reads `data` and
    `mime_type` from the first `type == "image"` block found in any `model_output` step.
  - **Synchronous by default**: confirmed via WebFetch of ai.google.dev/gemini-api/docs/
    image-generation (2026-08-27) - "The API is synchronous by default - it blocks until
    generation completes." This matches the 11.6s-34.0s single-POST latencies observed in the
    actual failed live run: the call already fully completed server-side; the adapter simply
    never looked in the right place for the image. Polling is therefore a FALLBACK only, for the
    (undocumented-as-default, but schema-supported) case where a POST response's own `status` is
    `in_progress`/`queued` - this file never sets `background=True` and never assumes polling is
    required.
  - **Usage object** (same reference): `total_input_tokens`/`total_output_tokens`/`total_tokens`
    (NOT `input_tokens`/`output_tokens` - a different shape than OpenAI's `Usage` type). Mapped
    into `CapabilityUsage.input_tokens`/`output_tokens` below.
  - **Request `response_format`** (ai.google.dev/gemini-api/docs/image-generation verbatim
    example + the breaking-changes migration guide, both fetched 2026-08-27): `{"type": "image",
    "mime_type": "image/jpeg", "aspect_ratio": "16:9"}` - this file now ALWAYS sends
    `response_format` (not only when `target_aspect_ratio` is set) since omitting it risks a
    text-only response (Step 4 scenario 5's own explicit "completed with text only / no image"
    test).
  - **Schema revision**: `Api-Revision: 2026-05-20` opts into the current `steps`-based schema.
    The migration guide (fetched 2026-08-27) states the legacy `outputs` schema was permanently
    removed after 2026-06-08 - i.e. today, this is already the unconditional default - but the
    header is still sent explicitly and defensively, pinning behavior rather than relying on an
    implicit default that could change again.
  - Model IDs (`gemini-3.1-flash-image`, `gemini-3-pro-image`) and pricing citations: unchanged
    from the V2.1 pass (see git history of this file / docs/phase_v2_1_provider_bakeoff_
    preparation_report.md) - not re-verified in V2.2A, since only the response contract was
    broken, not the model IDs (the live calls DID reach the right models).

Provider isolation (mirrors `openai_adapter.py`'s own P11 rule): this is the ONLY file in this
codebase that constructs a Gemini/Google API HTTP request.

Shared for both `gemini-3.1-flash-image` and `gemini-3-pro-image`: identical request/response
shape, differing only in the `model` field - one adapter class, never two duplicated ones.

Never logs raw image bytes, base64 payloads, or the API key."""
from __future__ import annotations

import asyncio
import base64
import binascii
import time

import httpx

from integrations.llm_gateway.image_protocol import (
    ImageAdapterCapabilities,
    ImageGenerationRequest,
    ImageGenerationResponse,
    MAX_REFERENCE_IMAGES,
)
from schemas.capability import CapabilityUsage

_INTERACTIONS_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
_REQUEST_TIMEOUT_SECONDS = 60.0
_API_REVISION = "2026-05-20"

# Polling fallback bounds (naming mirrors core/config.py's own established
# `*_poll_interval_seconds` / `*_timeout_seconds` convention) - only used when a response's own
# `status` is genuinely in_progress/queued, never applied unconditionally.
_POLL_INTERVAL_SECONDS = 2.0
_MAX_POLL_WAIT_SECONDS = 90.0

GEMINI_3_1_FLASH_IMAGE = "gemini-3.1-flash-image"
GEMINI_3_PRO_IMAGE = "gemini-3-pro-image"
SUPPORTED_GEMINI_IMAGE_MODELS = (GEMINI_3_1_FLASH_IMAGE, GEMINI_3_PRO_IMAGE)

_STATUS_COMPLETED = "completed"
_STATUS_NON_TERMINAL = frozenset({"in_progress", "queued"})
_STATUS_TERMINAL_FAILURE = frozenset({"failed", "cancelled", "incomplete", "budget_exceeded", "requires_action"})


class GeminiImageAdapterError(RuntimeError):
    """Raised for any Gemini API failure (transport error, non-2xx response, malformed response
    body, terminal non-completed status, polling timeout) - always a plain, typed exception the
    existing bounded-retry `except Exception` convention already handles correctly."""


def _extract_image_from_payload(payload: dict) -> tuple[bytes, str]:
    """Extraction order per this phase's own instruction:
    A. A raw `output_image`/`outputImage` convenience field, IF a future API revision ever adds
       one to the raw JSON (currently believed SDK-only - see module docstring - but checked
       first defensively, never assumed absent).
    B. Otherwise scan `steps` for a `model_output` step whose `content` array has a block with
       `type == "image"` - the real, confirmed shape.
    Raises GeminiImageAdapterError with a clear, non-secret diagnostic if neither yields a usable
    image - never guesses, never fabricates."""
    convenience = payload.get("output_image") or payload.get("outputImage")
    if isinstance(convenience, dict) and convenience.get("data"):
        data_b64 = convenience["data"]
        mime_type = convenience.get("mime_type") or convenience.get("mimeType") or "image/png"
        return _decode_base64_image(data_b64, mime_type)

    steps = payload.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict) or step.get("type") != "model_output":
                continue
            for block in step.get("content", []) or []:
                if isinstance(block, dict) and block.get("type") == "image" and block.get("data"):
                    return _decode_base64_image(block["data"], block.get("mime_type", "image/png"))

    step_types = [s.get("type") for s in steps if isinstance(s, dict)] if isinstance(steps, list) else None
    raise GeminiImageAdapterError(
        "Gemini interaction has no usable image - no output_image/outputImage convenience field "
        f"and no image content block in any model_output step. status={payload.get('status')!r}, "
        f"step types present={step_types!r}, top-level keys={sorted(payload.keys())}"
    )


def _decode_base64_image(data_b64: str, mime_type: str) -> tuple[bytes, str]:
    try:
        return base64.b64decode(data_b64, validate=True), mime_type
    except (binascii.Error, ValueError) as exc:
        raise GeminiImageAdapterError("Gemini interaction image content block 'data' is not valid base64") from exc


def _map_usage(payload: dict) -> CapabilityUsage:
    """`total_input_tokens`/`total_output_tokens` (module docstring) - never invented when
    absent."""
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return CapabilityUsage(units=1, unit_type="image")
    return CapabilityUsage(
        input_tokens=usage.get("total_input_tokens"),
        output_tokens=usage.get("total_output_tokens"),
        units=1,
        unit_type="image",
    )


class GeminiImageAdapter:
    """Implements `ImageGenerationGateway` for one Gemini image model. Construct one instance per
    model_id (`GEMINI_3_1_FLASH_IMAGE` or `GEMINI_3_PRO_IMAGE`) - the API contract is identical,
    only the `model` field in the request body differs."""

    def __init__(self, *, model_id: str, api_key: str, client: httpx.AsyncClient | None = None) -> None:
        if model_id not in SUPPORTED_GEMINI_IMAGE_MODELS:
            raise ValueError(f"Unsupported Gemini image model_id {model_id!r} - supported: {SUPPORTED_GEMINI_IMAGE_MODELS}")
        self._model_id = model_id
        self._api_key = api_key
        self._client = client  # injectable for tests - never a real network call in this repo's own tests

    @property
    def CAPABILITIES(self) -> ImageAdapterCapabilities:  # noqa: N802 - matches the established class-attribute convention
        return ImageAdapterCapabilities(
            supports_text_to_image=True, supports_image_edit=True,
            max_reference_images=MAX_REFERENCE_IMAGES, supports_aspect_ratio_control=True,
        )

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self._api_key, "Content-Type": "application/json", "Api-Revision": _API_REVISION}

    async def _post_interaction(self, client: httpx.AsyncClient, body: dict) -> dict:
        try:
            response = await client.post(_INTERACTIONS_ENDPOINT, headers=self._headers(), json=body)
        except httpx.HTTPError as exc:
            raise GeminiImageAdapterError(f"Gemini interactions request failed (transport): {type(exc).__name__}") from exc
        return self._parse_response(response)

    async def _get_interaction(self, client: httpx.AsyncClient, interaction_id: str) -> dict:
        try:
            response = await client.get(f"{_INTERACTIONS_ENDPOINT}/{interaction_id}", headers=self._headers())
        except httpx.HTTPError as exc:
            raise GeminiImageAdapterError(f"Gemini interactions polling GET failed (transport): {type(exc).__name__}") from exc
        return self._parse_response(response)

    @staticmethod
    def _parse_response(response: httpx.Response) -> dict:
        if response.status_code >= 400:
            # Never log the response body verbatim - it could echo back request content.
            raise GeminiImageAdapterError(f"Gemini interactions request returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise GeminiImageAdapterError("Gemini interactions response was not valid JSON") from exc
        if not isinstance(payload, dict):
            raise GeminiImageAdapterError("Gemini interactions response was not a JSON object")
        return payload

    async def _await_terminal(self, client: httpx.AsyncClient, payload: dict) -> dict:
        """Polling fallback only - entered when `status` is genuinely `in_progress`/`queued`.
        Bounded interval/timeout (Stage 3's own "never poll forever")."""
        status = payload.get("status")
        if status not in _STATUS_NON_TERMINAL:
            return payload
        interaction_id = payload.get("id")
        if not interaction_id:
            raise GeminiImageAdapterError(
                f"Gemini interaction status={status!r} but no 'id' was returned to poll with"
            )
        deadline = time.monotonic() + _MAX_POLL_WAIT_SECONDS
        while True:
            if time.monotonic() >= deadline:
                raise GeminiImageAdapterError(
                    f"Gemini interaction {interaction_id} polling timed out after {_MAX_POLL_WAIT_SECONDS}s "
                    f"(last status={status!r})"
                )
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            payload = await self._get_interaction(client, interaction_id)
            status = payload.get("status")
            if status not in _STATUS_NON_TERMINAL:
                return payload

    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        input_blocks: list[dict] = [{"type": "text", "text": request.prompt}]
        for ref in request.reference_images:
            input_blocks.append({
                "type": "image", "mime_type": ref.mime_type,
                "data": base64.b64encode(ref.data).decode("ascii"),
            })

        response_format: dict = {"type": "image", "mime_type": "image/jpeg"}
        if request.target_aspect_ratio:
            response_format["aspect_ratio"] = request.target_aspect_ratio

        body: dict = {"model": self._model_id, "input": input_blocks, "response_format": response_format}

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS)
        try:
            payload = await self._post_interaction(client, body)
            payload = await self._await_terminal(client, payload)
        finally:
            if owns_client:
                await client.aclose()

        status = payload.get("status")
        if status != _STATUS_COMPLETED and status in _STATUS_TERMINAL_FAILURE:
            raise GeminiImageAdapterError(f"Gemini interaction ended in non-completed terminal status={status!r}")

        image_bytes, mime_type = _extract_image_from_payload(payload)
        request_id = payload.get("id")

        return ImageGenerationResponse(
            image_bytes=image_bytes,
            mime_type="image/png" if "png" in mime_type else "image/jpeg",
            model_used=self._model_id,
            provider="gemini",
            usage=_map_usage(payload),
            request_id=str(request_id) if request_id is not None else None,
            cost_usd=None,  # never invented - the Interactions API's Usage object reports tokens,
            # not a dollar amount (module docstring) - see the bake-off harness's own ESTIMATE-
            # labeled cost figures for anything dollar-denominated.
        )
