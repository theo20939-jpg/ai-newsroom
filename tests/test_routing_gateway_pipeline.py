"""M17: full-pipeline tests for integrations.llm_gateway.gateway.RoutingGateway.generate()
(docs/phase7_architecture_contract.md §15.2). Per-component behavior (routing, fallback,
cache, cost, budget, rate limiting) already has its own dedicated tests
(test_routing_engine.py, test_fallback_policy.py, test_cache_coordinator.py,
test_cost_estimator.py, test_budget_guard_real.py, test_rate_limiter.py) - this file's job is
proving RoutingGateway.generate() correctly builds RoutingCriteria from a real GenerateRequest
and threads it end to end through RoutingEngine -> FallbackPolicy, not re-testing each
component's own internal logic.
"""
from decimal import Decimal
from typing import Any

import pytest

from capabilities.errors import BudgetExceededError
from integrations.llm_gateway.cache.coordinator import CacheCoordinator
from integrations.llm_gateway.errors import AllProvidersFailedError, RateLimitExceededError
from integrations.llm_gateway.fallback.policy import FallbackPolicy
from integrations.llm_gateway.gateway import RoutingGateway
from integrations.llm_gateway.models.registry import ModelDescriptor, ModelRegistry, PricingTier
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, Message, ToolDefinition
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


def _model(model_id: str, provider_id: str, supports_tools: bool = False) -> ModelDescriptor:
    return ModelDescriptor(
        model_id=model_id,
        provider_id=provider_id,
        display_name=model_id,
        context_window_tokens=128_000,
        supports_tools=supports_tools,
        pricing_tiers=[
            PricingTier(
                condition="standard", input_price_per_million=Decimal("1"), output_price_per_million=Decimal("0")
            )
        ],
    )


class _ConfigurableBudgetGuard:
    def __init__(self, deny_first_n_calls: int = 0) -> None:
        self._deny_first_n_calls = deny_first_n_calls
        self.check_calls = 0

    async def check(self, capability_name: str, priority: Any, worst_case: Decimal) -> None:
        self.check_calls += 1
        if self.check_calls <= self._deny_first_n_calls:
            raise BudgetExceededError("denied by fake")


class _ConfigurableRateLimiter:
    def __init__(self, deny_first_n_calls: int = 0) -> None:
        self._deny_first_n_calls = deny_first_n_calls
        self.acquire_calls = 0

    async def acquire(self, keys: list[Any]) -> None:
        self.acquire_calls += 1
        if self.acquire_calls <= self._deny_first_n_calls:
            raise RateLimitExceededError("denied by fake")


def _build_gateway(
    models: list[ModelDescriptor],
    adapters: dict[str, FakeProviderAdapter],
    *,
    budget_guard: Any = None,
    rate_limiter: Any = None,
    cost_estimator: Any = None,
    max_same_candidate_retries: int = 1,
) -> RoutingGateway:
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
        policy_registry=RoutingPolicyRegistry(),
    )
    fallback_policy = FallbackPolicy(
        provider_registry=providers,
        health_store=PermissiveProviderHealthStore(),
        cache_coordinator=CacheCoordinator(InMemoryCacheStore()),
        cost_estimator=cost_estimator or CostEstimator(ModelRegistryPricingCatalog(model_registry)),
        budget_guard=budget_guard or AllowingBudgetGuard(),
        rate_limiter=rate_limiter,
        max_same_candidate_retries=max_same_candidate_retries,
    )
    return RoutingGateway(routing_engine=routing_engine, fallback_policy=fallback_policy)


def _request(**metadata: object) -> GenerateRequest:
    return GenerateRequest(
        messages=[Message(role="user", content=[ContentPart(type="text", text="hello")])],
        metadata=metadata,
    )


@pytest.mark.asyncio
async def test_full_pipeline_cross_provider_fallback_via_generate() -> None:
    """Cross-provider fallback proven end to end through generate() itself, not just
    FallbackPolicy.dispatch() directly - the whole RoutingGateway -> RoutingEngine ->
    FallbackPolicy chain is exercised."""
    failing = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="transient_failure")
    succeeding = FakeProviderAdapter(provider_id="fake-provider-b", model_id="model-b", behavior="success")
    gateway = _build_gateway(
        [_model("model-a", "fake-provider-a"), _model("model-b", "fake-provider-b")],
        {"fake-provider-a": failing, "fake-provider-b": succeeding},
        max_same_candidate_retries=0,  # isolate cross-candidate fallback from same-candidate retry (§6)
    )

    response = await gateway.generate(_request())

    assert response.model_used == "model-b"
    assert failing.call_count == 1
    assert succeeding.call_count == 1


@pytest.mark.asyncio
async def test_full_pipeline_cache_hit_skips_cost_and_budget_via_generate() -> None:
    adapter = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="success")
    budget_guard = _ConfigurableBudgetGuard()
    gateway = _build_gateway([_model("model-a", "fake-provider-a")], {"fake-provider-a": adapter}, budget_guard=budget_guard)
    request = _request()

    first = await gateway.generate(request)
    calls_after_first = budget_guard.check_calls
    second = await gateway.generate(request)

    assert second.text == first.text
    assert adapter.call_count == 1  # never dispatched twice - second call served from cache
    assert budget_guard.check_calls == calls_after_first  # never re-checked


@pytest.mark.asyncio
async def test_full_pipeline_budget_denial_continues_fallback_via_generate() -> None:
    never_reached = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="success")
    succeeding = FakeProviderAdapter(provider_id="fake-provider-b", model_id="model-b", behavior="success")
    budget_guard = _ConfigurableBudgetGuard(deny_first_n_calls=1)
    gateway = _build_gateway(
        [_model("model-a", "fake-provider-a"), _model("model-b", "fake-provider-b")],
        {"fake-provider-a": never_reached, "fake-provider-b": succeeding},
        budget_guard=budget_guard,
    )

    response = await gateway.generate(_request())

    assert response.model_used == "model-b"
    assert never_reached.call_count == 0


@pytest.mark.asyncio
async def test_full_pipeline_rate_limit_denial_continues_fallback_via_generate() -> None:
    never_reached = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="success")
    succeeding = FakeProviderAdapter(provider_id="fake-provider-b", model_id="model-b", behavior="success")
    rate_limiter = _ConfigurableRateLimiter(deny_first_n_calls=1)
    gateway = _build_gateway(
        [_model("model-a", "fake-provider-a"), _model("model-b", "fake-provider-b")],
        {"fake-provider-a": never_reached, "fake-provider-b": succeeding},
        rate_limiter=rate_limiter,
    )

    response = await gateway.generate(_request())

    assert response.model_used == "model-b"
    assert never_reached.call_count == 0
    assert rate_limiter.acquire_calls == 2


@pytest.mark.asyncio
async def test_full_pipeline_exhaustion_raises_all_providers_failed_error() -> None:
    failing_a = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="transient_failure")
    failing_b = FakeProviderAdapter(provider_id="fake-provider-b", model_id="model-b", behavior="transient_failure")
    gateway = _build_gateway(
        [_model("model-a", "fake-provider-a"), _model("model-b", "fake-provider-b")],
        {"fake-provider-a": failing_a, "fake-provider-b": failing_b},
    )

    with pytest.raises(AllProvidersFailedError):
        await gateway.generate(_request())


@pytest.mark.asyncio
async def test_capability_name_and_priority_travel_via_metadata_to_budget_guard() -> None:
    adapter = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="success")

    class _RecordingBudgetGuard:
        def __init__(self) -> None:
            self.calls: list[tuple[str, Any, Decimal]] = []

        async def check(self, capability_name: str, priority: Any, worst_case: Decimal) -> None:
            self.calls.append((capability_name, priority, worst_case))

    guard = _RecordingBudgetGuard()
    gateway = _build_gateway([_model("model-a", "fake-provider-a")], {"fake-provider-a": adapter}, budget_guard=guard)

    await gateway.generate(_request(capability_name="research", priority="A"))

    assert len(guard.calls) == 1
    assert guard.calls[0][0] == "research"
    assert guard.calls[0][1].value == "A"


@pytest.mark.asyncio
async def test_requires_tools_hard_filter_works_end_to_end() -> None:
    with_tools = FakeProviderAdapter(provider_id="fake-provider-a", model_id="with-tools", behavior="success")
    without_tools_adapter = FakeProviderAdapter(provider_id="fake-provider-b", model_id="without-tools", behavior="success")
    gateway = _build_gateway(
        [
            _model("with-tools", "fake-provider-a", supports_tools=True),
            _model("without-tools", "fake-provider-b", supports_tools=False),
        ],
        {"fake-provider-a": with_tools, "fake-provider-b": without_tools_adapter},
    )
    request = GenerateRequest(
        messages=[Message(role="user", content=[ContentPart(type="text", text="hi")])],
        tools=[ToolDefinition(name="search", description="search the web", parameters_schema={"type": "object"})],
    )

    response = await gateway.generate(request)

    assert response.model_used == "with-tools"
    assert without_tools_adapter.call_count == 0


@pytest.mark.asyncio
async def test_excluded_providers_hard_filter_works_end_to_end() -> None:
    excluded = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="success")
    included = FakeProviderAdapter(provider_id="fake-provider-b", model_id="model-b", behavior="success")
    gateway = _build_gateway(
        [_model("model-a", "fake-provider-a"), _model("model-b", "fake-provider-b")],
        {"fake-provider-a": excluded, "fake-provider-b": included},
    )

    response = await gateway.generate(_request(excluded_providers=["fake-provider-a"]))

    assert response.model_used == "model-b"
    assert excluded.call_count == 0


@pytest.mark.asyncio
async def test_preferred_model_promotion_works_end_to_end() -> None:
    preferred = FakeProviderAdapter(provider_id="fake-provider-a", model_id="preferred-model", behavior="success")
    other = FakeProviderAdapter(provider_id="fake-provider-b", model_id="other-model", behavior="success")
    gateway = _build_gateway(
        [_model("preferred-model", "fake-provider-a"), _model("other-model", "fake-provider-b")],
        {"fake-provider-a": preferred, "fake-provider-b": other},
    )
    request = GenerateRequest(
        messages=[Message(role="user", content=[ContentPart(type="text", text="hi")])],
        preferred_model="preferred-model",
    )

    response = await gateway.generate(request)

    assert response.model_used == "preferred-model"
    assert other.call_count == 0
