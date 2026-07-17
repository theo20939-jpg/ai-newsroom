"""M20: cross-cutting end-to-end and regression validation for the AI Integration Layer
(docs/phase7_architecture_contract.md §15.2's full pipeline).

Per-component behavior already has its own dedicated unit/integration test suite
(test_routing_engine.py, test_fallback_policy.py, test_cache_coordinator.py,
test_cost_estimator.py, test_budget_guard_real.py, test_rate_limiter.py,
test_provider_health_store.py), and tests/test_routing_gateway_pipeline.py already proves most
of RoutingGateway.generate()'s pipeline wiring using permissive, always-healthy fakes. This
file's job is different and narrower: prove properties that only show up when REAL,
cross-call-persistent infrastructure (real Redis-backed CacheStore/ProviderHealthStore) is
driven through the full real `RoutingGateway.generate()` pipeline more than once - properties a
permissive fake can never demonstrate because it never actually remembers anything between
calls. No real network call anywhere: every provider is a FakeProviderAdapter.
"""
import uuid
from decimal import Decimal

import pytest
from redis.asyncio import Redis

from integrations.llm_gateway.boot import validate_retry_ceiling
from integrations.llm_gateway.cache.coordinator import CacheCoordinator
from integrations.llm_gateway.cache.store import RedisCacheStore
from integrations.llm_gateway.errors import AllProvidersFailedError, RetryCeilingExceededError
from integrations.llm_gateway.fallback.health_store import RedisProviderHealthStore
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


def _unique_id(label: str) -> str:
    return f"{label}-{uuid.uuid4()}"


def _model(
    model_id: str, provider_id: str, *, combined_price: Decimal, quality_tier: int = 0
) -> ModelDescriptor:
    half = combined_price / 2
    return ModelDescriptor(
        model_id=model_id,
        provider_id=provider_id,
        display_name=model_id,
        context_window_tokens=128_000,
        quality_tier=quality_tier,
        pricing_tiers=[
            PricingTier(condition="standard", input_price_per_million=half, output_price_per_million=half)
        ],
    )


def _build_gateway(
    models: list[ModelDescriptor],
    adapters: dict[str, FakeProviderAdapter],
    *,
    health_store: object,
    cache_coordinator: CacheCoordinator,
    budget_guard: object = None,
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
        health_store=health_store,  # type: ignore[arg-type]
        latency_tracker=EmptyLatencyTracker(),
        policy_registry=RoutingPolicyRegistry(),
    )
    fallback_policy = FallbackPolicy(
        provider_registry=providers,
        health_store=health_store,  # type: ignore[arg-type]
        cache_coordinator=cache_coordinator,
        cost_estimator=CostEstimator(ModelRegistryPricingCatalog(model_registry)),
        budget_guard=budget_guard or AllowingBudgetGuard(),  # type: ignore[arg-type]
    )
    return RoutingGateway(routing_engine=routing_engine, fallback_policy=fallback_policy)


def _request() -> GenerateRequest:
    return GenerateRequest(messages=[Message(role="user", content=[ContentPart(type="text", text="hello")])])


# ---------------------------------------------------------------------------
# 1. Cache skip, proven against a REAL Redis-backed CacheStore (not the in-memory fake) -
#    real cross-process-shaped serialization/deserialization, not just a dict lookup.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_skips_cost_and_budget_against_real_redis_cache_store(redis_client: Redis) -> None:
    provider_id, model_id = _unique_id("provider"), _unique_id("model")
    adapter = FakeProviderAdapter(provider_id=provider_id, model_id=model_id, behavior="success")
    cache_coordinator = CacheCoordinator(RedisCacheStore(redis_client))
    gateway = _build_gateway(
        [_model(model_id, provider_id, combined_price=Decimal("1"))],
        {provider_id: adapter},
        health_store=PermissiveProviderHealthStore(),
        cache_coordinator=cache_coordinator,
    )
    request = _request()

    first = await gateway.generate(request)
    second = await gateway.generate(request)

    assert second.text == first.text
    assert adapter.call_count == 1  # the second call was served entirely from real Redis


# ---------------------------------------------------------------------------
# 2. Fallback eligibility is anchored to the CHEAPEST candidate in the filtered set, never to
#    whichever candidate the objective ranked first - proven through the full real
#    gateway.generate() pipeline (RoutingGateway.generate() always routes under the default
#    BEST_QUALITY objective, since no Capability yet threads a different one through
#    RoutingCriteria.objective - the exact scenario §5.1's binding cost-anchor rule exists for).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_cost_anchor_is_cheapest_not_first_ranked_end_to_end() -> None:
    expensive_provider, expensive_model = _unique_id("provider"), _unique_id("model")
    mid_provider, mid_model = _unique_id("provider"), _unique_id("model")
    cheap_provider, cheap_model = _unique_id("provider"), _unique_id("model")

    # BEST_QUALITY ranks [expensive(100), mid(50), cheap(1)] first-to-last - expensive is
    # ranked FIRST despite costing 4x the cheapest. Correct anchor (cheapest=$1) => eligibility
    # bound = 3x$1=$3 => expensive ($4) is excluded; mid ($2.5) and cheap ($1) survive. A wrong
    # "anchor to first-ranked" implementation would instead bound at 3x$4=$12 and never exclude
    # expensive at all.
    expensive = FakeProviderAdapter(provider_id=expensive_provider, model_id=expensive_model, behavior="success")
    mid = FakeProviderAdapter(provider_id=mid_provider, model_id=mid_model, behavior="success")
    cheap = FakeProviderAdapter(provider_id=cheap_provider, model_id=cheap_model, behavior="success")

    gateway = _build_gateway(
        [
            _model(expensive_model, expensive_provider, combined_price=Decimal("4"), quality_tier=100),
            _model(mid_model, mid_provider, combined_price=Decimal("2.5"), quality_tier=50),
            _model(cheap_model, cheap_provider, combined_price=Decimal("1"), quality_tier=1),
        ],
        {expensive_provider: expensive, mid_provider: mid, cheap_provider: cheap},
        health_store=PermissiveProviderHealthStore(),
        cache_coordinator=CacheCoordinator(InMemoryCacheStore()),
    )

    response = await gateway.generate(_request())

    assert response.model_used == mid_model  # first ELIGIBLE candidate in rank order, not first-ranked
    assert expensive.call_count == 0  # excluded by eligibility filtering entirely - never attempted
    assert mid.call_count == 1
    assert cheap.call_count == 0  # never reached; mid already succeeded


# ---------------------------------------------------------------------------
# 3. Cross-provider TRANSIENT fallback + unhealthy-TTL-skip on a REPEAT call, proven against
#    real Redis-backed ProviderHealthStore - a permissive fake cannot demonstrate this because
#    it never actually remembers a mark between two separate generate() calls.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unhealthy_mark_from_one_call_skips_that_provider_on_the_next_call(redis_client: Redis) -> None:
    failing_provider, failing_model = _unique_id("provider"), _unique_id("model")
    healthy_provider, healthy_model = _unique_id("provider"), _unique_id("model")
    health_store = RedisProviderHealthStore(redis_client)
    try:
        failing = FakeProviderAdapter(provider_id=failing_provider, model_id=failing_model, behavior="transient_failure")
        healthy = FakeProviderAdapter(provider_id=healthy_provider, model_id=healthy_model, behavior="success")
        gateway = _build_gateway(
            [
                _model(failing_model, failing_provider, combined_price=Decimal("1")),
                _model(healthy_model, healthy_provider, combined_price=Decimal("1")),
            ],
            {failing_provider: failing, healthy_provider: healthy},
            health_store=health_store,
            cache_coordinator=CacheCoordinator(InMemoryCacheStore()),
        )

        first = await gateway.generate(_request())
        assert first.model_used == healthy_model
        calls_after_first_generate = failing.call_count
        assert calls_after_first_generate >= 1  # attempted (and marked unhealthy) on the first call

        second = await gateway.generate(_request())

        assert second.model_used == healthy_model
        # The health filter (RoutingEngine step 4) excluded `failing` entirely on this repeat
        # call - it was never attempted again, proving the Redis-backed mark from call 1
        # persisted and was actually consulted, not just written and ignored.
        assert failing.call_count == calls_after_first_generate
    finally:
        await redis_client.delete(health_store._redis_key(failing_provider, failing_model))  # noqa: SLF001
        await redis_client.delete(health_store._redis_key(healthy_provider, healthy_model))  # noqa: SLF001


# ---------------------------------------------------------------------------
# 4. Exhaustion raises AllProvidersFailedError with the correct reason code.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exhaustion_raises_all_providers_failed_error_with_all_candidates_failed_reason() -> None:
    provider_a, model_a = _unique_id("provider"), _unique_id("model")
    provider_b, model_b = _unique_id("provider"), _unique_id("model")
    failing_a = FakeProviderAdapter(provider_id=provider_a, model_id=model_a, behavior="transient_failure")
    failing_b = FakeProviderAdapter(provider_id=provider_b, model_id=model_b, behavior="transient_failure")
    gateway = _build_gateway(
        [_model(model_a, provider_a, combined_price=Decimal("1")), _model(model_b, provider_b, combined_price=Decimal("1"))],
        {provider_a: failing_a, provider_b: failing_b},
        health_store=PermissiveProviderHealthStore(),
        cache_coordinator=CacheCoordinator(InMemoryCacheStore()),
    )

    with pytest.raises(AllProvidersFailedError) as excinfo:
        await gateway.generate(_request())

    assert excinfo.value.reason == "all_candidates_failed"


# ---------------------------------------------------------------------------
# 5. Retry-multiplication ceiling, exercised against the SAME defaults the real boot-assembled
#    FallbackPolicy actually uses (max_fallback_attempts=3, max_same_candidate_retries=1, per
#    FallbackEligibility's and FallbackPolicy's own production defaults) - the arithmetic a real
#    boot path would run once a concrete Capability exists to register (§6 rule 4). No
#    CapabilityRegistry enumeration exists yet to call this automatically (documented at M19 as
#    a correctly-deferred gap - CapabilityRegistry exposes no iteration API), so this proves the
#    function itself gates correctly against production-shaped values rather than exercising the
#    (nonexistent) automatic call site.
# ---------------------------------------------------------------------------


def test_retry_ceiling_passes_for_the_real_boot_defaults() -> None:
    validate_retry_ceiling(  # must not raise
        workflow_retry_max_attempts=2,
        max_fallback_attempts=3,  # FallbackEligibility's production default
        max_same_candidate_retries=1,  # FallbackPolicy's production default
    )


def test_retry_ceiling_rejects_a_capability_config_that_would_exceed_it_at_the_real_boot_defaults() -> None:
    with pytest.raises(RetryCeilingExceededError):
        validate_retry_ceiling(
            workflow_retry_max_attempts=6,
            max_fallback_attempts=3,  # FallbackEligibility's production default
            max_same_candidate_retries=1,  # FallbackPolicy's production default
        )  # 6 x 3 x 2 = 36 > ceiling 30

