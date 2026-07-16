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
    """Implements LLMGateway with deterministic, hardcoded responses."""

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
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
