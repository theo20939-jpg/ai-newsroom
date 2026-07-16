"""AIExecutionMapper Protocol (docs/phase6_architecture_contract.md §10.1, Amendment B §16).

Provider-neutral mapping boundary between CapabilityCall (schemas.capability
- the complete, permanent, in-memory contract a Capability already produces)
and the AIExecution row shape (database.models.ai_execution) - WITHOUT
writing any row. This gives the mapping logic exactly one home, makes it
unit-testable against fakes, and leaves it ready to be wired to a real write
path once a future phase reviews the AIExecution schema against real
provider responses.

Phase 6 validates compatibility for SUCCESS-status calls only
(AIExecutionMappingError for anything else) - mapping the complete
failed/partial-call contract (status/error/provider/request-id) is
explicitly deferred to that future phase. No component here holds a database
session or performs I/O; DefaultAIExecutionMapper is a pure function.
"""
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from capabilities.capability_mapping import resolve_ai_capability
from schemas.capability import CapabilityCall


class AIExecutionMappingError(Exception):
    """Raised when a CapabilityCall cannot be mapped - e.g. status != SUCCESS
    in Phase 6, where only successful-call compatibility is validated."""


class AIExecutionMapperResult(BaseModel):
    """The AIExecution row shape one CapabilityCall would produce. Never
    written to the database in Phase 6 - this is the mapping's output, not a
    persisted row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: UUID
    capability: str
    model: str | None
    prompt_version: str | None
    input_tokens: int
    output_tokens: int
    cost: Decimal | None
    response: dict[str, Any] | None


class AIExecutionMapper(Protocol):
    """Provider-neutral mapping boundary from CapabilityCall -> AIExecution
    row shape. Implemented in Phase 6 for validation only - never invoked to
    perform a real database write. CapabilityExecutor MUST NOT write
    AIExecution rows in Phase 6 (Amendment B, §16)."""

    def to_execution_row(
        self, task_id: UUID, capability_name: str, call: CapabilityCall
    ) -> AIExecutionMapperResult:
        """Maps one CapabilityCall to the row shape it would produce.

        MUST raise AIExecutionMappingError if call.status != "SUCCESS" - Phase 6
        validates compatibility for successful calls only (§16); mapping the
        complete failed/partial-call contract is deferred to the future real
        Gateway/Cost Tracker phase.
        """
        ...


class DefaultAIExecutionMapper:
    """The Phase 6 reference implementation of AIExecutionMapper. Pure
    mapping function - no I/O, no database session, never invoked by
    CapabilityExecutor at runtime in Phase 6."""

    def to_execution_row(
        self, task_id: UUID, capability_name: str, call: CapabilityCall
    ) -> AIExecutionMapperResult:
        if call.status != "SUCCESS":
            raise AIExecutionMappingError(
                f"Cannot map CapabilityCall {call.call_id}: status={call.status!r}. "
                "Phase 6 validates compatibility for SUCCESS-status calls only (Amendment B, §16)."
            )
        ai_capability = resolve_ai_capability(capability_name)
        return AIExecutionMapperResult(
            task_id=task_id,
            capability=ai_capability.value,
            model=call.model_used,
            prompt_version=call.prompt_version,
            input_tokens=call.usage.input_tokens or 0,
            output_tokens=call.usage.output_tokens or 0,
            cost=None,
            response={"units": call.usage.units, "unit_type": call.usage.unit_type}
            if call.usage.units is not None
            else None,
        )
