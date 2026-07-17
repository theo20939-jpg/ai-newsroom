"""Tests for integrations.llm_gateway.routing.engine.RoutingEngine
(docs/phase7_architecture_contract.md §4.3, §4.4). Pure unit tests against fakes - no Redis,
no network - proving the six-step sequence, cross-provider candidate handling (≥2 fake
provider_ids), and RoutingPolicy exception isolation."""
from decimal import Decimal
from typing import Any

import pytest

from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.errors import NoRoutableCandidateError
from integrations.llm_gateway.models.registry import ModelDescriptor, ModelRegistry, PricingTier
from integrations.llm_gateway.providers.base import ProviderDescriptor, ProviderRegistry
from integrations.llm_gateway.routing.criteria import RoutingCriteria
from integrations.llm_gateway.routing.engine import RoutingEngine
from integrations.llm_gateway.routing.latency_tracker import RoutingTelemetrySnapshot
from integrations.llm_gateway.routing.registry import RoutingPolicyRegistry


class _FakeProviderHealthStore:
    def __init__(self) -> None:
        self._unhealthy: set[tuple[str, str]] = set()

    async def mark_unhealthy(self, provider_id: str, model_id: str, ttl_seconds: int = 60) -> None:
        self._unhealthy.add((provider_id, model_id))

    async def mark_runtime_unavailable(self, provider_id: str, model_id: str) -> None:
        self._unhealthy.add((provider_id, model_id))

    async def is_healthy(self, provider_id: str, model_id: str) -> bool:
        return (provider_id, model_id) not in self._unhealthy


class _FakeLatencyTracker:
    def __init__(self, snapshot: RoutingTelemetrySnapshot | None = None) -> None:
        self._snapshot = snapshot if snapshot is not None else RoutingTelemetrySnapshot()

    async def record(self, provider_id: str, model_id: str, latency_ms: float) -> None:
        return None

    async def snapshot(self) -> RoutingTelemetrySnapshot:
        return self._snapshot


class _DummyAdapter:
    """Never called by these tests - ProviderRegistry.register() only stores a reference."""


def _dummy_adapter() -> Any:
    return _DummyAdapter()


class _AlwaysRaisingPolicy:
    def rank(self, candidates, criteria, telemetry):  # type: ignore[no-untyped-def]
        raise RuntimeError("this policy is broken")


def _model(model_id: str, provider_id: str, quality_tier: int = 0, **overrides: object) -> ModelDescriptor:
    fields: dict[str, object] = {
        "model_id": model_id,
        "provider_id": provider_id,
        "display_name": model_id,
        "context_window_tokens": 128_000,
        "quality_tier": quality_tier,
        "pricing_tiers": [
            PricingTier(
                condition="standard",
                input_price_per_million=Decimal("1.00"),
                output_price_per_million=Decimal("2.00"),
            )
        ],
    }
    fields.update(overrides)
    return ModelDescriptor(**fields)  # type: ignore[arg-type]


def _criteria(**overrides: object) -> RoutingCriteria:
    fields: dict[str, object] = {
        "gateway_method": "generate",
        "capability_name": "research",
        "priority": TaskPriority.B,
    }
    fields.update(overrides)
    return RoutingCriteria(**fields)  # type: ignore[arg-type]


def _engine(
    models: list[ModelDescriptor],
    enabled_provider_ids: set[str],
    health_store: _FakeProviderHealthStore | None = None,
    latency_tracker: _FakeLatencyTracker | None = None,
    policy_registry: RoutingPolicyRegistry | None = None,
) -> RoutingEngine:
    model_registry = ModelRegistry()
    for model in models:
        model_registry.register(model)
    model_registry.seal()

    provider_registry = ProviderRegistry()
    for provider_id in enabled_provider_ids:
        provider_registry.register(ProviderDescriptor(provider_id=provider_id, display_name=provider_id), _dummy_adapter())
    provider_registry.seal()

    return RoutingEngine(
        model_registry=model_registry,
        provider_registry=provider_registry,
        health_store=health_store or _FakeProviderHealthStore(),
        latency_tracker=latency_tracker or _FakeLatencyTracker(),
        policy_registry=policy_registry if policy_registry is not None else RoutingPolicyRegistry(),
    )


@pytest.mark.asyncio
async def test_hard_filter_excludes_candidates_missing_required_capability() -> None:
    with_tools = _model("with-tools", "provider-a", supports_tools=True)
    without_tools = _model("without-tools", "provider-a", supports_tools=False)
    engine = _engine([with_tools, without_tools], {"provider-a"})

    ranked = await engine.route(_criteria(requires_tools=True))

    assert [m.model_id for m in ranked] == ["with-tools"]


@pytest.mark.asyncio
async def test_provider_enabled_filter_excludes_candidates_from_a_disabled_provider() -> None:
    enabled_model = _model("enabled-model", "provider-a")
    disabled_model = _model("disabled-model", "provider-b")
    # provider-b is never registered in ProviderRegistry -> is_enabled("provider-b") is False
    engine = _engine([enabled_model, disabled_model], {"provider-a"})

    ranked = await engine.route(_criteria())

    assert [m.model_id for m in ranked] == ["enabled-model"]


@pytest.mark.asyncio
async def test_exclusion_filter_excludes_caller_excluded_providers() -> None:
    model_a = _model("model-a", "provider-a")
    model_b = _model("model-b", "provider-b")
    engine = _engine([model_a, model_b], {"provider-a", "provider-b"})

    ranked = await engine.route(_criteria(excluded_providers=["provider-a"]))

    assert [m.model_id for m in ranked] == ["model-b"]


@pytest.mark.asyncio
async def test_health_filter_excludes_unhealthy_candidates() -> None:
    healthy_model = _model("healthy-model", "provider-a")
    unhealthy_model = _model("unhealthy-model", "provider-a")
    health_store = _FakeProviderHealthStore()
    await health_store.mark_unhealthy("provider-a", "unhealthy-model")
    engine = _engine([healthy_model, unhealthy_model], {"provider-a"}, health_store=health_store)

    ranked = await engine.route(_criteria())

    assert [m.model_id for m in ranked] == ["healthy-model"]


@pytest.mark.asyncio
async def test_zero_candidates_raises_no_routable_candidate_error() -> None:
    model = _model("model-a", "provider-a", supports_vision=False)
    engine = _engine([model], {"provider-a"})

    with pytest.raises(NoRoutableCandidateError):
        await engine.route(_criteria(requires_vision=True))


@pytest.mark.asyncio
async def test_preference_ranking_orders_survivors_by_best_quality_objective() -> None:
    low = _model("low", "provider-a", quality_tier=10)
    high = _model("high", "provider-a", quality_tier=90)
    engine = _engine([low, high], {"provider-a"})

    ranked = await engine.route(_criteria(objective="best_quality"))

    assert [m.model_id for m in ranked] == ["high", "low"]


@pytest.mark.asyncio
async def test_cross_provider_candidates_both_appear_when_healthy_and_enabled() -> None:
    model_a = _model("model-a", "fake-provider-a", quality_tier=50)
    model_b = _model("model-b", "fake-provider-b", quality_tier=60)
    engine = _engine([model_a, model_b], {"fake-provider-a", "fake-provider-b"})

    ranked = await engine.route(_criteria(objective="best_quality"))

    assert {m.model_id for m in ranked} == {"model-a", "model-b"}
    assert ranked[0].model_id == "model-b"  # higher quality_tier ranks first


@pytest.mark.asyncio
async def test_policy_failure_falls_back_to_the_built_in_default_and_never_propagates() -> None:
    low = _model("low", "provider-a", quality_tier=10)
    high = _model("high", "provider-a", quality_tier=90)
    policy_registry = RoutingPolicyRegistry()
    policy_registry.register("best_quality", _AlwaysRaisingPolicy())
    policy_registry.seal()
    engine = _engine([low, high], {"provider-a"}, policy_registry=policy_registry)

    ranked = await engine.route(_criteria(objective="best_quality"))  # must not raise

    assert [m.model_id for m in ranked] == ["high", "low"]  # built-in BestQualityPolicy fallback


@pytest.mark.asyncio
async def test_unregistered_objective_silently_uses_the_built_in_default() -> None:
    low = _model("low", "provider-a", quality_tier=10)
    high = _model("high", "provider-a", quality_tier=90)
    engine = _engine([low, high], {"provider-a"}, policy_registry=RoutingPolicyRegistry())

    ranked = await engine.route(_criteria(objective="best_quality"))

    assert [m.model_id for m in ranked] == ["high", "low"]


@pytest.mark.asyncio
async def test_preferred_model_is_promoted_to_the_front_even_when_ranked_lower() -> None:
    """§4.1 rule 1: preferred_model is advisory, never a hard filter - here it overrides the
    objective's own ranking (best_quality would otherwise put "high" first)."""
    low = _model("low", "provider-a", quality_tier=10)
    high = _model("high", "provider-a", quality_tier=90)
    engine = _engine([low, high], {"provider-a"})

    ranked = await engine.route(_criteria(objective="best_quality", preferred_model="low"))

    assert [m.model_id for m in ranked] == ["low", "high"]


@pytest.mark.asyncio
async def test_preferred_model_not_among_survivors_is_silently_skipped_never_an_error() -> None:
    low = _model("low", "provider-a", quality_tier=10)
    high = _model("high", "provider-a", quality_tier=90)
    engine = _engine([low, high], {"provider-a"})

    ranked = await engine.route(_criteria(objective="best_quality", preferred_model="does-not-exist"))

    assert [m.model_id for m in ranked] == ["high", "low"]  # unchanged, normal ranking


@pytest.mark.asyncio
async def test_preferred_provider_is_promoted_when_preferred_model_is_unset() -> None:
    model_a = _model("model-a", "provider-a", quality_tier=90)
    model_b = _model("model-b", "provider-b", quality_tier=10)
    engine = _engine([model_a, model_b], {"provider-a", "provider-b"})

    ranked = await engine.route(_criteria(objective="best_quality", preferred_provider="provider-b"))

    assert [m.model_id for m in ranked] == ["model-b", "model-a"]


@pytest.mark.asyncio
async def test_preferred_model_takes_priority_over_preferred_provider_when_both_set() -> None:
    model_a = _model("model-a", "provider-a", quality_tier=90)
    model_b = _model("model-b", "provider-b", quality_tier=10)
    engine = _engine([model_a, model_b], {"provider-a", "provider-b"})

    ranked = await engine.route(
        _criteria(objective="best_quality", preferred_model="model-a", preferred_provider="provider-b")
    )

    assert [m.model_id for m in ranked] == ["model-a", "model-b"]
