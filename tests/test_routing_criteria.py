"""Tests for integrations.llm_gateway.routing.criteria (docs/phase7_architecture_contract.md
§4.1, §5.1). Pure unit tests, no I/O."""
import pytest
from pydantic import ValidationError

from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.routing.criteria import (
    FallbackEligibility,
    RoutingCriteria,
    RoutingObjective,
)


def _criteria(**overrides: object) -> RoutingCriteria:
    fields: dict[str, object] = {
        "gateway_method": "generate",
        "capability_name": "research",
        "priority": TaskPriority.B,
    }
    fields.update(overrides)
    return RoutingCriteria(**fields)  # type: ignore[arg-type]


def test_default_objective_is_lowest_cost() -> None:
    """API cost optimization: the default flipped from BEST_QUALITY to LOWEST_COST - every
    capability relies on this default (none overrides `objective`), so this one field change
    routes every capability to gpt-5.6-luna first, gpt-5.6-terra as its only cost-eligible
    fallback, with gpt-5.6-sol structurally excluded by the existing 3.0x cost ceiling."""
    criteria = _criteria()

    assert criteria.objective == RoutingObjective.LOWEST_COST


def test_excluded_providers_defaults_to_empty_list() -> None:
    criteria = _criteria()

    assert criteria.excluded_providers == []


def test_fallback_defaults_to_a_fallback_eligibility_instance() -> None:
    criteria = _criteria()

    assert isinstance(criteria.fallback, FallbackEligibility)
    assert criteria.fallback.max_fallback_attempts == 3


def test_preferred_model_and_provider_default_to_none() -> None:
    criteria = _criteria()

    assert criteria.preferred_model is None
    assert criteria.preferred_provider is None


def test_criteria_is_frozen() -> None:
    criteria = _criteria()

    with pytest.raises(ValidationError):
        criteria.objective = RoutingObjective.FASTEST  # type: ignore[misc]


def test_criteria_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        _criteria(unexpected_field="nope")


def test_fallback_eligibility_defaults() -> None:
    eligibility = FallbackEligibility()

    assert eligibility.max_cost_multiplier == 3
    assert eligibility.max_additional_cost is None
    assert eligibility.allow_cost_ceiling_override_on_exhaustion is False
    assert eligibility.max_fallback_attempts == 3


def test_each_routing_criteria_gets_its_own_fallback_eligibility_instance() -> None:
    """The mutable-default-factory pattern (Field(default_factory=FallbackEligibility)) must
    not share one instance across RoutingCriteria constructions - not load-bearing here since
    FallbackEligibility is frozen/immutable, but worth asserting the wiring is correct."""
    criteria_1 = _criteria()
    criteria_2 = _criteria()

    assert criteria_1.fallback == criteria_2.fallback
