"""Tests for services.ai_execution_mapper.DefaultAIExecutionMapper - no
database, no network, no persistence.

Proves the AIExecutionMapper mapping boundary is compatible with the
AIExecution row shape for SUCCESS-status CapabilityCalls (Amendment B, §16)
and that a non-SUCCESS call is explicitly rejected, never silently mapped.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from database.models.ai_execution import AICapability
from capabilities.errors import CapabilityConfigurationError
from schemas.capability import CapabilityCall, CapabilityUsage
from services.ai_execution_mapper import AIExecutionMappingError, DefaultAIExecutionMapper


def _call(status: str = "SUCCESS", units: int | None = None, unit_type: str | None = None) -> CapabilityCall:
    now = datetime.now(timezone.utc)
    return CapabilityCall(
        call_id=uuid4(), sequence=0, gateway_method="generate", status=status,
        model_used="fake-model-v1" if status == "SUCCESS" else None,
        prompt_name="fake-prompt", prompt_version="1",
        usage=CapabilityUsage(input_tokens=10, output_tokens=5, units=units, unit_type=unit_type),
        started_at=now, finished_at=now, duration_seconds=0.01,
        error=None if status == "SUCCESS" else "boom",
    )


def test_maps_a_successful_call_to_the_execution_row_shape() -> None:
    mapper = DefaultAIExecutionMapper()
    task_id = uuid4()

    row = mapper.to_execution_row(task_id, "research", _call())

    assert row.task_id == task_id
    assert row.capability == AICapability.RESEARCH.value
    assert row.model == "fake-model-v1"
    assert row.input_tokens == 10
    assert row.output_tokens == 5
    assert row.cost is None  # Phase 6 never invokes CostTracker's price table


def test_resolves_engagement_to_its_own_capability_through_the_centralized_mapping() -> None:
    """Phase 18.10 M9: engagement no longer aliases to INTELLIGENCE (the resolved Amendment A
    persistence gap) - it resolves to its own AICapability.ENGAGEMENT value."""
    mapper = DefaultAIExecutionMapper()

    row = mapper.to_execution_row(uuid4(), "engagement", _call())

    assert row.capability == AICapability.ENGAGEMENT.value


def test_non_success_call_is_rejected_not_silently_mapped() -> None:
    mapper = DefaultAIExecutionMapper()

    with pytest.raises(AIExecutionMappingError):
        mapper.to_execution_row(uuid4(), "research", _call(status="FAILED"))


def test_unmapped_capability_name_raises_configuration_error() -> None:
    mapper = DefaultAIExecutionMapper()

    with pytest.raises(CapabilityConfigurationError):
        mapper.to_execution_row(uuid4(), "no_such_capability", _call())


def test_non_token_billed_usage_is_recorded_in_response_metadata() -> None:
    mapper = DefaultAIExecutionMapper()

    row = mapper.to_execution_row(uuid4(), "research", _call(units=3, unit_type="search_query"))

    assert row.response == {"units": 3, "unit_type": "search_query"}
