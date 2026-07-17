"""RoutingPolicy Protocol and built-in policies (docs/phase7_architecture_contract.md §4.2,
§4.7). Every `rank()` implementation is pure: no I/O, no read of external mutable state -
every input it needs is one of its three parameters. `WeightedSplitPolicy` is the one named
exception to *determinism* (not purity) - its random draw is generated fresh, locally, inside
the call, never read from any external/shared state.
"""
import random
from typing import Protocol

from integrations.llm_gateway.models.registry import ModelDescriptor, standard_combined_price
from integrations.llm_gateway.routing.criteria import RoutingCriteria
from integrations.llm_gateway.routing.latency_tracker import RoutingTelemetrySnapshot

_REASONING_TIER_RANK: dict[str, int] = {"extended": 2, "standard": 1, "none": 0}


class RoutingPolicy(Protocol):
    def rank(
        self,
        candidates: list[ModelDescriptor],
        criteria: RoutingCriteria,
        telemetry: RoutingTelemetrySnapshot,
    ) -> list[ModelDescriptor]:
        """No I/O, no read of any external mutable state - every input this method needs is
        one of the three parameters above. Non-FASTEST policies simply ignore `telemetry`."""
        ...


class BestQualityPolicy:
    """Ranks by ModelDescriptor.quality_tier, descending (higher = better, §3)."""

    def rank(
        self,
        candidates: list[ModelDescriptor],
        criteria: RoutingCriteria,
        telemetry: RoutingTelemetrySnapshot,
    ) -> list[ModelDescriptor]:
        return sorted(candidates, key=lambda m: m.quality_tier, reverse=True)


class LowestCostPolicy:
    """Ranks by the standard-tier combined input+output price per million tokens, ascending."""

    def rank(
        self,
        candidates: list[ModelDescriptor],
        criteria: RoutingCriteria,
        telemetry: RoutingTelemetrySnapshot,
    ) -> list[ModelDescriptor]:
        return sorted(candidates, key=standard_combined_price)


class FastestPolicy:
    """Ranks by LatencyTracker's rolling p50, ascending, when available. Per §4.6's binding
    fallback rule, a candidate missing telemetry data falls back to the static quality_tier
    heuristic rather than being ranked arbitrarily - known-latency candidates always rank
    ahead of unknown-latency ones, and among the unknowns, higher quality_tier ranks better.
    """

    def rank(
        self,
        candidates: list[ModelDescriptor],
        criteria: RoutingCriteria,
        telemetry: RoutingTelemetrySnapshot,
    ) -> list[ModelDescriptor]:
        def _key(model: ModelDescriptor) -> tuple[int, float]:
            latency = telemetry.p50_latency_ms_by_model.get(model.model_id)
            if latency is not None:
                return (0, latency)
            return (1, -model.quality_tier)

        return sorted(candidates, key=_key)


class ReasoningPolicy:
    """Ranks by ModelDescriptor.reasoning_tier (extended > standard > none) first, then
    quality_tier as a tiebreaker within the same reasoning tier."""

    def rank(
        self,
        candidates: list[ModelDescriptor],
        criteria: RoutingCriteria,
        telemetry: RoutingTelemetrySnapshot,
    ) -> list[ModelDescriptor]:
        return sorted(
            candidates,
            key=lambda m: (_REASONING_TIER_RANK.get(m.reasoning_tier, 0), m.quality_tier),
            reverse=True,
        )


class WeightedSplitPolicy:
    """Opt-in, built-in RoutingPolicy for gradual provider/model migration (§4.7). A
    Capability opts in explicitly for a migration window; weights are edited and redeployed
    manually (restart-gated, P18) - no automatic promotion or rollback exists.

    `rank()` draws one weighted-random candidate (among those named in `weights`) to rank
    first; every other candidate follows, ordered by quality_tier, as the fallback sequence.
    Candidates not named in `weights` are never chosen as the primary pick but remain
    available as fallback candidates.
    """

    def __init__(self, weights: dict[str, float]) -> None:
        self._weights = weights

    def rank(
        self,
        candidates: list[ModelDescriptor],
        criteria: RoutingCriteria,
        telemetry: RoutingTelemetrySnapshot,
    ) -> list[ModelDescriptor]:
        weighted_candidates = [c for c in candidates if c.model_id in self._weights and self._weights[c.model_id] > 0]
        weighted_ids = {c.model_id for c in weighted_candidates}
        remainder = sorted(
            (c for c in candidates if c.model_id not in weighted_ids),
            key=lambda m: m.quality_tier,
            reverse=True,
        )
        if not weighted_candidates:
            return remainder

        chosen = random.choices(  # noqa: S311 - a percentage-split traffic router, not a security control
            weighted_candidates, weights=[self._weights[c.model_id] for c in weighted_candidates], k=1
        )[0]
        rest_weighted = sorted(
            (c for c in weighted_candidates if c.model_id != chosen.model_id),
            key=lambda m: m.quality_tier,
            reverse=True,
        )
        return [chosen, *rest_weighted, *remainder]
