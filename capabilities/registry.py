"""CapabilityRegistry: resolves a capability name to its registered
(CapabilityDefinition, Capability) pair.

Identical shape to workflows.registry.WorkflowRegistry: mutable via
register() only until seal() is called, after which register() raises
CapabilityRegistryAlreadySealedError. No dynamic discovery (docs/
phase6_architecture_contract.md §6, §9/P9).

Phase 6 ships no concrete Capability implementation (Research/Intelligence/
etc. remain future work) - build_registry() therefore returns an empty,
sealed registry, exactly mirroring how WorkflowType.DAILY_DIGEST is declared
but never registered in Phase 5.
"""
import logging
from typing import Protocol

from schemas.capability import CapabilityContext, CapabilityResult
from schemas.capability_definition import CapabilityDefinition
from capabilities.errors import (
    CapabilityRegistryAlreadySealedError,
    DuplicateCapabilityRegistrationError,
    UnknownCapabilityError,
)

logger = logging.getLogger(__name__)


class Capability(Protocol):
    """One AI-capability module. See P3/P4. Never calls a provider SDK.
    Never calls another Capability. Communicates only through CapabilityContext
    (in) and CapabilityResult (out)."""

    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        """Run once. Raises only CapabilityError subtypes - never a bare Exception."""
        ...


class CapabilityRegistry:
    """Resolves a capability name to its registered, immutable
    (CapabilityDefinition, Capability) pair."""

    def __init__(self) -> None:
        self._definitions: dict[str, CapabilityDefinition] = {}
        self._capabilities: dict[str, Capability] = {}
        self._sealed = False

    def register(self, definition: CapabilityDefinition, capability: Capability) -> None:
        """Register one (CapabilityDefinition, Capability) pair.

        Raises CapabilityRegistryAlreadySealedError if the registry has been
        sealed, or DuplicateCapabilityRegistrationError if `definition.name`
        is already registered - regardless of `definition.version`.
        """
        if self._sealed:
            raise CapabilityRegistryAlreadySealedError(
                f"Cannot register '{definition.name}' version {definition.version}: "
                "this CapabilityRegistry is sealed and accepts no further registrations."
            )
        if definition.name in self._definitions:
            existing = self._definitions[definition.name]
            raise DuplicateCapabilityRegistrationError(
                f"Capability '{definition.name}' is already registered "
                f"(version {existing.version}); cannot register version {definition.version} again."
            )
        self._definitions[definition.name] = definition
        self._capabilities[definition.name] = capability
        logger.info("Registered capability %s version %d", definition.name, definition.version)

    def seal(self) -> None:
        """Permanently stop accepting further register() calls."""
        self._sealed = True

    def resolve(self, name: str) -> tuple[CapabilityDefinition, Capability]:
        """Return the registered (CapabilityDefinition, Capability) pair for `name`.

        Raises UnknownCapabilityError if unregistered. Read-only regardless of
        seal state - resolve() works identically before and after sealing.
        """
        definition = self._definitions.get(name)
        capability = self._capabilities.get(name)
        if definition is None or capability is None:
            raise UnknownCapabilityError(f"No Capability registered for name '{name}'")
        return definition, capability


def build_registry() -> CapabilityRegistry:
    """Build and seal the Phase 6 CapabilityRegistry.

    No concrete Capability implementation exists yet in Phase 6 - this
    registry ships empty-but-sealed, exactly mirroring Phase 5's
    WorkflowType.DAILY_DIGEST precedent (declared, not registered).
    """
    registry = CapabilityRegistry()
    registry.seal()
    return registry


registry = build_registry()
