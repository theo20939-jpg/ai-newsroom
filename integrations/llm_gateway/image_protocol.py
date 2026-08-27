"""ImageGenerationGateway Protocol and its provider-neutral request/response schemas (Phase 18
M5, docs/phase18_m5_meme_image_generation_report.md).

Deliberately a SEPARATE Protocol from `integrations.llm_gateway.protocol.LLMGateway`, not an
extension of it - see the M5 report §2 for the full rationale. In short: `LLMGateway.generate()`'s
shape (`messages`, `tools`, `response_schema`, streaming) is built entirely around chat/text
completion; image generation is a single text-prompt-in, single-image-out call with none of that
structure. Extending the shared, already-widely-implemented `LLMGateway` Protocol (every existing
provider adapter, the routing/fallback layer, and `FakeLLMGateway` across ~150+ existing tests)
just to add one unrelated method would be a much larger, riskier blast radius than this file's
own, independent seam - and violates "не менять архитектуру проекта без необходимости" for no
real benefit. This module follows the *exact same design discipline* `LLMGateway` itself
established (provider-neutral request/response, no provider SDK type anywhere in this file, a
Capability may only ever call this Protocol, never a provider SDK directly) - it is the same
architecture pattern, applied to a modality the original Protocol was never shaped for.

Binary image bytes ARE inlined in `ImageGenerationResponse` (unlike `GenerateResponse`, which
represents multimodal *output* as an `ArtifactRef` only) - deliberately, because generating the
artifact is this call's entire purpose, and no separate storage step has happened yet for the
caller to reference. Byte content must never be logged in full anywhere downstream of this call
(callers log `len(image_bytes)`/a hash, never the bytes themselves) - the same discipline
`services/image_intelligence.py` already established for fetched (not generated) image bytes.

Phase V2.1 (docs/nnj_source_faithful_editorial_visual_recomposition_v1.md): extends this Protocol
to support IMAGE_EDIT (a real source/reference image supplied alongside the prompt) - the
architectural blocker the V2 design phase found and disclosed rather than working around
(`ImageGenerationRequest` previously carried `prompt: str` only, with no way to attach a source
image at all). Every field below is added BACKWARDS-COMPATIBLY: `ImageGenerationRequest(prompt=
"...")` - the exact construction every existing call site (`services/meme_image_generation.py`,
every test in `tests/test_phase18_m5_meme_image_generation.py`/`test_phase18_m6_meme_render.py`)
already uses - continues to work unchanged, defaulting to `operation=TEXT_TO_IMAGE`,
`reference_images=()`. The previous `size: Literal["1024x1024"]` field is removed: confirmed by a
full-repository grep before this edit that it was NEVER read anywhere (not by `MockImageAdapter`,
not by any caller) and NEVER passed explicitly by any construction site - a genuinely dead field,
safe to replace with the new provider-neutral `target_width`/`target_height`/`target_aspect_ratio`
hints (also all optional, also never breaking an existing caller).

NO paid/live image-editing call has been made anywhere while writing this module - every model ID/
API-contract claim in the two new provider adapter files this phase adds is backed by a live,
dated public-documentation citation in that file's own docstring (this codebase's own established
`openai_adapter.py` "official-source verification" precedent, applied here since no network
browsing tool was available for automated API-shape confirmation until this phase).
"""
from enum import Enum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.capability import CapabilityUsage

# Bounded, provider-neutral limits (Stage 4's own explicit "bounded count"/"bounded total payload
# size" requirement) - deliberately generous enough to cover every adapter this phase adds
# (OpenAI's own images.edit endpoint accepts up to 16 reference images per its own docs), never
# unbounded.
_SUPPORTED_REFERENCE_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
MAX_REFERENCE_IMAGES = 16
MAX_REFERENCE_IMAGE_BYTES = 20_000_000
MAX_TOTAL_REFERENCE_BYTES = 60_000_000


class ImageGenerationOperation(str, Enum):
    """TEXT_TO_IMAGE (default, existing behavior, unchanged) vs IMAGE_EDIT (Phase V2.1, new) - a
    real source/reference image is supplied and the model is instructed to edit/recompose it,
    never to invent a scene from text alone."""

    TEXT_TO_IMAGE = "text_to_image"
    IMAGE_EDIT = "image_edit"


class ReferenceImage(BaseModel):
    """One input image for an IMAGE_EDIT request. `role` is a free-form, provider-agnostic hint
    (e.g. "subject") - never a provider-specific field; each adapter decides for itself how (or
    whether) to use it. `__repr__` is overridden so accidental logging/debugging output never
    dumps raw image bytes (module docstring's own "never log raw bytes" rule, extended here from
    output bytes to input bytes)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    data: bytes = Field(min_length=1)
    mime_type: str
    role: str | None = None

    @field_validator("mime_type")
    @classmethod
    def _validate_mime_type(cls, value: str) -> str:
        if value not in _SUPPORTED_REFERENCE_MIME_TYPES:
            raise ValueError(
                f"Unsupported reference image mime_type {value!r} - supported: "
                f"{sorted(_SUPPORTED_REFERENCE_MIME_TYPES)}"
            )
        return value

    @field_validator("data")
    @classmethod
    def _validate_data_size(cls, value: bytes) -> bytes:
        if len(value) > MAX_REFERENCE_IMAGE_BYTES:
            raise ValueError(
                f"Reference image is {len(value)} bytes, exceeds MAX_REFERENCE_IMAGE_BYTES={MAX_REFERENCE_IMAGE_BYTES}"
            )
        return value

    def __repr__(self) -> str:
        return f"ReferenceImage(mime_type={self.mime_type!r}, role={self.role!r}, data=<{len(self.data)} bytes>)"

    __str__ = __repr__


class ImageGenerationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: str = Field(min_length=1)
    operation: ImageGenerationOperation = ImageGenerationOperation.TEXT_TO_IMAGE
    reference_images: tuple[ReferenceImage, ...] = ()
    preferred_model: str | None = None
    preferred_provider: str | None = None
    # Provider-neutral output hints only (Stage 3's own explicit "Only add output/quality fields
    # if they can genuinely remain provider-neutral" instruction) - never a provider-specific
    # knob like Gemini's own generation options or OpenAI's `input_fidelity`/`quality`, which
    # belong inside each adapter/its own configuration, never this shared schema.
    target_aspect_ratio: str | None = None  # e.g. "16:9" - a hint, not every provider guarantees it
    target_width: int | None = None
    target_height: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_operation_consistency(self) -> "ImageGenerationRequest":
        if self.operation == ImageGenerationOperation.IMAGE_EDIT and not self.reference_images:
            raise ValueError("ImageGenerationOperation.IMAGE_EDIT requires at least one reference_images entry")
        if len(self.reference_images) > MAX_REFERENCE_IMAGES:
            raise ValueError(f"reference_images has {len(self.reference_images)} entries, exceeds MAX_REFERENCE_IMAGES={MAX_REFERENCE_IMAGES}")
        total_bytes = sum(len(ref.data) for ref in self.reference_images)
        if total_bytes > MAX_TOTAL_REFERENCE_BYTES:
            raise ValueError(f"reference_images total {total_bytes} bytes, exceeds MAX_TOTAL_REFERENCE_BYTES={MAX_TOTAL_REFERENCE_BYTES}")
        return self

    def __repr__(self) -> str:
        return (
            f"ImageGenerationRequest(operation={self.operation!r}, "
            f"reference_images=<{len(self.reference_images)} refs>, prompt_len={len(self.prompt)}, "
            f"preferred_model={self.preferred_model!r})"
        )

    __str__ = __repr__


class ImageGenerationResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    image_bytes: bytes
    mime_type: Literal["image/png", "image/jpeg"] = "image/png"
    model_used: str
    provider: str | None = None
    usage: CapabilityUsage
    # Phase V2.1 additions, both optional and populated ONLY when the real provider response
    # reports them directly (mirrors CapabilityUsage's own established "never invented" discipline
    # for cached_input_tokens/reasoning_tokens) - never fabricated, never estimated here.
    request_id: str | None = None
    cost_usd: str | None = None

    def __repr__(self) -> str:
        return (
            f"ImageGenerationResponse(provider={self.provider!r}, model_used={self.model_used!r}, "
            f"image_bytes=<{len(self.image_bytes)} bytes>, request_id={self.request_id!r})"
        )

    __str__ = __repr__


class ImageAdapterCapabilities(BaseModel):
    """The smallest capability descriptor the system needs to know what an adapter can do
    (Phase V2.1 Stage 5) - never a new plugin framework, just a plain, inspectable value each
    adapter exposes as a class attribute. A caller (or the bake-off harness) checks this BEFORE
    building an IMAGE_EDIT request, rather than discovering incompatibility only via a runtime
    failure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    supports_text_to_image: bool
    supports_image_edit: bool
    max_reference_images: int = 0
    supports_aspect_ratio_control: bool = False


class ImageGenerationGateway(Protocol):
    """The ONLY thing a Capability may call for AI image generation - mirrors `LLMGateway`'s own
    "the ONLY thing a Capability may call for AI inference" rule, applied to this modality.

    Phase V2.1: every conforming adapter also exposes a class-level `CAPABILITIES:
    ImageAdapterCapabilities` attribute (see individual adapters) - not part of this Protocol's
    own `generate_image()` signature (Protocols cannot mandate a class attribute contract cleanly
    without turning this into an ABC, which the original M5 design deliberately avoided), but a
    real, checked-by-tests convention every adapter in this codebase follows."""

    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse: ...
