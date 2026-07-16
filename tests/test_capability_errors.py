"""Identity checks for the capabilities.errors hierarchy - no database, no network."""
from capabilities.errors import (
    BudgetExceededError,
    CapabilityConfigurationError,
    CapabilityError,
    CapabilityRegistryAlreadySealedError,
    CapabilityRegistryError,
    CapabilityTimeoutError,
    DuplicateCapabilityRegistrationError,
    PermanentCapabilityError,
    RetryableCapabilityError,
    UnknownCapabilityError,
    ValidationCapabilityError,
)


def test_all_execution_errors_subclass_capability_error() -> None:
    for error_type in (
        CapabilityConfigurationError,
        ValidationCapabilityError,
        RetryableCapabilityError,
        PermanentCapabilityError,
        CapabilityTimeoutError,
    ):
        assert issubclass(error_type, CapabilityError)


def test_budget_exceeded_is_a_permanent_capability_error() -> None:
    assert issubclass(BudgetExceededError, PermanentCapabilityError)
    assert issubclass(BudgetExceededError, CapabilityError)


def test_registry_errors_subclass_capability_registry_error() -> None:
    for error_type in (
        DuplicateCapabilityRegistrationError,
        CapabilityRegistryAlreadySealedError,
        UnknownCapabilityError,
    ):
        assert issubclass(error_type, CapabilityRegistryError)


def test_registry_errors_are_not_capability_errors() -> None:
    # Registry/config errors are a distinct concern from execution errors -
    # never conflated into the CapabilityError hierarchy a Capability raises.
    assert not issubclass(CapabilityRegistryError, CapabilityError)
