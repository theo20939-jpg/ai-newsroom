"""Golden Path test for integrations.llm_gateway.gateway.RoutingGateway (originally M6, updated
at M17 to construct the now-required RoutingEngine/FallbackPolicy dependencies).

Proves the smallest possible generate() slice end to end through the REAL full pipeline: one
resolved model, one FakeProviderAdapter, no real fallback/retry exercised (only one candidate
exists), no real network, a deterministic response, and explicit ObservabilityContext
propagation threaded through every layer (RoutingGateway -> RoutingEngine -> FallbackPolicy).

Per instruction, this file remains the simplest regression case for the full §15.2 pipeline
added at M17: the SCENARIO and ASSERTIONS below are unchanged from the original M6 version -
only the setup/construction code was updated to match RoutingGateway's evolved constructor, the
same way any class's constructor naturally evolves as more of it is built. The pipeline is now
exercised for real (permissive fakes for health/latency/budget/cache infra, not a bypass), which
is a strictly stronger regression guarantee than the original bypass-based Golden Path.
"""
from decimal import Decimal

import pytest

from integrations.llm_gateway.cache.coordinator import CacheCoordinator
from integrations.llm_gateway.errors import NoRoutableCandidateError
from integrations.llm_gateway.fallback.policy import FallbackPolicy
from integrations.llm_gateway.gateway import RoutingGateway
from integrations.llm_gateway.models.registry import ModelDescriptor, ModelRegistry, PricingTier
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, Message
from integrations.llm_gateway.providers.base import ProviderDescriptor, ProviderRegistry
from integrations.llm_gateway.routing.engine import RoutingEngine
from integrations.llm_gateway.routing.registry import RoutingPolicyRegistry
from services.cost_estimator import CostEstimator
from services.pricing_catalog import ModelRegistryPricingCatalog
from tests.fakes.fake_infra import (
    AllowingBudgetGuard,
    EmptyLatencyTracker,
    InMemoryCacheStore,
    PermissiveProviderHealthStore,
)
from tests.fakes.fake_provider_adapter import FakeProviderAdapter


def _model(model_id: str = "fake-model-a", provider_id: str = "fake-provider-a") -> ModelDescriptor:
    return ModelDescriptor(
        model_id=model_id,
        provider_id=provider_id,
        display_name=model_id,
        context_window_tokens=128_000,
        pricing_tiers=[
            PricingTier(
                condition="standard",
                input_price_per_million=Decimal("1.00"),
                output_price_per_million=Decimal("2.00"),
            )
        ],
    )


def _build_gateway(models: list[ModelDescriptor], adapters: dict[str, FakeProviderAdapter]) -> RoutingGateway:
    providers = ProviderRegistry()
    for provider_id, adapter in adapters.items():
        providers.register(ProviderDescriptor(provider_id=provider_id, display_name=provider_id), adapter)
    providers.seal()

    model_registry = ModelRegistry()
    for model in models:
        model_registry.register(model)
    model_registry.seal()

    routing_engine = RoutingEngine(
        model_registry=model_registry,
        provider_registry=providers,
        health_store=PermissiveProviderHealthStore(),
        latency_tracker=EmptyLatencyTracker(),
        policy_registry=RoutingPolicyRegistry(),  # empty - falls back to built-in defaults
    )
    fallback_policy = FallbackPolicy(
        provider_registry=providers,
        health_store=PermissiveProviderHealthStore(),
        cache_coordinator=CacheCoordinator(InMemoryCacheStore()),
        cost_estimator=CostEstimator(ModelRegistryPricingCatalog(model_registry)),
        budget_guard=AllowingBudgetGuard(),
    )
    return RoutingGateway(routing_engine=routing_engine, fallback_policy=fallback_policy)


def _single_provider_gateway(
    provider_id: str = "fake-provider-a", model_id: str = "fake-model-a"
) -> RoutingGateway:
    adapter = FakeProviderAdapter(provider_id=provider_id, model_id=model_id)
    return _build_gateway([_model(model_id=model_id, provider_id=provider_id)], {provider_id: adapter})


def _request(**metadata: str) -> GenerateRequest:
    return GenerateRequest(
        messages=[Message(role="user", content=[ContentPart(type="text", text="hello")])],
        metadata=metadata,
    )


@pytest.mark.asyncio
async def test_generate_resolves_the_one_registered_model_and_dispatches() -> None:
    gateway = _single_provider_gateway()

    response = await gateway.generate(_request())

    assert response.model_used == "fake-model-a"
    assert response.finish_reason == "stop"
    assert response.text == "fake response from fake-model-a"


@pytest.mark.asyncio
async def test_generate_is_deterministic_across_repeated_calls() -> None:
    gateway = _single_provider_gateway()

    first = await gateway.generate(_request())
    second = await gateway.generate(_request())

    assert first.text == second.text
    assert first.model_used == second.model_used


@pytest.mark.asyncio
async def test_generate_raises_when_no_model_is_registered() -> None:
    gateway = _build_gateway([], {})

    with pytest.raises(NoRoutableCandidateError):
        await gateway.generate(_request())


def test_build_observability_context_propagates_explicit_ids() -> None:
    gateway = _single_provider_gateway()
    request = _request(
        request_id="call-123", trace_id="task-abc", capability_execution_id="task-abc:research:1"
    )

    ctx = gateway._build_observability_context(request)  # noqa: SLF001 - white-box unit test

    assert ctx.request_id == "call-123"
    assert ctx.trace_id == "task-abc"
    assert ctx.capability_execution_id == "task-abc:research:1"


def test_build_observability_context_generates_fallback_ids_when_metadata_is_empty() -> None:
    gateway = _single_provider_gateway()
    request = _request()

    ctx = gateway._build_observability_context(request)  # noqa: SLF001 - white-box unit test

    assert ctx.request_id is not None
    assert ctx.trace_id == ctx.request_id
    assert ctx.capability_execution_id == ctx.request_id


def test_build_observability_context_generates_distinct_ids_per_call() -> None:
    gateway = _single_provider_gateway()

    first = gateway._build_observability_context(_request())  # noqa: SLF001
    second = gateway._build_observability_context(_request())  # noqa: SLF001

    assert first.request_id != second.request_id


@pytest.mark.asyncio
async def test_generate_never_touches_a_second_provider_or_model() -> None:
    """A second, registered-but-not-model-backed provider is never consulted: only model A is
    registered in ModelRegistry (B is a registered provider but has no matching model), so
    RoutingEngine's hard filter alone excludes it before FallbackPolicy ever runs."""
    adapter_a = FakeProviderAdapter(provider_id="fake-provider-a", model_id="fake-model-a")
    adapter_b = FakeProviderAdapter(provider_id="fake-provider-b", model_id="fake-model-b")
    gateway = _build_gateway(
        [_model(model_id="fake-model-a", provider_id="fake-provider-a")],
        {"fake-provider-a": adapter_a, "fake-provider-b": adapter_b},
    )

    await gateway.generate(_request())

    assert adapter_a.call_count == 1
    assert adapter_b.call_count == 0
