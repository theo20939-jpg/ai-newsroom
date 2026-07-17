"""Tests for integrations.llm_gateway.routing.registry.RoutingPolicyRegistry
(docs/phase7_architecture_contract.md §4.5). Pure unit tests, no I/O."""
import pytest

from integrations.llm_gateway.errors import (
    RoutingPolicyRegistryAlreadySealedError,
    UnknownRoutingObjectiveError,
)
from integrations.llm_gateway.models.registry import ModelDescriptor
from integrations.llm_gateway.routing.criteria import RoutingCriteria
from integrations.llm_gateway.routing.latency_tracker import RoutingTelemetrySnapshot
from integrations.llm_gateway.routing.registry import RoutingPolicyRegistry


class _NoopPolicy:
    def rank(
        self, candidates: list[ModelDescriptor], criteria: RoutingCriteria, telemetry: RoutingTelemetrySnapshot
    ) -> list[ModelDescriptor]:
        return candidates


def test_register_then_resolve_round_trips() -> None:
    registry = RoutingPolicyRegistry()
    policy = _NoopPolicy()

    registry.register("best_quality", policy)

    assert registry.resolve("best_quality") is policy


def test_resolve_unknown_objective_raises() -> None:
    registry = RoutingPolicyRegistry()

    with pytest.raises(UnknownRoutingObjectiveError):
        registry.resolve("does-not-exist")


def test_register_after_seal_raises() -> None:
    registry = RoutingPolicyRegistry()
    registry.seal()

    with pytest.raises(RoutingPolicyRegistryAlreadySealedError):
        registry.register("best_quality", _NoopPolicy())


def test_resolve_works_identically_before_and_after_seal() -> None:
    registry = RoutingPolicyRegistry()
    policy = _NoopPolicy()
    registry.register("best_quality", policy)
    before = registry.resolve("best_quality")
    registry.seal()
    after = registry.resolve("best_quality")

    assert before is after
