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

M19 (docs/phase7_architecture_contract.md §19 rule 2): build_registry() gains the
injected-dependency signature the frozen contract specifies -
`build_registry(gateway, prompt_repository, budget_guard, tool_registry) -> CapabilityRegistry`,
"the sole boot-sequence entry point that constructs every Capability with its dependencies
injected." All four parameters are accepted and type-checked here, matching the contract
exactly, but none is threaded anywhere yet: this milestone still ships an empty, sealed
registry (no concrete Capability exists to inject them into). Note the same real-but-harmless
inconsistency §19 rule 2's own text carries forward from before Amendment C (§25) was appended:
`budget_guard` appears in this signature, yet Amendment C explicitly forbids a `Capability`
from ever holding or calling `BudgetGuard` directly. Amendment C never edits §19 rule 2's text
(§26's append-only discipline forbids in-place edits to prior sections), so resolving whether
a future concrete Capability actually receives `budget_guard` - almost certainly it must not,
per Amendment C - is deferred to whichever future milestone builds the first real Capability;
nothing here decides it. The previous, zero-argument `build_registry()` had a module-level
`registry = build_registry()` singleton (constructed at import time); that singleton is removed
in this milestone since the new signature cannot be satisfied at import time without
constructing a real Gateway/PromptRepository/BudgetGuard as a side effect of merely importing
this module - callers now go through `integrations.llm_gateway.boot.assemble_ai_integration_
layer()` instead, exactly as the contract's fixed boot order (§19 rule 3) specifies.
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
from integrations.llm_gateway.protocol import LLMGateway
from integrations.llm_gateway.tools.registry import ToolRegistry
from integrations.prompts.protocol import PromptRepository
from services.budget_guard import BudgetGuard

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


def build_registry(
    gateway: LLMGateway,
    prompt_repository: PromptRepository,
    budget_guard: BudgetGuard,
    tool_registry: ToolRegistry,
) -> CapabilityRegistry:
    """Build and seal the CapabilityRegistry (docs/phase7_architecture_contract.md §19 rule 2).

    The sole boot-sequence entry point that would construct every Capability with its
    dependencies injected - no concrete Capability implementation exists yet anywhere in this
    codebase, so this registry ships empty-but-sealed, exactly mirroring Phase 5's
    WorkflowType.DAILY_DIGEST precedent (declared, not registered). See this module's
    docstring for why all four parameters are accepted, type-checked, and unused today.
    """
    registry = CapabilityRegistry()
    registry.seal()
    return registry
