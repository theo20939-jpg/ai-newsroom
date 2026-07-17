"""ToolRegistry (docs/phase7_architecture_contract.md §9.1, §9.2): sealed-after-boot,
explicit-registration-only tool registry - identical discipline to every other registry in
this contract (P18), mirroring ProviderRegistry (§2), ModelRegistry (§3), and
RoutingPolicyRegistry (§4.5) exactly.

M19 note: this milestone (boot sequence + CapabilityRegistry wiring) needs `ToolRegistry` to
exist purely so `capabilities.registry.build_registry()`'s contract-mandated signature
(§19 rule 2: `build_registry(gateway, prompt_repository, budget_guard, tool_registry)`) can be
satisfied and type-checked. No concrete tool is registered anywhere yet - `assemble_ai_
integration_layer()` constructs and seals an empty ToolRegistry, exactly mirroring how
`build_registry()` itself still ships an empty, sealed `CapabilityRegistry` (no concrete
Capability exists yet either). The tool-use loop itself (§9.3), `MAX_TOOL_ROUNDS` (§9.4), and
the per-round timeout split (§9.5) remain entirely out of scope here - those live inside a
future `Capability.execute()`, which doesn't exist yet in this codebase.
"""
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from integrations.llm_gateway.errors import (
    DuplicateToolRegistrationError,
    ToolRegistryAlreadySealedError,
    UnknownToolError,
)
from integrations.llm_gateway.protocol import ToolCall, ToolDefinition


class ToolExecutionRequest(BaseModel):
    """The one genuinely new field this contract introduces anywhere (§9.1) -
    `tool_call_id`, derived by a future Capability's tool loop as
    `f"{capability_execution_id}:tool:{round_index}:{tool_index}"` (§16.1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_call_id: str
    tool_call: ToolCall


class ToolExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["SUCCESS", "FAILED"]
    output: dict[str, Any] | None
    error: str | None = None


class ToolExecutor(Protocol):
    """Injected into a Capability exactly like LLMGateway/PromptRepository/BudgetGuard (§9.1).
    Never called by CapabilityExecutor, LLMGateway, or a ProviderAdapter - those three only
    ever see ToolDefinition/ToolCall as opaque data."""

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult: ...


class ToolRegistry:
    """`provider_id`-style opaque `name -> (ToolDefinition, ToolExecutor, idempotent)` registry
    (§9.2). `idempotent` is stored alongside the registration - NEVER added to Phase 6's
    `ToolDefinition` itself (§9.2's own binding text)."""

    def __init__(self) -> None:
        self._tools: dict[str, tuple[ToolDefinition, ToolExecutor, bool]] = {}
        self._sealed = False

    def register(self, definition: ToolDefinition, executor: ToolExecutor, idempotent: bool) -> None:
        """Raises ToolRegistryAlreadySealedError if seal() has already been called, or
        DuplicateToolRegistrationError if `definition.name` is already registered."""
        if self._sealed:
            raise ToolRegistryAlreadySealedError(
                f"Cannot register tool '{definition.name}': this ToolRegistry is sealed and "
                "accepts no further registrations."
            )
        if definition.name in self._tools:
            raise DuplicateToolRegistrationError(f"Tool '{definition.name}' is already registered.")
        self._tools[definition.name] = (definition, executor, idempotent)

    def seal(self) -> None:
        self._sealed = True

    def resolve(self, name: str) -> tuple[ToolDefinition, ToolExecutor, bool]:
        """Raises UnknownToolError if `name` is not registered."""
        entry = self._tools.get(name)
        if entry is None:
            raise UnknownToolError(f"No tool registered for name '{name}'")
        return entry
