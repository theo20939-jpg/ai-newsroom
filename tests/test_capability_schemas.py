"""Unit tests for schemas.capability / schemas.capability_definition - no
database, no network. Mirrors tests/test_workflow_schemas.py's style: boundary
+ extra="forbid" rejection for every schema.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from database.models.editorial_task import TaskPriority
from schemas.capability import (
    BusinessContext,
    CapabilityCall,
    CapabilityContext,
    CapabilityResult,
    CapabilityUsage,
    ExecutionContext,
    NewsEventSnapshot,
    RuntimeContext,
    WorkflowExecutionStateSnapshot,
)
from schemas.capability_definition import CapabilityConfig, CapabilityDefinition


def _news_event_snapshot() -> NewsEventSnapshot:
    return NewsEventSnapshot(
        id=uuid4(), title="t", summary=None, content="c", url=None, category="AI", published_at=None
    )


def _workflow_state_snapshot() -> WorkflowExecutionStateSnapshot:
    return WorkflowExecutionStateSnapshot(
        workflow_name="NEWS_ANALYSIS", workflow_version=1, completed_steps=[], step_results={}
    )


def _context() -> CapabilityContext:
    return CapabilityContext(
        business=BusinessContext(news_event=_news_event_snapshot(), workflow_state=_workflow_state_snapshot()),
        runtime=RuntimeContext(
            task_id=uuid4(),
            event_id=uuid4(),
            capability_name="research",
            priority=TaskPriority.B,
            attempt=1,
            iteration_count=0,
        ),
        execution=ExecutionContext(),
    )


def test_capability_context_builds_from_nested_submodels() -> None:
    context = _context()
    assert context.business.news_event.title == "t"
    assert context.runtime.attempt == 1
    assert context.execution.preferred_model is None


def test_business_context_event_recap_evidence_text_defaults_to_none() -> None:
    """NINJA PULSE RECAP Phase R2 integration, Phase B.1: a plain optional field, default None -
    every existing BusinessContext construction (this file's own _context() helper included)
    continues to validate unchanged."""
    context = _context()
    assert context.business.event_recap_evidence_text is None


def test_business_context_accepts_event_recap_evidence_text() -> None:
    business = BusinessContext(
        news_event=_news_event_snapshot(), workflow_state=_workflow_state_snapshot(),
        event_recap_evidence_text="Story: Example\n\nANNOUNCEMENT CONTEXT:\n\n- [ORIGIN]\nExample headline",
    )
    assert business.event_recap_evidence_text is not None
    assert "ANNOUNCEMENT CONTEXT" in business.event_recap_evidence_text


def test_capability_context_rejects_unknown_top_level_field() -> None:
    with pytest.raises(ValidationError):
        CapabilityContext(
            business=BusinessContext(news_event=_news_event_snapshot(), workflow_state=_workflow_state_snapshot()),
            runtime=RuntimeContext(
                task_id=uuid4(), event_id=uuid4(), capability_name="research",
                priority=TaskPriority.B, attempt=1, iteration_count=0,
            ),
            execution=ExecutionContext(),
            unexpected="nope",  # type: ignore[call-arg]
        )


def test_capability_context_is_frozen() -> None:
    context = _context()
    with pytest.raises(ValidationError):
        context.runtime = RuntimeContext(  # type: ignore[misc]
            task_id=uuid4(), event_id=uuid4(), capability_name="research",
            priority=TaskPriority.B, attempt=2, iteration_count=0,
        )


def test_capability_result_allows_zero_calls() -> None:
    now = datetime.now(timezone.utc)
    result = CapabilityResult(
        status="SUCCESS", structured_output={"a": 1}, calls=[], started_at=now, finished_at=now, duration_seconds=0.0
    )
    assert result.calls == []


def test_capability_result_has_no_top_level_scalar_ai_fields() -> None:
    field_names = set(CapabilityResult.model_fields)
    assert "model_used" not in field_names
    assert "prompt_name" not in field_names
    assert "prompt_version" not in field_names
    assert "usage" not in field_names
    assert "calls" in field_names


def test_capability_call_requires_usage_and_status() -> None:
    now = datetime.now(timezone.utc)
    call = CapabilityCall(
        call_id=uuid4(), sequence=0, gateway_method="generate", status="SUCCESS",
        model_used="m", usage=CapabilityUsage(input_tokens=1, output_tokens=1),
        started_at=now, finished_at=now, duration_seconds=0.1,
    )
    assert call.status == "SUCCESS"


def test_capability_usage_supports_non_token_billed_calls() -> None:
    usage = CapabilityUsage(units=3, unit_type="search_query")
    assert usage.input_tokens is None
    assert usage.output_tokens is None


def test_capability_definition_requires_positive_version() -> None:
    with pytest.raises(ValidationError):
        CapabilityDefinition(
            name="research", version=0, config=CapabilityConfig(timeout_seconds=10),
            required_context=["news_event"], expected_output_keys=["summary"],
        )


def test_capability_config_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        CapabilityConfig(timeout_seconds=10, unknown_field=True)  # type: ignore[call-arg]
