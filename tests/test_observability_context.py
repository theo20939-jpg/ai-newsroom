"""Tests for integrations.llm_gateway.observability (docs/phase7_architecture_contract.md §16.1)."""
import pytest
from pydantic import ValidationError

from integrations.llm_gateway.observability import (
    ObservabilityContext,
    derive_model_route_id,
    derive_provider_attempt_id,
)


def test_observability_context_constructs_with_required_fields_only() -> None:
    ctx = ObservabilityContext(trace_id="task-1", capability_execution_id="task-1:research:1")

    assert ctx.trace_id == "task-1"
    assert ctx.capability_execution_id == "task-1:research:1"
    assert ctx.request_id is None


def test_observability_context_accepts_request_id() -> None:
    ctx = ObservabilityContext(
        trace_id="task-1", capability_execution_id="task-1:research:1", request_id="call-1"
    )

    assert ctx.request_id == "call-1"


def test_observability_context_is_frozen() -> None:
    ctx = ObservabilityContext(trace_id="task-1", capability_execution_id="task-1:research:1")

    with pytest.raises(ValidationError):
        ctx.trace_id = "mutated"  # type: ignore[misc]


def test_observability_context_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ObservabilityContext(
            trace_id="task-1",
            capability_execution_id="task-1:research:1",
            unexpected_field="nope",  # type: ignore[call-arg]
        )


def test_derive_provider_attempt_id_matches_contract_format() -> None:
    assert derive_provider_attempt_id("call-1", 0) == "call-1:0"
    assert derive_provider_attempt_id("call-1", 2) == "call-1:2"


def test_derive_model_route_id_matches_contract_format() -> None:
    provider_attempt_id = derive_provider_attempt_id("call-1", 0)

    assert (
        derive_model_route_id(provider_attempt_id, "openai", "gpt-4o")
        == "call-1:0:openai:gpt-4o"
    )
