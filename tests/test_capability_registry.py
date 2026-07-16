"""Tests for capabilities.registry.CapabilityRegistry. Pure unit tests, no database."""
import pytest

from schemas.capability_definition import CapabilityConfig, CapabilityDefinition
from capabilities.errors import (
    CapabilityRegistryAlreadySealedError,
    DuplicateCapabilityRegistrationError,
    UnknownCapabilityError,
)
from capabilities.registry import CapabilityRegistry
from capabilities.registry import registry as default_registry
from tests.fakes.fake_capability import AlwaysSucceedsCapability


def _definition(name: str = "research", version: int = 1) -> CapabilityDefinition:
    return CapabilityDefinition(
        name=name, version=version, config=CapabilityConfig(timeout_seconds=10),
        required_context=["news_event"], expected_output_keys=["summary"],
    )


def test_register_and_resolve() -> None:
    registry = CapabilityRegistry()
    definition = _definition()
    capability = AlwaysSucceedsCapability()
    registry.register(definition, capability)

    resolved_definition, resolved_capability = registry.resolve("research")
    assert resolved_definition is definition
    assert resolved_capability is capability


def test_duplicate_registration_raises() -> None:
    registry = CapabilityRegistry()
    registry.register(_definition(), AlwaysSucceedsCapability())

    with pytest.raises(DuplicateCapabilityRegistrationError):
        registry.register(_definition(), AlwaysSucceedsCapability())


def test_unknown_name_raises() -> None:
    registry = CapabilityRegistry()

    with pytest.raises(UnknownCapabilityError):
        registry.resolve("research")


def test_registration_after_sealing_raises() -> None:
    registry = CapabilityRegistry()
    registry.register(_definition(), AlwaysSucceedsCapability())
    registry.seal()

    with pytest.raises(CapabilityRegistryAlreadySealedError):
        registry.register(_definition(name="intelligence"), AlwaysSucceedsCapability())


def test_resolution_after_sealing_still_works() -> None:
    registry = CapabilityRegistry()
    definition = _definition()
    capability = AlwaysSucceedsCapability()
    registry.register(definition, capability)
    registry.seal()

    resolved_definition, resolved_capability = registry.resolve("research")
    assert resolved_definition is definition
    assert resolved_capability is capability


def test_the_real_registry_ships_empty_but_sealed() -> None:
    """No concrete Capability implementation exists yet in Phase 6 - mirrors
    Phase 5's WorkflowType.DAILY_DIGEST precedent (declared, not registered)."""
    with pytest.raises(UnknownCapabilityError):
        default_registry.resolve("research")

    with pytest.raises(CapabilityRegistryAlreadySealedError):
        default_registry.register(_definition(), AlwaysSucceedsCapability())
