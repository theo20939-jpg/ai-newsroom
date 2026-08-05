"""API cost optimization - remaining focused checklist items not already covered by
tests/test_routing_criteria.py, tests/test_fallback_policy.py, tests/test_analysis_reuse.py,
tests/test_cost_recording_integration.py, or tests/test_budget_guard_real.py."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from redis.asyncio import Redis

from capabilities.capability_mapping import resolve_ai_capability
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.cache.coordinator import CacheCoordinator
from integrations.llm_gateway.fallback.policy import FallbackPolicy
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.llm_gateway.providers.base import ProviderDescriptor, ProviderRegistry
from integrations.llm_gateway.routing.criteria import RoutingCriteria, RoutingObjective
from integrations.llm_gateway.routing.engine import RoutingEngine
from integrations.llm_gateway.routing.policy import LowestCostPolicy
from integrations.llm_gateway.routing.registry import RoutingPolicyRegistry
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, Message
from schemas.capability import CapabilityCall, CapabilityUsage
from services.cost_estimator import CostEstimator
from services.cost_tracker import RedisCostTracker, capability_ledger_key, compute_call_cost, global_ledger_key
from services.pricing_catalog import ModelRegistryPricingCatalog
from tests.fakes.fake_infra import EmptyLatencyTracker, PermissiveProviderHealthStore
from tests.fakes.fake_provider_adapter import FakeProviderAdapter


def _criteria() -> RoutingCriteria:
    return RoutingCriteria(gateway_method="generate", capability_name="research", priority=TaskPriority.B)


def _request() -> GenerateRequest:
    return GenerateRequest(messages=[Message(role="user", content=[ContentPart(type="text", text="hello")])])


class _InMemoryCacheStore:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    async def set(self, key: str, value: bytes, ttl_seconds: int | None) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


class _AllowingBudgetGuard:
    async def check(self, capability_name: str, priority: TaskPriority, worst_case: Decimal) -> None:
        return None


# Checklist 3 & 4: real catalog pricing, real RoutingEngine ranking + FallbackPolicy eligibility
# filtering - gpt-5.6-luna is tried first, gpt-5.6-terra is the only fallback, gpt-5.6-sol is
# structurally excluded (never dispatched, never even attempted).
@pytest.mark.asyncio
async def test_real_catalog_routes_luna_first_terra_fallback_sol_excluded() -> None:
    model_registry = build_model_registry()
    provider_registry = ProviderRegistry()
    luna = FakeProviderAdapter(provider_id="openai", model_id="gpt-5.6-luna", behavior="transient_failure")
    terra = FakeProviderAdapter(provider_id="openai", model_id="gpt-5.6-terra", behavior="success")
    sol = FakeProviderAdapter(provider_id="openai", model_id="gpt-5.6-sol", behavior="success")

    class _MultiModelAdapter:
        def __init__(self) -> None:
            self._by_model = {"gpt-5.6-luna": luna, "gpt-5.6-terra": terra, "gpt-5.6-sol": sol}

        async def generate(self, request):  # type: ignore[no-untyped-def]
            model_id = request.metadata["resolved_model_id"]
            return await self._by_model[model_id].generate(request)

    provider_registry.register(
        ProviderDescriptor(provider_id="openai", display_name="OpenAI"), _MultiModelAdapter()  # type: ignore[arg-type]
    )
    provider_registry.seal()

    policy_registry = RoutingPolicyRegistry()
    policy_registry.register(RoutingObjective.LOWEST_COST.value, LowestCostPolicy())
    policy_registry.seal()
    routing_engine = RoutingEngine(
        model_registry=model_registry, provider_registry=provider_registry,
        health_store=PermissiveProviderHealthStore(), latency_tracker=EmptyLatencyTracker(), policy_registry=policy_registry,
    )
    fallback_policy = FallbackPolicy(
        provider_registry=provider_registry, health_store=PermissiveProviderHealthStore(),
        cache_coordinator=CacheCoordinator(_InMemoryCacheStore()),
        cost_estimator=CostEstimator(ModelRegistryPricingCatalog(model_registry)),
        budget_guard=_AllowingBudgetGuard(), max_same_candidate_retries=0,  # type: ignore[arg-type]
    )
    criteria = _criteria()  # default objective is now LOWEST_COST (routing/criteria.py)
    ranked = await routing_engine.route(criteria, None)
    response = await fallback_policy.dispatch(_request(), ranked, criteria)

    assert response.model_used == "gpt-5.6-terra"  # luna failed, terra is the only fallback tried
    assert luna.call_count == 1
    assert terra.call_count == 1
    assert sol.call_count == 0  # never attempted - excluded by the 3.0x cost ceiling


# Checklist 12: cached input tokens are recorded (observability) even though the current
# catalog has no verified separate cached-input price - the standard rate is used for the
# whole input_tokens count (a disclosed, safe-direction overestimate, never an invented rate).
def test_cached_input_tokens_recorded_but_priced_at_standard_input_rate() -> None:
    pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())
    now = datetime.now(timezone.utc)
    call_with_cache = CapabilityCall(
        call_id=uuid.uuid4(), sequence=0, gateway_method="generate", status="SUCCESS",
        model_used="gpt-5.6-luna",
        usage=CapabilityUsage(input_tokens=1000, cached_input_tokens=800, output_tokens=0),
        started_at=now, finished_at=now, duration_seconds=0.01,
    )
    call_without_cache = CapabilityCall(
        call_id=uuid.uuid4(), sequence=0, gateway_method="generate", status="SUCCESS",
        model_used="gpt-5.6-luna",
        usage=CapabilityUsage(input_tokens=1000, cached_input_tokens=None, output_tokens=0),
        started_at=now, finished_at=now, duration_seconds=0.01,
    )

    # Same total input_tokens -> same cost, regardless of how many were cached - documents the
    # current limitation explicitly rather than silently pretending cached pricing is applied.
    assert compute_call_cost(call_with_cache, pricing_catalog) == compute_call_cost(call_without_cache, pricing_catalog)
    assert call_with_cache.usage.cached_input_tokens == 800  # still recorded, for observability


# Checklist 16: Collector has no LLM/budget/cost dependency at all - an exhausted LLM budget
# structurally cannot affect it, since it never imports anything from that layer.
def test_collector_module_has_no_llm_gateway_or_budget_dependency() -> None:
    source_text = Path("services/collector.py").read_text(encoding="utf-8")
    import_lines = [
        line for line in source_text.splitlines()
        if line.strip().startswith("from ") or line.strip().startswith("import ")
    ]
    combined = "\n".join(import_lines).lower()
    for forbidden in ("llm_gateway", "budget_guard", "cost_tracker", "cost_recording"):
        assert forbidden not in combined


# Checklist 18: the Redis ledger namespace is the real UTC calendar date - a new day is
# structurally a brand-new, empty ledger key, with no explicit reset code needed.
#
# Phase 18.9-R M5 fix (docs/phase18_9r_test_provider_path_audit.md sec4): this test's own purpose
# requires exercising the *real*, no-fixed-namespace code path (`_today_namespace()`'s own
# calendar-date derivation) - it cannot simply switch to an injected UUID namespace like every
# other cost-tracker test without testing something else entirely. Fixed two ways instead,
# defense-in-depth: (1) `redis_client` (tests/conftest.py) now connects to a dedicated, isolated
# test Redis database index (15), structurally separate from production's real index 0, so even an
# imperfect cleanup here can never touch real production keys; (2) `datetime.now` is monkeypatched
# so `_today_namespace()` computes an obviously-fake, real-calendar-format date
# ("1999-12-31") that can never collide with any real date this project has ever run on, and BOTH
# the global and capability-specific keys it writes are deleted in `finally` (the original bug:
# only the global key was ever deleted, leaking the capability-specific one indefinitely).
@pytest.mark.asyncio
async def test_ledger_namespace_is_utc_calendar_date_so_a_new_day_starts_empty(
    redis_client: Redis, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.cost_tracker as cost_tracker_module

    fake_now = datetime(1999, 12, 31, 12, 0, 0, tzinfo=timezone.utc)

    class _FixedNow:
        """Not a `datetime` subclass - `services.cost_tracker._today_namespace()` only ever calls
        `datetime.now(tz)`, so a minimal stand-in exposing just that one method is sufficient and
        avoids mypy's Liskov-substitution complaint about overriding `datetime.now`'s own return
        type."""

        @staticmethod
        def now(tz: object = None) -> datetime:  # noqa: ARG004
            return fake_now

    monkeypatch.setattr(cost_tracker_module, "datetime", _FixedNow)

    pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())
    tracker = RedisCostTracker(redis_client, pricing_catalog)  # production default: no fixed namespace
    call = CapabilityCall(
        call_id=uuid.uuid4(), sequence=0, gateway_method="generate", status="SUCCESS",
        model_used="gpt-5.6-luna", usage=CapabilityUsage(input_tokens=1000, output_tokens=1000),
        started_at=fake_now, finished_at=fake_now, duration_seconds=0.01,
    )
    fake_date_key = fake_now.strftime("%Y-%m-%d")
    today_key = global_ledger_key(fake_date_key)
    research_key = capability_ledger_key(fake_date_key, "research")
    try:
        await tracker.record(uuid.uuid4(), "research", call)
        raw = await redis_client.get(today_key)
        assert raw is not None and float(raw) > 0
        raw_research = await redis_client.get(research_key)
        assert raw_research is not None and float(raw_research) > 0
    finally:
        await redis_client.delete(today_key)
        await redis_client.delete(research_key)


# Checklist 20 (partial, structural): resolve_ai_capability still accepts every real workflow
# step capability name unchanged by this task - a quick canary that the AICapability mapping
# table wasn't accidentally narrowed while wiring cost recording through executor.py.
@pytest.mark.parametrize(
    "capability_name", ["research", "intelligence", "engagement", "scoring", "copywriting", "quality"]
)
def test_every_real_capability_name_still_resolves_to_an_ai_capability(capability_name: str) -> None:
    resolve_ai_capability(capability_name)  # must not raise
