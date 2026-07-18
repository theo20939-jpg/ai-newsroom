"""FakeLLMGateway: deterministic, hardcoded responses - no network, no provider.

Used to prove the LLMGateway Protocol shape is implementable, and available
for future capability-level tests once real capabilities exist.
"""
from collections.abc import AsyncIterator

from integrations.llm_gateway.protocol import (
    ClassificationResult,
    ClassifyRequest,
    ClassifyResponse,
    EmbedRequest,
    EmbedResponse,
    GenerateChunk,
    GenerateRequest,
    GenerateResponse,
    ModerateRequest,
    ModerateResponse,
    RerankRequest,
    RerankResponse,
    RerankResult,
)
from schemas.capability import CapabilityUsage


class FakeLLMGateway:
    """Implements LLMGateway with deterministic, hardcoded responses.

    generate() returns a fixed default response unless a specific response or exception is
    configured at construction - additive, backward-compatible with every existing caller
    that relies on the default shape (Phase 8 M3: a real Capability's own tests need to
    configure a schema-matching response/failure, which the previous unconditional fixed
    response could never provide).

    `generate_responses` (Phase 8 M5: a retry-then-succeed test needs a *sequence* of
    responses, one per successive generate() call - falls back to repeating the last entry
    once exhausted, rather than raising, to keep tests that don't care about the exact call
    count simple) takes precedence over `generate_response` when both are set; `received_
    requests` records every request generate() was called with, in order, so a test can
    assert on message-list growth / preferred_model pinning across calls.
    """

    def __init__(
        self,
        *,
        generate_response: GenerateResponse | None = None,
        generate_responses: list[GenerateResponse] | None = None,
        generate_error: Exception | None = None,
    ) -> None:
        self._generate_response = generate_response
        self._generate_responses = generate_responses
        self._generate_error = generate_error
        self.received_requests: list[GenerateRequest] = []

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.received_requests.append(request)
        if self._generate_error is not None:
            raise self._generate_error
        if self._generate_responses is not None:
            index = min(len(self.received_requests) - 1, len(self._generate_responses) - 1)
            return self._generate_responses[index]
        if self._generate_response is not None:
            return self._generate_response
        return GenerateResponse(
            text="fake response",
            structured_output={"fake": True},
            finish_reason="stop",
            model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=10, output_tokens=5),
        )

    async def generate_stream(self, request: GenerateRequest) -> AsyncIterator[GenerateChunk]:
        yield GenerateChunk(delta_text="fake ", is_final=False)
        yield GenerateChunk(
            delta_text="response",
            is_final=True,
            usage=CapabilityUsage(input_tokens=10, output_tokens=5),
        )

    async def embed(self, request: EmbedRequest) -> EmbedResponse:
        return EmbedResponse(
            vectors=[[0.1, 0.2, 0.3] for _ in request.inputs],
            model_used="fake-embed-v1",
            usage=CapabilityUsage(units=len(request.inputs), unit_type="embedding"),
        )

    async def classify(self, request: ClassifyRequest) -> ClassifyResponse:
        return ClassifyResponse(
            results=[ClassificationResult(label=request.labels[0], score=0.99)],
            model_used="fake-classify-v1",
            usage=CapabilityUsage(units=1, unit_type="classification"),
        )

    async def moderate(self, request: ModerateRequest) -> ModerateResponse:
        return ModerateResponse(
            flagged=False,
            categories=[],
            model_used="fake-moderate-v1",
            usage=CapabilityUsage(units=1, unit_type="moderation"),
        )

    async def rerank(self, request: RerankRequest) -> RerankResponse:
        return RerankResponse(
            results=[RerankResult(index=i, score=1.0 - i * 0.1) for i in range(len(request.documents))],
            model_used="fake-rerank-v1",
            usage=CapabilityUsage(units=len(request.documents), unit_type="document"),
        )
