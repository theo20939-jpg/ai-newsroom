"""Provider-adapter contract test (docs/phase7_architecture_contract.md §20.1 step 2 - this
exact file, named by the frozen contract itself, gates onboarding step 3).

Proves an adapter satisfies the LLMGateway Protocol shape via real Pydantic validation, no
network. Exercised here against FakeProviderAdapter; the same shape of assertions apply to any
future real adapter (e.g. OpenAI's, M18) against a mocked transport.
"""
import pytest

from integrations.llm_gateway.errors import (
    ProviderModerationBlockedError,
    ProviderPermanentIncompatibleError,
    ProviderTransientError,
)
from integrations.llm_gateway.protocol import (
    ClassifyRequest,
    ContentPart,
    EmbedRequest,
    GenerateRequest,
    Message,
    ModerateRequest,
    RerankRequest,
    UnsupportedGatewayCapabilityError,
)
from tests.fakes.fake_provider_adapter import FakeProviderAdapter


def _request() -> GenerateRequest:
    return GenerateRequest(messages=[Message(role="user", content=[ContentPart(type="text", text="hi")])])


@pytest.mark.asyncio
async def test_generate_returns_a_provider_neutral_response() -> None:
    adapter = FakeProviderAdapter(provider_id="fake-a", model_id="fake-model-a")

    response = await adapter.generate(_request())

    assert response.model_used == "fake-model-a"
    assert response.finish_reason == "stop"
    assert response.usage.input_tokens == 10


@pytest.mark.asyncio
async def test_generate_call_count_increments_on_every_attempt() -> None:
    adapter = FakeProviderAdapter(provider_id="fake-a", model_id="fake-model-a")

    await adapter.generate(_request())
    await adapter.generate(_request())

    assert adapter.call_count == 2


@pytest.mark.asyncio
async def test_transient_failure_behavior_raises_provider_transient_error() -> None:
    adapter = FakeProviderAdapter(
        provider_id="fake-a", model_id="fake-model-a", behavior="transient_failure"
    )

    with pytest.raises(ProviderTransientError):
        await adapter.generate(_request())

    assert adapter.call_count == 1  # counted even though the attempt failed


@pytest.mark.asyncio
async def test_permanent_incompatible_behavior_raises_provider_permanent_incompatible_error() -> None:
    adapter = FakeProviderAdapter(
        provider_id="fake-a", model_id="fake-model-a", behavior="permanent_incompatible"
    )

    with pytest.raises(ProviderPermanentIncompatibleError):
        await adapter.generate(_request())


@pytest.mark.asyncio
async def test_moderation_block_behavior_raises_provider_moderation_blocked_error() -> None:
    adapter = FakeProviderAdapter(
        provider_id="fake-a", model_id="fake-model-a", behavior="moderation_block"
    )

    with pytest.raises(ProviderModerationBlockedError):
        await adapter.generate(_request())


@pytest.mark.asyncio
async def test_generate_stream_is_deferred_and_raises_unsupported() -> None:
    adapter = FakeProviderAdapter(provider_id="fake-a", model_id="fake-model-a")

    with pytest.raises(UnsupportedGatewayCapabilityError):
        async for _ in adapter.generate_stream(_request()):
            pass


@pytest.mark.asyncio
async def test_embed_is_deferred_and_raises_unsupported() -> None:
    adapter = FakeProviderAdapter(provider_id="fake-a", model_id="fake-model-a")

    with pytest.raises(UnsupportedGatewayCapabilityError):
        await adapter.embed(EmbedRequest(inputs=["hi"]))


@pytest.mark.asyncio
async def test_classify_is_deferred_and_raises_unsupported() -> None:
    adapter = FakeProviderAdapter(provider_id="fake-a", model_id="fake-model-a")

    with pytest.raises(UnsupportedGatewayCapabilityError):
        await adapter.classify(ClassifyRequest(input="hi", labels=["a", "b"]))


@pytest.mark.asyncio
async def test_moderate_is_deferred_and_raises_unsupported() -> None:
    adapter = FakeProviderAdapter(provider_id="fake-a", model_id="fake-model-a")

    with pytest.raises(UnsupportedGatewayCapabilityError):
        await adapter.moderate(ModerateRequest(input="hi"))


@pytest.mark.asyncio
async def test_rerank_is_deferred_and_raises_unsupported() -> None:
    adapter = FakeProviderAdapter(provider_id="fake-a", model_id="fake-model-a")

    with pytest.raises(UnsupportedGatewayCapabilityError):
        await adapter.rerank(RerankRequest(query="hi", documents=["a", "b"]))


def test_two_distinct_fake_providers_are_independently_usable_together() -> None:
    adapter_a = FakeProviderAdapter(provider_id="fake-provider-a", model_id="fake-model-a")
    adapter_b = FakeProviderAdapter(provider_id="fake-provider-b", model_id="fake-model-b")

    assert adapter_a.provider_id != adapter_b.provider_id
    assert adapter_a.model_id != adapter_b.model_id
    assert adapter_a.call_count == 0
    assert adapter_b.call_count == 0
