"""Pydantic contracts for the Capability Framework (Phase 6).

Per docs/phase6_architecture_contract.md §3-§4. CapabilityContext is one
immutable object composed of three nested, frozen sub-models - not a
3-parameter split (§3 rationale). CapabilityResult supports zero, one, or
many AI calls via `calls: list[CapabilityCall]` - never a scalar
model_used/prompt_name/prompt_version/usage field (§4 binding rules).

NewsEventSnapshot/WorkflowExecutionStateSnapshot are read-only snapshots
built by capabilities.executor.CapabilityExecutor - never the SQLAlchemy
NewsEvent/EditorialTask rows themselves (§3, no ORM object crosses into a
Capability).
"""
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from database.models.editorial_task import TaskPriority


class NewsEventSnapshot(BaseModel):
    """Read-only snapshot of the NewsEvent a Capability is operating on."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    title: str
    summary: str | None
    content: str | None
    url: str | None
    category: str
    published_at: datetime | None


class WorkflowExecutionStateSnapshot(BaseModel):
    """Read-only snapshot of prior Workflow progress, for step chaining (P4).

    step_results maps a completed step's name to its result payload - only
    steps that finished SUCCESS with a non-null result are included, since
    those are the only prior outputs a later Capability could meaningfully
    read.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_name: str
    workflow_version: int
    completed_steps: list[str]
    step_results: dict[str, dict[str, Any]] = Field(default_factory=dict)


class BusinessContext(BaseModel):
    """Domain data the capability operates on. Read-only snapshots, never ORM objects."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    news_event: NewsEventSnapshot
    workflow_state: WorkflowExecutionStateSnapshot
    language: str = "en"
    audience: str | None = None
    brand_voice: dict[str, Any] | None = None


class RuntimeContext(BaseModel):
    """Metadata owned by CapabilityExecutor/WorkflowRunner - never set by the capability itself."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: UUID
    event_id: UUID
    capability_name: str
    priority: TaskPriority
    attempt: int = Field(ge=1)
    iteration_count: int = Field(ge=0)


class ExecutionContext(BaseModel):
    """Advisory Gateway-routing hints. LLMGateway makes the final model/provider choice."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    preferred_model: str | None = None
    preferred_provider: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None


class CapabilityContext(BaseModel):
    """The complete, immutable, read-only input a Capability.execute() call receives."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    business: BusinessContext
    runtime: RuntimeContext
    execution: ExecutionContext


class CapabilityUsage(BaseModel):
    """Token or unit cost of one AI interaction. Fields are optional, not
    zero-defaulted, so a non-token-billed call (e.g. a flat-rate search API)
    is representable without a hack."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    units: int | None = Field(default=None, ge=0)
    unit_type: str | None = None


class CapabilityCall(BaseModel):
    """Everything required to reconstruct one AI interaction that occurred
    while producing a CapabilityResult. One CapabilityCall MUST correspond to
    exactly one LLMGateway method invocation - never a batch of several."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_id: UUID
    sequence: int = Field(ge=0)
    gateway_method: Literal["generate", "generate_stream", "embed", "classify", "moderate", "rerank"]
    status: Literal["SUCCESS", "FAILED"]

    model_used: str | None
    provider: str | None = None
    prompt_name: str | None = None
    prompt_version: str | None = None

    usage: CapabilityUsage

    started_at: datetime
    finished_at: datetime
    duration_seconds: float

    error: str | None = None


class CapabilityResult(BaseModel):
    """The complete, immutable output of one Capability.execute() call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["SUCCESS", "FAILED"]
    structured_output: dict[str, Any] | None
    confidence: int | None = Field(default=None, ge=0, le=100)

    calls: list[CapabilityCall] = Field(default_factory=list)

    started_at: datetime
    finished_at: datetime
    duration_seconds: float

    metadata: dict[str, Any] = Field(default_factory=dict)
    logs: list[str] = Field(default_factory=list)
    next_context: dict[str, Any] | None = None
