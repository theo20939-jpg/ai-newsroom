"""LLMGateway Protocol and its provider-neutral request/response schemas
(docs/phase6_architecture_contract.md §7).

This is the ONLY thing a Capability may call for AI inference (P1, P3). No
provider implementation exists in Phase 6 - contract only. None of these
types encode a provider-specific shape (no openai.ChatCompletion, no
Anthropic message-block format); a provider adapter built in a later phase
is solely responsible for translating to/from this shape.
"""
from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from schemas.capability import CapabilityUsage


class UnsupportedGatewayCapabilityError(Exception):
    """Raised by a provider implementation that declines to support a given
    method (e.g. no moderation endpoint) - a provider-routing concern, not a
    reason to change the LLMGateway Protocol."""


class ContentPart(BaseModel):
    """One piece of a message - text or a reference to a non-text artifact.
    Binary content is never inlined; multimodal input/output is always a
    reference (URI/artifact id), never raw bytes in this contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["text", "artifact_ref"]
    text: str | None = None
    artifact_ref: str | None = None
    mime_type: str | None = None


class Message(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    role: Literal["system", "user", "assistant", "tool"]
    content: list[ContentPart]


class ToolDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    description: str
    parameters_schema: dict[str, Any]


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    arguments: dict[str, Any]


def _default_modalities() -> list[Literal["text", "image", "audio"]]:
    return ["text"]


class GenerateRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    messages: list[Message]
    preferred_model: str | None = None
    preferred_provider: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    # API cost optimization: OpenAI's Responses API `reasoning.effort` parameter. `None` (the
    # default) omits the field entirely - unchanged behavior for every existing caller.
    reasoning_effort: Literal["none", "low", "medium", "high"] | None = None

    tools: list[ToolDefinition] | None = None
    tool_choice: Literal["auto", "none", "required"] | None = None

    response_mode: Literal["text", "json_schema"] = "text"
    response_schema: dict[str, Any] | None = None

    modalities: list[Literal["text", "image", "audio"]] = Field(default_factory=_default_modalities)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    uri: str
    mime_type: str


class GenerateResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str | None
    structured_output: dict[str, Any] | None
    tool_calls: list[ToolCall] | None = None
    artifacts: list[ArtifactRef] | None = None
    finish_reason: Literal["stop", "tool_calls", "length", "content_filter"]
    model_used: str
    usage: CapabilityUsage


class GenerateChunk(BaseModel):
    """One increment of a streamed generate() call."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    delta_text: str | None = None
    delta_tool_call: ToolCall | None = None
    is_final: bool = False
    usage: CapabilityUsage | None = None


class EmbedRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    inputs: list[str] = Field(min_length=1)
    preferred_model: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EmbedResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    vectors: list[list[float]]
    model_used: str
    usage: CapabilityUsage


class ClassifyRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    input: str
    labels: list[str] = Field(min_length=1)
    preferred_model: str | None = None


class ClassificationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    label: str
    score: float = Field(ge=0, le=1)


class ClassifyResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    results: list[ClassificationResult]
    model_used: str
    usage: CapabilityUsage


class ModerateRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    input: str
    preferred_model: str | None = None


class ModerationCategory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    category: str
    flagged: bool
    score: float = Field(ge=0, le=1)


class ModerateResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    flagged: bool
    categories: list[ModerationCategory]
    model_used: str
    usage: CapabilityUsage


class RerankRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    query: str
    documents: list[str] = Field(min_length=1)
    top_n: int | None = Field(default=None, ge=1)
    preferred_model: str | None = None


class RerankResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    index: int = Field(ge=0)
    score: float


class RerankResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    results: list[RerankResult]
    model_used: str
    usage: CapabilityUsage


class LLMGateway(Protocol):
    """The ONLY thing a Capability may call for AI inference. Unimplemented
    in Phase 6 - contract only. No provider-specific parameter anywhere in
    this Protocol or its request/response types."""

    async def generate(self, request: GenerateRequest) -> GenerateResponse: ...
    def generate_stream(self, request: GenerateRequest) -> AsyncIterator[GenerateChunk]: ...
    async def embed(self, request: EmbedRequest) -> EmbedResponse: ...
    async def classify(self, request: ClassifyRequest) -> ClassifyResponse: ...
    async def moderate(self, request: ModerateRequest) -> ModerateResponse: ...
    async def rerank(self, request: RerankRequest) -> RerankResponse: ...
