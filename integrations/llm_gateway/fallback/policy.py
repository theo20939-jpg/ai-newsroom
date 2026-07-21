"""FallbackPolicy (docs/phase7_architecture_contract.md §5, §6): eligibility filtering, the
dispatch loop, same-candidate retry, and exhaustion.

Wired into RoutingGateway starting at M17 (see integrations/llm_gateway/gateway.py). Proves
cross-provider fallback with ≥2 FakeProviderAdapters (see tests/test_fallback_policy.py).

Scope note: `dispatch()` calls `adapter.generate()` only - this delivery's reduced scope
covers generate() alone; a future milestone would generalize across the other deferred
LLMGateway methods.

Rate limiting placement (M17): §15.2's sequence diagram lists a single "RateLimiter check"
step before RoutingEngine even runs, but RateLimitKey.provider_id is a REQUIRED field (§14) -
composite provider/model/capability rate limiting is structurally impossible before a
candidate is resolved. Implemented here instead, per-candidate, immediately before dispatch -
the same place cost estimation and budget approval already live - constructing a real
composite key list (provider-wide, model-specific, capability-specific, §14 rule 1) from the
actual candidate being attempted. A RateLimitExceededError is treated exactly like a budget
denial: continue to the next candidate, never fail the call outright while alternatives remain
(consistent with §14 rule 3's RateLimitExceededError -> RetryableCapabilityError mapping - a
rate-limited candidate is a transient, try-elsewhere condition, not a terminal one).
`rate_limiter` is optional (default None, meaning "no rate limiting enforced") so this remains
backward compatible with every M15 test, which predates this addition.

Resolved-candidate propagation (M18): `_attempt_candidate()` previously called
`adapter.generate(request)` with the plain, unmodified request - never telling the adapter
which `(provider_id, model_id)` routing/fallback had actually resolved for this attempt. This
was invisible with `FakeProviderAdapter` (each fake test instance is hard-wired to exactly one
model, so it never needed to ask), but breaks down for a real, multi-model provider adapter
(e.g. `OpenAIAdapter`, serving `gpt-5.6-sol`/`-terra`/`-luna` under one `provider_id`), which has
no other way to know which model to call. Fixed by injecting `resolved_provider_id`/
`resolved_model_id` into `request.metadata` immediately before each dispatch attempt - the same
"extend via metadata, never the frozen schema" pattern already used throughout M17 (request_id,
capability_name, priority, excluded_providers, cache_policy), and confirmed cache-key-neutral:
`CacheKeyComponents.normalized_request_hash` (§13.2) already excludes `metadata` entirely, so
this addition cannot perturb cache correctness.
"""
import asyncio
import logging
import random
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from capabilities.errors import BudgetExceededError
from integrations.llm_gateway.cache.coordinator import CacheCoordinator
from integrations.llm_gateway.errors import AllProvidersFailedError, RateLimitExceededError
from integrations.llm_gateway.errors import (
    ProviderModerationBlockedError,
    ProviderPermanentIncompatibleError,
    ProviderTransientError,
)
from integrations.llm_gateway.fallback.health_store import ProviderHealthStore
from integrations.llm_gateway.models.registry import ModelDescriptor, standard_combined_price
from integrations.llm_gateway.observability import ObservabilityContext
from integrations.llm_gateway.protocol import GenerateRequest, GenerateResponse
from integrations.llm_gateway.providers.base import ProviderRegistry
from integrations.llm_gateway.rate_limit.limiter import RateLimiter, RateLimitKey
from integrations.llm_gateway.routing.criteria import FallbackEligibility, RoutingCriteria
from services.budget_guard import BudgetGuard
from services.cost_estimator import CostEstimator

logger = logging.getLogger(__name__)

_BACKOFF_BASE_MS = 250.0
_BACKOFF_CAP_MS = 2000.0


def _observability_log_fields(observability: ObservabilityContext | None) -> dict[str, str | None]:
    """§16.1: every emitted log/metric reads whatever ids it needs from the explicitly-passed
    ObservabilityContext. Returns an empty dict when None was passed."""
    if observability is None:
        return {}
    return {
        "trace_id": observability.trace_id,
        "capability_execution_id": observability.capability_execution_id,
        "request_id": observability.request_id,
    }


class FailureClass(str, Enum):
    TRANSIENT = "transient"  # auth (this attempt only), rate limit, timeout, 5xx
    PERMANENT_INCOMPATIBLE = "permanent_incompatible"  # claimed capability not actually
    # supported, or a moderation block


def _backoff_delay_seconds(attempt_index: int) -> float:
    """Short, capped exponential backoff, full jitter (§6 rule 2): base 250ms, cap 2s."""
    capped_ms = min(_BACKOFF_CAP_MS, _BACKOFF_BASE_MS * (2**attempt_index))
    return random.uniform(0, capped_ms) / 1000  # noqa: S311 - retry jitter, not a security control


@dataclass
class _AttemptOutcome:
    success: bool
    response: GenerateResponse | None
    failure_class: FailureClass | None
    # OpenAI structured-outputs remediation, Track B (docs/openai_structured_outputs_
    # remediation_plan.md): the provider adapter's own already-redacted, safe-to-log exception
    # message (str(exc) - never a raw provider exception, never request/response objects), so a
    # genuine provider rejection reason is no longer discarded before it reaches
    # AllProvidersFailedError / WorkflowStepResult.error. None only when no failure occurred.
    failure_detail: str | None = None


class FallbackPolicy:
    def __init__(
        self,
        provider_registry: ProviderRegistry,
        health_store: ProviderHealthStore,
        cache_coordinator: CacheCoordinator,
        cost_estimator: CostEstimator,
        budget_guard: BudgetGuard,
        *,
        rate_limiter: RateLimiter | None = None,
        max_same_candidate_retries: int = 1,
    ) -> None:
        self._provider_registry = provider_registry
        self._health_store = health_store
        self._cache_coordinator = cache_coordinator
        self._cost_estimator = cost_estimator
        self._budget_guard = budget_guard
        self._rate_limiter = rate_limiter
        self._max_same_candidate_retries = max_same_candidate_retries

    def _build_attempt_sequence(
        self,
        ranked_candidates: list[ModelDescriptor],
        request: GenerateRequest,
        fallback: FallbackEligibility,
        *,
        unbounded: bool = False,
    ) -> list[ModelDescriptor]:
        """§5.3: eligibility filtering. Preserves RoutingPolicy's relative order among
        survivors (rule 3) - never re-ranks. The cost anchor is the CHEAPEST price among the
        filtered candidate set, never the first-ranked candidate's price (§5.1 binding rule).

        Uses `standard_combined_price` (a lightweight per-model rate comparison, the same one
        `LowestCostPolicy` ranks by) rather than `CostEstimator.estimate()` deliberately:
        eligibility filtering runs before any cache lookup (§5.4 step 1), so it must never
        invoke `CostEstimator` itself - a cache hit MUST be served without invoking
        CostEstimator at all (P15), and that guarantee would break if merely *filtering*
        candidates already triggered a CostEstimator call for every one of them.
        """
        if not ranked_candidates:
            return []

        prices: dict[str, Decimal] = {c.model_id: standard_combined_price(c) for c in ranked_candidates}
        cheapest_price = min(prices.values())

        if unbounded:
            survivors = list(ranked_candidates)
        else:
            survivors = []
            for candidate in ranked_candidates:
                price = prices[candidate.model_id]
                if price > cheapest_price * fallback.max_cost_multiplier:
                    continue
                if (
                    fallback.max_additional_cost is not None
                    and (price - cheapest_price) > fallback.max_additional_cost
                ):
                    continue
                survivors.append(candidate)

        return survivors[: fallback.max_fallback_attempts]

    async def _attempt_candidate(
        self,
        request: GenerateRequest,
        candidate: ModelDescriptor,
        observability: ObservabilityContext | None,
    ) -> _AttemptOutcome:
        """§5.4 step 3-4 + §6: up to `max_same_candidate_retries` retries against this same
        candidate before it is considered to have failed. A PERMANENT_INCOMPATIBLE failure
        (including a moderation block) MUST NEVER be retried (§6 rule 2) - the attempt cycle
        ends on the first such failure.
        """
        adapter = self._provider_registry.resolve(candidate.provider_id)
        provider_id, model_id = candidate.provider_id, candidate.model_id

        # M18 gap fix (see module docstring): tell the adapter which candidate routing/
        # fallback actually resolved, via metadata - the only channel available on the frozen
        # GenerateRequest schema. Built once per candidate (not per same-candidate retry
        # attempt), since it doesn't change across those retries.
        resolved_request = request.model_copy(
            update={
                "metadata": {
                    **request.metadata,
                    "resolved_provider_id": provider_id,
                    "resolved_model_id": model_id,
                }
            }
        )

        for attempt_index in range(self._max_same_candidate_retries + 1):
            try:
                response = await adapter.generate(resolved_request)
                return _AttemptOutcome(success=True, response=response, failure_class=None)
            except ProviderModerationBlockedError:
                await self._health_store.mark_runtime_unavailable(provider_id, model_id)
                raise  # §5.4: MUST NOT continue the loop at all for a moderation block
            except ProviderPermanentIncompatibleError as exc:
                await self._health_store.mark_runtime_unavailable(provider_id, model_id)
                return _AttemptOutcome(
                    success=False,
                    response=None,
                    failure_class=FailureClass.PERMANENT_INCOMPATIBLE,
                    failure_detail=str(exc),
                )
            except ProviderTransientError as exc:
                if attempt_index < self._max_same_candidate_retries:
                    backoff_seconds = _backoff_delay_seconds(attempt_index)
                    logger.info(
                        "retry",
                        extra={
                            **_observability_log_fields(observability),
                            "same_candidate_retry_index": attempt_index,
                            "backoff_ms": backoff_seconds * 1000,
                        },
                    )
                    await asyncio.sleep(backoff_seconds)
                    continue
                await self._health_store.mark_unhealthy(provider_id, model_id, ttl_seconds=60)
                return _AttemptOutcome(
                    success=False, response=None, failure_class=FailureClass.TRANSIENT, failure_detail=str(exc)
                )

        raise AssertionError("unreachable - the loop above always returns or raises")

    async def dispatch(
        self,
        request: GenerateRequest,
        ranked_candidates: list[ModelDescriptor],
        criteria: RoutingCriteria,
        observability: ObservabilityContext | None = None,
    ) -> GenerateResponse:
        """§5.3 (eligibility filtering) + §5.4 (dispatch loop) + §5.5 (exhaustion), in order.

        `observability` is optional (default None) for backward compatibility with callers
        that predate its introduction; when given, its ids are attached to the fallback/retry
        log events (§16.1: threaded explicitly, never a contextvar)."""
        sequence = self._build_attempt_sequence(ranked_candidates, request, criteria.fallback)
        return await self._run_sequence(
            request, ranked_candidates, sequence, criteria, observability, widened=False
        )

    async def _run_sequence(
        self,
        request: GenerateRequest,
        ranked_candidates: list[ModelDescriptor],
        sequence: list[ModelDescriptor],
        criteria: RoutingCriteria,
        observability: ObservabilityContext | None,
        *,
        widened: bool,
    ) -> GenerateResponse:
        any_dispatch_attempted = False
        any_budget_denied = False
        attempted_pairs: set[tuple[str, str]] = set()
        last_failure_detail: str | None = None

        for attempt_index, candidate in enumerate(sequence):
            attempted_pairs.add((candidate.provider_id, candidate.model_id))

            # §5.4 step 1: cache first (P15) - a hit skips cost estimate and BudgetGuard entirely.
            cached = await self._cache_coordinator.lookup(
                request, candidate.provider_id, candidate.model_id
            )
            if cached is not None:
                return cached

            # §5.4 step 2: on a miss, estimate cost and obtain BudgetGuard approval.
            estimate = self._cost_estimator.estimate(candidate, request)
            try:
                await self._budget_guard.check(criteria.capability_name, criteria.priority, estimate.worst_case)
            except BudgetExceededError:
                any_budget_denied = True
                continue  # never fail the call outright while cheaper candidates remain untried

            # Rate limit, per candidate (see module docstring for why this lives here rather
            # than as a single pre-routing step). Treated exactly like a budget denial.
            if self._rate_limiter is not None:
                keys = [
                    RateLimitKey(provider_id=candidate.provider_id),
                    RateLimitKey(provider_id=candidate.provider_id, model_id=candidate.model_id),
                    RateLimitKey(provider_id=candidate.provider_id, capability_name=criteria.capability_name),
                ]
                try:
                    await self._rate_limiter.acquire(keys)
                except RateLimitExceededError:
                    any_budget_denied = True
                    continue

            # §5.4 step 3-4: dispatch, with same-candidate retry nested inside the attempt.
            any_dispatch_attempted = True
            outcome = await self._attempt_candidate(request, candidate, observability)
            if outcome.success:
                assert outcome.response is not None
                await self._cache_coordinator.store(
                    request, candidate.provider_id, candidate.model_id, outcome.response
                )
                return outcome.response

            last_failure_detail = outcome.failure_detail
            logger.info(
                "fallback",
                extra={
                    **_observability_log_fields(observability),
                    "attempt_index": attempt_index,
                    "candidate_provider_id": candidate.provider_id,
                    "candidate_model_id": candidate.model_id,
                    "reason": outcome.failure_class.value if outcome.failure_class else "unknown",
                    "failure_detail": outcome.failure_detail,
                },
            )

        # §5.5: exhaustion.
        if criteria.fallback.allow_cost_ceiling_override_on_exhaustion and not widened:
            remaining = [
                c for c in ranked_candidates if (c.provider_id, c.model_id) not in attempted_pairs
            ]
            widened_sequence = self._build_attempt_sequence(
                remaining, request, criteria.fallback, unbounded=True
            )
            if widened_sequence:
                return await self._run_sequence(
                    request, ranked_candidates, widened_sequence, criteria, observability, widened=True
                )

        if not sequence:
            reason = "cost_ceiling_exhausted"
        elif not any_dispatch_attempted and any_budget_denied:
            reason = "all_candidates_budget_denied"
        else:
            reason = "all_candidates_failed"

        # OpenAI structured-outputs remediation, Track B: surface the last attempted candidate's
        # already-redacted, safe-to-log provider rejection detail, when one exists - previously
        # discarded entirely, leaving only this templated string with zero per-candidate detail.
        detail_suffix = f"; last error: {last_failure_detail}" if last_failure_detail else ""
        raise AllProvidersFailedError(
            f"All candidates exhausted for capability '{criteria.capability_name}' "
            f"(objective={criteria.objective.value}, reason={reason}){detail_suffix}",
            reason=reason,
        )
