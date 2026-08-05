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
"""
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from schemas.capability import CapabilityUsage


class ImageGenerationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: str = Field(min_length=1)
    preferred_model: str | None = None
    preferred_provider: str | None = None
    # A small, fixed set - MVP scope (docs/phase18_m0_meme_discovery_report.md §8/§10: "один
    # визуальный формат... без сложных многостраничных комиксов"). Square is the only size M6's
    # renderer is built against as of M5/M6.
    size: Literal["1024x1024"] = "1024x1024"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImageGenerationResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    image_bytes: bytes
    mime_type: Literal["image/png"] = "image/png"
    model_used: str
    provider: str | None = None
    usage: CapabilityUsage


class ImageGenerationGateway(Protocol):
    """The ONLY thing a Capability may call for AI image generation - mirrors `LLMGateway`'s own
    "the ONLY thing a Capability may call for AI inference" rule, applied to this modality."""

    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse: ...
