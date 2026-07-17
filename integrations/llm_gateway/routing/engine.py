"""RoutingEngine (docs/phase7_architecture_contract.md §4.3, §4.4): the canonical
filter-and-rank sequence, executed in this exact order for every routed call.

RoutingEngine MUST NOT dispatch to a ProviderAdapter itself - its output (a ranked candidate
list) is handed to FallbackPolicy (§5), which owns everything from eligibility filtering
onward. Wired into RoutingGateway starting at M17 (see integrations/llm_gateway/gateway.py).
"""
import logging

from integrations.llm_gateway.errors import NoRoutableCandidateError, UnknownRoutingObjectiveError
from integrations.llm_gateway.fallback.health_store import ProviderHealthStore
from integrations.llm_gateway.models.registry import ModelDescriptor, ModelRegistry
from integrations.llm_gateway.observability import ObservabilityContext
from integrations.llm_gateway.providers.base import ProviderRegistry
from integrations.llm_gateway.routing.criteria import RoutingCriteria, RoutingObjective
from integrations.llm_gateway.routing.latency_tracker import LatencyTracker, RoutingTelemetrySnapshot
from integrations.llm_gateway.routing.policy import (
    BestQualityPolicy,
    FastestPolicy,
    LowestCostPolicy,
    ReasoningPolicy,
    RoutingPolicy,
)
from integrations.llm_gateway.routing.registry import RoutingPolicyRegistry

logger = logging.getLogger(__name__)


def _observability_log_fields(observability: ObservabilityContext | None) -> dict[str, str | None]:
    """§16.1: every emitted log/metric reads whatever ids it needs from the explicitly-passed
    ObservabilityContext. Returns an empty dict when None was passed, so callers that predate
    its introduction still produce valid (if less-attributed) log events."""
    if observability is None:
        return {}
    return {
        "trace_id": observability.trace_id,
        "capability_execution_id": observability.capability_execution_id,
        "request_id": observability.request_id,
    }


class RoutingEngine:
    """Holds sealed registries and Redis-backed runtime-state components by reference (§18),
    constructed once at boot (from M19 onward)."""

    def __init__(
        self,
        model_registry: ModelRegistry,
        provider_registry: ProviderRegistry,
        health_store: ProviderHealthStore,
        latency_tracker: LatencyTracker,
        policy_registry: RoutingPolicyRegistry,
    ) -> None:
        self._model_registry = model_registry
        self._provider_registry = provider_registry
        self._health_store = health_store
        self._latency_tracker = latency_tracker
        self._policy_registry = policy_registry
        # RoutingEngine's OWN built-in defaults, independent of whatever is (or isn't)
        # registered in policy_registry - used as the §4.4 exception-isolation fallback, so a
        # buggy/third-party policy registered under an objective can never fail the call
        # outright, and an objective with nothing registered at all still routes correctly.
        self._default_policies: dict[str, RoutingPolicy] = {
            RoutingObjective.BEST_QUALITY.value: BestQualityPolicy(),
            RoutingObjective.LOWEST_COST.value: LowestCostPolicy(),
            RoutingObjective.FASTEST.value: FastestPolicy(),
            RoutingObjective.REASONING.value: ReasoningPolicy(),
        }

    async def route(
        self, criteria: RoutingCriteria, observability: ObservabilityContext | None = None
    ) -> list[ModelDescriptor]:
        """Executes §4.3's six-step sequence and returns the best-first ranked survivor list.
        Raises NoRoutableCandidateError if zero candidates survive steps 1-4 (step 5).

        `observability` is optional (default None) for backward compatibility with callers
        that predate its introduction; when given, its ids are attached to the
        routing_decision/routing_policy_failure log events (§16.1: threaded explicitly,
        never a contextvar)."""
        candidates_considered = len(self._model_registry.all_models())

        # Step 1: hard filter.
        candidates = self._model_registry.filter(
            requires_tools=criteria.requires_tools,
            requires_vision=criteria.requires_vision,
            requires_streaming=criteria.requires_streaming,
            requires_structured_output=criteria.requires_structured_output,
        )
        candidates_after_hard_filter = len(candidates)

        # Step 2: provider-enabled filter.
        candidates = [c for c in candidates if self._provider_registry.is_enabled(c.provider_id)]

        # Step 3: exclusion filter (hard, not advisory).
        if criteria.excluded_providers:
            excluded = set(criteria.excluded_providers)
            candidates = [c for c in candidates if c.provider_id not in excluded]

        # Step 4: health filter.
        healthy_candidates: list[ModelDescriptor] = []
        for candidate in candidates:
            if await self._health_store.is_healthy(candidate.provider_id, candidate.model_id):
                healthy_candidates.append(candidate)
        candidates = healthy_candidates

        # Step 5: zero-candidate check.
        if not candidates:
            raise NoRoutableCandidateError(
                f"No routable candidate for capability '{criteria.capability_name}' "
                f"(objective={criteria.objective.value})"
            )

        # Step 6: preference ranking.
        telemetry = await self._latency_tracker.snapshot()
        ranked = self._rank_with_isolation(candidates, criteria, telemetry, observability)
        ranked = self._promote_preferred(ranked, criteria)

        logger.info(
            "routing_decision",
            extra={
                **_observability_log_fields(observability),
                "objective": criteria.objective.value,
                "candidates_considered": candidates_considered,
                "candidates_after_hard_filter": candidates_after_hard_filter,
                # RoutingEngine's own recommendation is always its top-ranked candidate;
                # FallbackPolicy (M15) is a later, separate stage that may dispatch a
                # different candidate from this same ranked list.
                "chosen_rank": 0,
            },
        )
        return ranked

    def _promote_preferred(
        self, ranked: list[ModelDescriptor], criteria: RoutingCriteria
    ) -> list[ModelDescriptor]:
        """§4.1 rule 1: preferred_model/preferred_provider MUST remain advisory only - never a
        hard filter (already true; they're never used as filter criteria in steps 1-5). An
        unavailable/incapable preferred candidate MUST be silently skipped, never an error -
        if the preference matches nothing in `ranked`, this returns `ranked` unchanged.
        `preferred_model` takes priority over `preferred_provider` when both are set.
        """
        if criteria.preferred_model is not None:
            preferred = [c for c in ranked if c.model_id == criteria.preferred_model]
            if preferred:
                others = [c for c in ranked if c.model_id != criteria.preferred_model]
                return preferred + others

        if criteria.preferred_provider is not None:
            preferred = [c for c in ranked if c.provider_id == criteria.preferred_provider]
            if preferred:
                others = [c for c in ranked if c.provider_id != criteria.preferred_provider]
                return preferred + others

        return ranked

    def _rank_with_isolation(
        self,
        candidates: list[ModelDescriptor],
        criteria: RoutingCriteria,
        telemetry: RoutingTelemetrySnapshot,
        observability: ObservabilityContext | None = None,
    ) -> list[ModelDescriptor]:
        objective = criteria.objective.value

        try:
            policy: RoutingPolicy = self._policy_registry.resolve(objective)
        except UnknownRoutingObjectiveError:
            # Nothing registered for this objective - not a "policy failure," just use the
            # built-in default silently.
            default_policy = self._default_policies.get(objective)
            if default_policy is None:
                raise
            return default_policy.rank(candidates, criteria, telemetry)

        try:
            return policy.rank(candidates, criteria, telemetry)
        except Exception as exc:  # noqa: BLE001 - §4.4: a buggy policy must never fail the call outright
            fallback_policy = self._default_policies.get(objective)
            logger.warning(
                "routing_policy_failure",
                extra={
                    **_observability_log_fields(observability),
                    "objective": objective,
                    "failed_policy_name": type(policy).__name__,
                    "error_type": type(exc).__name__,
                    "fallback_policy_used": type(fallback_policy).__name__ if fallback_policy else None,
                },
            )
            if fallback_policy is None:
                raise
            return fallback_policy.rank(candidates, criteria, telemetry)
