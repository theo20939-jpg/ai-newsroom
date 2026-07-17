"""Tests for integrations.llm_gateway.errors - the Gateway-layer exception hierarchy.

Pure identity/hierarchy tests: every exception is a GatewayError, none is a
capabilities.errors.CapabilityError subtype (the Gateway boundary must never
import upward into capabilities/, docs/phase7_architecture_contract.md §1).
"""
import pytest

from capabilities.errors import CapabilityError
from integrations.llm_gateway.errors import (
    AllProvidersFailedError,
    DuplicateModelRegistrationError,
    DuplicateProviderRegistrationError,
    GatewayError,
    MissingRedisFailurePolicyError,
    ModelRegistryAlreadySealedError,
    NoRoutableCandidateError,
    ProviderRegistryAlreadySealedError,
    RateLimitExceededError,
    RegistryConsistencyError,
    RetryCeilingExceededError,
    UnknownModelError,
    UnknownModelPricingError,
    UnknownProviderError,
    UnknownRoutingObjectiveError,
)

ALL_GATEWAY_EXCEPTIONS = (
    UnknownProviderError,
    DuplicateProviderRegistrationError,
    ProviderRegistryAlreadySealedError,
    UnknownModelError,
    DuplicateModelRegistrationError,
    ModelRegistryAlreadySealedError,
    RegistryConsistencyError,
    UnknownModelPricingError,
    NoRoutableCandidateError,
    UnknownRoutingObjectiveError,
    RateLimitExceededError,
    MissingRedisFailurePolicyError,
    RetryCeilingExceededError,
)


@pytest.mark.parametrize("exc_type", ALL_GATEWAY_EXCEPTIONS)
def test_every_gateway_exception_subclasses_gateway_error(exc_type: type[Exception]) -> None:
    assert issubclass(exc_type, GatewayError)


@pytest.mark.parametrize("exc_type", (*ALL_GATEWAY_EXCEPTIONS, AllProvidersFailedError))
def test_no_gateway_exception_subclasses_capability_error(exc_type: type[Exception]) -> None:
    assert not issubclass(exc_type, CapabilityError)


def test_gateway_error_is_a_plain_exception_base() -> None:
    assert issubclass(GatewayError, Exception)
    assert not issubclass(GatewayError, CapabilityError)


def test_all_providers_failed_error_carries_reason() -> None:
    error = AllProvidersFailedError("every candidate failed", reason="all_candidates_failed")

    assert error.reason == "all_candidates_failed"
    assert issubclass(AllProvidersFailedError, GatewayError)
    assert str(error) == "every candidate failed"


def test_all_providers_failed_error_is_raisable_and_catchable() -> None:
    with pytest.raises(AllProvidersFailedError) as excinfo:
        raise AllProvidersFailedError("cost ceiling exhausted", reason="cost_ceiling_exhausted")

    assert excinfo.value.reason == "cost_ceiling_exhausted"
