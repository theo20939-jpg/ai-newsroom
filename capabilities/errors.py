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
"""


class CapabilityError(Exception):
    """Base class for every error a Capability.execute() implementation may raise."""


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
