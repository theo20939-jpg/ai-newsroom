"""Tests for integrations.llm_gateway.fallback.policy.FallbackPolicy
(docs/phase7_architecture_contract.md §5, §6). Pure unit tests against fakes - no Redis, no
network - proving cross-provider fallback with ≥2 FakeProviderAdapters, same-candidate retry,
the cheapest-price cost anchor, and exhaustion."""
from collections.abc import Callable
from decimal import Decimal

import pytest

from capabilities.errors import BudgetExceededError
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.cache.coordinator import CacheCoordinator
from integrations.llm_gateway.errors import (
    AllProvidersFailedError,
    ProviderModerationBlockedError,
    ProviderPermanentIncompatibleError,
    RateLimitExceededError,
)
from integrations.llm_gateway.fallback.policy import FailureClass, FallbackPolicy
from integrations.llm_gateway.models.registry import ModelDescriptor, ModelRegistry, PricingTier
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, GenerateResponse, Message
from integrations.llm_gateway.providers.base import ProviderDescriptor, ProviderRegistry
from integrations.llm_gateway.routing.criteria import FallbackEligibility, RoutingCriteria
from services.cost_estimator import CostEstimator
from services.pricing_catalog import ModelRegistryPricingCatalog
from tests.fakes.fake_provider_adapter import FakeProviderAdapter


class _InMemoryCacheStore:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    async def set(self, key: str, value: bytes, ttl_seconds: int | None) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


class _FakeProviderHealthStore:
    def __init__(self) -> None:
        self.unhealthy_marks: list[tuple[str, str]] = []
        self.runtime_unavailable_marks: list[tuple[str, str]] = []
        # Phase 15 runtime reliability fix: records the ttl_seconds passed to each
        # mark_runtime_unavailable() call (None = permanent, unbounded), and every mark_healthy()
        # call - so tests can assert bounded-vs-permanent classification and auto-clear-on-success.
        self.runtime_unavailable_ttls: list[tuple[str, str, int | None]] = []
        self.healthy_marks: list[tuple[str, str]] = []
        self._down: set[tuple[str, str]] = set()

    async def mark_unhealthy(self, provider_id: str, model_id: str, ttl_seconds: int = 60) -> None:
        self.unhealthy_marks.append((provider_id, model_id))
        self._down.add((provider_id, model_id))

    async def mark_runtime_unavailable(
        self, provider_id: str, model_id: str, ttl_seconds: int | None = None
    ) -> None:
        self.runtime_unavailable_marks.append((provider_id, model_id))
        self.runtime_unavailable_ttls.append((provider_id, model_id, ttl_seconds))
        self._down.add((provider_id, model_id))

    async def mark_healthy(self, provider_id: str, model_id: str) -> None:
        self.healthy_marks.append((provider_id, model_id))
        self._down.discard((provider_id, model_id))

    async def is_healthy(self, provider_id: str, model_id: str) -> bool:
        return (provider_id, model_id) not in self._down


class _ConfigurableBudgetGuard:
    def __init__(
        self,
        should_deny: Callable[[Decimal], bool] | None = None,
        deny_first_n_calls: int = 0,
    ) -> None:
        self._should_deny = should_deny or (lambda worst_case: False)
        self._deny_first_n_calls = deny_first_n_calls
        self.check_calls: list[Decimal] = []

    async def check(self, capability_name: str, priority: TaskPriority, worst_case: Decimal) -> None:
        self.check_calls.append(worst_case)
        if len(self.check_calls) <= self._deny_first_n_calls or self._should_deny(worst_case):
            raise BudgetExceededError("denied by fake budget guard")


class _CountingCostEstimator(CostEstimator):
    def __init__(self, pricing_catalog: ModelRegistryPricingCatalog) -> None:
        super().__init__(pricing_catalog)
        self.estimate_calls = 0

    def estimate(self, model, request):  # type: ignore[no-untyped-def]
        self.estimate_calls += 1
        return super().estimate(model, request)


def _model(model_id: str, provider_id: str, input_price: str = "1", output_price: str = "0") -> ModelDescriptor:
    return ModelDescriptor(
        model_id=model_id,
        provider_id=provider_id,
        display_name=model_id,
        context_window_tokens=128_000,
        pricing_tiers=[
            PricingTier(
                condition="standard",
                input_price_per_million=Decimal(input_price),
                output_price_per_million=Decimal(output_price),
            )
        ],
    )


def _request(text: str = "hello world", max_tokens: int | None = 0) -> GenerateRequest:
    return GenerateRequest(
        messages=[Message(role="user", content=[ContentPart(type="text", text=text)])],
        max_tokens=max_tokens,
    )


def _criteria(**overrides: object) -> RoutingCriteria:
    fields: dict[str, object] = {
        "gateway_method": "generate",
        "capability_name": "research",
        "priority": TaskPriority.B,
    }
    fields.update(overrides)
    return RoutingCriteria(**fields)  # type: ignore[arg-type]


class _ConfigurableRateLimiter:
    def __init__(self, deny_first_n_calls: int = 0) -> None:
        self._deny_first_n_calls = deny_first_n_calls
        self.acquire_calls: list[list] = []

    async def acquire(self, keys: list) -> None:  # type: ignore[no-untyped-def]
        self.acquire_calls.append(keys)
        if len(self.acquire_calls) <= self._deny_first_n_calls:
            raise RateLimitExceededError("denied by fake rate limiter")


def _build_policy(
    models: list[ModelDescriptor],
    adapters: dict[str, FakeProviderAdapter],
    *,
    budget_guard: _ConfigurableBudgetGuard | None = None,
    health_store: _FakeProviderHealthStore | None = None,
    cost_estimator: _CountingCostEstimator | None = None,
    rate_limiter: _ConfigurableRateLimiter | None = None,
    max_same_candidate_retries: int = 1,
) -> tuple[FallbackPolicy, _FakeProviderHealthStore, _ConfigurableBudgetGuard, _CountingCostEstimator]:
    provider_registry = ProviderRegistry()
    for provider_id, adapter in adapters.items():
        provider_registry.register(ProviderDescriptor(provider_id=provider_id, display_name=provider_id), adapter)
    provider_registry.seal()

    model_registry = ModelRegistry()
    for model in models:
        model_registry.register(model)
    model_registry.seal()

    resolved_health_store = health_store or _FakeProviderHealthStore()
    resolved_budget_guard = budget_guard or _ConfigurableBudgetGuard()
    resolved_cost_estimator = cost_estimator or _CountingCostEstimator(ModelRegistryPricingCatalog(model_registry))
    cache_coordinator = CacheCoordinator(_InMemoryCacheStore())

    policy = FallbackPolicy(
        provider_registry=provider_registry,
        health_store=resolved_health_store,
        cache_coordinator=cache_coordinator,
        cost_estimator=resolved_cost_estimator,
        budget_guard=resolved_budget_guard,
        rate_limiter=rate_limiter,
        max_same_candidate_retries=max_same_candidate_retries,
    )
    return policy, resolved_health_store, resolved_budget_guard, resolved_cost_estimator


@pytest.mark.asyncio
async def test_cross_provider_fallback_transient_failure_moves_to_next_candidate() -> None:
    """Cross-provider fallback proven with 2 distinct fake provider_ids."""
    failing = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="transient_failure")
    succeeding = FakeProviderAdapter(provider_id="fake-provider-b", model_id="model-b", behavior="success")
    model_a = _model("model-a", "fake-provider-a")
    model_b = _model("model-b", "fake-provider-b")
    policy, health_store, _, _ = _build_policy(
        [model_a, model_b], {"fake-provider-a": failing, "fake-provider-b": succeeding}, max_same_candidate_retries=0
    )

    response = await policy.dispatch(_request(), [model_a, model_b], _criteria())

    assert response.model_used == "model-b"
    assert failing.call_count == 1
    assert succeeding.call_count == 1
    assert ("fake-provider-a", "model-a") in health_store.unhealthy_marks


@pytest.mark.asyncio
async def test_permanent_incompatible_marks_runtime_unavailable_and_continues() -> None:
    failing = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="permanent_incompatible")
    succeeding = FakeProviderAdapter(provider_id="fake-provider-b", model_id="model-b", behavior="success")
    model_a = _model("model-a", "fake-provider-a")
    model_b = _model("model-b", "fake-provider-b")
    policy, health_store, _, _ = _build_policy([model_a, model_b], {"fake-provider-a": failing, "fake-provider-b": succeeding})

    response = await policy.dispatch(_request(), [model_a, model_b], _criteria())

    assert response.model_used == "model-b"
    assert ("fake-provider-a", "model-a") in health_store.runtime_unavailable_marks
    assert failing.call_count == 1  # never retried - permanent_incompatible is never retried
    # A genuinely permanent config failure is marked with no TTL (None) - unbounded, unchanged.
    assert ("fake-provider-a", "model-a", None) in health_store.runtime_unavailable_ttls


@pytest.mark.asyncio
async def test_regional_unavailable_marks_runtime_unavailable_with_a_bounded_ttl_and_continues() -> None:
    """Phase 15 runtime reliability fix (docs/phase15_runtime_reliability_report.md): a
    regional/account-scoped permission failure (403) is marked runtime_unavailable WITH the
    configured cooldown TTL - unlike a genuinely permanent config failure (the test above),
    which gets no TTL at all."""
    failing = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="regional_unavailable")
    succeeding = FakeProviderAdapter(provider_id="fake-provider-b", model_id="model-b", behavior="success")
    model_a = _model("model-a", "fake-provider-a")
    model_b = _model("model-b", "fake-provider-b")
    policy, health_store, _, _ = _build_policy(
        [model_a, model_b], {"fake-provider-a": failing, "fake-provider-b": succeeding}
    )

    response = await policy.dispatch(_request(), [model_a, model_b], _criteria())

    assert response.model_used == "model-b"
    assert ("fake-provider-a", "model-a") in health_store.runtime_unavailable_marks
    assert failing.call_count == 1  # never retried - same as permanent_incompatible
    ttl_entries = [t for t in health_store.runtime_unavailable_ttls if t[:2] == ("fake-provider-a", "model-a")]
    assert len(ttl_entries) == 1
    assert ttl_entries[0][2] == 3600  # the default cooldown, since _build_policy doesn't override it


@pytest.mark.asyncio
async def test_regional_unavailable_cooldown_is_configurable_via_constructor() -> None:
    failing = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="regional_unavailable")
    succeeding = FakeProviderAdapter(provider_id="fake-provider-b", model_id="model-b", behavior="success")
    model_a = _model("model-a", "fake-provider-a")
    model_b = _model("model-b", "fake-provider-b")
    provider_registry = ProviderRegistry()
    provider_registry.register(ProviderDescriptor(provider_id="fake-provider-a", display_name="a"), failing)
    provider_registry.register(ProviderDescriptor(provider_id="fake-provider-b", display_name="b"), succeeding)
    provider_registry.seal()
    model_registry = ModelRegistry()
    model_registry.register(model_a)
    model_registry.register(model_b)
    model_registry.seal()
    health_store = _FakeProviderHealthStore()
    policy = FallbackPolicy(
        provider_registry=provider_registry,
        health_store=health_store,
        cache_coordinator=CacheCoordinator(_InMemoryCacheStore()),
        cost_estimator=_CountingCostEstimator(ModelRegistryPricingCatalog(model_registry)),
        budget_guard=_ConfigurableBudgetGuard(),
        regional_unavailable_cooldown_seconds=120,
    )

    await policy.dispatch(_request(), [model_a, model_b], _criteria())

    ttl_entries = [t for t in health_store.runtime_unavailable_ttls if t[:2] == ("fake-provider-a", "model-a")]
    assert ttl_entries[0][2] == 120


@pytest.mark.asyncio
async def test_successful_dispatch_marks_the_candidate_healthy() -> None:
    """Phase 15 runtime reliability fix: a real successful call clears any stale unhealthy/
    runtime_unavailable state for that exact candidate immediately - the other half of automatic
    recovery, alongside the bounded TTL above."""
    succeeding = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="success")
    model_a = _model("model-a", "fake-provider-a")
    policy, health_store, _, _ = _build_policy([model_a], {"fake-provider-a": succeeding})

    await policy.dispatch(_request(), [model_a], _criteria())

    assert ("fake-provider-a", "model-a") in health_store.healthy_marks


@pytest.mark.asyncio
async def test_moderation_block_raises_immediately_without_further_fallback() -> None:
    blocked = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="moderation_block")
    never_called = FakeProviderAdapter(provider_id="fake-provider-b", model_id="model-b", behavior="success")
    model_a = _model("model-a", "fake-provider-a")
    model_b = _model("model-b", "fake-provider-b")
    policy, health_store, _, _ = _build_policy([model_a, model_b], {"fake-provider-a": blocked, "fake-provider-b": never_called})

    with pytest.raises(ProviderModerationBlockedError):
        await policy.dispatch(_request(), [model_a, model_b], _criteria())

    assert never_called.call_count == 0
    assert ("fake-provider-a", "model-a") in health_store.runtime_unavailable_marks


@pytest.mark.asyncio
async def test_same_candidate_retry_up_to_configured_limit_before_moving_on() -> None:
    failing = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="transient_failure")
    succeeding = FakeProviderAdapter(provider_id="fake-provider-b", model_id="model-b", behavior="success")
    model_a = _model("model-a", "fake-provider-a")
    model_b = _model("model-b", "fake-provider-b")
    policy, _, _, _ = _build_policy(
        [model_a, model_b], {"fake-provider-a": failing, "fake-provider-b": succeeding}, max_same_candidate_retries=2
    )

    response = await policy.dispatch(_request(), [model_a, model_b], _criteria())

    assert response.model_used == "model-b"
    assert failing.call_count == 3  # 1 initial try + 2 retries, all against the same candidate


@pytest.mark.asyncio
async def test_budget_denial_continues_to_next_candidate() -> None:
    never_reached_due_to_deny = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="success")
    succeeding = FakeProviderAdapter(provider_id="fake-provider-b", model_id="model-b", behavior="success")
    model_a = _model("model-a", "fake-provider-a", input_price="1")
    model_b = _model("model-b", "fake-provider-b", input_price="1")
    # deny only the first candidate's check() call; the second is approved
    budget_guard = _ConfigurableBudgetGuard(deny_first_n_calls=1)
    policy, _, _, _ = _build_policy(
        [model_a, model_b],
        {"fake-provider-a": never_reached_due_to_deny, "fake-provider-b": succeeding},
        budget_guard=budget_guard,
    )

    response = await policy.dispatch(_request(), [model_a, model_b], _criteria())

    assert response.model_used == "model-b"
    assert never_reached_due_to_deny.call_count == 0
    assert len(budget_guard.check_calls) == 2


@pytest.mark.asyncio
async def test_cache_hit_skips_cost_estimate_and_budget_check_entirely() -> None:
    adapter = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="success")
    model_a = _model("model-a", "fake-provider-a")
    policy, _, budget_guard, cost_estimator = _build_policy([model_a], {"fake-provider-a": adapter})
    request = _request()

    # Prime the cache by dispatching once for real.
    first = await policy.dispatch(request, [model_a], _criteria())
    assert adapter.call_count == 1
    calls_before_second_dispatch = cost_estimator.estimate_calls
    budget_checks_before_second_dispatch = len(budget_guard.check_calls)

    second = await policy.dispatch(request, [model_a], _criteria())

    assert second.text == first.text
    assert adapter.call_count == 1  # never dispatched again - served from cache
    assert cost_estimator.estimate_calls == calls_before_second_dispatch  # never re-estimated
    assert len(budget_guard.check_calls) == budget_checks_before_second_dispatch  # never re-checked


@pytest.mark.asyncio
async def test_cost_anchor_is_the_cheapest_candidate_never_the_first_ranked() -> None:
    """§5.1 binding rule: eligibility MUST anchor to the cheapest price in the set, not
    whichever candidate happens to be ranked first. `expensive` is passed first in the ranked
    list (simulating a BEST_QUALITY ranking that put it first) but must still be excluded
    based on its price relative to the cheapest candidate, `cheap`."""
    cheap = _model("cheap", "fake-provider-a", input_price="1")
    mid = _model("mid", "fake-provider-a", input_price="2")
    expensive = _model("expensive", "fake-provider-a", input_price="10")
    policy, _, _, _ = _build_policy([cheap, mid, expensive], {"fake-provider-a": FakeProviderAdapter("fake-provider-a", "cheap")})

    # default max_cost_multiplier=3.0: cheapest=1, cap=3 -> mid(2) survives, expensive(10) does not
    sequence = policy._build_attempt_sequence(  # noqa: SLF001 - white-box unit test of the eligibility filter
        [expensive, mid, cheap], _request(), FallbackEligibility()
    )

    assert [m.model_id for m in sequence] == ["mid", "cheap"]


@pytest.mark.asyncio
async def test_exhaustion_raises_all_providers_failed_error_with_all_candidates_failed_reason() -> None:
    failing_a = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="transient_failure")
    failing_b = FakeProviderAdapter(provider_id="fake-provider-b", model_id="model-b", behavior="transient_failure")
    model_a = _model("model-a", "fake-provider-a")
    model_b = _model("model-b", "fake-provider-b")
    policy, _, _, _ = _build_policy(
        [model_a, model_b], {"fake-provider-a": failing_a, "fake-provider-b": failing_b}, max_same_candidate_retries=0
    )

    with pytest.raises(AllProvidersFailedError) as excinfo:
        await policy.dispatch(_request(), [model_a, model_b], _criteria())

    assert excinfo.value.reason == "all_candidates_failed"


@pytest.mark.asyncio
async def test_exhaustion_raises_all_candidates_budget_denied_when_nothing_is_ever_dispatched() -> None:
    adapter = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="success")
    model_a = _model("model-a", "fake-provider-a")
    budget_guard = _ConfigurableBudgetGuard(should_deny=lambda w: True)
    policy, _, _, _ = _build_policy([model_a], {"fake-provider-a": adapter}, budget_guard=budget_guard)

    with pytest.raises(AllProvidersFailedError) as excinfo:
        await policy.dispatch(_request(), [model_a], _criteria())

    assert excinfo.value.reason == "all_candidates_budget_denied"
    assert adapter.call_count == 0


@pytest.mark.asyncio
async def test_allow_cost_ceiling_override_on_exhaustion_retries_with_widened_bounds() -> None:
    cheap_failing = FakeProviderAdapter(provider_id="fake-provider-a", model_id="cheap", behavior="transient_failure")
    expensive_succeeding = FakeProviderAdapter(provider_id="fake-provider-b", model_id="expensive", behavior="success")
    cheap = _model("cheap", "fake-provider-a", input_price="1")
    # 100x the cheapest price - excluded by the default max_cost_multiplier=3.0 unless widened
    expensive = _model("expensive", "fake-provider-b", input_price="100")
    policy, _, _, _ = _build_policy(
        [cheap, expensive],
        {"fake-provider-a": cheap_failing, "fake-provider-b": expensive_succeeding},
        max_same_candidate_retries=0,
    )
    criteria = _criteria(fallback=FallbackEligibility(allow_cost_ceiling_override_on_exhaustion=True))

    response = await policy.dispatch(_request(), [cheap, expensive], criteria)

    assert response.model_used == "expensive"
    assert expensive_succeeding.call_count == 1


@pytest.mark.asyncio
async def test_rate_limit_denial_continues_to_next_candidate() -> None:
    never_reached = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="success")
    succeeding = FakeProviderAdapter(provider_id="fake-provider-b", model_id="model-b", behavior="success")
    model_a = _model("model-a", "fake-provider-a")
    model_b = _model("model-b", "fake-provider-b")
    rate_limiter = _ConfigurableRateLimiter(deny_first_n_calls=1)
    policy, _, _, _ = _build_policy(
        [model_a, model_b],
        {"fake-provider-a": never_reached, "fake-provider-b": succeeding},
        rate_limiter=rate_limiter,
    )

    response = await policy.dispatch(_request(), [model_a, model_b], _criteria())

    assert response.model_used == "model-b"
    assert never_reached.call_count == 0
    assert len(rate_limiter.acquire_calls) == 2


@pytest.mark.asyncio
async def test_rate_limiter_is_called_with_composite_provider_model_capability_keys() -> None:
    adapter = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="success")
    model_a = _model("model-a", "fake-provider-a")
    rate_limiter = _ConfigurableRateLimiter()
    policy, _, _, _ = _build_policy(
        [model_a], {"fake-provider-a": adapter}, rate_limiter=rate_limiter
    )

    await policy.dispatch(_request(), [model_a], _criteria(capability_name="research"))

    assert len(rate_limiter.acquire_calls) == 1
    keys = rate_limiter.acquire_calls[0]
    assert len(keys) == 3
    assert {k.model_id for k in keys} == {None, "model-a"}
    assert {k.capability_name for k in keys} == {None, "research"}
    assert all(k.provider_id == "fake-provider-a" for k in keys)


@pytest.mark.asyncio
async def test_no_rate_limiter_configured_skips_rate_limiting_entirely() -> None:
    adapter = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="success")
    model_a = _model("model-a", "fake-provider-a")
    policy, _, _, _ = _build_policy([model_a], {"fake-provider-a": adapter})  # rate_limiter=None (default)

    response = await policy.dispatch(_request(), [model_a], _criteria())

    assert response.model_used == "model-a"


# ---------------------------------------------------------------------------
# OpenAI structured-outputs remediation, Track B (docs/openai_structured_outputs_
# remediation_plan.md): FallbackPolicy must preserve, not discard, the last attempted
# candidate's already-redacted provider rejection detail. Existing tests above (unmodified)
# are the primary no-regression proof; these are additions, not replacements.
# ---------------------------------------------------------------------------


class _CustomMessageFailingAdapter(FakeProviderAdapter):
    """Raises ProviderPermanentIncompatibleError with a caller-supplied message, instead of
    FakeProviderAdapter's fixed template string - needed to prove the enrichment threads an
    arbitrary (already-redacted-by-the-real-adapter-layer) message through unmodified."""

    def __init__(self, provider_id: str, model_id: str, message: str) -> None:
        super().__init__(provider_id, model_id, behavior="permanent_incompatible")
        self._message = message

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.call_count += 1
        raise ProviderPermanentIncompatibleError(self._message)


@pytest.mark.asyncio
async def test_exhaustion_message_preserves_last_candidates_failure_detail() -> None:
    """The original provider rejection reason must survive into the final, surfaced
    AllProvidersFailedError - previously discarded entirely, leaving only a templated string
    with zero per-candidate detail."""
    failing = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="permanent_incompatible")
    model_a = _model("model-a", "fake-provider-a")
    policy, _, _, _ = _build_policy([model_a], {"fake-provider-a": failing})

    with pytest.raises(AllProvidersFailedError) as excinfo:
        await policy.dispatch(_request(), [model_a], _criteria())

    assert "simulated permanent-incompatible failure" in str(excinfo.value)
    assert excinfo.value.reason == "all_candidates_failed"  # classification unchanged


@pytest.mark.asyncio
async def test_exhaustion_message_does_not_expose_additional_sensitive_data() -> None:
    """This fix only threads through whatever the provider adapter layer already redacted
    upstream (openai_adapter.py's own _redact(), unchanged by this fix, is the sole redaction
    authority) - confirms the fix adds no NEW exposure by passing an already-redacted-looking
    string through unmodified, never re-exposing anything _redact() would have stripped."""
    already_redacted_message = "openai: bad request (code=invalid_request): [REDACTED]"
    failing = _CustomMessageFailingAdapter("fake-provider-a", "model-a", already_redacted_message)
    model_a = _model("model-a", "fake-provider-a")
    policy, _, _, _ = _build_policy([model_a], {"fake-provider-a": failing})

    with pytest.raises(AllProvidersFailedError) as excinfo:
        await policy.dispatch(_request(), [model_a], _criteria())

    assert already_redacted_message in str(excinfo.value)
    assert "sk-" not in str(excinfo.value)
    assert "Bearer" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_attempt_candidate_failure_classification_unchanged_by_detail_enrichment() -> None:
    """White-box: FailureClass classification (TRANSIENT vs PERMANENT_INCOMPATIBLE) is exactly
    what it was before this fix - the new failure_detail field is purely additive on
    _AttemptOutcome, never a replacement for or influence on failure_class."""
    permanent = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="permanent_incompatible")
    transient = FakeProviderAdapter(provider_id="fake-provider-b", model_id="model-b", behavior="transient_failure")
    model_a = _model("model-a", "fake-provider-a")
    model_b = _model("model-b", "fake-provider-b")
    policy, _, _, _ = _build_policy(
        [model_a, model_b],
        {"fake-provider-a": permanent, "fake-provider-b": transient},
        max_same_candidate_retries=0,
    )

    permanent_outcome = await policy._attempt_candidate(_request(), model_a, None)
    transient_outcome = await policy._attempt_candidate(_request(), model_b, None)

    assert permanent_outcome.failure_class == FailureClass.PERMANENT_INCOMPATIBLE
    assert permanent_outcome.failure_detail is not None
    assert transient_outcome.failure_class == FailureClass.TRANSIENT
    assert transient_outcome.failure_detail is not None


@pytest.mark.asyncio
async def test_successful_attempt_has_no_failure_detail() -> None:
    succeeding = FakeProviderAdapter(provider_id="fake-provider-a", model_id="model-a", behavior="success")
    model_a = _model("model-a", "fake-provider-a")
    policy, _, _, _ = _build_policy([model_a], {"fake-provider-a": succeeding})

    outcome = await policy._attempt_candidate(_request(), model_a, None)

    assert outcome.success is True
    assert outcome.failure_class is None
    assert outcome.failure_detail is None
