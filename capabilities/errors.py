"""Typed exception hierarchy for the Capability Framework (Phase 6).

Mirrors workflows/errors.py's pattern: a distinct base per concern (registry
config vs. execution), never a bare Exception. capabilities.executor is the
only place that translates the *CapabilityError hierarchy below into the
workflows.errors hierarchy - a Capability implementation never imports
workflows.errors directly (docs/phase6_architecture_contract.md §5, §13 of
the planning document's error table).

Mapping at the CapabilityExecutor boundary (unchanged by Amendments A/B):
    RetryableCapabilityError   -> workflows.errors.StepExecutionError
    CapabilityTimeoutError     -> workflows.errors.StepExecutionError (retryable by default)
    PermanentCapabilityError   -> workflows.errors.PermanentStepFailureError
    ValidationCapabilityError  -> workflows.errors.PermanentStepFailureError
    CapabilityConfigurationError -> workflows.errors.PermanentStepFailureError

Cost-accounting forensic fix (real production truncated-Research canary): a gateway call can
succeed (real provider spend, real usage/model data) and still lead a Capability to raise a
CapabilityError - e.g. the response's structured output fails §9.1 floor validation. Before this
fix, that already-completed CapabilityCall was silently discarded the instant the Capability
raised, since CapabilityExecutor only ever read `CapabilityResult.calls` on the success return
path (capabilities/executor.py's own `_record_cost` call site) - a real paid call the provider
actually billed was never persisted as an AIExecution row. `calls` below (optional, defaults to
empty) lets a Capability attach whichever CapabilityCall objects actually completed before it
raised, so CapabilityExecutor can cost them through the exact same, unmodified `_record_cost()`
seam (which already only ever costs `status == "SUCCESS"` calls - never fabricates, never costs
a call that never reached the provider) before translating the error and re-raising. Every
existing raise site that doesn't pass `calls=` is completely unaffected - `calls` stays empty."""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from schemas.capability import CapabilityCall


class CapabilityError(Exception):
    """Base class for every error a Capability.execute() implementation may raise."""

    def __init__(self, message: str, *, calls: "list[CapabilityCall] | None" = None) -> None:
        super().__init__(message)
        self.calls: "list[CapabilityCall]" = calls if calls is not None else []


class CapabilityConfigurationError(CapabilityError):
    """Bad CapabilityDefinition/config, or an unmapped capability name (§10/Amendment A) - never retried."""


class ValidationCapabilityError(CapabilityError):
    """Gateway response failed output-schema validation - not retried (bad prompt/model behavior)."""


class RetryableCapabilityError(CapabilityError):
    """Transient failure (rate limit, transient provider error) - eligible for step-level retry."""


class PermanentCapabilityError(CapabilityError):
    """Non-retryable business failure - fails the owning step immediately."""


class CapabilityTimeoutError(CapabilityError):
    """Capability-internal timeout (see the 3-boundary note in §5 of the contract).

    Treated as retryable by default at the CapabilityExecutor boundary.
    """


class BudgetExceededError(PermanentCapabilityError):
    """Raised by a BudgetGuard implementation's pre-flight check (§9) - non-retryable."""


class CapabilityRegistryError(Exception):
    """Base class for errors in capability registration, not execution."""


class DuplicateCapabilityRegistrationError(CapabilityRegistryError):
    """Raised when register() is called with a name that is already registered."""


class CapabilityRegistryAlreadySealedError(CapabilityRegistryError):
    """Raised when register() is called after CapabilityRegistry.seal()."""


class UnknownCapabilityError(CapabilityRegistryError):
    """Raised when resolve() is asked for an unregistered capability name."""
