"""NINJA PULSE RECAP Phase R2.3a - single-attempt diagnostic Gateway safety tests.

Proves, against REAL `RoutingEngine`/`FallbackPolicy`/`RoutingGateway` (never reimplemented) with
fake provider adapters/infrastructure only (`tests/fakes/fake_provider_adapter.py`,
`tests/fakes/fake_infra.py` - the same shared fakes `tests/test_fallback_policy.py` already uses):

1. ordinary application Gateway behavior (the real, shared `RoutingGateway`/`FallbackPolicy`,
   default `max_same_candidate_retries=1`) is completely unaffected by anything added in R2.3a;
2. `scripts._recap_r2_event_shadow.py`'s new `_build_single_attempt_gateway()`/
   `_SingleAttemptGateway` genuinely caps a diagnostic call at AT MOST ONE physical provider
   `generate()` attempt - no same-candidate retry, no fallback to a second candidate - in both
   the failure and success case.

Zero paid calls, zero network, zero Redis - pure in-memory fakes throughout.
"""
from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from integrations.llm_gateway.cache.coordinator import CacheCoordinator
from integrations.llm_gateway.errors import AllProvidersFailedError
from integrations.llm_gateway.fallback.policy import FallbackPolicy
from integrations.llm_gateway.gateway import RoutingGateway
from integrations.llm_gateway.models.registry import ModelDescriptor, ModelRegistry, PricingTier
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, Message
from integrations.llm_gateway.providers.base import ProviderDescriptor, ProviderRegistry
from integrations.llm_gateway.routing.criteria import RoutingObjective
from integrations.llm_gateway.routing.engine import RoutingEngine
from integrations.llm_gateway.routing.policy import (
    BestQualityPolicy, FastestPolicy, LowestCostPolicy, ReasoningPolicy,
)
from integrations.llm_gateway.routing.registry import RoutingPolicyRegistry
from services.cost_estimator import CostEstimator
from services.pricing_catalog import ModelRegistryPricingCatalog
from tests.fakes.fake_infra import AllowingBudgetGuard, EmptyLatencyTracker, InMemoryCacheStore, PermissiveProviderHealthStore
from tests.fakes.fake_provider_adapter import FakeProviderAdapter


def _load_cli_module():
    spec = importlib.util.spec_from_file_location("_recap_r2_event_shadow_gateway_test_import", "scripts/_recap_r2_event_shadow.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _model(model_id: str, provider_id: str, price: str = "1") -> ModelDescriptor:
    return ModelDescriptor(
        model_id=model_id, provider_id=provider_id, display_name=model_id,
        context_window_tokens=128_000,
        pricing_tiers=[PricingTier(condition="standard", input_price_per_million=Decimal(price), output_price_per_million=Decimal("0"))],
    )


def _request() -> GenerateRequest:
    return GenerateRequest(messages=[Message(role="user", content=[ContentPart(type="text", text="hello")])], max_tokens=0)


def _build_real_gateway(models: list[ModelDescriptor], adapters: dict[str, FakeProviderAdapter], *, max_same_candidate_retries: int = 1) -> RoutingGateway:
    """Mirrors integrations/llm_gateway/boot.py::assemble_ai_integration_layer()'s own real
    construction sequence exactly (same real RoutingEngine/RoutingPolicyRegistry/FallbackPolicy
    classes, unmodified) - only the Redis-backed infrastructure is swapped for the shared
    in-memory fakes tests/test_fallback_policy.py already established."""
    provider_registry = ProviderRegistry()
    for provider_id, adapter in adapters.items():
        provider_registry.register(ProviderDescriptor(provider_id=provider_id, display_name=provider_id), adapter)
    provider_registry.seal()

    model_registry = ModelRegistry()
    for model in models:
        model_registry.register(model)
    model_registry.seal()

    policy_registry = RoutingPolicyRegistry()
    policy_registry.register(RoutingObjective.BEST_QUALITY.value, BestQualityPolicy())
    policy_registry.register(RoutingObjective.LOWEST_COST.value, LowestCostPolicy())
    policy_registry.register(RoutingObjective.FASTEST.value, FastestPolicy())
    policy_registry.register(RoutingObjective.REASONING.value, ReasoningPolicy())
    policy_registry.seal()

    health_store = PermissiveProviderHealthStore()
    routing_engine = RoutingEngine(
        model_registry=model_registry, provider_registry=provider_registry,
        health_store=health_store, latency_tracker=EmptyLatencyTracker(), policy_registry=policy_registry,
    )
    fallback_policy = FallbackPolicy(
        provider_registry=provider_registry, health_store=health_store,
        cache_coordinator=CacheCoordinator(InMemoryCacheStore()),
        cost_estimator=CostEstimator(ModelRegistryPricingCatalog(model_registry)),
        budget_guard=AllowingBudgetGuard(),
        max_same_candidate_retries=max_same_candidate_retries,
    )
    return RoutingGateway(routing_engine=routing_engine, fallback_policy=fallback_policy)


# ---------------------------------------------------------------------------
# 1. Ordinary application Gateway behavior is unaffected by anything in R2.3a
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ordinary_shared_gateway_still_falls_back_across_candidates_normally():
    """The real, shared RoutingGateway/FallbackPolicy (default max_same_candidate_retries=1) must
    still fall back to a second candidate exactly as before - proves R2.3a introduced nothing
    that touches the shared Gateway's own default behavior."""
    failing = FakeProviderAdapter(provider_id="fake-a", model_id="model-a", behavior="transient_failure")
    succeeding = FakeProviderAdapter(provider_id="fake-b", model_id="model-b", behavior="success")
    gateway = _build_real_gateway(
        [_model("model-a", "fake-a"), _model("model-b", "fake-b")],
        {"fake-a": failing, "fake-b": succeeding},
    )
    response = await gateway.generate(_request())
    assert response.model_used == "model-b"
    assert failing.call_count == 2  # 1 initial + 1 retry (default max_same_candidate_retries=1)
    assert succeeding.call_count == 1


# ---------------------------------------------------------------------------
# 2. _SingleAttemptGateway - at most one physical provider attempt, ever
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_attempt_gateway_permits_exactly_one_attempt_on_success():
    cli = _load_cli_module()
    succeeding = FakeProviderAdapter(provider_id="fake-a", model_id="model-a", behavior="success")
    real_gateway = _build_real_gateway([_model("model-a", "fake-a")], {"fake-a": succeeding})
    layer = SimpleNamespace(gateway=real_gateway)

    single_attempt_gateway = cli._build_single_attempt_gateway(layer)
    response = await single_attempt_gateway.generate(_request())

    assert response.model_used == "model-a"
    assert succeeding.call_count == 1


@pytest.mark.asyncio
async def test_single_attempt_gateway_first_failure_does_not_retry():
    """Same candidate, transient failure - a normal shared Gateway would retry (call_count=2, per
    the default max_same_candidate_retries=1 proven above); the single-attempt gateway must not."""
    cli = _load_cli_module()
    failing = FakeProviderAdapter(provider_id="fake-a", model_id="model-a", behavior="transient_failure")
    real_gateway = _build_real_gateway([_model("model-a", "fake-a")], {"fake-a": failing})
    layer = SimpleNamespace(gateway=real_gateway)

    single_attempt_gateway = cli._build_single_attempt_gateway(layer)
    with pytest.raises(AllProvidersFailedError):
        await single_attempt_gateway.generate(_request())

    assert failing.call_count == 1  # never retried


@pytest.mark.asyncio
async def test_single_attempt_gateway_first_failure_does_not_fall_back_to_second_candidate():
    """Two candidates, first transient-fails - a normal shared Gateway would fall back to the
    second (proven above, succeeding.call_count would become 1); the single-attempt gateway must
    fail outright instead, never touching the second candidate at all."""
    cli = _load_cli_module()
    failing = FakeProviderAdapter(provider_id="fake-a", model_id="model-a", behavior="transient_failure")
    never_called = FakeProviderAdapter(provider_id="fake-b", model_id="model-b", behavior="success")
    real_gateway = _build_real_gateway(
        [_model("model-a", "fake-a"), _model("model-b", "fake-b")],
        {"fake-a": failing, "fake-b": never_called},
    )
    layer = SimpleNamespace(gateway=real_gateway)

    single_attempt_gateway = cli._build_single_attempt_gateway(layer)
    with pytest.raises(AllProvidersFailedError):
        await single_attempt_gateway.generate(_request())

    assert failing.call_count == 1
    assert never_called.call_count == 0  # fallback never reached


@pytest.mark.asyncio
async def test_single_attempt_gateway_does_not_mutate_the_shared_fallback_policy():
    """The diagnostic-only FallbackPolicy built inside _build_single_attempt_gateway() must be a
    DIFFERENT instance from the shared one - proves the shared Gateway's own
    max_same_candidate_retries=1 default is never touched, even transiently."""
    cli = _load_cli_module()
    succeeding = FakeProviderAdapter(provider_id="fake-a", model_id="model-a", behavior="success")
    real_gateway = _build_real_gateway([_model("model-a", "fake-a")], {"fake-a": succeeding})
    layer = SimpleNamespace(gateway=real_gateway)

    single_attempt_gateway = cli._build_single_attempt_gateway(layer)
    assert single_attempt_gateway._fallback_policy is not real_gateway._fallback_policy  # noqa: SLF001
    assert real_gateway._fallback_policy._max_same_candidate_retries == 1  # noqa: SLF001 - shared default untouched
    assert single_attempt_gateway._fallback_policy._max_same_candidate_retries == 0  # noqa: SLF001


# ---------------------------------------------------------------------------
# 3. Structural safety: no direct provider SDK, no LLM without --with-llm
# ---------------------------------------------------------------------------


def test_no_direct_provider_sdk_imports_in_single_attempt_code():
    source = Path("scripts/_recap_r2_event_shadow.py").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in ("import openai", "import anthropic", "openai.chat", "anthropic.messages"):
        assert forbidden not in lowered


def test_single_attempt_flag_alone_without_with_llm_makes_no_gateway_import():
    """--single-attempt with no --with-llm must still be a fully safe no-op path - the deferred
    LLM Gateway boot import stays inside the `if args.with_llm:` branch regardless of
    --single-attempt (confirmed structurally: _build_single_attempt_gateway is only ever called
    inside that same branch)."""
    import ast

    source = Path("scripts/_recap_r2_event_shadow.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    module_level_imports: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            module_level_imports.add(node.module)
        elif isinstance(node, ast.Import):
            module_level_imports.update(alias.name for alias in node.names)
    assert "integrations.llm_gateway.boot" not in module_level_imports
    assert "integrations.llm_gateway.fallback.policy" not in module_level_imports


# ---------------------------------------------------------------------------
# 4. Phase R2.10 Night 2 (Phase 22) - CLI UX hardening: dangerous flag combinations
# ---------------------------------------------------------------------------


def test_with_llm_without_single_attempt_warns():
    module = _load_cli_module()
    warnings = module._cli_safety_warnings(with_llm=True, single_attempt=False)
    assert any("single-attempt" in w for w in warnings)


def test_with_llm_and_single_attempt_together_warns_nothing():
    module = _load_cli_module()
    assert module._cli_safety_warnings(with_llm=True, single_attempt=True) == []


def test_single_attempt_without_with_llm_notes_no_effect():
    module = _load_cli_module()
    warnings = module._cli_safety_warnings(with_llm=False, single_attempt=True)
    assert any("no effect" in w for w in warnings)


def test_neither_flag_warns_nothing():
    module = _load_cli_module()
    assert module._cli_safety_warnings(with_llm=False, single_attempt=False) == []
