"""Contract/shape tests for integrations.llm_gateway.protocol - no real network.

Proves the LLMGateway Protocol is implementable via FakeLLMGateway and that
every request/response schema round-trips through Pydantic validation.
"""
import pytest

from integrations.llm_gateway.protocol import (
    ClassifyRequest,
    ContentPart,
    EmbedRequest,
    GenerateRequest,
    LLMGateway,
    Message,
    ModerateRequest,
    RerankRequest,
)
from tests.fakes.fake_gateway import FakeLLMGateway


def _fake() -> LLMGateway:
    return FakeLLMGateway()


@pytest.mark.asyncio
async def test_generate_returns_provider_neutral_response() -> None:
    request = GenerateRequest(messages=[Message(role="user", content=[ContentPart(type="text", text="hi")])])
    response = await _fake().generate(request)
    assert response.model_used == "fake-model-v1"
    assert response.usage.input_tokens == 10


@pytest.mark.asyncio
async def test_generate_stream_yields_chunks_with_final_usage() -> None:
    request = GenerateRequest(messages=[Message(role="user", content=[ContentPart(type="text", text="hi")])])
    chunks = [chunk async for chunk in _fake().generate_stream(request)]
    assert chunks[-1].is_final
    assert chunks[-1].usage is not None


@pytest.mark.asyncio
async def test_embed_returns_one_vector_per_input() -> None:
    response = await _fake().embed(EmbedRequest(inputs=["a", "b", "c"]))
    assert len(response.vectors) == 3


@pytest.mark.asyncio
async def test_classify_returns_a_classification_result() -> None:
    response = await _fake().classify(ClassifyRequest(input="text", labels=["spam", "ham"]))
    assert response.results[0].label == "spam"


@pytest.mark.asyncio
async def test_moderate_returns_a_moderation_response() -> None:
    response = await _fake().moderate(ModerateRequest(input="text"))
    assert response.flagged is False


@pytest.mark.asyncio
async def test_rerank_returns_one_result_per_document() -> None:
    response = await _fake().rerank(RerankRequest(query="q", documents=["d1", "d2"]))
    assert len(response.results) == 2
