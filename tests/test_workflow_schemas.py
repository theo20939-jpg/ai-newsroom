"""Tests proving every Phase 5 Pydantic schema rejects unknown fields (extra="forbid").

Pure unit tests, no database. Each of the 8 public Phase 5 schemas gets
exactly one rejection test here, so this file is the single place that
proves "strict" holds for all of them.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from database.models.editorial_task import TaskPriority, TaskStatus
from schemas.editorial_task import EditorialTaskCreate, EditorialTaskRead
from schemas.workflow import (
    WorkflowDefinition,
    WorkflowExecutionState,
    WorkflowRetryPolicy,
    WorkflowRunResult,
    WorkflowStepDefinition,
    WorkflowStepResult,
    WorkflowType,
)

_NOW = datetime.now(timezone.utc)


def test_workflow_retry_policy_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        WorkflowRetryPolicy(max_attempts=1, retryable_error_types=["StepExecutionError"], unexpected="x")  # type: ignore[call-arg]


def test_workflow_step_definition_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        WorkflowStepDefinition(name="s", capability="research", timeout_seconds=10, unexpected="x")  # type: ignore[call-arg]


def test_workflow_definition_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        WorkflowDefinition(
            name=WorkflowType.NEWS_ANALYSIS,
            version=1,
            steps=[WorkflowStepDefinition(name="s", capability="research", timeout_seconds=10)],
            retry_policy=WorkflowRetryPolicy(max_attempts=1, retryable_error_types=["StepExecutionError"]),
            timeout_seconds=60,
            required_input=["event_id"],
            expected_output=["result"],
            unexpected="x",  # type: ignore[call-arg]
        )


def test_workflow_execution_state_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        WorkflowExecutionState(
            workflow_name=WorkflowType.NEWS_ANALYSIS,
            workflow_version=1,
            current_step=None,
            unexpected="x",  # type: ignore[call-arg]
        )


def test_workflow_step_result_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        WorkflowStepResult(
            step_name="s", status="SUCCESS", attempt=1, started_at=_NOW, finished_at=_NOW, unexpected="x"  # type: ignore[call-arg]
        )


def test_workflow_run_result_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        WorkflowRunResult(
            task_id=uuid4(), status="COMPLETED", iterations_used=1, step_results=[], unexpected="x"  # type: ignore[call-arg]
        )


def test_editorial_task_create_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        EditorialTaskCreate(
            event_id=uuid4(), workflow_type=WorkflowType.NEWS_ANALYSIS, priority=TaskPriority.B, unexpected="x"  # type: ignore[call-arg]
        )


def test_editorial_task_read_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        EditorialTaskRead(
            id=uuid4(),
            event_id=uuid4(),
            priority=TaskPriority.B,
            status=TaskStatus.CREATED,
            retry_count=0,
            current_step=None,
            created_at=_NOW,
            updated_at=_NOW,
            unexpected="x",  # type: ignore[call-arg]
        )
