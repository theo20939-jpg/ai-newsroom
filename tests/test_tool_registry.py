"""Tests for integrations.llm_gateway.tools.registry.ToolRegistry
(docs/phase7_architecture_contract.md §9.1, §9.2). Pure unit tests, no I/O - identical
discipline to test_provider_registry.py / test_model_registry.py / test_routing_policy_registry.py.
"""
import pytest

from integrations.llm_gateway.errors import (
    DuplicateToolRegistrationError,
    ToolRegistryAlreadySealedError,
    UnknownToolError,
)
from integrations.llm_gateway.protocol import ToolCall, ToolDefinition
from integrations.llm_gateway.tools.registry import (
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutor,
    ToolRegistry,
)


class _FakeToolExecutor:
    """Structurally satisfies ToolExecutor - never actually called by these tests (the tool-use
    loop itself is out of scope, §9.3, deferred to a future Capability)."""

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        raise NotImplementedError


def _tool_definition(name: str = "search") -> ToolDefinition:
    return ToolDefinition(name=name, description="search the web", parameters_schema={"type": "object"})


def test_register_and_resolve() -> None:
    registry = ToolRegistry()
    definition = _tool_definition()
    executor: ToolExecutor = _FakeToolExecutor()
    registry.register(definition, executor, idempotent=True)

    resolved_definition, resolved_executor, resolved_idempotent = registry.resolve("search")
    assert resolved_definition is definition
    assert resolved_executor is executor
    assert resolved_idempotent is True


def test_idempotent_flag_is_stored_per_registration() -> None:
    registry = ToolRegistry()
    registry.register(_tool_definition("search"), _FakeToolExecutor(), idempotent=True)
    registry.register(_tool_definition("send_email"), _FakeToolExecutor(), idempotent=False)

    _, _, search_idempotent = registry.resolve("search")
    _, _, email_idempotent = registry.resolve("send_email")
    assert search_idempotent is True
    assert email_idempotent is False


def test_duplicate_registration_raises() -> None:
    registry = ToolRegistry()
    registry.register(_tool_definition(), _FakeToolExecutor(), idempotent=True)

    with pytest.raises(DuplicateToolRegistrationError):
        registry.register(_tool_definition(), _FakeToolExecutor(), idempotent=True)


def test_unknown_name_raises() -> None:
    registry = ToolRegistry()

    with pytest.raises(UnknownToolError):
        registry.resolve("search")


def test_registration_after_sealing_raises() -> None:
    registry = ToolRegistry()
    registry.register(_tool_definition(), _FakeToolExecutor(), idempotent=True)
    registry.seal()

    with pytest.raises(ToolRegistryAlreadySealedError):
        registry.register(_tool_definition("other"), _FakeToolExecutor(), idempotent=True)


def test_resolution_after_sealing_still_works() -> None:
    registry = ToolRegistry()
    definition = _tool_definition()
    registry.register(definition, _FakeToolExecutor(), idempotent=True)
    registry.seal()

    resolved_definition, _, _ = registry.resolve("search")
    assert resolved_definition is definition


def test_empty_sealed_registry_resolves_nothing() -> None:
    """Mirrors capabilities.registry.build_registry()'s own "ships empty-sealed" state -
    the shape an M19 boot sequence actually constructs (no concrete tool exists yet)."""
    registry = ToolRegistry()
    registry.seal()

    with pytest.raises(UnknownToolError):
        registry.resolve("anything")


def test_tool_execution_request_carries_the_derived_tool_call_id_shape() -> None:
    """§9.1: the one genuinely new field this contract introduces anywhere."""
    request = ToolExecutionRequest(
        tool_call_id="task-1:research:1:tool:0:0",
        tool_call=ToolCall(name="search", arguments={"query": "hi"}),
    )
    assert request.tool_call_id == "task-1:research:1:tool:0:0"
    assert request.tool_call.name == "search"


def test_tool_execution_result_shape() -> None:
    success = ToolExecutionResult(status="SUCCESS", output={"result": "ok"})
    failure = ToolExecutionResult(status="FAILED", output=None, error="boom")
    assert success.status == "SUCCESS"
    assert failure.error == "boom"
