"""Tests for integrations.llm_gateway.routing.policy's built-in RoutingPolicy implementations
(docs/phase7_architecture_contract.md §4.2, §4.7). Pure unit tests, no I/O."""
from decimal import Decimal

from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.models.registry import ModelDescriptor, PricingTier
from integrations.llm_gateway.routing.criteria import RoutingCriteria
from integrations.llm_gateway.routing.latency_tracker import RoutingTelemetrySnapshot
from integrations.llm_gateway.routing.policy import (
    BestQualityPolicy,
    FastestPolicy,
    LowestCostPolicy,
    ReasoningPolicy,
    WeightedSplitPolicy,
)


def _model(
    model_id: str,
    quality_tier: int = 0,
    reasoning_tier: str = "none",
    input_price: str = "1.00",
    output_price: str = "2.00",
) -> ModelDescriptor:
    return ModelDescriptor(
        model_id=model_id,
        provider_id="fake-provider",
        display_name=model_id,
        context_window_tokens=128_000,
        quality_tier=quality_tier,
        reasoning_tier=reasoning_tier,  # type: ignore[arg-type]
        pricing_tiers=[
            PricingTier(
                condition="standard",
                input_price_per_million=Decimal(input_price),
                output_price_per_million=Decimal(output_price),
            )
        ],
    )


def _criteria(objective: str = "best_quality") -> RoutingCriteria:
    return RoutingCriteria(
        gateway_method="generate", capability_name="research", priority=TaskPriority.B, objective=objective  # type: ignore[arg-type]
    )


def test_best_quality_policy_ranks_descending_by_quality_tier() -> None:
    low = _model("low", quality_tier=10)
    high = _model("high", quality_tier=90)
    mid = _model("mid", quality_tier=50)

    ranked = BestQualityPolicy().rank([low, high, mid], _criteria(), RoutingTelemetrySnapshot())

    assert [m.model_id for m in ranked] == ["high", "mid", "low"]


def test_lowest_cost_policy_ranks_ascending_by_combined_standard_price() -> None:
    cheap = _model("cheap", input_price="0.50", output_price="1.00")
    expensive = _model("expensive", input_price="5.00", output_price="10.00")
    mid = _model("mid", input_price="2.00", output_price="3.00")

    ranked = LowestCostPolicy().rank([expensive, cheap, mid], _criteria(), RoutingTelemetrySnapshot())

    assert [m.model_id for m in ranked] == ["cheap", "mid", "expensive"]


def test_fastest_policy_ranks_by_p50_latency_when_data_is_available() -> None:
    slow = _model("slow", quality_tier=100)
    fast = _model("fast", quality_tier=1)
    telemetry = RoutingTelemetrySnapshot(p50_latency_ms_by_model={"slow": 900.0, "fast": 100.0})

    ranked = FastestPolicy().rank([slow, fast], _criteria("fastest"), telemetry)

    assert [m.model_id for m in ranked] == ["fast", "slow"]


def test_fastest_policy_falls_back_to_quality_tier_when_telemetry_is_missing() -> None:
    high_quality = _model("high-quality", quality_tier=90)
    low_quality = _model("low-quality", quality_tier=10)

    ranked = FastestPolicy().rank([low_quality, high_quality], _criteria("fastest"), RoutingTelemetrySnapshot())

    assert [m.model_id for m in ranked] == ["high-quality", "low-quality"]


def test_fastest_policy_prefers_known_latency_over_unknown_regardless_of_quality_tier() -> None:
    known_but_low_quality = _model("known", quality_tier=1)
    unknown_but_high_quality = _model("unknown", quality_tier=100)
    telemetry = RoutingTelemetrySnapshot(p50_latency_ms_by_model={"known": 500.0})

    ranked = FastestPolicy().rank(
        [unknown_but_high_quality, known_but_low_quality], _criteria("fastest"), telemetry
    )

    assert [m.model_id for m in ranked] == ["known", "unknown"]


def test_reasoning_policy_ranks_extended_above_standard_above_none() -> None:
    none_tier = _model("none-tier", reasoning_tier="none", quality_tier=100)
    standard_tier = _model("standard-tier", reasoning_tier="standard", quality_tier=1)
    extended_tier = _model("extended-tier", reasoning_tier="extended", quality_tier=1)

    ranked = ReasoningPolicy().rank(
        [none_tier, standard_tier, extended_tier], _criteria("reasoning"), RoutingTelemetrySnapshot()
    )

    assert [m.model_id for m in ranked] == ["extended-tier", "standard-tier", "none-tier"]


def test_reasoning_policy_uses_quality_tier_as_a_tiebreaker_within_the_same_tier() -> None:
    low = _model("low", reasoning_tier="standard", quality_tier=10)
    high = _model("high", reasoning_tier="standard", quality_tier=90)

    ranked = ReasoningPolicy().rank([low, high], _criteria("reasoning"), RoutingTelemetrySnapshot())

    assert [m.model_id for m in ranked] == ["high", "low"]


def test_weighted_split_policy_always_chooses_one_of_the_weighted_candidates_first() -> None:
    a = _model("model-a", quality_tier=1)
    b = _model("model-b", quality_tier=1)
    policy = WeightedSplitPolicy(weights={"model-a": 0.5, "model-b": 0.5})

    for _ in range(20):
        ranked = policy.rank([a, b], _criteria(), RoutingTelemetrySnapshot())
        assert ranked[0].model_id in {"model-a", "model-b"}
        assert {m.model_id for m in ranked} == {"model-a", "model-b"}


def test_weighted_split_policy_eventually_picks_both_candidates_across_many_trials() -> None:
    a = _model("model-a")
    b = _model("model-b")
    policy = WeightedSplitPolicy(weights={"model-a": 0.5, "model-b": 0.5})

    chosen_ids = {policy.rank([a, b], _criteria(), RoutingTelemetrySnapshot())[0].model_id for _ in range(200)}

    assert chosen_ids == {"model-a", "model-b"}


def test_weighted_split_policy_with_empty_weights_falls_back_to_quality_tier_order() -> None:
    low = _model("low", quality_tier=10)
    high = _model("high", quality_tier=90)
    policy = WeightedSplitPolicy(weights={})

    ranked = policy.rank([low, high], _criteria(), RoutingTelemetrySnapshot())

    assert [m.model_id for m in ranked] == ["high", "low"]


def test_weighted_split_policy_never_chooses_an_unweighted_candidate_as_primary() -> None:
    weighted = _model("weighted", quality_tier=1)
    unweighted = _model("unweighted", quality_tier=100)
    policy = WeightedSplitPolicy(weights={"weighted": 1.0})

    for _ in range(20):
        ranked = policy.rank([weighted, unweighted], _criteria(), RoutingTelemetrySnapshot())
        assert ranked[0].model_id == "weighted"
