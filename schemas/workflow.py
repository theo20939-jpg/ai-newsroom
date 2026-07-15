"""Pydantic contracts for the Workflow Engine (Phase 5).

Typed, versioned descriptions of workflows and their steps - registered once,
at import time, in workflows.registry.WorkflowRegistry - plus the runtime
execution-state shape persisted into EditorialTask.workflow (JSON) and the
result shapes WorkflowRunner returns. Nothing here touches the database or
any AI provider.
"""
from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WorkflowType(str, Enum):
    """Supported workflow types (docs/10 PHASE 5).

    DAILY_DIGEST is declared here for forward compatibility with the future
    Digest Engine phase, but is never registered in WorkflowRegistry during
    Phase 5 - EditorialTask.event_id is a single foreign key, and a digest
    inherently spans many events. Resolving it raises UnknownWorkflowTypeError.
    """

    NEWS_ANALYSIS = "NEWS_ANALYSIS"
    CONTENT_GENERATION = "CONTENT_GENERATION"
    DAILY_DIGEST = "DAILY_DIGEST"


class WorkflowRetryPolicy(BaseModel):
    """How a retryable step failure is retried - distinct from the step's own max_attempts ceiling."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_attempts: int = Field(ge=1, le=10)
    retry_delay_seconds: float = Field(default=0, ge=0)
    retryable_error_types: list[str] = Field(min_length=1)


class WorkflowStepDefinition(BaseModel):
    """One step of a WorkflowDefinition.

    `capability` is a placeholder identifier (e.g. "research"), not an
    implementation - see workflows.runner.StepExecutor.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    capability: str
    required: bool = True
    max_attempts: int = Field(default=3, ge=1, le=10)
    timeout_seconds: int = Field(ge=1)


class WorkflowDefinition(BaseModel):
    """Typed, versioned, immutable description of one workflow type."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: WorkflowType
    version: int = Field(ge=1)
    steps: list[WorkflowStepDefinition] = Field(min_length=1)
    max_iterations: int = Field(default=3, ge=1, le=10)
    retry_policy: WorkflowRetryPolicy
    timeout_seconds: int = Field(ge=1)
    required_input: list[str]
    expected_output: list[str]


StepStatus = Literal["SUCCESS", "FAILED", "SKIPPED"]


class WorkflowStepResult(BaseModel):
    """Outcome of one executed step attempt - JSON-serializable only.

    started_at/finished_at exist so SLA measurement, Capability duration
    analytics, and bottleneck-finding can be built later without any change
    to this shape.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    step_name: str
    status: StepStatus
    attempt: int = Field(ge=1)
    started_at: datetime
    finished_at: datetime
    error: str | None = None
    result: dict[str, Any] | None = None


class WorkflowExecutionState(BaseModel):
    """Exactly what is persisted into EditorialTask.workflow (JSON).

    Never holds a WorkflowDefinition, Python objects, or callables - only
    JSON-serializable snapshot data. The full definition is re-resolved from
    WorkflowRegistry each time, by (workflow_name, workflow_version).

    iteration_count and each step's attempt/retry tracking are deliberately
    independent: a retry of one step never increments iteration_count, and
    iteration_count is never used to mean "this step was retried."

    Deliberately not frozen: workflows.runner.WorkflowRunner mutates this
    object in place throughout a run (current_step, completed_steps,
    iteration_count, step_results, failure) rather than rebuilding it via
    model_copy() on every change. extra="forbid" still applies - unknown
    fields are rejected even though the model itself is mutable.
    """

    model_config = ConfigDict(extra="forbid")

    workflow_name: WorkflowType
    workflow_version: int
    current_step: str | None
    completed_steps: list[str] = Field(default_factory=list)
    iteration_count: int = Field(default=0, ge=0)
    step_results: list[WorkflowStepResult] = Field(default_factory=list)
    failure: dict[str, Any] | None = None


RunStatus = Literal["COMPLETED", "FAILED"]


class WorkflowRunResult(BaseModel):
    """Returned by WorkflowRunner.run()."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: UUID
    status: RunStatus
    iterations_used: int
    step_results: list[WorkflowStepResult]
